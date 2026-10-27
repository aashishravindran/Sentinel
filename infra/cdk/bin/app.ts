#!/usr/bin/env node
// Copyright (c) 2026 Aashish Ravindran. All rights reserved.
// Use of this software is governed by the Elastic License 2.0
// found in the LICENSE file.

import * as path from 'node:path';
import { App, CliCredentialsStackSynthesizer, Tags, Validations } from 'aws-cdk-lib';
import * as iam from 'aws-cdk-lib/aws-iam';
import { AwsSolutionsChecks } from 'cdk-nag';
import { APP_TAG_KEY, APP_TAG_VALUE, assetsBucketName, BOUNDARY_POLICY_NAME, CiCdStack, DEMO_STACK } from '../lib/cicd-stack';
import { SentinelDemoStack } from '../lib/demo-stack';

const app = new App();

// Default: no knowledge base (identity, interceptors and logging only; nothing bills while idle).
//   cdk deploy -c knowledgeBaseId=<id> -c knowledgeBaseKind=standard|managed-kb   bring your own KB
//   cdk deploy -c createManagedKb=true                                           create one (bills while it exists)
const knowledgeBaseId: string | undefined = app.node.tryGetContext('knowledgeBaseId');
const createManagedKb = app.node.tryGetContext('createManagedKb') === 'true';

const env = { account: process.env.CDK_DEFAULT_ACCOUNT, region: process.env.CDK_DEFAULT_REGION ?? 'us-east-1' };

const demo = new SentinelDemoStack(app, DEMO_STACK, {
  env,
  description: 'Sentinel: permission-aware retrieval behind AgentCore Gateway',
  // Deployed with the caller's credentials and this app's own asset bucket, never the CDK bootstrap
  // roles (their deploy role can update any stack in the account). CloudFormation runs as the scoped
  // execution role from SentinelCiCd, passed with --role-arn.
  synthesizer: new CliCredentialsStackSynthesizer({ fileAssetsBucketName: assetsBucketName() }),
  lambdaBundlePath: path.resolve(__dirname, '../../../build/lambda'),
  knowledgeBase: knowledgeBaseId
    ? { existing: app.node.tryGetContext('knowledgeBaseKind') === 'managed-kb' ? 'managed-kb' : 'standard', knowledgeBaseId }
    : createManagedKb
      ? { create: 'managed-kb' }
      : { none: true },
});

// Every role in the demo stack carries the boundary; the execution role refuses to create one without it.
iam.PermissionsBoundary.of(demo).apply(iam.ManagedPolicy.fromManagedPolicyName(demo, 'Boundary', BOUNDARY_POLICY_NAME));
Tags.of(demo).add(APP_TAG_KEY, APP_TAG_VALUE);

// Deployed by hand, once: `npx cdk deploy SentinelCiCd`. The pipeline only deploys SentinelDemo.
new CiCdStack(app, 'SentinelCiCd', {
  env,
  repository: 'aashishravindran/Sentinel',
  repositoryIds: { owner: 16415392, repo: 1184016811 },
  environment: 'production',
  createOidcProvider: app.node.tryGetContext('createGithubOidcProvider') === 'true',
});

Validations.of(app).addPlugins(new AwsSolutionsChecks(app, { verbose: true }));
