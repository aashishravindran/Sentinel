#!/usr/bin/env node
// Copyright (c) 2026 Aashish Ravindran. All rights reserved.
// Use of this software is governed by the Elastic License 2.0
// found in the LICENSE file.

import * as path from 'node:path';
import { App, Validations } from 'aws-cdk-lib';
import { AwsSolutionsChecks } from 'cdk-nag';
import { SentinelDemoStack } from '../lib/demo-stack';

const app = new App();

// Default: no knowledge base (identity, interceptors and logging only; nothing bills while idle).
//   cdk deploy -c knowledgeBaseId=<id> -c knowledgeBaseKind=standard|managed-kb   bring your own KB
//   cdk deploy -c createManagedKb=true                                           create one (bills while it exists)
const knowledgeBaseId: string | undefined = app.node.tryGetContext('knowledgeBaseId');
const createManagedKb = app.node.tryGetContext('createManagedKb') === 'true';

new SentinelDemoStack(app, 'SentinelDemo', {
  description: 'Sentinel: permission-aware retrieval behind AgentCore Gateway',
  lambdaBundlePath: path.resolve(__dirname, '../../../build/lambda'),
  knowledgeBase: knowledgeBaseId
    ? { existing: app.node.tryGetContext('knowledgeBaseKind') === 'managed-kb' ? 'managed-kb' : 'standard', knowledgeBaseId }
    : createManagedKb
      ? { create: 'managed-kb' }
      : { none: true },
});

Validations.of(app).addPlugins(new AwsSolutionsChecks(app, { verbose: true }));
