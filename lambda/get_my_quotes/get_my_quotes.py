"""
Get My Quotes API - handles GET /v1/my-quotes

Returns all transactions for the authenticated user, with submission profile,
plan selection status, and recommendations (for COMPLETE transactions).
"""

import os
import json
import datetime
from decimal import Decimal

import boto3

REGION = os.environ.get("REGION", "us-east-1")
CLUSTER_ARN = os.environ["DB_CLUSTER_ARN"]
SECRET_ARN = os.environ["DB_SECRET_ARN"]
DB_TXN = os.environ.get("DB_NAME_TXN", "txndb")
QUOTE_RESULTS_TABLE = os.environ.get("QUOTE_RESULTS_TABLE", "iqg-quote-results")

rds = boto3.client("rds-data", region_name=REGION)
dynamodb = boto3.resource("dynamodb", region_name=REGION)
results_table = dynamodb.Table(QUOTE_RESULTS_TABLE)


# --------------------------------------------------------------------------- #
# Aurora Data API helpers
# --------------------------------------------------------------------------- #
def db_execute(sql, params=None, database=DB_TXN):
    kwargs = dict(
        resourceArn=CLUSTER_ARN,
        secretArn=SECRET_ARN,
        database=database,
        sql=sql,
        includeResultMetadata=True,
    )
    if params:
        kwargs["parameters"] = params
    return rds.execute_statement(**kwargs)


def rows_to_dicts(result):
    if not result.get("records"):
        return []
    cols = [m["name"] for m in result["columnMetadata"]]
    rows = []
    for record in result["records"]:
        row = {}
        for col, field in zip(cols, record):
            if not field or "isNull" in field:
                val = None
            else:
                val = list(field.values())[0]
            row[col] = val
        rows.append(row)
    return rows


def make_param(name, value):
    if value is None:
        return {"name": name, "value": {"isNull": True}}
    if isinstance(value, bool):
        return {"name": name, "value": {"booleanValue": value}}
    if isinstance(value, int):
        return {"name": name, "value": {"longValue": value}}
    if isinstance(value, float):
        return {"name": name, "value": {"doubleValue": value}}
    return {"name": name, "value": {"stringValue": str(value)}}


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


def _json_default(obj):
    if isinstance(obj, Decimal):
        if obj == obj.to_integral_value():
            return int(obj)
        return float(obj)
    if isinstance(obj, datetime.datetime):
        return obj.isoformat()
    raise TypeError("Object of type %s is not JSON serializable" % type(obj))


def _slim_recommendation(rec):
    """Keep only the fields needed for the My Quotes view."""
    return {
        "plan_id": rec.get("plan_id"),
        "plan_name": rec.get("plan_name"),
        "annual_premium": rec.get("annual_premium"),
        "sum_insured": rec.get("sum_insured"),
        "tier": rec.get("tier"),
        "highlights": rec.get("highlights"),
        "reason": rec.get("reason"),
    }


def handler(event, context):
    # 1. Authorizer context
    try:
        user_id = event["requestContext"]["authorizer"]["userId"]
    except (KeyError, TypeError):
        return respond(401, {"error": "Unauthorized: missing user context"})

    # 2. Query Aurora for all transactions belonging to this user
    try:
        result = db_execute(
            """
            SELECT
                t.transaction_id,
                t.status,
                t.created_at,
                s.age,
                s.category,
                s.family_composition,
                s.target_si,
                s.budget_premium,
                ps.plan_id  AS selected_plan_id,
                ps.selected_at
            FROM transactions t
            JOIN submissions s ON s.submission_id = t.submission_id
            LEFT JOIN LATERAL (
                SELECT plan_id, selected_at
                FROM plan_selections
                WHERE transaction_id = t.transaction_id
                ORDER BY selected_at DESC
                LIMIT 1
            ) ps ON true
            WHERE t.user_id = :user_id
            ORDER BY t.created_at DESC
            LIMIT 20
            """,
            [make_param("user_id", user_id)],
        )
        rows = rows_to_dicts(result)
    except Exception as exc:
        print("Transaction query failed: %s" % exc)
        return respond(500, {"error": "Failed to fetch transactions"})

    if not rows:
        return respond(200, {"transactions": [], "count": 0})

    # 3. For COMPLETE transactions fetch recommendations from DynamoDB
    transactions = []
    for row in rows:
        txn_id = str(row.get("transaction_id") or "")
        status = row.get("status") or "UNKNOWN"

        recommendations = []
        if status == "COMPLETE" and txn_id:
            try:
                ddb_resp = results_table.get_item(Key={"transactionId": txn_id})
                item = ddb_resp.get("Item") or {}
                raw_recs = item.get("recommendations") or []
                recommendations = [_slim_recommendation(r) for r in raw_recs]
            except Exception as exc:
                print("DynamoDB fetch failed for %s: %s" % (txn_id, exc))

        created_at = row.get("created_at")
        selected_at = row.get("selected_at")

        transactions.append(
            {
                "transaction_id": txn_id,
                "status": status,
                "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at or ""),
                "profile": {
                    "age": row.get("age"),
                    "category": row.get("category"),
                    "family_composition": row.get("family_composition"),
                    "target_si": row.get("target_si"),
                    "budget_premium": row.get("budget_premium"),
                },
                "selected_plan_id": row.get("selected_plan_id"),
                "selected_at": selected_at.isoformat() if hasattr(selected_at, "isoformat") else (str(selected_at) if selected_at else None),
                "recommendations": recommendations,
            }
        )

    return respond(200, {"transactions": transactions, "count": len(transactions)})
