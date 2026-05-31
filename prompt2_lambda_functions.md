# Lambda Functions Implementation

Write complete Python 3.12 Lambda function code for the GenAI Insurance Quote Generator.

## Shared context for ALL functions:
- AWS Region: us-east-1
- Aurora Cluster ARN: arn:aws:rds:us-east-1:867344470917:cluster:iqg-aurora-cluster
- Aurora Secret ARN: arn:aws:secretsmanager:us-east-1:867344470917:secret:AuroraSecret41E6E877-ogZqDVP4P1dt-JcOo7c
- DB txndb: users, submissions, transactions, plan_selections, audit_log tables
- DB plandb: plans table (30 SwiftCare plans)
- All env vars are pre-set (read from os.environ)
- Use boto3 rds-data client for ALL DB calls (Aurora Data API) - NO psycopg2
- Bedrock model: anthropic.claude-sonnet-4-6
- Return format for ALL REST Lambdas:
  {
    "statusCode": 200,
    "headers": {
      "Content-Type": "application/json",
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Headers": "Content-Type,Authorization,X-Correlation-Id,Idempotency-Key",
      "Access-Control-Allow-Methods": "OPTIONS,GET,POST"
    },
    "body": json.dumps({...})
  }

## Environment variables available in all Lambdas:
- REGION
- DB_CLUSTER_ARN
- DB_SECRET_ARN
- DB_NAME_TXN (= "txndb")
- DB_NAME_PLAN (= "plandb")
- QUOTE_JOBS_QUEUE_URL
- QUOTE_RESULTS_TABLE (= "iqg-quote-results")
- CHAT_HISTORY_TABLE (= "iqg-chat-history")
- AUDIT_BUCKET
- BEDROCK_MODEL_ID (= "anthropic.claude-sonnet-4-6")
- USER_POOL_ID
- USER_POOL_CLIENT_ID

---

## FILE 1: lambda/authorizer/authorizer.py

JWT Token Authorizer for API Gateway.

Logic:
1. Extract token from event["authorizationToken"] - strip "Bearer " prefix
2. Decode JWT header to get "kid" (key ID) - use base64 decode, NO external libraries
3. Fetch Cognito JWKS from:
   https://cognito-idp.us-east-1.amazonaws.com/{USER_POOL_ID}/.well-known/jwks.json
   Cache in module-level dict keyed by kid, expire after 300 seconds
4. Find the matching key by kid
5. Verify the JWT signature using the public key
   - Use PyJWT library: import jwt as pyjwt
   - pyjwt.decode(token, public_key, algorithms=["RS256"], options={"verify_aud": False})
6. Extract sub claim as user_id
7. Return IAM policy:
   - Effect: "Allow" if valid, "Deny" if invalid
   - Resource: event["methodArn"]
   - Context: {"userId": sub, "email": email claim if present}

Handle these errors gracefully (return Deny policy, never raise):
- Token missing
- Token expired
- Invalid signature
- JWKS fetch failure

Note: PyJWT is NOT available by default. Use a fallback:
- Try: import jwt as pyjwt
- Except ImportError: implement manual JWT validation using only stdlib
  (base64, json, hmac - just decode without verification for lab purposes,
   extract claims from payload section)

---

## FILE 2: lambda/ingestion_api/ingestion_api.py

Handles POST /v1/quotes/submit

Logic:
1. Parse and validate request body (JSON):
   Required fields:
   - user.category: must be one of "individual", "family", "senior"
   - user.age: integer 18-99
   - user.email: string, basic format check
   - preferences.target_sum_insured: integer > 0
   - preferences.budget_annual_premium_inr: integer > 0
   - consent.irdai_disclosure_ack: must be True
   Return 400 with error details if validation fails.

2. Extract user_id from authorizer context:
   user_id = event["requestContext"]["authorizer"]["userId"]

3. Idempotency check:
   - Check header "Idempotency-Key" in event["headers"]
   - If present, check DynamoDB iqg-idempotency-keys table
   - If found, return 202 with cached transaction_id

