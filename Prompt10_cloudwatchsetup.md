In iqg-cdk/lib/iqg-cdk-stack.ts, add a CloudWatch dashboard 
after the existing outputs section, just before the closing 
brace of the constructor.

First add this import at the top with the other imports:
import * as cloudwatch from 'aws-cdk-lib/aws-cloudwatch';

Then add this block before the final closing brace of the constructor:

    // ------------------------------------------------------------------
    // CLOUDWATCH DASHBOARD
    // ------------------------------------------------------------------
    const dashboard = new cloudwatch.Dashboard(this, 'IqgOpsDashboard', {
      dashboardName: 'IQG-Operations',
    });

    dashboard.addWidgets(
      // Row 1: API Health
      new cloudwatch.GraphWidget({
        title: 'API Gateway 5xx Error Rate',
        left: [new cloudwatch.Metric({
          namespace: 'AWS/ApiGateway',
          metricName: 'Count',
          dimensionsMap: { ApiName: 'iqg-api', Stage: 'v1' },
          statistic: 'Sum',
          period: Duration.minutes(5),
        })],
        width: 8,
      }),
      new cloudwatch.GraphWidget({
        title: 'ALB Response Time (p95)',
        left: [new cloudwatch.Metric({
          namespace: 'AWS/ApplicationELB',
          metricName: 'TargetResponseTime',
          dimensionsMap: { LoadBalancer: alb.loadBalancerFullName },
          statistic: 'p95',
          period: Duration.minutes(5),
        })],
        width: 8,
      }),
      new cloudwatch.GraphWidget({
        title: 'ECS Running Task Count',
        left: [new cloudwatch.Metric({
          namespace: 'AWS/ECS',
          metricName: 'RunningTaskCount',
          dimensionsMap: {
            ClusterName: 'iqg-ecs-cluster',
            ServiceName: 'iqg-ingestion-api',
          },
          statistic: 'Average',
          period: Duration.minutes(1),
        })],
        width: 8,
      }),
    );

    dashboard.addWidgets(
      // Row 2: AI Pipeline
      new cloudwatch.GraphWidget({
        title: 'Quote Worker Lambda Errors',
        left: [new cloudwatch.Metric({
          namespace: 'AWS/Lambda',
          metricName: 'Errors',
          dimensionsMap: { FunctionName: 'iqg-quote-worker' },
          statistic: 'Sum',
          period: Duration.minutes(5),
          color: cloudwatch.Color.RED,
        })],
        width: 8,
      }),
      new cloudwatch.GraphWidget({
        title: 'SQS Queue Depth',
        left: [
          new cloudwatch.Metric({
            namespace: 'AWS/SQS',
            metricName: 'ApproximateNumberOfMessagesVisible',
            dimensionsMap: { QueueName: 'iqg-quote-jobs' },
            statistic: 'Maximum',
            period: Duration.minutes(1),
            label: 'Queue Depth',
          }),
          new cloudwatch.Metric({
            namespace: 'AWS/SQS',
            metricName: 'ApproximateNumberOfMessagesVisible',
            dimensionsMap: { QueueName: 'iqg-quote-jobs-dlq' },
            statistic: 'Maximum',
            period: Duration.minutes(1),
            label: 'DLQ Depth',
            color: cloudwatch.Color.RED,
          }),
        ],
        width: 8,
      }),
      new cloudwatch.GraphWidget({
        title: 'Lambda Duration p95 (Quote Worker)',
        left: [new cloudwatch.Metric({
          namespace: 'AWS/Lambda',
          metricName: 'Duration',
          dimensionsMap: { FunctionName: 'iqg-quote-worker' },
          statistic: 'p95',
          period: Duration.minutes(5),
        })],
        width: 8,
      }),
    );

    dashboard.addWidgets(
      // Row 3: Data Layer
      new cloudwatch.GraphWidget({
        title: 'Aurora CPU Utilization',
        left: [new cloudwatch.Metric({
          namespace: 'AWS/RDS',
          metricName: 'CPUUtilization',
          dimensionsMap: { DBClusterIdentifier: 'iqg-aurora-cluster' },
          statistic: 'Average',
          period: Duration.minutes(5),
        })],
        width: 8,
      }),
      new cloudwatch.GraphWidget({
        title: 'DynamoDB Throttled Requests',
        left: [
          new cloudwatch.Metric({
            namespace: 'AWS/DynamoDB',
            metricName: 'ThrottledRequests',
            dimensionsMap: { TableName: 'iqg-quote-results' },
            statistic: 'Sum',
            period: Duration.minutes(5),
            label: 'Quote Results',
          }),
          new cloudwatch.Metric({
            namespace: 'AWS/DynamoDB',
            metricName: 'ThrottledRequests',
            dimensionsMap: { TableName: 'iqg-chat-history' },
            statistic: 'Sum',
            period: Duration.minutes(5),
            label: 'Chat History',
          }),
        ],
        width: 8,
      }),
      new cloudwatch.GraphWidget({
        title: 'WebSocket Connections',
        left: [new cloudwatch.Metric({
          namespace: 'AWS/ApiGateway',
          metricName: 'ConnectCount',
          dimensionsMap: { ApiId: wsApi.ref, Stage: 'v1' },
          statistic: 'Sum',
          period: Duration.minutes(5),
        })],
        width: 8,
      }),
    );

    new CfnOutput(this, 'DashboardUrl', {
      value: `https://console.aws.amazon.com/cloudwatch/home?region=${this.region}#dashboards:name=IQG-Operations`,
      description: 'CloudWatch Operations Dashboard',
    });

After making the changes run:
cd iqg-cdk && npx tsc --noEmit 2>&1

Report any TypeScript errors but do NOT run cdk deploy.