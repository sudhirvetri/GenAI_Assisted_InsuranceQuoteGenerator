I'm building a GenAI Insurance Quote Generator on AWS. Build me the complete CDK TypeScript infrastructure.

ACCOUNT DETAILS:
- Account: 867344470917
- Region: us-east-1
- VPC: vpc-02b8b81c9e12e82dd
- Subnets: subnet-0d0d97ee08af0c292 (1d), subnet-0fbb8c5dabc9099a6 (1f), subnet-0e3ada429e10603e3 (1b), subnet-0a7b31cc011811219 (1c), subnet-0537592d752dcaaa3 (1e), subnet-0113efea3112b7b32 (1a)
- CDK already bootstrapped

PROJECT STRUCTURE:
/workspaces/GenAI_Assisted_InsuranceQuoteGenerator/
  iqg-cdk/          ← CDK app (already init'd)
  lambda/
    ingestion_api/
    quote_worker/
    chat_conversation/
    authorizer/
    get_quote/
    persist_selection/
    shared/
  frontend/

WHAT TO BUILD — replace everything in iqg-cdk/lib/iqg-cdk-stack.ts with a single CDK stack that creates:

1. AURORA SERVERLESS V2 (PostgreSQL-compatible)
   - Engine: aurora-postgresql, engineVersion 15.4
   - Cluster: ServerlessV2, minCapacity 0.5, maxCapacity 4
   - Use the default VPC (vpc-02b8b81c9e12e82dd) — import it with Vpc.fromLookup
   - Use subnets: subnet-0e3ada429e10603e3, subnet-0a7b31cc011811219, subnet-0113efea3112b7b32 (1b, 1c, 1a)
   - Security group: allow port 5432 from within the VPC CIDR 172.31.0.0/16
   - TWO logical databases inside the cluster:
       Database 1: txndb  — for user submissions, transactions, plan_selections, audit_log
       Database 2: plandb — for SwiftCare 30-plan catalog (seeded once, read-mostly)
   - Enable Data API (enableDataApi: true) — CRITICAL, lets Lambda call DB without a driver
   - Store credentials in Secrets Manager automatically (use DatabaseSecret)
   - Cluster identifier: iqg-aurora-cluster
   - Master username: iqgadmin

2. DYNAMODB TABLES (all on-demand billing, TTL enabled)
   - Table 1: iqg-ws-connections
       PK: connectionId (String)
       TTL attribute: expiresAt

   - Table 2: iqg-chat-history
       PK: userId (String)
       SK: turnId (String)
       TTL attribute: expiresAt

   - Table 3: iqg-idempotency-keys
       PK: idempotencyKey (String)
       TTL attribute: expiresAt

   - Table 4: iqg-quote-results
       PK: transactionId (String)
       TTL attribute: expiresAt
       NOTE: Items in this table will have a "status" field: "PENDING" or "COMPLETE"
       When quote_worker Lambda finishes, it writes status=COMPLETE + recommendations JSON
       The get_quote Lambda polls this table and returns status to the browser
       Browser polls GET /v1/quotes/{transactionId} every 2 seconds until status=COMPLETE

3. S3 BUCKET
   - Name: iqg-audit-{account}-{region} using Aws.ACCOUNT_ID and Aws.REGION tokens
   - Versioned: true
   - Block all public access
   - Lifecycle rule: transition to GLACIER after 90 days

4. SQS QUEUE + DLQ
   - DLQ: iqg-quote-jobs-dlq, retentionPeriod 14 days
   - Main queue: iqg-quote-jobs, visibilityTimeout 5 minutes, retentionPeriod 4 days
   - Dead letter queue config: maxReceiveCount 3, queue = dlq
   - Encryption: SQS_MANAGED

5. COGNITO USER POOL
   - Pool name: iqg-user-pool
   - Self sign up: true
   - Email as username (signInAliases: { email: true })
   - Password policy: minLength 8, requireSymbols false
   - Auto verify email: true
   - Standard attributes: email (required, mutable)
   - App client: iqg-web-client
     - Auth flows: ALLOW_USER_PASSWORD_AUTH, ALLOW_REFRESH_TOKEN_AUTH, ALLOW_USER_SRP_AUTH
     - No client secret (public client for SPA)
     - OAuth: implicit + code grant
     - Callback URLs: http://localhost:5173/callback, https://localhost:5173/callback
     - Logout URLs: http://localhost:5173, https://localhost:5173
     - Scopes: email, openid, profile
   - Domain prefix: iqg-auth-867344470917

6. IAM ROLE FOR LAMBDAS
   - Role name: iqg-lambda-role
   - Policies:
     - AWSLambdaBasicExecutionRole (managed)
     - Inline policy with these permissions:
       - bedrock:InvokeModel, bedrock:InvokeModelWithResponseStream on "*"
       - dynamodb:GetItem, PutItem, UpdateItem, DeleteItem, Query, Scan on all 4 DynamoDB table ARNs
       - sqs:SendMessage, ReceiveMessage, DeleteMessage, GetQueueAttributes on queue ARN
       - s3:PutObject, GetObject on audit bucket ARN and audit bucket ARN + "/*"
       - secretsmanager:GetSecretValue on Aurora secret ARN
       - rds-data:ExecuteStatement, rds-data:BatchExecuteStatement,
         rds-data:BeginTransaction, rds-data:CommitTransaction,
         rds-data:RollbackTransaction on Aurora cluster ARN

7. LAMBDA FUNCTIONS (all Python 3.12, 256MB memory, 30s timeout unless noted)

   ALL Lambdas share these environment variables:
   - REGION: us-east-1
   - DB_CLUSTER_ARN: Aurora cluster ARN
   - DB_SECRET_ARN: Aurora secret ARN
   - DB_NAME_TXN: txndb
   - DB_NAME_PLAN: plandb
   - QUOTE_JOBS_QUEUE_URL: SQS queue URL
   - QUOTE_RESULTS_TABLE: iqg-quote-results
   - CHAT_HISTORY_TABLE: iqg-chat-history
   - WS_CONNECTIONS_TABLE: iqg-ws-connections
   - IDEMPOTENCY_TABLE: iqg-idempotency-keys
   - AUDIT_BUCKET: audit bucket name
   - BEDROCK_MODEL_ID: anthropic.claude-sonnet-4-6
   - USER_POOL_ID: Cognito user pool id
   - USER_POOL_CLIENT_ID: Cognito app client id

   Lambda a) iqg-ingestion-api
     - handler: ingestion_api.handler
     - code: ../lambda/ingestion_api
     - timeout: 29 seconds

   Lambda b) iqg-quote-worker
     - handler: quote_worker.handler
     - code: ../lambda/quote_worker
     - timeout: 5 minutes
     - memory: 512MB
     - Add SQS event source mapping: queue=iqg-quote-jobs, batchSize=1, enabled=true

   Lambda c) iqg-chat-conversation
     - handler: chat_conversation.handler
     - code: ../lambda/chat_conversation
     - timeout: 60 seconds
     - memory: 512MB

   Lambda d) iqg-authorizer
     - handler: authorizer.handler
     - code: ../lambda/authorizer
     - timeout: 10 seconds

   Lambda e) iqg-get-quote
     - handler: get_quote.handler
     - code: ../lambda/get_quote
     - timeout: 10 seconds

   Lambda f) iqg-persist-selection
     - handler: persist_selection.handler
     - code: ../lambda/persist_selection
     - timeout: 15 seconds