4. Upsert user in txndb.users:
   INSERT INTO users (user_id, email_hash, consent_at)
   VALUES (:user_id, :email_hash, NOW())
   ON CONFLICT (user_id) DO NOTHING
   (email_hash = sha256 of email, hex digest)

5. Insert submission in txndb.submissions:
   INSERT INTO submissions (user_id, age, category, family_composition,
     lifestyle_json, pre_existing_json, target_si, budget_premium)
   VALUES (...)
   RETURNING submission_id

6. Insert transaction in txndb.transactions:
   INSERT INTO transactions (submission_id, user_id, status)
   VALUES (:submission_id, :user_id, 'QUEUED')
   RETURNING transaction_id

7. Write PENDING item to DynamoDB iqg-quote-results:
   {
     "transactionId": transaction_id,
     "status": "PENDING",
     "userId": user_id,
     "expiresAt": int(time.time()) + 86400  # 24h TTL
   }

8. Publish to SQS iqg-quote-jobs:
   {
     "transaction_id": transaction_id,
     "submission_id": submission_id,
     "user_id": user_id,
     "age": age,
     "category": category,
     "family_composition": family_composition,
     "lifestyle_priorities": lifestyle_priorities,
     "pre_existing_conditions": pre_existing_conditions,
     "target_si": target_si,
     "budget_premium": budget_premium
   }

9. If Idempotency-Key header was present, store in DynamoDB:
   {
     "idempotencyKey": key,
     "transactionId": transaction_id,
     "expiresAt": int(time.time()) + 86400
   }

10. Return 202:
    {
      "transaction_id": transaction_id,
      "status": "QUEUED",
      "message": "Quote generation started. Poll GET /v1/quotes/{transaction_id} for results."
    }

---

## FILE 3: lambda/get_quote/get_quote.py

Handles GET /v1/quotes/{transactionId} AND GET /v1/healthz

Logic:

If path is /v1/healthz (check event["path"]):
  Return 200: {"status": "ok", "version": "1.0.0", "timestamp": ISO timestamp}

Otherwise (quote fetch):
1. Extract transactionId from event["pathParameters"]["transactionId"]
2. Extract user_id from event["requestContext"]["authorizer"]["userId"]
3. Get item from DynamoDB iqg-quote-results where transactionId = transactionId
4. If not found: return 404 {"error": "Transaction not found"}
5. If found and item["userId"] != user_id: return 403 {"error": "Forbidden"}
6. Return 200 with the full item:
   - If status = "PENDING": {"transaction_id": ..., "status": "PENDING"}
   - If status = "COMPLETE": {"transaction_id": ..., "status": "COMPLETE", "recommendations": [...]}
   - If status = "FAILED": {"transaction_id": ..., "status": "FAILED", "error": "..."}

---

## FILE 4: lambda/quote_worker/quote_worker.py

SQS-triggered. Processes one quote job at a time (batchSize=1).

Logic:
1. Parse SQS message body (JSON)
2. Extract: transaction_id, user_id, age, category, family_composition,
   lifestyle_priorities, pre_existing_conditions, target_si, budget_premium

3. Query plandb.plans - filter by category and age:
   SELECT * FROM plans
   WHERE category = :category
   AND min_age <= :age
   AND max_age >= :age
   ORDER BY annual_premium_base ASC

4. If no plans found, update DynamoDB with FAILED status and return.

5. Build LLM prompt using PromptBuilder (implement inline):

SYSTEM prompt:
"You are a health insurance advisor for SwiftCare Health Insurance.
Recommend the TOP 3 most suitable plans from the provided plan catalog
for the user profile below. Use the best_for field as the primary
semantic match signal. Reject any plan whose key_exclusions contradict
the user's stated needs. Return ONLY valid JSON matching the output format.
Do not include any text outside the JSON."

USER prompt:
"USER PROFILE:
- Age: {age}, Category: {category}
- Family composition: {family_composition}
- Budget (annual premium INR): up to {budget_premium}
- Pre-existing conditions: {pre_existing or 'None declared'}
- Lifestyle priorities: {lifestyle_priorities}

