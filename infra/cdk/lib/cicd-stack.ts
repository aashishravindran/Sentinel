// Copyright (c) 2026 Aashish Ravindran. All rights reserved.
// Use of this software is governed by the Elastic License 2.0
// found in the LICENSE file.

import { Aws, CfnOutput, Duration, RemovalPolicy, Stack, type StackProps, Validations } from 'aws-cdk-lib';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as s3 from 'aws-cdk-lib/aws-s3';
import type { Construct } from 'constructs';

/** The deployed stack's name; every resource it creates is named `SentinelDemo-*`. */
export const DEMO_STACK = 'SentinelDemo';
/** Every role the demo stack creates carries this boundary; the execution role can't create one without it. */
export const BOUNDARY_POLICY_NAME = 'sentinel-demo-boundary';
/** On every demo resource; the deploy role's Cognito admin calls (smoke test) only work on a pool with it. */
export const APP_TAG_KEY = 'app';
export const APP_TAG_VALUE = 'sentinel-demo';

/** Asset bucket for SentinelDemo deploys; the synthesizer resolves the placeholders. */
export function assetsBucketName(account = '${AWS::AccountId}', region = '${AWS::Region}'): string {
  return `sentinel-demo-assets-${account}-${region}`;
}

export interface CiCdStackProps extends StackProps {
  /** owner/name of the GitHub repository allowed to deploy. */
  readonly repository: string;
  /** GitHub's immutable owner and repo IDs, so a recreated repo with the same name is not trusted. */
  readonly repositoryIds: { readonly owner: number; readonly repo: number };
  /** GitHub environment the deploy job runs in; only it can assume the role. */
  readonly environment: string;
  /**
   * Create the account's GitHub OIDC provider. An account has at most one; by default this stack
   * uses the existing one (here, created by the sentinel-resume CI/CD stack).
   */
  readonly createOidcProvider?: boolean;
}

/**
 * What GitHub Actions may do to this AWS account for Sentinel. No stored AWS keys.
 *
 * - DeployRole: assumed through GitHub OIDC; deploys only the SentinelDemo stack and runs the smoke test.
 * - ExecutionRole: CloudFormation's role for that stack, scoped to the services it uses.
 * - Boundary: caps every role the stack creates, so a template can't mint an admin role.
 *
 * Deployed by hand, never by the pipeline: the pipeline cannot widen its own permissions.
 * Knowledge-base modes that create resources (`createManagedKb`) are not covered; deploy those by hand.
 */