8. API GATEWAY (REST API)
   - API name: iqg-api
   - Deploy to stage: v1
   - CORS: enable on all resources
     origins: "*"
     methods: "OPTIONS,GET,POST"
     headers: "Content-Type,Authorization,X-Correlation-Id,Idempotency-Key"

   Lambda Authorizer:
   - Type: TOKEN
   - Name: iqg-token-authorizer
   - Handler Lambda: iqg-authorizer
   - Identity source: method.request.header.Authorization
   - Results TTL: 300 seconds

   Routes:
   - POST /v1/quotes/submit     → iqg-ingestion-api       (WITH authorizer)
   - GET  /v1/quotes/{transactionId} → iqg-get-quote      (WITH authorizer)
   - POST /v1/chat              → iqg-chat-conversation    (WITH authorizer)
   - POST /v1/selections        → iqg-persist-selection    (WITH authorizer)
   - GET  /v1/healthz           → iqg-get-quote            (NO authorizer)

9. CLOUDFORMATION OUTPUTS
   - ApiUrl: API Gateway invoke URL for stage v1
   - UserPoolId: Cognito user pool ID
   - UserPoolClientId: Cognito app client ID
   - CognitoDomain: full hosted UI domain URL (https://iqg-auth-867344470917.auth.us-east-1.amazoncognito.com)
   - AuroraClusterArn: Aurora cluster ARN
   - AuroraSecretArn: Aurora credentials secret ARN
   - AuditBucketName: S3 audit bucket name
   - QuoteJobsQueueUrl: SQS queue URL
   - QuoteResultsTableName: iqg-quote-results
   - ChatHistoryTableName: iqg-chat-history

ADDITIONAL FILES TO CREATE:

1. Update iqg-cdk/bin/iqg-cdk.ts:
   Set env: { account: '867344470917', region: 'us-east-1' }

2. Update iqg-cdk/cdk.json context to include:
   "@aws-cdk/core:enablePartitionLiterals": true
   "aws-cdk:enableDiffNoFail": true
   "@aws-cdk/aws-apigateway:usagePlanKeyOrderInsensitiveId": true
   "@aws-cdk/aws-rds:lowercaseDbIdentifier": false

3. Create placeholder Lambda files so CDK deploy does not fail on missing code:
   lambda/ingestion_api/ingestion_api.py     → def handler(event, context): return {"statusCode": 200, "body": "placeholder"}
   lambda/quote_worker/quote_worker.py       → def handler(event, context): return {"statusCode": 200, "body": "placeholder"}
   lambda/chat_conversation/chat_conversation.py → def handler(event, context): return {"statusCode": 200, "body": "placeholder"}
   lambda/authorizer/authorizer.py           → def handler(event, context): return {"statusCode": 200, "body": "placeholder"}
   lambda/get_quote/get_quote.py             → def handler(event, context): return {"statusCode": 200, "body": "placeholder"}
   lambda/persist_selection/persist_selection.py → def handler(event, context): return {"statusCode": 200, "body": "placeholder"}

Write the complete iqg-cdk/lib/iqg-cdk-stack.ts with all necessary imports from aws-cdk-lib only.
Make it compile cleanly with tsc. Do not use any @aws-cdk/aws-xxx individual packages.
