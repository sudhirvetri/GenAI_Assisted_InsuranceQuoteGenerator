#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib/core';
import { IqgCdkStack } from '../lib/iqg-cdk-stack';

const app = new cdk.App();
new IqgCdkStack(app, 'IqgCdkStack', {
  env: { account: '867344470917', region: 'us-east-1' },
});
