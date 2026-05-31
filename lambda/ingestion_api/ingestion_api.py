"""
Ingestion API - handles POST /v1/quotes/submit

Validates the incoming quote request, upserts the user, records a submission and
a transaction in Aurora (txndb), writes a PENDING result item to DynamoDB,
and publishes a job to SQS for the async quote worker. Supports idempotency via
the Idempotency-Key header.
"""

import os
import json
import time
import hashlib
import re

import boto3

REGION = os.environ.get("REGION", "us-east-1")
CLUSTER_ARN = os.environ["DB_CLUSTER_ARN"]
SECRET_ARN = os.environ["DB_SECRET_ARN"]
DB_TXN = os.environ.get("DB_NAME_TXN", "txndb")
DB_PLAN = os.environ.get("DB_NAME_PLAN", "plandb")

QUOTE_JOBS_QUEUE_URL = os.environ["QUOTE_JOBS_QUEUE_URL"]
QUOTE_RESULTS_TABLE = os.environ.get("QUOTE_RESULTS_TABLE", "iqg-quote-results")
IDEMPOTENCY_TABLE = os.environ.get("IDEMPOTENCY_TABLE", "iqg-idempotency-keys")

rds = boto3.client("rds-data", region_name=REGION)
sqs = boto3.client("sqs", region_name=REGION)
dynamodb = boto3.resource("dynamodb", region_name=REGION)

results_table = dynamodb.Table(QUOTE_RESULTS_TABLE)
idempotency_table = dynamodb.Table(IDEMPOTENCY_TABLE)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
VALID_CATEGORIES = {"individual", "family", "senior"}


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


# --------------------------------------------------------------------------- #
# Response helper
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
def validate_payload(payload):
    """Return a list of error strings; empty list means valid."""
    errors = []

    user = payload.get("user") or {}
    preferences = payload.get("preferences") or {}
    consent = payload.get("consent") or {}

    category = user.get("category")
    if category not in VALID_CATEGORIES:
        errors.append(
            "user.category must be one of: individual, family, senior"
        )

    age = user.get("age")
    if not isinstance(age, int) or isinstance(age, bool) or not (18 <= age <= 99):
        errors.append("user.age must be an integer between 18 and 99")

    email = user.get("email")
    if not isinstance(email, str) or not EMAIL_RE.match(email or ""):
        errors.append("user.email must be a valid email address")

    target_si = preferences.get("target_sum_insured")
    if not isinstance(target_si, int) or isinstance(target_si, bool) or target_si <= 0:
        errors.append("preferences.target_sum_insured must be an integer > 0")

    budget = preferences.get("budget_annual_premium_inr")
    if not isinstance(budget, int) or isinstance(budget, bool) or budget <= 0:
        errors.append(
            "preferences.budget_annual_premium_inr must be an integer > 0"
        )

    if consent.get("irdai_disclosure_ack") is not True:
        errors.append("consent.irdai_disclosure_ack must be true")

    return errors


def _get_header(headers, name):
    """Case-insensitive header lookup."""
    if not headers:
        return None
    lname = name.lower()
    for k, v in headers.items():
        if k.lower() == lname:
            return v
    return None


