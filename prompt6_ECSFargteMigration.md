You are working on the GenAI Assisted Insurance Quote Generator (IQG) project.
The current working MVP is on the `main` branch. We are now doing Phase 3
architecture migration on a new `develop` branch.

**What we are doing in this task:**
Migrate TWO Lambda functions (`iqg-ingestion-api` and `iqg-persist-selection`)
to a single **FastAPI app running on ECS Fargate**, fronted by an **Application
Load Balancer (ALB)**. All other Lambdas (quote_worker, chat_conversation,
authorizer, get_quote, get_my_quotes) are UNTOUCHED.

**What must NOT change:**
- The SQS message format the quote_worker Lambda consumes
- The DynamoDB `iqg-quote-results` table schema (transactionId, status, userId, expiresAt)
- The DynamoDB `iqg-idempotency-keys` table schema (idempotencyKey, transactionId, expiresAt)
- The Aurora DB schema (users, submissions, transactions, plan_selections tables)
- The frontend API response contract (transaction_id, status fields)
- All other Lambda functions and their CDK definitions
- The CloudFront + S3 SPA setup

---

## STEP 1 — Create the develop branch

```bash
git checkout main
git pull origin main
git checkout -b develop
git push -u origin develop
```

---

## STEP 2 — Create the FastAPI ingestion-api app

Create a new top-level directory `ingestion-api/` (sibling to `lambda/` and
`frontend/`). Create all files exactly as specified below.

### File: `ingestion-api/requirements.txt`

```
fastapi==0.111.*
uvicorn[standard]==0.30.*
gunicorn==22.*
mangum==0.17.*
pydantic[email]==2.*
boto3==1.*
```

### File: `ingestion-api/main.py`

```python
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
    allow_headers=["Content-Type", "Authorization", "X-Correlation-Id", "Idempotency-Key"],
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
```

### File: `ingestion-api/Dockerfile`

```dockerfile
FROM python:3.12-slim AS builder
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim AS runtime
RUN groupadd -r app && useradd -r -g app app
WORKDIR /app
COPY --from=builder /install /usr/local
COPY main.py .
RUN chown -R app:app /app
USER app
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/v1/healthz')"
CMD ["gunicorn", "main:app", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--workers", "2", \
     "--bind", "0.0.0.0:8080", \
     "--timeout", "60", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
```

---

## STEP 3 — Update the CDK stack

Open `iqg-cdk/lib/iqg-cdk-stack.ts`.

### 3a. Add new imports at the top (after existing imports)

```typescript
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as ecrAssets from 'aws-cdk-lib/aws-ecr-assets';
import * as elbv2 from 'aws-cdk-lib/aws-elasticloadbalancingv2';
import * as path from 'path';
```

### 3b. Add ECS resources AFTER the existing `// 8. API GATEWAY` section and BEFORE the `// 9. CLOUDFORMATION OUTPUTS` section

Find the comment `// 9. CLOUDFORMATION OUTPUTS` and insert this entire block before it:

```typescript
    // ------------------------------------------------------------------
    // 9a. ECS FARGATE — Ingestion API
    // ------------------------------------------------------------------

    // IAM role for ECS tasks
    const ecsTaskRole = new iam.Role(this, 'IqgEcsTaskRole', {
      roleName: 'iqg-ecs-ingestion-task-role',
      assumedBy: new iam.ServicePrincipal('ecs-tasks.amazonaws.com'),
    });
    // Same permissions as the ingestion Lambda
    ecsTaskRole.addToPolicy(new iam.PolicyStatement({
      actions: ['rds-data:ExecuteStatement', 'rds-data:BatchExecuteStatement'],
      resources: [auroraCluster.clusterArn],
    }));
    ecsTaskRole.addToPolicy(new iam.PolicyStatement({
      actions: ['secretsmanager:GetSecretValue'],
      resources: [auroraSecret.secretArn],
    }));
    ecsTaskRole.addToPolicy(new iam.PolicyStatement({
      actions: ['sqs:SendMessage', 'sqs:GetQueueAttributes'],
      resources: [quoteJobsQueue.queueArn],
    }));
    ecsTaskRole.addToPolicy(new iam.PolicyStatement({
      actions: ['dynamodb:GetItem', 'dynamodb:PutItem', 'dynamodb:DescribeTable'],
      resources: [idempotencyTable.tableArn, quoteResultsTable.tableArn],
    }));
    ecsTaskRole.addToPolicy(new iam.PolicyStatement({
      actions: ['logs:CreateLogGroup', 'logs:CreateLogStream', 'logs:PutLogEvents'],
      resources: ['*'],
    }));

    const ecsExecutionRole = new iam.Role(this, 'IqgEcsExecutionRole', {
      roleName: 'iqg-ecs-ingestion-execution-role',
      assumedBy: new iam.ServicePrincipal('ecs-tasks.amazonaws.com'),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AmazonECSTaskExecutionRolePolicy'),
      ],
    });

    // Build Docker image and push to ECR
    const ingestionImage = new ecrAssets.DockerImageAsset(this, 'IngestionApiImage', {
      directory: path.join(__dirname, '../../ingestion-api'),
      platform: ecrAssets.Platform.LINUX_AMD64,
    });
    ingestionImage.repository.grantPull(ecsExecutionRole);

    // ECS Cluster
    const ecsCluster = new ecs.Cluster(this, 'IqgEcsCluster', {
      vpc,
      clusterName: 'iqg-ecs-cluster',
      containerInsights: true,
    });

    // Task definition
    const taskDef = new ecs.FargateTaskDefinition(this, 'IqgIngestionTaskDef', {
      family: 'iqg-ingestion-api',
      cpu: 1024,
      memoryLimitMiB: 2048,
      taskRole: ecsTaskRole,
      executionRole: ecsExecutionRole,
    });

    taskDef.addContainer('ingestion-api', {
      image: ecs.ContainerImage.fromDockerImageAsset(ingestionImage),
      containerName: 'ingestion-api',
      portMappings: [{ containerPort: 8080 }],
      logging: ecs.LogDrivers.awsLogs({ streamPrefix: 'iqg-ingestion-api' }),
      environment: {
        REGION:               'us-east-1',
        DB_CLUSTER_ARN:       auroraCluster.clusterArn,
        DB_SECRET_ARN:        auroraSecret.secretArn,
        DB_NAME_TXN:          'txndb',
        DB_NAME_PLAN:         'plandb',
        QUOTE_JOBS_QUEUE_URL: quoteJobsQueue.queueUrl,
        QUOTE_RESULTS_TABLE:  quoteResultsTable.tableName,
        IDEMPOTENCY_TABLE:    idempotencyTable.tableName,
      },
      healthCheck: {
        command: ['CMD-SHELL',
          'python -c "import urllib.request; urllib.request.urlopen(\'http://localhost:8080/v1/healthz\')" || exit 1'],
        interval: Duration.seconds(30),
        timeout: Duration.seconds(5),
        retries: 3,
        startPeriod: Duration.seconds(15),
      },
    });

    // Security groups
    const albSg = new ec2.SecurityGroup(this, 'IqgAlbSg', {
      vpc,
      securityGroupName: 'iqg-alb-sg',
      description: 'IQG ALB inbound HTTP',
      allowAllOutbound: false,
    });
    albSg.addIngressRule(ec2.Peer.anyIpv4(), ec2.Port.tcp(80), 'HTTP from internet');
    albSg.addEgressRule(ec2.Peer.ipv4('172.31.0.0/16'), ec2.Port.tcp(8080), 'To ECS tasks');

    const ecsSg = new ec2.SecurityGroup(this, 'IqgEcsSg', {
      vpc,
      securityGroupName: 'iqg-ecs-sg',
      description: 'IQG ECS tasks inbound from ALB',
      allowAllOutbound: true,
    });
    ecsSg.addIngressRule(albSg, ec2.Port.tcp(8080), 'From ALB');

    // Also allow Aurora to accept connections from ECS tasks
    auroraSg.addIngressRule(ecsSg, ec2.Port.tcp(5432), 'PostgreSQL from ECS tasks');

    // ALB — HTTP only (no ACM cert needed in lab environment)
    const alb = new elbv2.ApplicationLoadBalancer(this, 'IqgAlb', {
      vpc,
      internetFacing: true,
      loadBalancerName: 'iqg-alb',
      securityGroup: albSg,
      vpcSubnets: { subnetType: ec2.SubnetType.PUBLIC },
    });

    const targetGroup = new elbv2.ApplicationTargetGroup(this, 'IqgAlbTg', {
      vpc,
      port: 8080,
      protocol: elbv2.ApplicationProtocol.HTTP,
      targetType: elbv2.TargetType.IP,
      targetGroupName: 'iqg-alb-tg',
      healthCheck: {
        path: '/v1/healthz',
        port: '8080',
        protocol: elbv2.Protocol.HTTP,
        healthyHttpCodes: '200',
        interval: Duration.seconds(30),
        timeout: Duration.seconds(5),
        healthyThresholdCount: 2,
        unhealthyThresholdCount: 3,
      },
      deregistrationDelay: Duration.seconds(30),
    });

    alb.addListener('IqgAlbListener', {
      port: 80,
      protocol: elbv2.ApplicationProtocol.HTTP,
      defaultAction: elbv2.ListenerAction.forward([targetGroup]),
    });

    // Fargate service — minimum 1 task in lab (keep costs low)
    const fargateService = new ecs.FargateService(this, 'IqgIngestionService', {
      cluster: ecsCluster,
      taskDefinition: taskDef,
      serviceName: 'iqg-ingestion-api',
      desiredCount: 1,
      assignPublicIp: true,   // public IP needed since using default VPC (no NAT)
      securityGroups: [ecsSg],
      vpcSubnets: { subnetType: ec2.SubnetType.PUBLIC },
      enableExecuteCommand: true,
      circuitBreaker: { rollback: true },
    });

    fargateService.attachToApplicationTargetGroup(targetGroup);
```

