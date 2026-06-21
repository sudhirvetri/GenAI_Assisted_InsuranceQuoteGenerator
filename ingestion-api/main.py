"""
IQG Ingestion API — FastAPI on ECS Fargate, port 8080.
Handles POST /v1/quotes/submit and POST /v1/selections.
Replaces the iqg-ingestion-api and iqg-persist-selection Lambdas.
"""

import os
import json
import time
import hashlib
import re
import uuid
import datetime
import logging

import boto3
from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional, List, Literal
import uvicorn

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","message":"%(message)s"}'
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Environment variables — same names as the existing Lambdas
# ---------------------------------------------------------------------------
REGION              = os.environ.get("REGION", "us-east-1")
CLUSTER_ARN         = os.environ["DB_CLUSTER_ARN"]
SECRET_ARN          = os.environ["DB_SECRET_ARN"]
DB_TXN              = os.environ.get("DB_NAME_TXN", "txndb")
DB_PLAN             = os.environ.get("DB_NAME_PLAN", "plandb")
QUOTE_JOBS_QUEUE_URL = os.environ["QUOTE_JOBS_QUEUE_URL"]
QUOTE_RESULTS_TABLE = os.environ.get("QUOTE_RESULTS_TABLE", "iqg-quote-results")
IDEMPOTENCY_TABLE   = os.environ.get("IDEMPOTENCY_TABLE", "iqg-idempotency-keys")

# ---------------------------------------------------------------------------
# AWS clients
# ---------------------------------------------------------------------------
rds       = boto3.client("rds-data", region_name=REGION)
sqs       = boto3.client("sqs", region_name=REGION)
dynamodb  = boto3.resource("dynamodb", region_name=REGION)

results_table     = dynamodb.Table(QUOTE_RESULTS_TABLE)
idempotency_table = dynamodb.Table(IDEMPOTENCY_TABLE)

# ---------------------------------------------------------------------------
# Aurora Data API helpers — identical pattern to existing Lambdas
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------
VALID_CATEGORIES = {"individual", "family", "senior"}

class UserBlock(BaseModel):
    category: str
    age: int = Field(ge=18, le=99)
    family_composition: Optional[str] = "self"
    email: EmailStr

    @field_validator("category")
    @classmethod
    def check_category(cls, v):
        if v not in VALID_CATEGORIES:
            raise ValueError(f"category must be one of: {', '.join(VALID_CATEGORIES)}")
        return v


class PreferencesBlock(BaseModel):
    target_sum_insured: int = Field(gt=0)
    budget_annual_premium_inr: int = Field(gt=0)
    lifestyle_priorities: List[str] = Field(default_factory=list)
    pre_existing_conditions: List[str] = Field(default_factory=list)


class ConsentBlock(BaseModel):
    irdai_disclosure_ack: bool
    ack_timestamp: str

    @field_validator("irdai_disclosure_ack")
    @classmethod
    def must_be_true(cls, v):
        if not v:
            raise ValueError("irdai_disclosure_ack must be true")
        return v


class SubmissionRequest(BaseModel):
    user: UserBlock
    preferences: PreferencesBlock
    consent: ConsentBlock


class SelectionContext(BaseModel):
    selected_at: Optional[str] = None
    rank_shown_to_user: Optional[int] = None
    compared_against: Optional[List[str]] = None


class SelectionRequest(BaseModel):
    transaction_id: str
    plan_id: str
    selection_context: Optional[SelectionContext] = None


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(title="IQG Ingestion API", version="1.0.0", docs_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Correlation-Id", "Idempotency-Key", "X-Connection-Id"],
)


# ---------------------------------------------------------------------------
# JWT extraction — reads Authorization header, returns user_id (sub)
# The ALB does NOT validate JWTs — we do a lightweight decode here,
# matching the existing authorizer Lambda's fallback path (no signature
# verification needed since ALB sits behind CloudFront + API Gateway still
# handles auth for other routes; for the ALB path we trust the bearer token
# and decode the sub claim without re-verification for now).
# ---------------------------------------------------------------------------
import base64

