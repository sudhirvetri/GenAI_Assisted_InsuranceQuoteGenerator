"""
Quote Worker - SQS-triggered (batchSize=1).

For each quote job:
  1. Loads candidate plans from plandb.plans (filtered by category + age).
  2. Builds a system + user prompt and calls Bedrock (Claude Sonnet 4.6).
  3. Parses the model's JSON recommendations (one strict retry on parse failure).
  4. Writes the COMPLETE result to DynamoDB, marks the transaction COMPLETE in
     Aurora, and writes a privacy-safe audit record to S3.

On any unrecoverable error the transaction is marked FAILED in DynamoDB.
"""

import os
import json
import time
import datetime
from decimal import Decimal

import boto3

REGION = os.environ.get("REGION", "us-east-1")
CLUSTER_ARN = os.environ["DB_CLUSTER_ARN"]
SECRET_ARN = os.environ["DB_SECRET_ARN"]
DB_TXN = os.environ.get("DB_NAME_TXN", "txndb")
DB_PLAN = os.environ.get("DB_NAME_PLAN", "plandb")

QUOTE_RESULTS_TABLE = os.environ.get("QUOTE_RESULTS_TABLE", "iqg-quote-results")
AUDIT_BUCKET = os.environ.get("AUDIT_BUCKET", "")
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-6")
WS_ENDPOINT = os.environ.get("WS_ENDPOINT", "")
WS_CONNECTIONS_TABLE = os.environ.get("WS_CONNECTIONS_TABLE", "iqg-ws-connections")

rds = boto3.client("rds-data", region_name=REGION)
bedrock = boto3.client("bedrock-runtime", region_name=REGION)
s3 = boto3.client("s3", region_name=REGION)
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
            val = list(field.values())[0] if field else None
            row[col] = val
        rows.append(row)
    return rows


def enrich_recommendations(recommendations, plans_map):
    """Merge full plan DB fields into each Bedrock recommendation."""
    enriched = []
    for rec in recommendations:
        plan_id = rec.get("plan_id", "")
        full_plan = plans_map.get(plan_id, {})
        merged = {
            # Bedrock fields
            "plan_id": plan_id,
            "plan_name": rec.get("plan_name", full_plan.get("plan_name", "")),
            "annual_premium": rec.get("annual_premium", full_plan.get("annual_premium_base", 0)),
            "sum_insured": rec.get("sum_insured", full_plan.get("sum_insured", 0)),
            "reason": rec.get("reason", ""),
            "highlights": rec.get("highlights", []),
            # Full plan fields from DB
            "tier": full_plan.get("tier", ""),
            "category": full_plan.get("category", ""),
            "co_payment_pct": full_plan.get("co_payment_pct", rec.get("co_payment_pct", 0)),
            "room_rent_limit": full_plan.get("room_rent_limit", ""),
            "ped_waiting_months": full_plan.get("ped_waiting_months", rec.get("ped_waiting_months", 0)),
            "initial_waiting_days": full_plan.get("initial_waiting_days", 30),
            "no_claim_bonus_pct": full_plan.get("no_claim_bonus_pct", 0),
            "max_ncb_pct": full_plan.get("max_ncb_pct", 0),
            "restoration_benefit": full_plan.get("restoration_benefit", False),
            "daycare_covered": full_plan.get("daycare_covered", False),
            "ambulance_cover": full_plan.get("ambulance_cover", 0),
            "ayush_covered": full_plan.get("ayush_covered", False),
            "maternity_covered": full_plan.get("maternity_covered", False),
            "annual_checkup": full_plan.get("annual_checkup", False),
            "network_hospitals": full_plan.get("network_hospitals", 0),
            "critical_illness_cover": full_plan.get("critical_illness_cover", False),
            "teleconsult": full_plan.get("teleconsult", False),
            "policy_tenure_options": full_plan.get("policy_tenure_options", "1/2/3"),
            "renewability": full_plan.get("renewability", "Lifelong"),
            "key_exclusions": full_plan.get("key_exclusions", ""),
            "best_for": full_plan.get("best_for", ""),
        }
        enriched.append(merged)
    return enriched


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