export class CiCdStack extends Stack {
  constructor(scope: Construct, id: string, props: CiCdStackProps) {
    super(scope, id, props);
    Validations.of(this).acknowledge({ id: 'AwsSolutions-S1', reason: 'Asset bucket: build artifacts only; access logs add cost, no value.' });

    const provider = props.createOidcProvider
      ? new iam.OpenIdConnectProvider(this, 'GitHub', {
          url: 'https://token.actions.githubusercontent.com',
          clientIds: ['sts.amazonaws.com'],
        })
      : iam.OpenIdConnectProvider.fromOpenIdConnectProviderArn(
          this,
          'GitHub',
          `arn:aws:iam::${Aws.ACCOUNT_ID}:oidc-provider/token.actions.githubusercontent.com`,
        );

    const [owner, name] = props.repository.split('/');
    // Pseudo-parameters, not the resolved env: keeps cdk-nag finding IDs identical in every account.
    const account = Aws.ACCOUNT_ID;
    const region = Aws.REGION;
    const arn = (service: string, resource: string) => `arn:aws:${service}:${region}:${account}:${resource}`;
    const prefix = `${DEMO_STACK}-*`;

    // --- Assets: a bucket only this app uses (not the account-wide CDK bootstrap bucket) ---------
    const assets = new s3.Bucket(this, 'Assets', {
      bucketName: assetsBucketName(account, region),
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      enforceSSL: true,
      removalPolicy: RemovalPolicy.RETAIN,
    });

    // --- Boundary: the most any role created by SentinelDemo can ever do -------------------------
    const logGroups = [arn('logs', `log-group:${prefix}`), arn('logs', `log-group:/aws/lambda/${prefix}`)];
    const tables = [arn('dynamodb', `table/${prefix}`)];
    const secrets = [arn('secretsmanager', 'secret:SentinelEnvelopeKey*')];
    const boundary = new iam.ManagedPolicy(this, 'Boundary', {
      managedPolicyName: BOUNDARY_POLICY_NAME,
      description: 'Permissions boundary for every role the SentinelDemo stack creates.',
      statements: [
        new iam.PolicyStatement({
          actions: ['logs:CreateLogGroup', 'logs:CreateLogStream', 'logs:PutLogEvents'],
          resources: logGroups.flatMap((g) => [g, `${g}:*`]),
        }),
        // Interceptors and the Lambda target read one identity item.
        new iam.PolicyStatement({ actions: ['dynamodb:GetItem'], resources: tables }),
        new iam.PolicyStatement({ actions: ['secretsmanager:GetSecretValue', 'secretsmanager:DescribeSecret'], resources: secrets }),
        // The gateway's service role invokes the interceptors and the target.
        new iam.PolicyStatement({ actions: ['lambda:InvokeFunction'], resources: [arn('lambda', `function:${prefix}`)] }),
        // Knowledge-base modes: the Lambda target and the managed-KB connector retrieve.
        new iam.PolicyStatement({ actions: ['bedrock:Retrieve'], resources: [arn('bedrock', 'knowledge-base/*')] }),
      ],
    });

    // --- CloudFormation execution role: what a SentinelDemo deploy may touch ---------------------
    const execution = new iam.Role(this, 'ExecutionRole', {
      assumedBy: new iam.ServicePrincipal('cloudformation.amazonaws.com'),
      description: 'CloudFormation runs SentinelDemo deploys as this role. Not assumable by anyone else.',
    });
    const allow = (actions: string[], resources: string[], conditions?: Record<string, unknown>) =>
      execution.addToPolicy(new iam.PolicyStatement({ actions, resources, conditions }));
    const appRoles = `arn:aws:iam::${account}:role/${prefix}`;
    const bounded = { StringEquals: { 'iam:PermissionsBoundary': boundary.managedPolicyArn } };
    // Roles: only SentinelDemo-* names, only with the boundary, no managed policies.
    allow(['iam:CreateRole', 'iam:PutRolePolicy', 'iam:DeleteRolePolicy', 'iam:PutRolePermissionsBoundary'], [appRoles], bounded);
    allow(['iam:GetRole', 'iam:GetRolePolicy', 'iam:ListRolePolicies', 'iam:ListAttachedRolePolicies', 'iam:DeleteRole',
      'iam:UpdateRole', 'iam:UpdateRoleDescription', 'iam:TagRole', 'iam:UntagRole', 'iam:UpdateAssumeRolePolicy'], [appRoles]);
    allow(['iam:PassRole'], [appRoles], {
      StringEquals: { 'iam:PassedToService': ['lambda.amazonaws.com', 'bedrock-agentcore.amazonaws.com'] },
    });
    allow(['dynamodb:*'], tables.flatMap((t) => [t, `${t}/*`]));
    allow(['dynamodb:DescribeLimits', 'dynamodb:ListTables'], ['*']);
    allow(['lambda:*'], [arn('lambda', `function:${prefix}`)]);
    allow(['lambda:ListTags'], ['*']);
    allow(['logs:*'], logGroups.flatMap((g) => [g, `${g}:*`]));
    allow(['logs:DescribeLogGroups'], ['*']);
    allow(['secretsmanager:*'], secrets);
    allow(['secretsmanager:GetRandomPassword'], ['*']);
    allow(['s3:GetObject'], [assets.arnForObjects('*')]);
    // Generated IDs: user pools and gateways can't be scoped by name.
    allow(['cognito-idp:*'], [arn('cognito-idp', 'userpool/*')]);
    allow(['cognito-idp:CreateUserPool', 'cognito-idp:ListUserPools'], ['*']);
    allow(['bedrock-agentcore:*'], [arn('bedrock-agentcore', '*')]);

    // --- GitHub deploy role: deploy one stack, run the smoke test, nothing else ------------------
    const role = new iam.Role(this, 'DeployRole', {
      maxSessionDuration: Duration.hours(1),
      assumedBy: new iam.WebIdentityPrincipal(provider.openIdConnectProviderArn, {
        StringEquals: {
          'token.actions.githubusercontent.com:aud': 'sts.amazonaws.com',
          // Only jobs that declare this environment; the environment only admits master.
          'token.actions.githubusercontent.com:sub': `repo:${owner}@${props.repositoryIds.owner}/${name}@${props.repositoryIds.repo}:environment:${props.environment}`,
        },
      }),
    });
    role.addToPolicy(
      new iam.PolicyStatement({
        actions: ['cloudformation:CreateChangeSet', 'cloudformation:DescribeChangeSet', 'cloudformation:ExecuteChangeSet',
          'cloudformation:DeleteChangeSet', 'cloudformation:DescribeStacks', 'cloudformation:DescribeStackEvents',
          'cloudformation:DescribeStackResources', 'cloudformation:ListStackResources', 'cloudformation:GetTemplate',
          'cloudformation:GetTemplateSummary'],
        resources: [arn('cloudformation', `stack/${DEMO_STACK}/*`)],
      }),
    );
    role.addToPolicy(
      new iam.PolicyStatement({
        actions: ['iam:PassRole'],
        resources: [execution.roleArn],
        conditions: { StringEquals: { 'iam:PassedToService': 'cloudformation.amazonaws.com' } },
      }),
    );
    assets.grantReadWrite(role);
    // demo/smoke.py: one throwaway user in the demo pool and its identity item, removed afterwards.
    role.addToPolicy(
      new iam.PolicyStatement({
        actions: ['cognito-idp:AdminCreateUser', 'cognito-idp:AdminSetUserPassword', 'cognito-idp:AdminDeleteUser'],
        resources: [arn('cognito-idp', 'userpool/*')],
        conditions: { StringEquals: { [`aws:ResourceTag/${APP_TAG_KEY}`]: APP_TAG_VALUE } },
      }),
    );
    role.addToPolicy(
      new iam.PolicyStatement({
        actions: ['dynamodb:PutItem', 'dynamodb:DeleteItem'],
        resources: [arn('dynamodb', `table/${DEMO_STACK}-Identity*`)],
      }),
    );

    acknowledgeWildcards(this);

    // Not printed by CI: store both as GitHub environment secrets.
    new CfnOutput(this, 'DeployRoleArn', { value: role.roleArn });
    new CfnOutput(this, 'ExecutionRoleArn', { value: execution.roleArn });
  }
}

