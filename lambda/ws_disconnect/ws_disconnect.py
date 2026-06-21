"""
WebSocket $disconnect handler.
Removes the connection record from DynamoDB.
"""

import os
import boto3

REGION = os.environ.get("REGION", "us-east-1")
WS_CONNECTIONS_TABLE = os.environ.get("WS_CONNECTIONS_TABLE", "iqg-ws-connections")

dynamodb = boto3.resource("dynamodb", region_name=REGION)
connections_table = dynamodb.Table(WS_CONNECTIONS_TABLE)


def handler(event, context):
    connection_id = event["requestContext"]["connectionId"]

    try:
        connections_table.delete_item(Key={"connectionId": connection_id})
        print("WebSocket disconnected: connection_id=%s" % connection_id)
    except Exception as exc:
        print("Failed to delete connection: %s" % exc)

    return {"statusCode": 200}
