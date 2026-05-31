"""
Get Quote API - handles:
  - GET /v1/healthz                      -> health check
  - GET /v1/quotes/{transactionId}       -> fetch quote result

Reads the quote result from DynamoDB (iqg-quote-results), enforces ownership,
and returns the appropriate status payload.
"""

import os
import json
import datetime
from decimal import Decimal

import boto3

REGION = os.environ.get("REGION", "us-east-1")
QUOTE_RESULTS_TABLE = os.environ.get("QUOTE_RESULTS_TABLE", "iqg-quote-results")

dynamodb = boto3.resource("dynamodb", region_name=REGION)
results_table = dynamodb.Table(QUOTE_RESULTS_TABLE)


def _json_default(obj):
    """Serialize DynamoDB Decimal values to int/float for JSON output."""
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


def _iso_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def handler(event, context):
    path = event.get("path", "") or ""

    # ----------------------------------------------------------------- #
    # Health check
    # ----------------------------------------------------------------- #
    if path.endswith("/healthz"):
        return respond(
            200,
            {
                "status": "ok",
                "version": "1.0.0",
                "timestamp": _iso_now(),
            },
        )

    # ----------------------------------------------------------------- #
    # Quote fetch
    # ----------------------------------------------------------------- #
    path_params = event.get("pathParameters") or {}
    transaction_id = path_params.get("transactionId")
    if not transaction_id:
        return respond(400, {"error": "transactionId path parameter is required"})

    try:
        user_id = event["requestContext"]["authorizer"]["userId"]
    except (KeyError, TypeError):
        return respond(401, {"error": "Unauthorized: missing user context"})

    try:
        resp = results_table.get_item(Key={"transactionId": transaction_id})
    except Exception as exc:
        print("DynamoDB get_item failed: %s" % exc)
        return respond(500, {"error": "Failed to fetch transaction"})

    item = resp.get("Item")
    if not item:
        return respond(404, {"error": "Transaction not found"})

    if item.get("userId") != user_id:
        return respond(403, {"error": "Forbidden"})

    status = item.get("status")

    if status == "PENDING":
        return respond(
            200,
            {"transaction_id": transaction_id, "status": "PENDING"},
        )

    if status == "COMPLETE":
        return respond(
            200,
            {
                "transaction_id": transaction_id,
                "status": "COMPLETE",
                "recommendations": item.get("recommendations", []),
                "modelId": item.get("modelId"),
                "plansConsidered": item.get("plansConsidered"),
                "completedAt": item.get("completedAt"),
            },
        )

    if status == "FAILED":
        return respond(
            200,
            {
                "transaction_id": transaction_id,
                "status": "FAILED",
                "error": item.get("error", "Quote generation failed"),
            },
        )

    # Unknown / legacy status - return what we have.
    return respond(
        200,
        {"transaction_id": transaction_id, "status": status or "UNKNOWN"},
    )
