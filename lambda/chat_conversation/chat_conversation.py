"""
Chat Conversation API - handles POST /v1/chat

Lets a user ask follow-up questions about their completed quote. Loads the quote
recommendations as context, replays the last 10 conversation turns, calls
Bedrock (Claude Sonnet 4.6), and persists both the user and assistant turns to
DynamoDB (iqg-chat-history).
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
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-6")

bedrock = boto3.client("bedrock-runtime", region_name=REGION)
dynamodb = boto3.resource("dynamodb", region_name=REGION)
results_table = dynamodb.Table(QUOTE_RESULTS_TABLE)
chat_table = dynamodb.Table(CHAT_HISTORY_TABLE)

MAX_MESSAGE_LEN = 1000
HISTORY_LIMIT = 10
CHAT_TTL_SECONDS = 2592000  # 30 days


def _json_default(obj):
    if isinstance(obj, Decimal):
        if obj == obj.to_integral_value():
            return int(obj)
        return float(obj)
    raise TypeError("Object of type %s is not JSON serializable" % type(obj))


def respond(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization,X-Correlation-Id,Idempotency-Key",
            "Access-Control-Allow-Methods": "OPTIONS,GET,POST",
        },
        "body": json.dumps(body, default=_json_default),
    }


def invoke_bedrock(system_prompt, messages, max_tokens=500):
    response = bedrock.invoke_model(
        modelId=BEDROCK_MODEL_ID,
        body=json.dumps(
            {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": max_tokens,
                "system": system_prompt,
                "messages": messages,
            }
        ),
        contentType="application/json",
        accept="application/json",
    )
    body = json.loads(response["body"].read())
    return body["content"][0]["text"]


def handler(event, context):
    # 1. Parse body
    try:
        raw_body = event.get("body") or "{}"
        payload = raw_body if isinstance(raw_body, dict) else json.loads(raw_body)
    except (ValueError, TypeError):
        return respond(400, {"error": "Invalid JSON body"})

    # 2. Authorizer context
    try:
        user_id = event["requestContext"]["authorizer"]["userId"]
    except (KeyError, TypeError):
        return respond(401, {"error": "Unauthorized: missing user context"})

    # 3. Validate
    transaction_id = payload.get("transaction_id")
    message = payload.get("message")

    if not transaction_id:
        return respond(400, {"error": "transaction_id is required"})
    if not message or not isinstance(message, str):
        return respond(400, {"error": "message is required"})
    if len(message) > MAX_MESSAGE_LEN:
        return respond(
            400,
            {"error": "message exceeds maximum length of %d characters" % MAX_MESSAGE_LEN},
        )

    # 4. Load quote context
    try:
        resp = results_table.get_item(Key={"transactionId": transaction_id})
    except Exception as exc:
        print("DynamoDB get_item failed: %s" % exc)
        return respond(500, {"error": "Failed to load quote context"})

    quote_item = resp.get("Item")
    if not quote_item:
        return respond(400, {"error": "Quote not found for transaction"})
    if quote_item.get("userId") != user_id:
        return respond(403, {"error": "Forbidden"})
    if quote_item.get("status") != "COMPLETE":
        return respond(
            400, {"error": "Quote is not yet complete; cannot start chat"}
        )

    plan_context = quote_item.get("recommendations", [])

    # 5. Load last 10 conversation turns
    history = []
    try:
        query_resp = chat_table.query(
            KeyConditionExpression=Key("userId").eq(user_id)
            & Key("turnId").begins_with(transaction_id),
            ScanIndexForward=True,  # ascending; ULID/timestamp sortable
        )
        items = query_resp.get("Items", [])
        history = items[-HISTORY_LIMIT:]
    except Exception as exc:
        # Non-fatal: proceed without prior context.
        print("Chat history query failed (continuing without history): %s" % exc)
        history = []

    # 6. Build conversation messages
    messages = []
    for turn in history:
        role = turn.get("role")
        content = turn.get("content")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": message})

    # 7. System prompt
    system_prompt = (
        "You are a helpful health insurance advisor for SwiftCare Health Insurance.\n"
        "The user is asking questions about their insurance quote recommendations.\n\n"
        "THEIR RECOMMENDED PLANS:\n"
        "{plans}\n\n"
        "Answer their questions clearly and concisely. Be helpful and informative.\n"
        "Do not make guaranteed coverage claims. Always recommend consulting\n"
        "an insurance professional for final decisions."
    ).format(plans=json.dumps(plan_context, indent=2, default=_json_default))

    # 8. Call Bedrock
    try:
        response_text = invoke_bedrock(system_prompt, messages, max_tokens=500)
    except Exception as exc:
        print("Bedrock invocation failed: %s" % exc)
        return respond(502, {"error": "Failed to generate a response"})

    # 10. Generate turn ids (millisecond precision; user turn ordered before assistant)
    now_ms = int(time.time() * 1000)
    user_turn_id = "{tid}#{ts}".format(tid=transaction_id, ts=now_ms - 1)
    assistant_turn_id = "{tid}#{ts}".format(tid=transaction_id, ts=now_ms)
    expires_at = int(time.time()) + CHAT_TTL_SECONDS

    # 11. Persist both turns
    try:
        chat_table.put_item(
            Item={
                "userId": user_id,
                "turnId": user_turn_id,
                "role": "user",
                "content": message,
                "transactionId": transaction_id,
                "expiresAt": expires_at,
            }
        )
        chat_table.put_item(
            Item={
                "userId": user_id,
                "turnId": assistant_turn_id,
                "role": "assistant",
                "content": response_text,
                "transactionId": transaction_id,
                "expiresAt": expires_at,
            }
        )
    except Exception as exc:
        # Response was generated; log persistence failure but still return it.
        print("Failed to persist chat turns (non-fatal): %s" % exc)

    # 12. Return
    return respond(
        200,
        {
            "turn_id": assistant_turn_id,
            "message": response_text,
            "transaction_id": transaction_id,
        },
    )