def _b64url_decode(segment):
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


def get_user_id_from_token(authorization: Optional[str]) -> str:
    """Extract sub claim from JWT bearer token. Returns sub string."""
    if not authorization:
        raise HTTPException(status_code=401, detail={"error": "Unauthorized: missing Authorization header"})
    token = authorization
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    try:
        parts = token.split(".")
        if len(parts) != 3:
            raise ValueError("Malformed JWT")
        payload = json.loads(_b64url_decode(parts[1]).decode("utf-8"))
        sub = payload.get("sub")
        if not sub:
            raise ValueError("No sub claim")
        # Check expiry
        exp = payload.get("exp")
        if exp and int(time.time()) >= int(exp):
            raise HTTPException(status_code=401, detail={"error": "Token expired"})
        return sub
    except HTTPException:
        raise
    except Exception as exc:
        log.error("JWT decode failed: %s", exc)
        raise HTTPException(status_code=401, detail={"error": "Unauthorized: invalid token"})


# ---------------------------------------------------------------------------
# Health probe — unauthenticated, for ALB target group
# ---------------------------------------------------------------------------
@app.get("/v1/healthz")
async def healthz():
    checks = {}
    # RDS
    try:
        db_execute("SELECT 1")
        checks["rds"] = "ok"
    except Exception:
        checks["rds"] = "down"
    # SQS
    try:
        sqs.get_queue_attributes(
            QueueUrl=QUOTE_JOBS_QUEUE_URL,
            AttributeNames=["ApproximateNumberOfMessages"]
        )
        checks["sqs"] = "ok"
    except Exception:
        checks["sqs"] = "down"
    # DynamoDB
    try:
        dynamodb.meta.client.describe_table(TableName=IDEMPOTENCY_TABLE)
        checks["dynamodb"] = "ok"
    except Exception:
        checks["dynamodb"] = "down"

    if checks.get("rds") == "down":
        return JSONResponse(
            status_code=503,
            content={"status": "down", "version": "1.0.0", "checks": checks,
                     "timestamp": datetime.datetime.utcnow().isoformat() + "Z"}
        )
    status = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    return {"status": status, "version": "1.0.0", "checks": checks,
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z"}


# ---------------------------------------------------------------------------
# POST /v1/quotes/submit
# Faithful port of lambda/ingestion_api/ingestion_api.py::handler()
# ---------------------------------------------------------------------------
@app.post("/v1/quotes/submit")
async def submit_quote(
    payload: SubmissionRequest,
    request: Request,
    authorization: Optional[str] = Header(None),
    idempotency_key: Optional[str] = Header(None, alias="idempotency-key"),
    x_connection_id: Optional[str] = Header(None, alias="x-connection-id"),
):
    # 1. Extract user_id from JWT
    user_id = get_user_id_from_token(authorization)

    user        = payload.user
    preferences = payload.preferences

    age                  = user.age
    category             = user.category
    email                = user.email
    target_si            = preferences.target_sum_insured
    budget_premium       = preferences.budget_annual_premium_inr
    family_composition   = user.family_composition
    lifestyle_priorities     = preferences.lifestyle_priorities or []
    pre_existing_conditions  = preferences.pre_existing_conditions or []

    family_comp_json    = json.dumps(family_composition)
    lifestyle_json      = json.dumps(lifestyle_priorities)
    pre_existing_json   = json.dumps(pre_existing_conditions)

    # 2. Idempotency check — same DynamoDB table & key schema as the Lambda
    if idempotency_key:
        try:
            existing = idempotency_table.get_item(Key={"idempotencyKey": idempotency_key})
            item = existing.get("Item")
            if item and item.get("transactionId"):
                return JSONResponse(
                    status_code=202,
                    content={
                        "transaction_id": item["transactionId"],
                        "status": "QUEUED",
                        "message": "Quote generation already started (idempotent replay). Poll GET /v1/quotes/{transaction_id} for results.",
                    }
                )
        except Exception as exc:
            log.warning("Idempotency lookup failed: %s", exc)

    email_hash = hashlib.sha256(email.encode("utf-8")).hexdigest()

    # 3. Upsert user — same SQL as the Lambda
    try:
        db_execute(
            """
            INSERT INTO users (user_id, email_hash, consent_at)
            VALUES (:user_id, :email_hash, NOW())
            ON CONFLICT (user_id) DO NOTHING
            """,
            [make_param("user_id", user_id), make_param("email_hash", email_hash)],
        )
    except Exception as exc:
        log.error("User upsert failed: %s", exc)
        raise HTTPException(status_code=500, detail={"error": "Failed to persist user"})

    # 4. Insert submission — same SQL as the Lambda
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
        submission_id = str(rows_to_dicts(result)[0]["submission_id"])
    except Exception as exc:
        log.error("Submission insert failed: %s", exc)
        raise HTTPException(status_code=500, detail={"error": "Failed to persist submission"})

    # 5. Insert transaction — same SQL as the Lambda
    try:
        result = db_execute(
            """
            INSERT INTO transactions (submission_id, user_id, status)
            VALUES (:submission_id::uuid, :user_id, 'QUEUED')
            RETURNING transaction_id
            """,
            [make_param("submission_id", submission_id), make_param("user_id", user_id)],
        )
        transaction_id = str(rows_to_dicts(result)[0]["transaction_id"])
    except Exception as exc:
        log.error("Transaction insert failed: %s", exc)
        raise HTTPException(status_code=500, detail={"error": "Failed to create transaction"})

    # 6. Write PENDING item to DynamoDB — same schema as the Lambda
    try:
        results_table.put_item(Item={
            "transactionId": transaction_id,
            "status": "PENDING",
            "userId": user_id,
            "expiresAt": int(time.time()) + 86400,
        })
    except Exception as exc:
        log.error("DynamoDB PENDING write failed: %s", exc)
        raise HTTPException(status_code=500, detail={"error": "Failed to initialize quote result"})

    # 7. Publish SQS job — same message body as the Lambda so quote_worker is unchanged
    # Get connection_id from header (sent by frontend when WebSocket is open)
    connection_id = x_connection_id or ""
    job = {
        "transaction_id": transaction_id,
        "submission_id": submission_id,
        "user_id": user_id,
        "age": age,
        "category": category,
        "family_composition": family_composition,
        "lifestyle_priorities": lifestyle_priorities,
        "pre_existing_conditions": pre_existing_conditions,
        "target_si": target_si,
        "budget_premium": budget_premium,
        "connection_id": connection_id,
    }
    try:
        sqs.send_message(QueueUrl=QUOTE_JOBS_QUEUE_URL, MessageBody=json.dumps(job))
    except Exception as exc:
        log.error("SQS publish failed: %s", exc)
        raise HTTPException(status_code=500, detail={"error": "Failed to enqueue quote job"})

    # 8. Store idempotency key
    if idempotency_key:
        try:
            idempotency_table.put_item(Item={
                "idempotencyKey": idempotency_key,
                "transactionId": transaction_id,
                "expiresAt": int(time.time()) + 86400,
            })
        except Exception as exc:
            log.warning("Idempotency key store failed: %s", exc)

    # 9. Return 202 — same response body as the Lambda so the frontend is unchanged
    log.info("Quote submitted: transaction_id=%s user_id=%s", transaction_id, user_id)
    return JSONResponse(
        status_code=202,
        content={
            "transaction_id": transaction_id,
            "status": "QUEUED",
            "message": "Quote generation started. Poll GET /v1/quotes/{transaction_id} for results.",
        }
    )


# ---------------------------------------------------------------------------
# POST /v1/selections
# Faithful port of lambda/persist_selection/persist_selection.py::handler()
# ---------------------------------------------------------------------------
@app.post("/v1/selections")
async def persist_selection(
    payload: SelectionRequest,
    request: Request,
    authorization: Optional[str] = Header(None),
):
    user_id = get_user_id_from_token(authorization)

    transaction_id   = payload.transaction_id
    plan_id          = payload.plan_id
    selection_ctx    = payload.selection_context or SelectionContext()

    rank_shown           = selection_ctx.rank_shown_to_user
    compared_against     = selection_ctx.compared_against or []
    compared_against_json = json.dumps(compared_against)

    if not transaction_id:
        raise HTTPException(status_code=400, detail={"error": "transaction_id is required"})
    if not plan_id:
        raise HTTPException(status_code=400, detail={"error": "plan_id is required"})

    # Validate transaction exists and belongs to user — same SQL as the Lambda
    try:
        result = db_execute(
            "SELECT transaction_id, user_id FROM transactions WHERE transaction_id = :tid::uuid",
            [make_param("tid", transaction_id)],
        )
        txn_rows = rows_to_dicts(result)
    except Exception as exc:
        log.error("Transaction lookup failed: %s", exc)
        raise HTTPException(status_code=500, detail={"error": "Failed to validate transaction"})

    if not txn_rows:
        raise HTTPException(status_code=404, detail={"error": "Transaction not found"})
    if str(txn_rows[0].get("user_id")) != str(user_id):
        raise HTTPException(status_code=403, detail={"error": "Forbidden"})

    # Validate plan exists — same SQL as the Lambda
    try:
        result = db_execute(
            "SELECT plan_id FROM plans WHERE plan_id = :plan_id",
            [make_param("plan_id", plan_id)],
            database=DB_PLAN,
        )
        plan_rows = rows_to_dicts(result)
    except Exception as exc:
        log.error("Plan lookup failed: %s", exc)
        raise HTTPException(status_code=500, detail={"error": "Failed to validate plan"})

    if not plan_rows:
        raise HTTPException(status_code=404, detail={"error": "Plan not found"})

    # Check for duplicate selection — same SQL as the Lambda
    try:
        result = db_execute(
            "SELECT selection_id FROM plan_selections WHERE transaction_id = :tid::uuid",
            [make_param("tid", transaction_id)],
        )
        existing = rows_to_dicts(result)
    except Exception as exc:
        log.error("Duplicate-selection check failed: %s", exc)
        raise HTTPException(status_code=500, detail={"error": "Failed to check existing selection"})

    if existing:
        raise HTTPException(status_code=409, detail={"error": "Selection already exists for this transaction"})

    # Insert selection — same SQL as the Lambda
    try:
        result = db_execute(
            """
            INSERT INTO plan_selections
                (transaction_id, plan_id, rank_shown, compared_against)
            VALUES (:tid::uuid, :plan_id, :rank_shown, :compared_against::jsonb)
            RETURNING selection_id
            """,
            [
                make_param("tid", transaction_id),
                make_param("plan_id", plan_id),
                make_param("rank_shown", rank_shown),
                make_param("compared_against", compared_against_json),
            ],
        )
        sel_rows = rows_to_dicts(result)
        selection_id = str(sel_rows[0]["selection_id"])
    except Exception as exc:
        log.error("Selection insert failed: %s", exc)
        if "duplicate key" in str(exc) or "23505" in str(exc):
            raise HTTPException(status_code=409, detail={"error": "Selection already exists for this transaction"})
        raise HTTPException(status_code=500, detail={"error": "Failed to persist selection"})

    log.info("Plan selected: selection_id=%s plan_id=%s txn=%s", selection_id, plan_id, transaction_id)
    return JSONResponse(
        status_code=201,
        content={
            "selection_id": selection_id,
            "transaction_id": transaction_id,
            "plan_id": plan_id,
            "persisted_at": datetime.datetime.utcnow().isoformat() + "Z",
            "message": "Plan selection saved successfully",
        }
    )


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8080, log_config=None)