PLAN CATALOG ({n} candidates):
{plans_json}

OUTPUT FORMAT (return ONLY this JSON, no other text):
{
  "recommendations": [
    {
      "plan_id": "...",
      "plan_name": "...",
      "annual_premium": 0,
      "sum_insured": 0,
      "reason": "2-3 sentence explanation",
      "highlights": ["benefit1", "benefit2", "benefit3"],
      "co_payment_pct": 0,
      "ped_waiting_months": 0
    }
  ]
}"

6. Call Bedrock:
   client = boto3.client("bedrock-runtime", region_name=REGION)
   response = client.invoke_model(
     modelId=BEDROCK_MODEL_ID,
     body=json.dumps({
       "anthropic_version": "bedrock-2023-05-31",
       "max_tokens": 2000,
       "system": system_prompt,
       "messages": [{"role": "user", "content": user_prompt}]
     }),
     contentType="application/json",
     accept="application/json"
   )
   Parse response body JSON, extract content[0]["text"]

7. Parse the Bedrock response as JSON to get recommendations list.
   If parsing fails, retry once with a stricter prompt.
   If still fails, set status=FAILED.

8. Update DynamoDB iqg-quote-results:
   {
     "transactionId": transaction_id,
     "status": "COMPLETE",
     "userId": user_id,
     "recommendations": recommendations_list,
     "modelId": BEDROCK_MODEL_ID,
     "plansConsidered": len(plans),
     "completedAt": ISO timestamp,
     "expiresAt": int(time.time()) + 86400
   }

9. Update txndb.transactions status to 'COMPLETE':
   UPDATE transactions SET status = 'COMPLETE'
   WHERE transaction_id = :transaction_id

10. Write audit log to S3:
    Key: year=YYYY/month=MM/day=DD/{transaction_id}.json
    Content: {
      "transaction_id": transaction_id,
      "user_id": user_id,
      "model_id": BEDROCK_MODEL_ID,
      "plans_considered": n,
      "recommendations_count": 3,
      "completed_at": ISO timestamp
    }
    NOTE: Do NOT include the full prompt or response in S3 for privacy.
    Just metadata.

---

## FILE 5: lambda/chat_conversation/chat_conversation.py

Handles POST /v1/chat

Request body:
{
  "transaction_id": "...",
  "message": "Why is Plan A higher than Plan B?",
  "turn_id": "optional-client-turn-id"
}

Logic:
1. Parse request body
2. Extract user_id from authorizer context
3. Validate: message required, max 1000 chars, transaction_id required

4. Load quote context from DynamoDB iqg-quote-results:
   Get item by transaction_id
   If not found or status != "COMPLETE": return 400
   Extract recommendations list as plan_context

5. Load last 10 conversation turns from DynamoDB iqg-chat-history:
   Query where userId = user_id AND begins_with(turnId, transaction_id)
   Sort by turnId ascending (ULIDs are time-sortable)
   Take last 10 items

6. Build conversation history for Bedrock:
   messages = []
   For each turn in history:
     messages.append({"role": turn["role"], "content": turn["content"]})
   messages.append({"role": "user", "content": message})

7. Build system prompt:
   "You are a helpful health insurance advisor for SwiftCare Health Insurance.
   The user is asking questions about their insurance quote recommendations.
   
   THEIR RECOMMENDED PLANS:
   {json.dumps(plan_context, indent=2)}
   
   Answer their questions clearly and concisely. Be helpful and informative.
   Do not make guaranteed coverage claims. Always recommend consulting
   an insurance professional for final decisions."

8. Call Bedrock invoke_model (same pattern as quote_worker):
   max_tokens: 500
   Use the messages array with history

9. Extract response text from Bedrock response

10. Generate turn_id as: f"{transaction_id}#{int(time.time()*1000)}"

11. Save both turns to DynamoDB iqg-chat-history:
    User turn:
    {
      "userId": user_id,
      "turnId": f"{transaction_id}#{timestamp-1}",
      "role": "user",
      "content": message,
      "transactionId": transaction_id,
      "expiresAt": int(time.time()) + 2592000  # 30 days
    }
    Assistant turn:
    {
      "userId": user_id,
      "turnId": f"{transaction_id}#{timestamp}",
      "role": "assistant",
      "content": response_text,
      "transactionId": transaction_id,
      "expiresAt": int(time.time()) + 2592000
    }

