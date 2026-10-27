import { App } from 'aws-cdk-lib';
import { Template } from 'aws-cdk-lib/assertions';
import { CiCdStack } from '../lib/cicd-stack';

const t = Template.fromStack(
  new CiCdStack(new App(), 'CiCd', {
    env: { account: '123456789012', region: 'us-east-1' },
    repository: 'owner/repo',
    repositoryIds: { owner: 1, repo: 2 },
    environment: 'production',
  }),
);

const statements = (logicalPrefix: string) =>
  Object.entries(t.findResources('AWS::IAM::Policy'))
    .filter(([id]) => id.startsWith(logicalPrefix))
    .flatMap(([, p]) => p.Properties.PolicyDocument.Statement as { Action: string | string[]; Condition?: unknown }[])
    .map((s) => ({ actions: ([] as string[]).concat(s.Action), condition: s.Condition }));

describe('CiCdStack', () => {
  test('only the production environment of the pinned repo can assume the deploy role', () => {
    const trust = JSON.stringify(t.findResources('AWS::IAM::Role'));
    expect(trust).toContain('repo:owner@1/repo@2:environment:production');
  });

  test('the deploy role cannot assume the CDK bootstrap roles or touch IAM beyond passing one role', () => {
    const s = statements('DeployRole');
    const actions = s.flatMap((x) => x.actions);
    expect(actions).not.toContain('sts:AssumeRole');
    expect(actions.filter((a) => a.startsWith('iam:'))).toEqual(['iam:PassRole']);
    expect(s.find((x) => x.actions.includes('iam:PassRole'))!.condition).toEqual({
      StringEquals: { 'iam:PassedToService': 'cloudformation.amazonaws.com' },
    });
    expect(JSON.stringify(t.findResources('AWS::IAM::Policy'))).toContain('stack/SentinelDemo/*');
  });

  test('the execution role can only create roles that carry the boundary', () => {
    const s = statements('ExecutionRole');
    for (const x of s.filter((x) => x.actions.some((a) => ['iam:CreateRole', 'iam:PutRolePolicy', 'iam:PutRolePermissionsBoundary'].includes(a)))) {
      expect(JSON.stringify(x.condition)).toContain('iam:PermissionsBoundary');
    }
    const actions = s.flatMap((x) => x.actions);
    for (const forbidden of ['iam:*', '*', 'iam:AttachRolePolicy', 'iam:DeleteRolePermissionsBoundary']) {
      expect(actions).not.toContain(forbidden);
    }
  });

  test('smoke-test Cognito calls only work on the tagged demo pool', () => {
    const cognito = statements('DeployRole').find((x) => x.actions.includes('cognito-idp:AdminCreateUser'))!;
    expect(cognito.condition).toEqual({ StringEquals: { 'aws:ResourceTag/app': 'sentinel-demo' } });
  });

  test('no role has a fixed, guessable name', () => {
    for (const role of Object.values(t.findResources('AWS::IAM::Role'))) expect(role.Properties.RoleName).toBeUndefined();
  });
});