# --------------------------------------------------------------------------- #
# Handler
# --------------------------------------------------------------------------- #
def handler(event, context):
    # Parse body
    try:
        raw_body = event.get("body") or "{}"
        if isinstance(raw_body, (dict, list)):
            payload = raw_body
        else:
            payload = json.loads(raw_body)
    except (ValueError, TypeError):
        return respond(400, {"error": "Invalid JSON body"})

    # Validate
    errors = validate_payload(payload)
    if errors:
        return respond(400, {"error": "Validation failed", "details": errors})

    # Extract authorizer context
    try:
        user_id = event["requestContext"]["authorizer"]["userId"]
    except (KeyError, TypeError):
        return respond(401, {"error": "Unauthorized: missing user context"})

    user = payload["user"]
    preferences = payload["preferences"]

    age = user["age"]
    category = user["category"]
    email = user["email"]
    target_si = preferences["target_sum_insured"]
    budget_premium = preferences["budget_annual_premium_inr"]

    family_composition = user.get("family_composition")
    lifestyle_priorities = payload.get("lifestyle_priorities") or user.get(
        "lifestyle_priorities"
    )
    pre_existing_conditions = payload.get("pre_existing_conditions") or user.get(
        "pre_existing_conditions"
    )

    # JSON-encode the structured fields for storage / messaging
    family_comp_json = json.dumps(family_composition) if family_composition is not None else None
    lifestyle_json = json.dumps(lifestyle_priorities) if lifestyle_priorities is not None else json.dumps([])
    pre_existing_json = json.dumps(pre_existing_conditions) if pre_existing_conditions is not None else json.dumps([])

    headers = event.get("headers") or {}
    idempotency_key = _get_header(headers, "Idempotency-Key")

    # ----------------------------------------------------------------- #
    # Idempotency check
    # ----------------------------------------------------------------- #
    if idempotency_key:
        try:
            existing = idempotency_table.get_item(
                Key={"idempotencyKey": idempotency_key}
            )
            item = existing.get("Item")
            if item and item.get("transactionId"):
                return respond(
                    202,
                    {
                        "transaction_id": item["transactionId"],
                        "status": "QUEUED",
                        "message": "Quote generation already started (idempotent replay). Poll GET /v1/quotes/{transaction_id} for results.",
                    },
                )
        except Exception as exc:
            # Non-fatal: log and continue without idempotency short-circuit.
            print("Idempotency lookup failed: %s" % exc)

    email_hash = hashlib.sha256(email.encode("utf-8")).hexdigest()

    # ----------------------------------------------------------------- #
    # 4. Upsert user
    # ----------------------------------------------------------------- #
    try:
        db_execute(
            """
            INSERT INTO users (user_id, email_hash, consent_at)
            VALUES (:user_id, :email_hash, NOW())
            ON CONFLICT (user_id) DO NOTHING
            """,
            [
                make_param("user_id", user_id),
                make_param("email_hash", email_hash),
            ],
        )
    except Exception as exc:
        print("User upsert failed: %s" % exc)
        return respond(500, {"error": "Failed to persist user"})

    # ----------------------------------------------------------------- #
    # 5. Insert submission
    # ----------------------------------------------------------------- #
    try:
        result = db_execute(
            """
            INSERT INTO submissions (user_id, age, category, family_composition,
                lifestyle_json, pre_existing_json, target_si, budget_premium)
            VALUES (:user_id, :age, :category, :family_composition::jsonb,
                :lifestyle_json::jsonb, :pre_existing_json::jsonb, :target_si, :budget_premium)
            RETURNING submission_id
            """,
            [
                make_param("user_id", user_id),
                make_param("age", age),
                make_param("category", category),
                make_param("family_composition", family_comp_json),
                make_param("lifestyle_json", lifestyle_json),
                make_param("pre_existing_json", pre_existing_json),
                make_param("target_si", target_si),
                make_param("budget_premium", budget_premium),
            ],
        )
        submission_rows = rows_to_dicts(result)
        submission_id = submission_rows[0]["submission_id"]
    except Exception as exc:
        print("Submission insert failed: %s" % exc)
        return respond(500, {"error": "Failed to persist submission"})

    # ----------------------------------------------------------------- #
    # 6. Insert transaction
    # ----------------------------------------------------------------- #
    try:
        result = db_execute(
            """
            INSERT INTO transactions (submission_id, user_id, status)
            VALUES (:submission_id::uuid, :user_id, 'QUEUED')
            RETURNING transaction_id
            """,
            [
                make_param("submission_id", submission_id),
                make_param("user_id", user_id),
            ],
        )
        txn_rows = rows_to_dicts(result)
        transaction_id = txn_rows[0]["transaction_id"]
    except Exception as exc:
        print("Transaction insert failed: %s" % exc)
        return respond(500, {"error": "Failed to create transaction"})

    transaction_id = str(transaction_id)
    submission_id = (
        int(submission_id) if isinstance(submission_id, (int, float)) else submission_id
    )

    # ----------------------------------------------------------------- #
    # 7. Write PENDING item to DynamoDB
    # ----------------------------------------------------------------- #
    try:
        results_table.put_item(
            Item={
                "transactionId": transaction_id,
                "status": "PENDING",
                "userId": user_id,
                "expiresAt": int(time.time()) + 86400,
            }
        )
    except Exception as exc:
        print("DynamoDB PENDING write failed: %s" % exc)
        return respond(500, {"error": "Failed to initialize quote result"})

    # ----------------------------------------------------------------- #
    # 8. Publish job to SQS
    # ----------------------------------------------------------------- #
    job = {
        "transaction_id": transaction_id,
        "submission_id": submission_id,
        "user_id": user_id,
        "age": age,
        "category": category,
        "family_composition": family_composition,
        "lifestyle_priorities": lifestyle_priorities if lifestyle_priorities is not None else [],
        "pre_existing_conditions": pre_existing_conditions if pre_existing_conditions is not None else [],
        "target_si": target_si,
        "budget_premium": budget_premium,
    }
    try:
        sqs.send_message(
            QueueUrl=QUOTE_JOBS_QUEUE_URL,
            MessageBody=json.dumps(job),
        )
    except Exception as exc:
        print("SQS publish failed: %s" % exc)
        return respond(500, {"error": "Failed to enqueue quote job"})

    # ----------------------------------------------------------------- #
    # 9. Store idempotency key (best effort)
    # ----------------------------------------------------------------- #
    if idempotency_key:
        try:
            idempotency_table.put_item(
                Item={
                    "idempotencyKey": idempotency_key,
                    "transactionId": transaction_id,
                    "expiresAt": int(time.time()) + 86400,
                }
            )
        except Exception as exc:
            print("Idempotency key store failed: %s" % exc)

    # ----------------------------------------------------------------- #
    # 10. Success
    # ----------------------------------------------------------------- #
    return respond(
        202,
        {
            "transaction_id": transaction_id,
            "status": "QUEUED",
            "message": "Quote generation started. Poll GET /v1/quotes/{transaction_id} for results.",
        },
    )
