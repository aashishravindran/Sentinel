// Copyright (c) 2026 Aashish Ravindran. All rights reserved.
// Use of this software is governed by the Elastic License 2.0
// found in the LICENSE file.

import { RemovalPolicy, Stack, Validations } from 'aws-cdk-lib';
import * as bedrock from 'aws-cdk-lib/aws-bedrock';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as s3 from 'aws-cdk-lib/aws-s3';
import { Construct } from 'constructs';

export interface SentinelManagedKbProps {
  readonly name: string;
  /** S3 prefix Sentinel's ingest writes documents and .metadata.json sidecars under. */
  readonly documentPrefix?: string;
}

/**
 * A Bedrock Managed Knowledge Base fed from S3.
 *
 * Bedrock runs the vector store. Sentinel's ingest stamps each document's
 * access tags into its .metadata.json sidecar, which is what the gateway
 * filter matches on.
 */
export class SentinelManagedKb extends Construct {
  readonly bucket: s3.Bucket;
  readonly knowledgeBaseId: string;
  readonly dataSourceId: string;

  constructor(scope: Construct, id: string, props: SentinelManagedKbProps) {
    super(scope, id);
    const prefix = props.documentPrefix ?? 'documents/';
    const { account } = Stack.of(this);

    this.bucket = new s3.Bucket(this, 'Documents', {
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      enforceSSL: true,
      versioned: true,
      removalPolicy: RemovalPolicy.RETAIN,
    });
    Validations.of(this.bucket).acknowledge({
      id: 'AwsSolutions-S1',
      reason: 'Demo corpus; enable server access logs or CloudTrail data events for production data.',
    });

    const role = new iam.Role(this, 'KbRole', {
      assumedBy: new iam.ServicePrincipal('bedrock.amazonaws.com', {
        conditions: { StringEquals: { 'aws:SourceAccount': account } },
      }),
    });
    this.bucket.grantRead(role, `${prefix}*`);
    const bucketId = Stack.of(this).getLogicalId(this.bucket.node.defaultChild as s3.CfnBucket);
    for (const finding of [
      'Action::s3:GetBucket*',
      'Action::s3:GetObject*',
      'Action::s3:List*',
      `Resource::<${bucketId}.Arn>/${prefix}*`,
    ]) {
      Validations.of(role).acknowledge({
        id: `AwsSolutions-IAM5[${finding}]`,
        reason: 'Read-only access for Bedrock ingestion, limited to the document prefix of this bucket.',
      });
    }

    const kb = new bedrock.CfnKnowledgeBase(this, 'KnowledgeBase', {
      name: props.name,
      description: 'Sentinel demo documents; access tags live in each document sidecar',
      roleArn: role.roleArn,
      knowledgeBaseConfiguration: { type: 'MANAGED', managedKnowledgeBaseConfiguration: {} },
    });

    const source = new bedrock.CfnDataSource(this, 'DataSource', {
      knowledgeBaseId: kb.attrKnowledgeBaseId,
      name: 'documents',
      dataSourceConfiguration: {
        type: 'MANAGED_KNOWLEDGE_BASE_CONNECTOR',
        managedKnowledgeBaseConnectorConfiguration: {
          connectorParameters: {
            type: 'S3',
            version: '1',
            connectionConfiguration: { bucketName: this.bucket.bucketName, bucketOwnerAccountId: account },
            filterConfiguration: { inclusionPrefixes: [prefix] },
          },
        },
      },
    });

    this.knowledgeBaseId = kb.attrKnowledgeBaseId;
    this.dataSourceId = source.attrDataSourceId;
  }
}
