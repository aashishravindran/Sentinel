import { App, Stack } from 'aws-cdk-lib';
import { Match, Template } from 'aws-cdk-lib/assertions';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import { type KnowledgeBaseTarget, SentinelGateway, type SentinelGatewayProps } from '../lib';

function synth(knowledgeBase: KnowledgeBaseTarget, extra: Partial<SentinelGatewayProps> = {}): Template {
  const stack = new Stack(new App(), 'Test');
  const identityTable = new dynamodb.TableV2(stack, 'Identity', {
    partitionKey: { name: 'user_id', type: dynamodb.AttributeType.STRING },
  });
  new SentinelGateway(stack, 'Sentinel', {
    oidc: {
      discoveryUrl: 'https://issuer.example.com/.well-known/openid-configuration',
      issuer: 'https://issuer.example.com',
      jwksUri: 'https://issuer.example.com/.well-known/jwks.json',
      allowedClients: ['client-1'],
    },
    knowledgeBase,
    identityTable,
    code: lambda.Code.fromInline('def handler(event, context): pass'),
    ...extra,
  });
  return Template.fromStack(stack);
}

const STANDARD: KnowledgeBaseTarget = { kind: 'lambda-target', knowledgeBaseId: 'KB12345678' };
const MANAGED: KnowledgeBaseTarget = { kind: 'managed-kb', knowledgeBaseId: 'KB12345678' };

describe('SentinelGateway', () => {
  test('one REQUEST and one RESPONSE interceptor, both with request headers', () => {
    const interceptor = (point: string) =>
      Match.objectLike({ InterceptionPoints: [point], InputConfiguration: { PassRequestHeaders: true } });
    synth(STANDARD).hasResourceProperties('AWS::BedrockAgentCore::Gateway', {
      AuthorizerType: 'CUSTOM_JWT',
      InterceptorConfigurations: [interceptor('REQUEST'), interceptor('RESPONSE')],
    });
  });

  test('the JWT authorizer pins issuer discovery and clients', () => {
    synth(STANDARD).hasResourceProperties('AWS::BedrockAgentCore::Gateway', {
      AuthorizerConfiguration: {
        CustomJWTAuthorizer: {
          DiscoveryUrl: 'https://issuer.example.com/.well-known/openid-configuration',
          AllowedClients: ['client-1'],
        },
      },
    });
  });

  test('lambda-target mode adds the secure_search target and scopes Retrieve to one KB', () => {
    const template = synth(STANDARD);
    template.resourceCountIs('AWS::Lambda::Function', 3);
    template.hasResourceProperties('AWS::BedrockAgentCore::GatewayTarget', { Name: 'sentinel' });
    template.hasResourceProperties('AWS::IAM::Policy', {
      PolicyDocument: {
        Statement: Match.arrayWith([
          Match.objectLike({
            Action: 'bedrock:Retrieve',
            Resource: { 'Fn::Join': ['', Match.arrayWith([Match.stringLikeRegexp(':knowledge-base/KB12345678$')])] },
          }),
        ]),
      },
    });
  });

  test('managed-kb mode exposes only the filter, never userContext by default', () => {
    const template = synth(MANAGED);
    template.resourceCountIs('AWS::Lambda::Function', 2);
    template.hasResourceProperties('AWS::BedrockAgentCore::GatewayTarget', {
      TargetConfiguration: {
        Mcp: {
          Connector: {
            Source: { ConnectorId: 'bedrock-knowledge-bases' },
            Configurations: [
              {
                Name: 'Retrieve',
                ParameterValues: { knowledgeBaseId: 'KB12345678' },
                ParameterOverrides: [
                  { Path: '$.retrievalQuery.text', Visible: true },
                  { Path: '$.retrievalConfiguration.managedSearchConfiguration.filter', Visible: true },
                ],
              },
            ],
          },
        },
      },
    });
  });

  test('functions are arm64, read only their identity item and run without idle cost by default', () => {
    const template = synth(STANDARD);
    template.allResourcesProperties('AWS::Lambda::Function', {
      Architectures: ['arm64'],
      LoggingConfig: Match.objectLike({ LogFormat: 'JSON', ApplicationLogLevel: 'INFO' }),
    });
    template.resourcePropertiesCountIs(
      'AWS::Lambda::Alias',
      { ProvisionedConcurrencyConfig: Match.anyValue() },
      0,
    );
    const policies = JSON.stringify(template.findResources('AWS::IAM::Policy'));
    expect(policies).not.toMatch(/"bedrock:\*"|"dynamodb:\*"|"lambda:\*"/);
    expect(policies).not.toMatch(/"Resource":"\*"/);
  });

  test('provisioned concurrency is opt-in', () => {
    synth(STANDARD, { provisionedConcurrency: 2 }).resourcePropertiesCountIs(
      'AWS::Lambda::Alias',
      { ProvisionedConcurrencyConfig: { ProvisionedConcurrentExecutions: 2 } },
      3,
    );
  });

  test('none mode serves what_can_i_access and grants no Bedrock access', () => {
    const template = synth({ kind: 'none' });
    template.resourceCountIs('AWS::Lambda::Function', 3);
    const target = JSON.stringify(template.findResources('AWS::BedrockAgentCore::GatewayTarget'));
    expect(target).toContain('what_can_i_access');
    expect(target).not.toContain('secure_search');
    expect(JSON.stringify(template.findResources('AWS::IAM::Policy'))).not.toContain('bedrock:');
  });

  test('no function uses the broad AWSLambdaBasicExecutionRole', () => {
    expect(JSON.stringify(synth(STANDARD).toJSON())).not.toContain('AWSLambdaBasicExecutionRole');
  });
});