def _iso_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _to_dynamo_safe(obj):
    """Recursively convert floats to Decimal for DynamoDB storage."""
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, list):
        return [_to_dynamo_safe(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _to_dynamo_safe(v) for k, v in obj.items()}
    return obj


# --------------------------------------------------------------------------- #
# Status helpers
# --------------------------------------------------------------------------- #
def _mark_failed(transaction_id, user_id, message):
    try:
        results_table.put_item(
            Item={
                "transactionId": transaction_id,
                "status": "FAILED",
                "userId": user_id,
                "error": message,
                "expiresAt": int(time.time()) + 86400,
            }
        )
    except Exception as exc:
        print("Failed to write FAILED status: %s" % exc)
    try:
        db_execute(
            "UPDATE transactions SET status = 'FAILED' WHERE transaction_id = :tid::uuid",
            [make_param("tid", transaction_id)],
        )
    except Exception as exc:
        print("Failed to mark transaction FAILED in Aurora: %s" % exc)


# --------------------------------------------------------------------------- #
# Prompt building
# --------------------------------------------------------------------------- #
SYSTEM_PROMPT = (
    "You are a health insurance advisor for SwiftCare Health Insurance.\n"
    "Recommend the TOP 3 most suitable plans from the provided plan catalog\n"
    "for the user profile below. Use the best_for field as the primary\n"
    "semantic match signal. Reject any plan whose key_exclusions contradict\n"
    "the user's stated needs. Return ONLY valid JSON matching the output format.\n"
    "Do not include any text outside the JSON."
)

OUTPUT_FORMAT = (
    "{\n"
    '  "recommendations": [\n'
    "    {\n"
    '      "plan_id": "...",\n'
    '      "plan_name": "...",\n'
    '      "annual_premium": 0,\n'
    '      "sum_insured": 0,\n'
    '      "reason": "2-3 sentence explanation",\n'
    '      "highlights": ["benefit1", "benefit2", "benefit3"],\n'
    '      "co_payment_pct": 0,\n'
    '      "ped_waiting_months": 0\n'
    "    }\n"
    "  ]\n"
    "}"
)


def build_user_prompt(job, plans):
    pre_existing = job.get("pre_existing_conditions")
    if not pre_existing:
        pre_existing = "None declared"
    lifestyle = job.get("lifestyle_priorities")
    if not lifestyle:
        lifestyle = "None declared"

    plans_json = json.dumps(plans, indent=2, default=str)

    return (
        "USER PROFILE:\n"
        "- Age: {age}, Category: {category}\n"
        "- Family composition: {family}\n"
        "- Budget (annual premium INR): up to {budget}\n"
        "- Pre-existing conditions: {pre_existing}\n"
        "- Lifestyle priorities: {lifestyle}\n\n"
        "PLAN CATALOG ({n} candidates):\n"
        "{plans_json}\n\n"
        "OUTPUT FORMAT (return ONLY this JSON, no other text):\n"
        "{output_format}"
    ).format(
        age=job.get("age"),
        category=job.get("category"),
        family=job.get("family_composition"),
        budget=job.get("budget_premium"),
        pre_existing=pre_existing,
        lifestyle=lifestyle,
        n=len(plans),
        plans_json=plans_json,
        output_format=OUTPUT_FORMAT,
    )


# --------------------------------------------------------------------------- #
# Bedrock
# --------------------------------------------------------------------------- #
def invoke_bedrock(system_prompt, user_prompt, max_tokens=2000):
    response = bedrock.invoke_model(
        modelId=BEDROCK_MODEL_ID,
        body=json.dumps(
            {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": max_tokens,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_prompt}],
            }
        ),
        contentType="application/json",
        accept="application/json",
    )
    body = json.loads(response["body"].read())
    return body["content"][0]["text"]


def _extract_json(text):
    """
    Parse the model output as JSON. Tolerates fenced code blocks and leading /
    trailing prose by extracting the outermost JSON object.
    """
    text = text.strip()
    if text.startswith("```"):
        # Strip a leading ```json / ``` fence and trailing fence.
        segments = text.split("```")
        if len(segments) >= 2:
            inner = segments[1]
            if inner.startswith("json"):
                inner = inner[4:]
            text = inner.strip()

    # Direct parse first.
    try:
        return json.loads(text)
    except ValueError:
        pass

    # Fallback: slice from first '{' to last '}'.
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(text[start : end + 1])

    raise ValueError("No JSON object found in model output")


# --------------------------------------------------------------------------- #
# S3 audit
# --------------------------------------------------------------------------- #
def write_audit(transaction_id, user_id, plans_considered, recommendations_count):
    if not AUDIT_BUCKET:
        return
    now = datetime.datetime.now(datetime.timezone.utc)
    key = "year={y}/month={m:02d}/day={d:02d}/{tid}.json".format(
        y=now.year, m=now.month, d=now.day, tid=transaction_id
    )
    audit = {
        "transaction_id": transaction_id,
        "user_id": user_id,
        "model_id": BEDROCK_MODEL_ID,
        "plans_considered": plans_considered,
        "recommendations_count": recommendations_count,
        "completed_at": now.isoformat(),
    }
    try:
        s3.put_object(
            Bucket=AUDIT_BUCKET,
            Key=key,
            Body=json.dumps(audit).encode("utf-8"),
            ContentType="application/json",
        )
    except Exception as exc:
        print("S3 audit write failed (non-fatal): %s" % exc)


def push_quote_result_via_websocket(connection_id, transaction_id, recommendations):
    """
    Push the completed quote result to the browser via WebSocket.
    Best-effort — failures are logged but do not fail the job
    since the result is already safely stored in DynamoDB.
    """
    if not connection_id or not WS_ENDPOINT:
        return
    try:
        apigw = boto3.client(
            "apigatewaymanagementapi",
            endpoint_url=WS_ENDPOINT,
            region_name=REGION,
        )
        payload = {
            "type": "quote_complete",
            "transaction_id": transaction_id,
            "recommendations": recommendations,
        }
        apigw.post_to_connection(
            ConnectionId=connection_id,
            Data=json.dumps(payload, default=str).encode("utf-8"),
        )
        print("Pushed quote result to WebSocket: connection_id=%s" % connection_id)
    except Exception as exc:
        # GoneException = browser disconnected mid-wait, which is fine
        print("WebSocket push failed (non-fatal): %s" % exc)


# --------------------------------------------------------------------------- #
# Core processing
# --------------------------------------------------------------------------- #
def process_job(job):
    transaction_id = str(job["transaction_id"])
    user_id = job["user_id"]
    age = job["age"]
    category = job["category"]

    # 3. Load candidate plans
    try:
        result = db_execute(
            """
            SELECT * FROM plans
            WHERE category = :category
              AND min_age <= :age
              AND max_age >= :age
            ORDER BY annual_premium_base ASC
            """,
            [
                make_param("category", category),
                make_param("age", age),
            ],
            database=DB_PLAN,
        )
        plans = rows_to_dicts(result)
    except Exception as exc:
        print("Plan query failed: %s" % exc)
        _mark_failed(transaction_id, user_id, "Failed to load plan catalog")
        return

    # 4. No plans -> FAILED
    if not plans:
        _mark_failed(
            transaction_id,
            user_id,
            "No eligible plans found for the provided profile",
        )
        return

    # 5. Build prompts
    user_prompt = build_user_prompt(job, plans)

    # 6 & 7. Call Bedrock, parse, retry once on parse failure
    recommendations = None
    try:
        text = invoke_bedrock(SYSTEM_PROMPT, user_prompt, max_tokens=2000)
        parsed = _extract_json(text)
        recommendations = parsed.get("recommendations")
        if not isinstance(recommendations, list):
            raise ValueError("'recommendations' missing or not a list")
    except Exception as exc:
        print(
            "First Bedrock attempt failed: %s - retrying with stricter prompt"
            % exc
        )
        strict_system = (
            SYSTEM_PROMPT
            + "\n\nCRITICAL: Your previous response could not be parsed. "
            "Respond with ONLY a single valid JSON object and absolutely no "
            "other text, markdown, or code fences."
        )
        try:
            text = invoke_bedrock(strict_system, user_prompt, max_tokens=2000)
            parsed = _extract_json(text)
            recommendations = parsed.get("recommendations")
            if not isinstance(recommendations, list):
                raise ValueError("'recommendations' missing or not a list")
        except Exception as exc2:
            print("Second Bedrock attempt failed: %s" % exc2)
            _mark_failed(
                transaction_id,
                user_id,
                "Model did not return parseable recommendations",
            )
            return

    # 8. Enrich recommendations with full plan details, then write to DynamoDB
    plans_map = {p["plan_id"]: p for p in plans}
    enriched_recommendations = enrich_recommendations(recommendations, plans_map)
    try:
        results_table.put_item(
            Item=_to_dynamo_safe(
                {
                    "transactionId": transaction_id,
                    "status": "COMPLETE",
                    "userId": user_id,
                    "recommendations": enriched_recommendations,
                    "modelId": BEDROCK_MODEL_ID,
                    "plansConsidered": len(plans),
                    "completedAt": _iso_now(),
                    "expiresAt": int(time.time()) + 86400,
                }
            )
        )
    except Exception as exc:
        print("DynamoDB COMPLETE write failed: %s" % exc)
        _mark_failed(transaction_id, user_id, "Failed to persist recommendations")
        return

    # 9. Mark transaction COMPLETE in Aurora
    try:
        db_execute(
            "UPDATE transactions SET status = 'COMPLETE' WHERE transaction_id = :tid::uuid",
            [make_param("tid", transaction_id)],
        )
    except Exception as exc:
        # Result is already stored; log but don't fail the job.
        print("Failed to mark transaction COMPLETE in Aurora: %s" % exc)

    # 10. Privacy-safe audit to S3
    write_audit(transaction_id, user_id, len(plans), len(enriched_recommendations))

    # 11. Push result to browser via WebSocket (best-effort)
    connection_id = job.get("connection_id", "")
    push_quote_result_via_websocket(
        connection_id, transaction_id, enriched_recommendations
    )


def handler(event, context):
    records = event.get("Records", [])
    for record in records:
        try:
            job = json.loads(record["body"])
        except (ValueError, KeyError) as exc:
            print("Skipping malformed SQS record: %s" % exc)
            continue

        try:
            process_job(job)
        except Exception as exc:
            # Last-resort guard so one bad job doesn't crash the batch.
            print("Unhandled error processing job: %s" % exc)
            tid = job.get("transaction_id")
            uid = job.get("user_id")
            if tid:
                _mark_failed(str(tid), uid, "Internal processing error")

    return {"statusCode": 200, "processed": len(records)}


