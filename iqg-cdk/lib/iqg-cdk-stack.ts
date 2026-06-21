import {
  Stack,
  StackProps,
  Aws,
  Duration,
  RemovalPolicy,
  CfnOutput,
} from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as rds from 'aws-cdk-lib/aws-rds';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as sqs from 'aws-cdk-lib/aws-sqs';
import * as cognito from 'aws-cdk-lib/aws-cognito';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as apigateway from 'aws-cdk-lib/aws-apigateway';
import * as cloudfront from 'aws-cdk-lib/aws-cloudfront';
import * as lambdaEventSources from 'aws-cdk-lib/aws-lambda-event-sources';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as ecrAssets from 'aws-cdk-lib/aws-ecr-assets';
import * as elbv2 from 'aws-cdk-lib/aws-elasticloadbalancingv2';
import * as path from 'path';

export class IqgCdkStack extends Stack {
  constructor(scope: Construct, id: string, props?: StackProps) {
    super(scope, id, props);

    // ------------------------------------------------------------------
    // 1. AURORA SERVERLESS V2 (PostgreSQL)
    // ------------------------------------------------------------------
    const vpc = ec2.Vpc.fromLookup(this, 'IqgVpc', {
      vpcId: 'vpc-02b8b81c9e12e82dd',
    });

    const auroraSubnets: ec2.ISubnet[] = [
      ec2.Subnet.fromSubnetId(this, 'AuroraSubnet1b', 'subnet-0e3ada429e10603e3'),
      ec2.Subnet.fromSubnetId(this, 'AuroraSubnet1c', 'subnet-0a7b31cc011811219'),
      ec2.Subnet.fromSubnetId(this, 'AuroraSubnet1a', 'subnet-0113efea3112b7b32'),
    ];

    const auroraSg = new ec2.SecurityGroup(this, 'AuroraSecurityGroup', {
      vpc,
      description: 'Allow PostgreSQL access from within the VPC',
      allowAllOutbound: true,
    });
    auroraSg.addIngressRule(
      ec2.Peer.ipv4('172.31.0.0/16'),
      ec2.Port.tcp(5432),
      'Allow PostgreSQL from within VPC CIDR',
    );

    const auroraSecret = new rds.DatabaseSecret(this, 'AuroraSecret', {
      username: 'iqgadmin',
    });

    const auroraCluster = new rds.DatabaseCluster(this, 'AuroraCluster', {
      clusterIdentifier: 'iqg-aurora-cluster',
      engine: rds.DatabaseClusterEngine.auroraPostgres({
        version: rds.AuroraPostgresEngineVersion.VER_15_8,
      }),
      credentials: rds.Credentials.fromSecret(auroraSecret),
      defaultDatabaseName: 'txndb',
      enableDataApi: true,
      serverlessV2MinCapacity: 0.5,
      serverlessV2MaxCapacity: 4,
      writer: rds.ClusterInstance.serverlessV2('writer'),
      vpc,
      vpcSubnets: { subnets: auroraSubnets },
      securityGroups: [auroraSg],
      removalPolicy: RemovalPolicy.DESTROY,
    });

    // Note: The cluster hosts two logical databases — txndb (default, created by the cluster)
    // and plandb (created post-deploy via the Data API or a bootstrap script).
    // Both names are passed to Lambdas via DB_NAME_TXN / DB_NAME_PLAN environment variables.

    // ------------------------------------------------------------------
    // 2. DYNAMODB TABLES
    // ------------------------------------------------------------------
    const wsConnectionsTable = new dynamodb.Table(this, 'WsConnectionsTable', {
      tableName: 'iqg-ws-connections',
      partitionKey: { name: 'connectionId', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      timeToLiveAttribute: 'expiresAt',
      removalPolicy: RemovalPolicy.DESTROY,
    });

    const chatHistoryTable = new dynamodb.Table(this, 'ChatHistoryTable', {
      tableName: 'iqg-chat-history',
      partitionKey: { name: 'userId', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'turnId', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      timeToLiveAttribute: 'expiresAt',
      removalPolicy: RemovalPolicy.DESTROY,
    });

    const idempotencyTable = new dynamodb.Table(this, 'IdempotencyKeysTable', {
      tableName: 'iqg-idempotency-keys',
      partitionKey: { name: 'idempotencyKey', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      timeToLiveAttribute: 'expiresAt',
      removalPolicy: RemovalPolicy.DESTROY,
    });

    const quoteResultsTable = new dynamodb.Table(this, 'QuoteResultsTable', {
      tableName: 'iqg-quote-results',
      partitionKey: { name: 'transactionId', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      timeToLiveAttribute: 'expiresAt',
      removalPolicy: RemovalPolicy.DESTROY,
    });

    // ------------------------------------------------------------------
    // 3. S3 BUCKET (audit)
    // ------------------------------------------------------------------
    const auditBucket = new s3.Bucket(this, 'AuditBucket', {
      bucketName: `iqg-audit-${Aws.ACCOUNT_ID}-${Aws.REGION}`,
      versioned: true,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      lifecycleRules: [
        {
          enabled: true,
          transitions: [
            {
              storageClass: s3.StorageClass.GLACIER,
              transitionAfter: Duration.days(90),
            },
          ],
        },
      ],
      removalPolicy: RemovalPolicy.RETAIN,
    });

    // ------------------------------------------------------------------
    // 4. SQS + DLQ
    // ------------------------------------------------------------------
    const quoteJobsDlq = new sqs.Queue(this, 'QuoteJobsDlq', {
      queueName: 'iqg-quote-jobs-dlq',
      retentionPeriod: Duration.days(14),
      encryption: sqs.QueueEncryption.SQS_MANAGED,
    });

    const quoteJobsQueue = new sqs.Queue(this, 'QuoteJobsQueue', {
      queueName: 'iqg-quote-jobs',
      visibilityTimeout: Duration.minutes(5),
      retentionPeriod: Duration.days(4),
      encryption: sqs.QueueEncryption.SQS_MANAGED,
      deadLetterQueue: {
        maxReceiveCount: 3,
        queue: quoteJobsDlq,
      },
    });

    // ------------------------------------------------------------------
    // 5. COGNITO USER POOL
    // ------------------------------------------------------------------
    const userPool = new cognito.UserPool(this, 'IqgUserPool', {
      userPoolName: 'iqg-user-pool',
      selfSignUpEnabled: true,
      signInAliases: { email: true },
      autoVerify: { email: true },
      standardAttributes: {
        email: { required: true, mutable: true },
      },
      passwordPolicy: {
        minLength: 8,
        requireSymbols: false,
      },
      removalPolicy: RemovalPolicy.DESTROY,
    });

    const userPoolClient = new cognito.UserPoolClient(this, 'IqgUserPoolClient', {
      userPool,
      userPoolClientName: 'iqg-web-client',
      generateSecret: false,
      authFlows: {
        userPassword: true,
        userSrp: true,
      },
      oAuth: {
        flows: {
          implicitCodeGrant: true,
          authorizationCodeGrant: true,
        },
        callbackUrls: [
          'http://localhost:5173/callback',
          'https://localhost:5173/callback',
        ],
        logoutUrls: [
          'http://localhost:5173',
          'https://localhost:5173',
        ],
        scopes: [
          cognito.OAuthScope.EMAIL,
          cognito.OAuthScope.OPENID,
          cognito.OAuthScope.PROFILE,
        ],
      },
    });

    new cognito.UserPoolDomain(this, 'IqgUserPoolDomain', {
      userPool,
      cognitoDomain: {
        domainPrefix: `iqg-auth-${Aws.ACCOUNT_ID}`,
      },
    });

    // ------------------------------------------------------------------
    // 6. IAM ROLE FOR LAMBDAS
    // ------------------------------------------------------------------
    const lambdaRole = new iam.Role(this, 'IqgLambdaRole', {
      roleName: 'iqg-lambda-role',
      assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AWSLambdaBasicExecutionRole'),
      ],
    });

    lambdaRole.addToPolicy(new iam.PolicyStatement({
      actions: ['bedrock:InvokeModel', 'bedrock:InvokeModelWithResponseStream'],
      resources: ['*'],
    }));

    lambdaRole.addToPolicy(new iam.PolicyStatement({
      actions: [
        'dynamodb:GetItem',
        'dynamodb:PutItem',
        'dynamodb:UpdateItem',
        'dynamodb:DeleteItem',
        'dynamodb:Query',
        'dynamodb:Scan',
      ],
      resources: [
        wsConnectionsTable.tableArn,
        chatHistoryTable.tableArn,
        idempotencyTable.tableArn,
        quoteResultsTable.tableArn,
      ],
    }));

    lambdaRole.addToPolicy(new iam.PolicyStatement({
      actions: [
        'sqs:SendMessage',
        'sqs:ReceiveMessage',
        'sqs:DeleteMessage',
        'sqs:GetQueueAttributes',
      ],
      resources: [quoteJobsQueue.queueArn],
    }));

    lambdaRole.addToPolicy(new iam.PolicyStatement({
      actions: ['s3:PutObject', 's3:GetObject'],
      resources: [auditBucket.bucketArn, `${auditBucket.bucketArn}/*`],
    }));

    lambdaRole.addToPolicy(new iam.PolicyStatement({
      actions: ['secretsmanager:GetSecretValue'],
      resources: [auroraSecret.secretArn],
    }));

    lambdaRole.addToPolicy(new iam.PolicyStatement({
      actions: [
        'rds-data:ExecuteStatement',
        'rds-data:BatchExecuteStatement',
        'rds-data:BeginTransaction',
        'rds-data:CommitTransaction',
        'rds-data:RollbackTransaction',
      ],
      resources: [auroraCluster.clusterArn],
    }));

    // ------------------------------------------------------------------
    // 7. LAMBDA FUNCTIONS
    // ------------------------------------------------------------------
    const commonEnv: { [key: string]: string } = {
      REGION: 'us-east-1',
      DB_CLUSTER_ARN: auroraCluster.clusterArn,
      DB_SECRET_ARN: auroraSecret.secretArn,
      DB_NAME_TXN: 'txndb',
      DB_NAME_PLAN: 'plandb',
      QUOTE_JOBS_QUEUE_URL: quoteJobsQueue.queueUrl,
      QUOTE_RESULTS_TABLE: quoteResultsTable.tableName,
      CHAT_HISTORY_TABLE: chatHistoryTable.tableName,
      WS_CONNECTIONS_TABLE: wsConnectionsTable.tableName,
      IDEMPOTENCY_TABLE: idempotencyTable.tableName,
      AUDIT_BUCKET: auditBucket.bucketName,
      BEDROCK_MODEL_ID: 'anthropic.claude-sonnet-4-6',
      USER_POOL_ID: userPool.userPoolId,
      USER_POOL_CLIENT_ID: userPoolClient.userPoolClientId,
    };

    const ingestionApiFn = new lambda.Function(this, 'IngestionApiFn', {
      functionName: 'iqg-ingestion-api',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'ingestion_api.handler',
      code: lambda.Code.fromAsset('../lambda/ingestion_api'),
      role: lambdaRole,
      memorySize: 256,
      timeout: Duration.seconds(29),
      environment: commonEnv,
    });

    const quoteWorkerFn = new lambda.Function(this, 'QuoteWorkerFn', {
      functionName: 'iqg-quote-worker',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'quote_worker.handler',
      code: lambda.Code.fromAsset('../lambda/quote_worker'),
      role: lambdaRole,
      memorySize: 512,
      timeout: Duration.minutes(5),
      environment: commonEnv,
    });

    quoteWorkerFn.addEventSource(new lambdaEventSources.SqsEventSource(quoteJobsQueue, {
      batchSize: 1,
      enabled: true,
    }));

    const chatConversationFn = new lambda.Function(this, 'ChatConversationFn', {
      functionName: 'iqg-chat-conversation',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'chat_conversation.handler',
      code: lambda.Code.fromAsset('../lambda/chat_conversation'),
      role: lambdaRole,
      memorySize: 512,
      timeout: Duration.seconds(60),
      environment: commonEnv,
    });

    const authorizerFn = new lambda.Function(this, 'AuthorizerFn', {
      functionName: 'iqg-authorizer',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'authorizer.handler',
      code: lambda.Code.fromAsset('../lambda/authorizer'),
      role: lambdaRole,
      memorySize: 256,
      timeout: Duration.seconds(10),
      environment: commonEnv,
    });

    const getQuoteFn = new lambda.Function(this, 'GetQuoteFn', {
      functionName: 'iqg-get-quote',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'get_quote.handler',
      code: lambda.Code.fromAsset('../lambda/get_quote'),
      role: lambdaRole,
      memorySize: 256,
      timeout: Duration.seconds(10),
      environment: commonEnv,
    });

    const persistSelectionFn = new lambda.Function(this, 'PersistSelectionFn', {
      functionName: 'iqg-persist-selection',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'persist_selection.handler',
      code: lambda.Code.fromAsset('../lambda/persist_selection'),
      role: lambdaRole,
      memorySize: 256,
      timeout: Duration.seconds(15),
      environment: commonEnv,
    });

    const getMyQuotesFn = new lambda.Function(this, 'GetMyQuotesFn', {
      functionName: 'iqg-get-my-quotes',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'get_my_quotes.handler',
      code: lambda.Code.fromAsset('../lambda/get_my_quotes'),
      role: lambdaRole,
      memorySize: 256,
      timeout: Duration.seconds(15),
      environment: commonEnv,
    });

    // ------------------------------------------------------------------
    // 8. API GATEWAY (REST API)
    // ------------------------------------------------------------------
    const api = new apigateway.RestApi(this, 'IqgApiV2', {
      restApiName: 'iqg-api',
      description: 'IQG Insurance Quote Generator API v1',
      endpointConfiguration: { types: [apigateway.EndpointType.REGIONAL] },
      deployOptions: { stageName: 'v1' },
      defaultCorsPreflightOptions: {
        allowOrigins: apigateway.Cors.ALL_ORIGINS,
        allowMethods: ['OPTIONS', 'GET', 'POST'],
        allowHeaders: [
          'Content-Type',
          'Authorization',
          'X-Correlation-Id',
          'Idempotency-Key',
        ],
      },
    });

    const tokenAuthorizer = new apigateway.TokenAuthorizer(this, 'IqgTokenAuthorizer', {
      authorizerName: 'iqg-token-authorizer',
      handler: authorizerFn,
      identitySource: 'method.request.header.Authorization',
      resultsCacheTtl: Duration.seconds(300),
    });

    const v1 = api.root;

    const quotes = v1.addResource('quotes');
    const quotesSubmit = quotes.addResource('submit');
    quotesSubmit.addMethod('POST', new apigateway.HttpIntegration(
      'http://iqg-alb-1023666751.us-east-1.elb.amazonaws.com/v1/quotes/submit',
      { httpMethod: 'POST', proxy: true }
    ), {
      authorizer: tokenAuthorizer,
      authorizationType: apigateway.AuthorizationType.CUSTOM,
    });

    const quotesById = quotes.addResource('{transactionId}');
    quotesById.addMethod('GET', new apigateway.LambdaIntegration(getQuoteFn), {
      authorizer: tokenAuthorizer,
      authorizationType: apigateway.AuthorizationType.CUSTOM,
    });

    const chat = v1.addResource('chat');
    chat.addMethod('POST', new apigateway.LambdaIntegration(chatConversationFn), {
      authorizer: tokenAuthorizer,
      authorizationType: apigateway.AuthorizationType.CUSTOM,
    });

    const selections = v1.addResource('selections');
    selections.addMethod('POST', new apigateway.HttpIntegration(
      'http://iqg-alb-1023666751.us-east-1.elb.amazonaws.com/v1/selections',
      { httpMethod: 'POST', proxy: true }
    ), {
      authorizer: tokenAuthorizer,
      authorizationType: apigateway.AuthorizationType.CUSTOM,
    });

    const myQuotes = v1.addResource('my-quotes');
    myQuotes.addMethod('GET', new apigateway.LambdaIntegration(getMyQuotesFn), {
      authorizer: tokenAuthorizer,
      authorizationType: apigateway.AuthorizationType.CUSTOM,
    });

    const healthz = v1.addResource('healthz');
    healthz.addMethod('GET', new apigateway.LambdaIntegration(getQuoteFn));

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

    // ------------------------------------------------------------------
    // 9. CLOUDFORMATION OUTPUTS
    // ------------------------------------------------------------------
    new CfnOutput(this, 'ApiUrl', { value: api.url });
    new CfnOutput(this, 'AlbUrl', {
      value: `http://${alb.loadBalancerDnsName}`,
      description: 'ALB URL for POST /v1/quotes/submit and POST /v1/selections',
    });
    new CfnOutput(this, 'UserPoolId', { value: userPool.userPoolId });
    new CfnOutput(this, 'UserPoolClientId', { value: userPoolClient.userPoolClientId });
    new CfnOutput(this, 'CognitoDomain', {
      value: `https://iqg-auth-${Aws.ACCOUNT_ID}.auth.us-east-1.amazoncognito.com`,
    });
    new CfnOutput(this, 'AuroraClusterArn', { value: auroraCluster.clusterArn });
    new CfnOutput(this, 'AuroraSecretArn', { value: auroraSecret.secretArn });
    new CfnOutput(this, 'AuditBucketName', { value: auditBucket.bucketName });
    new CfnOutput(this, 'QuoteJobsQueueUrl', { value: quoteJobsQueue.queueUrl });
    new CfnOutput(this, 'QuoteResultsTableName', { value: quoteResultsTable.tableName });
    new CfnOutput(this, 'ChatHistoryTableName', { value: chatHistoryTable.tableName });

    // ------------------------------------------------------------------
    // FRONTEND — S3 + CloudFront
    // ------------------------------------------------------------------
    const spaBucket = new s3.Bucket(this, 'SpaBucket', {
      bucketName: `iqg-spa-${Aws.ACCOUNT_ID}-${Aws.REGION}`,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      removalPolicy: RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
    });

    const oac = new cloudfront.CfnOriginAccessControl(this, 'SpaOAC', {
      originAccessControlConfig: {
        name: 'iqg-spa-oac',
        originAccessControlOriginType: 's3',
        signingBehavior: 'always',
        signingProtocol: 'sigv4',
      },
    });

    const distribution = new cloudfront.CfnDistribution(this, 'SpaDistribution', {
      distributionConfig: {
        enabled: true,
        defaultRootObject: 'index.html',
        origins: [{
          id: 'spa-s3-origin',
          domainName: spaBucket.bucketRegionalDomainName,
          originAccessControlId: oac.attrId,
          s3OriginConfig: { originAccessIdentity: '' },
        }],
        defaultCacheBehavior: {
          targetOriginId: 'spa-s3-origin',
          viewerProtocolPolicy: 'redirect-to-https',
          allowedMethods: ['GET', 'HEAD', 'OPTIONS'],
          cachedMethods: ['GET', 'HEAD'],
          compress: true,
          forwardedValues: {
            queryString: false,
            cookies: { forward: 'none' },
          },
          defaultTtl: 86400,
        },
        customErrorResponses: [
          { errorCode: 403, responseCode: 200, responsePagePath: '/index.html' },
          { errorCode: 404, responseCode: 200, responsePagePath: '/index.html' },
        ],
        httpVersion: 'http2',
        priceClass: 'PriceClass_100',
      },
    });

    spaBucket.addToResourcePolicy(new iam.PolicyStatement({
      actions: ['s3:GetObject'],
      resources: [`${spaBucket.bucketArn}/*`],
      principals: [new iam.ServicePrincipal('cloudfront.amazonaws.com')],
      conditions: {
        StringEquals: {
          'AWS:SourceArn': `arn:aws:cloudfront::${Aws.ACCOUNT_ID}:distribution/${distribution.attrId}`,
        },
      },
    }));

    new CfnOutput(this, 'SpaBucketName', { value: spaBucket.bucketName });
    new CfnOutput(this, 'CloudFrontUrl', { value: `https://${distribution.attrDomainName}` });
    new CfnOutput(this, 'CloudFrontDistributionId', { value: distribution.attrId });
  }
}
