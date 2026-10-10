#!/usr/bin/env node
// Copyright (c) 2026 Aashish Ravindran. All rights reserved.
// Use of this software is governed by the Elastic License 2.0
// found in the LICENSE file.

import * as path from 'node:path';
import { App, Validations } from 'aws-cdk-lib';
import { AwsSolutionsChecks } from 'cdk-nag';
import { SentinelDemoStack } from '../lib/demo-stack';

const app = new App();

// Bring your own knowledge base:
//   cdk synth -c knowledgeBaseId=<id> -c knowledgeBaseKind=standard|managed-kb
// Or, knowing a Managed KB bills for as long as it exists:
//   cdk synth -c createManagedKb=true
const knowledgeBaseId: string | undefined = app.node.tryGetContext('knowledgeBaseId');
const createManagedKb = app.node.tryGetContext('createManagedKb') === 'true';
if (!knowledgeBaseId && !createManagedKb) {
  throw new Error('Pass -c knowledgeBaseId=<id> (and -c knowledgeBaseKind=standard|managed-kb) or -c createManagedKb=true');
}

new SentinelDemoStack(app, 'SentinelDemo', {
  description: 'Sentinel: permission-aware retrieval behind AgentCore Gateway',
  lambdaBundlePath: path.resolve(__dirname, '../../../build/lambda'),
  knowledgeBase: knowledgeBaseId
    ? { existing: app.node.tryGetContext('knowledgeBaseKind') === 'managed-kb' ? 'managed-kb' : 'standard', knowledgeBaseId }
    : { create: 'managed-kb' },
});

Validations.of(app).addPlugins(new AwsSolutionsChecks(app, { verbose: true }));
