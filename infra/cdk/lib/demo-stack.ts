// Copyright (c) 2026 Aashish Ravindran. All rights reserved.
// Use of this software is governed by the Elastic License 2.0
// found in the LICENSE file.

import { CfnOutput, RemovalPolicy, Stack, type StackProps, Validations } from 'aws-cdk-lib';
import * as cognito from 'aws-cdk-lib/aws-cognito';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import type { Construct } from 'constructs';
import { SentinelManagedKb } from './managed-kb';
import { type KnowledgeBaseTarget, SentinelGateway } from './sentinel-gateway';

export interface SentinelDemoStackProps extends StackProps {
  /** Path to the Lambda bundle built by scripts/build_lambda.sh. */
  readonly lambdaBundlePath: string;
  /**
   * The knowledge base to put behind the gateway. Nothing is created unless
   * `{ create: 'managed-kb' }` is passed: a knowledge base's vector store bills
   * while idle, so the demo never provisions one implicitly.
   */
  readonly knowledgeBase:
    | { readonly existing: 'managed-kb' | 'standard'; readonly knowledgeBaseId: string }
    | { readonly create: 'managed-kb' };
}

/** A complete demo org: Cognito users, a DynamoDB identity store, a knowledge base and the gateway. */
export class SentinelDemoStack extends Stack {
  constructor(scope: Construct, id: string, props: SentinelDemoStackProps) {
    super(scope, id, props);

    const userPool = new cognito.UserPool(this, 'Users', {
      selfSignUpEnabled: false,
      signInAliases: { username: true },
      passwordPolicy: {
        minLength: 12,
        requireDigits: true,
        requireLowercase: true,
        requireUppercase: true,
        requireSymbols: true,
      },
      removalPolicy: RemovalPolicy.DESTROY,
    });
    for (const [id, reason] of [
      ['AwsSolutions-COG2', 'Demo personas are scripted; require MFA for real users.'],
      ['AwsSolutions-COG8', 'Threat protection (Plus tier) is out of scope for the demo org.'],
    ]) {
      Validations.of(userPool).acknowledge({ id, reason });
    }
    const client = userPool.addClient('DemoClient', {
      authFlows: { userPassword: true },
      generateSecret: false,
    });

    const identityTable = new dynamodb.TableV2(this, 'Identity', {
      partitionKey: { name: 'user_id', type: dynamodb.AttributeType.STRING },
      pointInTimeRecoverySpecification: { pointInTimeRecoveryEnabled: true },
      removalPolicy: RemovalPolicy.DESTROY,
    });

    let knowledgeBase: KnowledgeBaseTarget;
    if ('existing' in props.knowledgeBase) {
      const { existing, knowledgeBaseId } = props.knowledgeBase;
      knowledgeBase =
        existing === 'managed-kb' ? { kind: 'managed-kb', knowledgeBaseId } : { kind: 'lambda-target', knowledgeBaseId };
    } else {
      const kb = new SentinelManagedKb(this, 'Kb', { name: 'sentinel-demo' });
      knowledgeBase = { kind: 'managed-kb', knowledgeBaseId: kb.knowledgeBaseId };
      new CfnOutput(this, 'DocumentsBucket', { value: kb.bucket.bucketName });
      new CfnOutput(this, 'KnowledgeBaseId', { value: kb.knowledgeBaseId });
      new CfnOutput(this, 'DataSourceId', { value: kb.dataSourceId });
    }

    const issuer = `https://cognito-idp.${this.region}.amazonaws.com/${userPool.userPoolId}`;
    const sentinel = new SentinelGateway(this, 'Sentinel', {
      oidc: {
        discoveryUrl: `${issuer}/.well-known/openid-configuration`,
        issuer,
        jwksUri: `${issuer}/.well-known/jwks.json`,
        allowedClients: [client.userPoolClientId],
      },
      knowledgeBase,
      identityTable,
      code: lambda.Code.fromAsset(props.lambdaBundlePath),
    });

    new CfnOutput(this, 'GatewayUrl', { value: sentinel.gateway.gatewayUrl ?? '' });
    new CfnOutput(this, 'UserPoolId', { value: userPool.userPoolId });
    new CfnOutput(this, 'UserPoolClientId', { value: client.userPoolClientId });
    new CfnOutput(this, 'IdentityTableName', { value: identityTable.tableName });
  }
}