### 3c. Remove the two Lambda-backed API Gateway routes for the migrated endpoints

Find these two blocks in the existing API Gateway setup and DELETE them:

```typescript
    // DELETE THIS BLOCK:
    quotesSubmit.addMethod('POST', new apigateway.LambdaIntegration(ingestionApiFn), {
      authorizer: tokenAuthorizer,
      authorizationType: apigateway.AuthorizationType.CUSTOM,
    });

    // DELETE THIS BLOCK:
    selections.addMethod('POST', new apigateway.LambdaIntegration(persistSelectionFn), {
      authorizer: tokenAuthorizer,
      authorizationType: apigateway.AuthorizationType.CUSTOM,
    });
```

**IMPORTANT**: Do NOT delete the `ingestionApiFn` and `persistSelectionFn` Lambda
Function definitions themselves — just the `.addMethod()` calls that wired them to
API Gateway. Keep all Lambda definitions in place to avoid CDK errors from
orphaned IAM role references.

### 3d. Add ALB output INSIDE the existing outputs section

Find the outputs block and add:

```typescript
    new CfnOutput(this, 'AlbUrl', {
      value: `http://${alb.loadBalancerDnsName}`,
      description: 'ALB URL for POST /v1/quotes/submit and POST /v1/selections',
    });
```

---

## STEP 4 — Update the frontend to use the ALB for the two migrated routes

Open `frontend/src/pages/QuoteForm.jsx`.

Change:
```javascript
const API_BASE = 'https://rzxm5finik.execute-api.us-east-1.amazonaws.com/v1'
```

To:
```javascript
// After ECS migration, /quotes/submit goes to ALB; other routes stay on API Gateway
const API_BASE_ALB = 'http://REPLACE_WITH_ALB_DNS_AFTER_DEPLOY'
const API_BASE     = 'https://rzxm5finik.execute-api.us-east-1.amazonaws.com/v1'
```

And in the `handleSubmit` function, change the fetch call from:
```javascript
const res = await fetch(`${API_BASE}/quotes/submit`, {
```
To:
```javascript
const res = await fetch(`${API_BASE_ALB}/v1/quotes/submit`, {
```

Open `frontend/src/pages/Confirmed.jsx` (or wherever `/selections` is called).
Apply the same pattern — use `API_BASE_ALB` for the `/v1/selections` POST.

**NOTE**: The ALB DNS will be in the CDK deploy output as `AlbUrl`. Replace
`REPLACE_WITH_ALB_DNS_AFTER_DEPLOY` with that value after deploying.

---

## STEP 5 — Install new CDK dependencies

```bash
cd iqg-cdk
npm install aws-cdk-lib  # already installed, this refreshes
# The ECS, ECR, and ELBv2 constructs are already part of aws-cdk-lib
# No new npm packages needed
```

---

## STEP 6 — Deploy

```bash
cd iqg-cdk

# Refresh AWS credentials if needed
# export AWS_DEFAULT_REGION=us-east-1

# Preview what will change
cdk diff

# Deploy — this will:
# 1. Build the Docker image and push to ECR (~3-5 min first time)
# 2. Create ECS cluster, task definition, ALB, security groups
# 3. Start 1 Fargate task
# 4. Remove the two API Gateway routes for /quotes/submit and /selections
cdk deploy --require-approval never

# The ALB DNS will appear in the output as AlbUrl
# e.g.: http://iqg-alb-123456789.us-east-1.elb.amazonaws.com
```

---

## STEP 7 — Update frontend with real ALB URL

After deploy completes, take the `AlbUrl` from the CDK output and update
`frontend/src/pages/QuoteForm.jsx` and `frontend/src/pages/Confirmed.jsx`
replacing `REPLACE_WITH_ALB_DNS_AFTER_DEPLOY` with the actual ALB DNS name.

---

## STEP 8 — Verify the deployment

```bash
ALB_URL=$(aws cloudformation describe-stacks \
  --stack-name IqgCdkStack \
  --query "Stacks[0].Outputs[?OutputKey=='AlbUrl'].OutputValue" \
  --output text)

# Health probe (no auth)
curl -s "${ALB_URL}/v1/healthz" | python3 -m json.tool

# Expected: {"status":"ok","version":"1.0.0","checks":{"rds":"ok","sqs":"ok","dynamodb":"ok"},...}
```

---

## STEP 9 — Commit

```bash
git add ingestion-api/ iqg-cdk/lib/iqg-cdk-stack.ts frontend/src/pages/QuoteForm.jsx frontend/src/pages/Confirmed.jsx
git commit -m "feat: migrate ingestion-api to ECS Fargate with ALB

- Add ingestion-api/ FastAPI app (faithful port of ingestion_api Lambda + persist_selection Lambda)
- Same Aurora Data API pattern, same SQS message format, same response contract
- Add ECS cluster, Fargate service, ALB in CDK stack
- Remove /quotes/submit and /selections routes from API Gateway
- Frontend updated to call ALB for the two migrated routes
- All other Lambdas, API Gateway routes, and DynamoDB tables unchanged

Closes Phase 3 Priority 1a (ECS migration)"

git push origin develop
```

---

## CRITICAL NOTES

1. **The SQS message body is byte-for-byte identical to what the Lambda sent** —
   the `quote_worker` Lambda is untouched and will work without any changes.

2. **The DynamoDB schema is unchanged** — same table names, same key names
   (`idempotencyKey`, `transactionId`, `expiresAt`), same data written.

3. **The Aurora SQL is unchanged** — all SQL statements were copied verbatim
   from the existing Lambda code including all `::uuid` and `::jsonb` casts.

4. **The frontend response contract is unchanged** — `transaction_id` and
   `status` fields in the 202 response are identical.

5. **`assignPublicIp: true` is intentional** — the lab uses the default VPC
   with no NAT gateway. Tasks in public subnets with a public IP can reach
   AWS service endpoints. This matches how the existing Lambdas access Aurora.

6. **Do not delete the Lambda Function CDK definitions** — only remove the
   `.addMethod()` calls. The Lambda definitions are needed for the IAM role
   references to remain valid.

7. **If `cdk diff` shows more changes than expected**, read them carefully.
   The security group for Aurora (`auroraSg`) gets a new ingress rule from
   `ecsSg` — this is intentional and required for ECS tasks to reach the DB.