/**
 * cdk-nag flags every wildcard. Each one here is deliberate: CloudFormation generates the resource
 * names, so the grant is scoped by the stack's name prefix, or (for generated IDs) by service.
 */
function acknowledgeWildcards(stack: Stack): void {
  const r = (resource: string) => `AwsSolutions-IAM5[Resource::arn:aws:${resource}]`;
  const findings: [string, string][] = [
    ['AwsSolutions-IAM5[Action::lambda:*]', 'Execution role manages the stack\'s functions, versions and aliases (SentinelDemo-*).'],
    ['AwsSolutions-IAM5[Action::logs:*]', 'Execution role manages the stack\'s log groups (SentinelDemo-*).'],
    ['AwsSolutions-IAM5[Action::dynamodb:*]', 'Execution role manages the stack\'s identity table (SentinelDemo-*).'],
    ['AwsSolutions-IAM5[Action::secretsmanager:*]', 'Execution role manages the envelope key secret only.'],
    ['AwsSolutions-IAM5[Action::cognito-idp:*]', 'Execution role manages the demo user pool; pool IDs are generated.'],
    ['AwsSolutions-IAM5[Action::bedrock-agentcore:*]', 'Execution role manages the gateway and its targets; gateway IDs are generated.'],
    ['AwsSolutions-IAM5[Action::s3:Abort*]', 'Deploy role uploads assets to this app\'s own bucket (grantReadWrite).'],
    ['AwsSolutions-IAM5[Action::s3:DeleteObject*]', 'Deploy role uploads assets to this app\'s own bucket (grantReadWrite).'],
    ['AwsSolutions-IAM5[Action::s3:GetBucket*]', 'Deploy role uploads assets to this app\'s own bucket (grantReadWrite).'],
    ['AwsSolutions-IAM5[Action::s3:GetObject*]', 'Deploy role uploads assets to this app\'s own bucket (grantReadWrite).'],
    ['AwsSolutions-IAM5[Action::s3:List*]', 'Deploy role uploads assets to this app\'s own bucket (grantReadWrite).'],
    ['AwsSolutions-IAM5[Resource::*]', 'List/describe calls and GetRandomPassword have no resource-level scoping.'],
    ['AwsSolutions-IAM5[Resource::<Assets9A31D427.Arn>/*]', 'Objects in this app\'s own asset bucket.'],
    [r('bedrock-agentcore:<AWS::Region>:<AWS::AccountId>:*'), 'Gateway and target IDs are generated; agentcore resources in this account.'],
    [r('bedrock:<AWS::Region>:<AWS::AccountId>:knowledge-base/*'), 'Boundary ceiling for KB modes; each role still names its one KB.'],
    [r('cloudformation:<AWS::Region>:<AWS::AccountId>:stack/SentinelDemo/*'), 'The SentinelDemo stack, any stack ID.'],
    [r('cognito-idp:<AWS::Region>:<AWS::AccountId>:userpool/*'), 'Pool IDs are generated; the deploy role also requires the app tag.'],
    [r('dynamodb:<AWS::Region>:<AWS::AccountId>:table/SentinelDemo-*'), 'Tables created by the SentinelDemo stack.'],
    [r('dynamodb:<AWS::Region>:<AWS::AccountId>:table/SentinelDemo-*/*'), 'Indexes and streams of those tables.'],
    [r('dynamodb:<AWS::Region>:<AWS::AccountId>:table/SentinelDemo-Identity*'), 'The demo identity table (smoke-test user item).'],
    [r('iam::<AWS::AccountId>:role/SentinelDemo-*'), 'Roles created by the stack; creating one requires the boundary.'],
    [r('lambda:<AWS::Region>:<AWS::AccountId>:function:SentinelDemo-*'), 'Functions created by the SentinelDemo stack.'],
    [r('logs:<AWS::Region>:<AWS::AccountId>:log-group:SentinelDemo-*'), 'Log groups created by the SentinelDemo stack.'],
    [r('logs:<AWS::Region>:<AWS::AccountId>:log-group:SentinelDemo-*:*'), 'Log streams in those groups.'],
    [r('logs:<AWS::Region>:<AWS::AccountId>:log-group:/aws/lambda/SentinelDemo-*'), 'Default log groups of the stack\'s functions.'],
    [r('logs:<AWS::Region>:<AWS::AccountId>:log-group:/aws/lambda/SentinelDemo-*:*'), 'Log streams in those groups.'],
    [r('secretsmanager:<AWS::Region>:<AWS::AccountId>:secret:SentinelEnvelopeKey*'), 'The envelope key; Secrets Manager appends a random suffix.'],
  ];
  for (const [id, reason] of findings) {
    Validations.of(stack).acknowledge({ id, reason });
  }
}