12. Return 200:
    {
      "turn_id": turn_id,
      "message": response_text,
      "transaction_id": transaction_id
    }

---

## FILE 6: lambda/persist_selection/persist_selection.py

Handles POST /v1/selections

Request body:
{
  "transaction_id": "...",
  "plan_id": "FAM-GLD-003",
  "selection_context": {
    "rank_shown_to_user": 1,
    "compared_against": ["FAM-GLD-003", "FAM-PLT-006", "FAM-GLD-005"]
  }
}

Logic:
1. Parse and validate request body
2. Extract user_id from authorizer context
3. Validate transaction exists and belongs to user:
   SELECT transaction_id, user_id FROM transactions
   WHERE transaction_id = :transaction_id
   If not found: 404. If user_id mismatch: 403.

4. Validate plan_id exists in plandb.plans:
   SELECT plan_id FROM plans WHERE plan_id = :plan_id
   If not found: 404 {"error": "Plan not found"}

5. Check for duplicate selection (one per transaction):
   SELECT selection_id FROM plan_selections
   WHERE transaction_id = :transaction_id
   If found: 409 {"error": "Selection already exists for this transaction"}

6. Insert into txndb.plan_selections:
   INSERT INTO plan_selections
     (transaction_id, plan_id, rank_shown, compared_against)
   VALUES (:transaction_id, :plan_id, :rank_shown, :compared_against::jsonb)
   RETURNING selection_id

7. Return 201:
   {
     "selection_id": selection_id,
     "transaction_id": transaction_id,
     "plan_id": plan_id,
     "persisted_at": ISO timestamp,
     "message": "Plan selection saved successfully"
   }

---

## IMPORTANT IMPLEMENTATION NOTES:

1. Aurora Data API helper - implement this in EVERY Lambda file that uses DB:

```python
import boto3, os, json

rds = boto3.client("rds-data", region_name=os.environ.get("REGION", "us-east-1"))
CLUSTER_ARN = os.environ["DB_CLUSTER_ARN"]
SECRET_ARN  = os.environ["DB_SECRET_ARN"]
DB_TXN      = os.environ.get("DB_NAME_TXN", "txndb")
DB_PLAN     = os.environ.get("DB_NAME_PLAN", "plandb")

def db_execute(sql, params=None, database=DB_TXN):
    kwargs = dict(resourceArn=CLUSTER_ARN, secretArn=SECRET_ARN,
                  database=database, sql=sql, includeResultMetadata=True)
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
```

2. Standard CORS response helper - implement in every REST Lambda:
```python
def respond(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization,X-Correlation-Id,Idempotency-Key",
            "Access-Control-Allow-Methods": "OPTIONS,GET,POST"
        },
        "body": json.dumps(body)
    }
```

3. For the authorizer - if PyJWT is not available, decode JWT manually:
```python
def decode_jwt_payload(token):
    parts = token.split(".")
    payload_b64 = parts[1] + "=" * (4 - len(parts[1]) % 4)
    payload = json.loads(base64.b64decode(payload_b64).decode("utf-8"))
    return payload
```

4. Do NOT use any external libraries except boto3 (already available in Lambda runtime).
   No requests, no pyjwt, no psycopg2. Only stdlib + boto3.

5. Write each file completely - no placeholders, no "TODO" comments.
   Every function must work end-to-end.

6. Use try/except around every external call (DB, Bedrock, DynamoDB, SQS, S3)
   and return appropriate error responses.

Write all 6 files now. Write them to these exact paths:
- lambda/authorizer/authorizer.py
- lambda/ingestion_api/ingestion_api.py
- lambda/get_quote/get_quote.py
- lambda/quote_worker/quote_worker.py
- lambda/chat_conversation/chat_conversation.py
- lambda/persist_selection/persist_selection.py

