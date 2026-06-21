"""
WebSocket sendMessage handler — streaming chat via WebSocket.

Replaces the REST POST /v1/chat endpoint for WebSocket clients.
Receives a chat message frame, calls Bedrock with streaming,
and pushes each token chunk back to the browser via PostToConnection.
"""

import os
import json
import time
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

REGION = os.environ.get("REGION", "us-east-1")
QUOTE_RESULTS_TABLE = os.environ.get("QUOTE_RESULTS_TABLE", "iqg-quote-results")
CHAT_HISTORY_TABLE = os.environ.get("CHAT_HISTORY_TABLE", "iqg-chat-history")
WS_CONNECTIONS_TABLE = os.environ.get("WS_CONNECTIONS_TABLE", "iqg-ws-connections")
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-6")
WS_ENDPOINT = os.environ.get("WS_ENDPOINT", "")  # injected by CDK

bedrock = boto3.client("bedrock-runtime", region_name=REGION)
dynamodb = boto3.resource("dynamodb", region_name=REGION)
results_table = dynamodb.Table(QUOTE_RESULTS_TABLE)
chat_table = dynamodb.Table(CHAT_HISTORY_TABLE)
connections_table = dynamodb.Table(WS_CONNECTIONS_TABLE)

MAX_TOKENS = int(os.environ.get("CHAT_MAX_TOKENS", "1000"))
MAX_MESSAGE_LEN = 1000
HISTORY_LIMIT = 10
CHAT_TTL_SECONDS = 2592000  # 30 days


def _json_default(obj):
    if isinstance(obj, Decimal):
        if obj == obj.to_integral_value():
            return int(obj)
        return float(obj)
    raise TypeError


def get_apigw_client(connection_id):
    """Create API Gateway Management API client for this connection."""
    return boto3.client(
        "apigatewaymanagementapi",
        endpoint_url=WS_ENDPOINT,
        region_name=REGION,
    )


def post_to_connection(apigw, connection_id, data):
    """Send a message to the WebSocket client. Returns False if connection gone."""
    try:
        apigw.post_to_connection(
            ConnectionId=connection_id,
            Data=json.dumps(data).encode("utf-8"),
        )
        return True
    except apigw.exceptions.GoneException:
        print("Connection gone: %s" % connection_id)
        return False
    except Exception as exc:
        print("PostToConnection failed: %s" % exc)
        return False


def handler(event, context):
    connection_id = event["requestContext"]["connectionId"]
    user_id = (
        event.get("requestContext", {})
             .get("authorizer", {})
             .get("userId", "")
    )

    apigw = get_apigw_client(connection_id)

    # Parse the incoming frame
    try:
        body = json.loads(event.get("body") or "{}")
    except Exception:
        post_to_connection(apigw, connection_id, {
            "type": "error", "message": "Invalid JSON frame"
        })
        return {"statusCode": 400}

    transaction_id = body.get("transaction_id")
    message = body.get("message", "").strip()
    turn_id = body.get("turn_id", str(int(time.time() * 1000)))

    if not transaction_id or not message:
        post_to_connection(apigw, connection_id, {
            "type": "error", "message": "transaction_id and message are required"
        })
        return {"statusCode": 400}

    if len(message) > MAX_MESSAGE_LEN:
        post_to_connection(apigw, connection_id, {
            "type": "error", "message": "Message too long (max 1000 chars)"
        })
        return {"statusCode": 400}

    # Load quote context
    try:
        resp = results_table.get_item(Key={"transactionId": transaction_id})
        quote_item = resp.get("Item")
    except Exception as exc:
        print("DynamoDB get_item failed: %s" % exc)
        post_to_connection(apigw, connection_id, {
            "type": "error", "message": "Failed to load quote context"
        })
        return {"statusCode": 500}

    if not quote_item:
        post_to_connection(apigw, connection_id, {
            "type": "error", "message": "Quote not found"
        })
        return {"statusCode": 404}

    if quote_item.get("userId") != user_id:
        post_to_connection(apigw, connection_id, {
            "type": "error", "message": "Forbidden"
        })
        return {"statusCode": 403}

    plan_context = quote_item.get("recommendations", [])

    # Load conversation history
    history = []
    try:
        query_resp = chat_table.query(
            KeyConditionExpression=Key("userId").eq(user_id)
                & Key("turnId").begins_with(transaction_id),
            ScanIndexForward=True,
        )
        items = query_resp.get("Items", [])
        history = items[-HISTORY_LIMIT:]
    except Exception as exc:
        print("Chat history query failed (continuing): %s" % exc)

    # Build messages
    messages = []
    for turn in history:
        role = turn.get("role")
        content = turn.get("content")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": message})

    system_prompt = (
        "You are a helpful health insurance advisor for SwiftCare Health Insurance.\n"
        "The user is asking questions about their insurance quote recommendations.\n\n"
        "THEIR RECOMMENDED PLANS:\n"
        "{plans}\n\n"
        "Answer clearly and concisely. Do not make guaranteed coverage claims."
    ).format(plans=json.dumps(plan_context, indent=2, default=_json_default))

    # Call Bedrock with STREAMING
    full_response = ""
    seq = 0
    try:
        response = bedrock.invoke_model_with_response_stream(
            modelId=BEDROCK_MODEL_ID,
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": MAX_TOKENS,
                "system": system_prompt,
                "messages": messages,
            }),
            contentType="application/json",
            accept="application/json",
        )

        for event_chunk in response["body"]:
            chunk_data = json.loads(event_chunk["chunk"]["bytes"])
            if chunk_data.get("type") == "content_block_delta":
                delta = chunk_data.get("delta", {}).get("text", "")
                if delta:
                    full_response += delta
                    seq += 1
                    # Push each token chunk to the browser
                    alive = post_to_connection(apigw, connection_id, {
                        "type": "chat_chunk",
                        "turn_id": turn_id,
                        "seq": seq,
                        "delta": delta,
                        "final": False,
                    })
                    if not alive:
                        # Client disconnected mid-stream — stop
                        return {"statusCode": 200}

        # Send final frame
        post_to_connection(apigw, connection_id, {
            "type": "chat_chunk",
            "turn_id": turn_id,
            "seq": seq + 1,
            "delta": "",
            "final": True,
        })

    except Exception as exc:
        print("Bedrock streaming failed: %s" % exc)
        post_to_connection(apigw, connection_id, {
            "type": "error",
            "turn_id": turn_id,
            "message": "Failed to generate response. Please try again.",
        })
        return {"statusCode": 502}

    # Persist both turns to DynamoDB
    now_ms = int(time.time() * 1000)
    expires_at = int(time.time()) + CHAT_TTL_SECONDS
    try:
        chat_table.put_item(Item={
            "userId": user_id,
            "turnId": "%s#%d" % (transaction_id, now_ms - 1),
            "role": "user",
            "content": message,
            "transactionId": transaction_id,
            "expiresAt": expires_at,
        })
        chat_table.put_item(Item={
            "userId": user_id,
            "turnId": "%s#%d" % (transaction_id, now_ms),
            "role": "assistant",
            "content": full_response,
            "transactionId": transaction_id,
            "expiresAt": expires_at,
        })
    except Exception as exc:
        print("Failed to persist chat turns (non-fatal): %s" % exc)

    return {"statusCode": 200}
