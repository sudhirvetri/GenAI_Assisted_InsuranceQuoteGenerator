"""
WebSocket $connect handler.
Stores connection_id → user_id mapping in DynamoDB iqg-ws-connections.
The Lambda Authorizer already validated the JWT before this runs —
user_id is available in requestContext.authorizer.userId.
"""

import os
import time
import json
import boto3

REGION = os.environ.get("REGION", "us-east-1")
WS_CONNECTIONS_TABLE = os.environ.get("WS_CONNECTIONS_TABLE", "iqg-ws-connections")

dynamodb = boto3.resource("dynamodb", region_name=REGION)
connections_table = dynamodb.Table(WS_CONNECTIONS_TABLE)


def handler(event, context):
    connection_id = event["requestContext"]["connectionId"]

    # userId injected by the Lambda Authorizer
    user_id = (
        event.get("requestContext", {})
             .get("authorizer", {})
             .get("userId", "unknown")
    )

    try:
        connections_table.put_item(Item={
            "connectionId": connection_id,
            "userId": user_id,
            "connectedAt": int(time.time()),
            "expiresAt": int(time.time()) + 28800,  # 8 hours TTL
        })
        print("WebSocket connected: connection_id=%s user_id=%s" % (connection_id, user_id))
    except Exception as exc:
        print("Failed to store connection: %s" % exc)
        return {"statusCode": 500}

    return {"statusCode": 200}
