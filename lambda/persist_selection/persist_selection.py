"""
Persist Selection API - handles POST /v1/selections

Records the plan a user ultimately selected for a given transaction. Validates
ownership of the transaction, that the plan exists, and that no selection has
already been recorded (one selection per transaction).
"""

import os
import json
import datetime

import boto3

REGION = os.environ.get("REGION", "us-east-1")
CLUSTER_ARN = os.environ["DB_CLUSTER_ARN"]
SECRET_ARN = os.environ["DB_SECRET_ARN"]
DB_TXN = os.environ.get("DB_NAME_TXN", "txndb")
DB_PLAN = os.environ.get("DB_NAME_PLAN", "plandb")

rds = boto3.client("rds-data", region_name=REGION)


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
            val = list(field.values())[0] if field else None
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
        "body": json.dumps(body),
    }


def _iso_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


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

    transaction_id = payload.get("transaction_id")
    plan_id = payload.get("plan_id")
    selection_context = payload.get("selection_context") or {}

    if not transaction_id:
        return respond(400, {"error": "transaction_id is required"})
    if not plan_id:
        return respond(400, {"error": "plan_id is required"})

    rank_shown = selection_context.get("rank_shown_to_user")
    compared_against = selection_context.get("compared_against") or []
    compared_against_json = json.dumps(compared_against)

    # 3. Validate transaction exists and belongs to user
    try:
        result = db_execute(
            """
            SELECT transaction_id, user_id FROM transactions
            WHERE transaction_id = :transaction_id::uuid
            """,
            [make_param("transaction_id", transaction_id)],
        )
        txn_rows = rows_to_dicts(result)
    except Exception as exc:
        print("Transaction lookup failed: %s" % exc)
        return respond(500, {"error": "Failed to validate transaction"})

    if not txn_rows:
        return respond(404, {"error": "Transaction not found"})
    if str(txn_rows[0].get("user_id")) != str(user_id):
        return respond(403, {"error": "Forbidden"})

    # 4. Validate plan exists
    try:
        result = db_execute(
            "SELECT plan_id FROM plans WHERE plan_id = :plan_id",
            [make_param("plan_id", plan_id)],
            database=DB_PLAN,
        )
        plan_rows = rows_to_dicts(result)
    except Exception as exc:
        print("Plan lookup failed: %s" % exc)
        return respond(500, {"error": "Failed to validate plan"})

    if not plan_rows:
        return respond(404, {"error": "Plan not found"})

    # 5. Check for duplicate selection
    try:
        result = db_execute(
            """
            SELECT selection_id FROM plan_selections
            WHERE transaction_id = :transaction_id::uuid
            """,
            [make_param("transaction_id", transaction_id)],
        )
        existing = rows_to_dicts(result)
    except Exception as exc:
        print("Duplicate-selection check failed: %s" % exc)
        return respond(500, {"error": "Failed to check existing selection"})

    if existing:
        return respond(
            409, {"error": "Selection already exists for this transaction"}
        )

    # 6. Insert selection
    try:
        result = db_execute(
            """
            INSERT INTO plan_selections
                (transaction_id, plan_id, rank_shown, compared_against)
            VALUES (:transaction_id::uuid, :plan_id, :rank_shown, :compared_against::jsonb)
            RETURNING selection_id
            """,
            [
                make_param("transaction_id", transaction_id),
                make_param("plan_id", plan_id),
                make_param("rank_shown", rank_shown),
                make_param("compared_against", compared_against_json),
            ],
        )
        sel_rows = rows_to_dicts(result)
        selection_id = sel_rows[0]["selection_id"]
    except Exception as exc:
        print("Selection insert failed: %s" % exc)
        if "duplicate key" in str(exc) or "23505" in str(exc) or "uq_plan_selections" in str(exc):
            return respond(409, {"error": "Selection already exists for this transaction"})
        return respond(500, {"error": "Failed to persist selection"})

    selection_id = (
        int(selection_id) if isinstance(selection_id, (int, float)) else selection_id
    )

    # 7. Success
    return respond(
        201,
        {
            "selection_id": selection_id,
            "transaction_id": transaction_id,
            "plan_id": plan_id,
            "persisted_at": _iso_now(),
            "message": "Plan selection saved successfully",
        },
    )
