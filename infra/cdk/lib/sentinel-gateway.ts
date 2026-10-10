// Copyright (c) 2026 Aashish Ravindran. All rights reserved.
// Use of this software is governed by the Elastic License 2.0
// found in the LICENSE file.

import { Duration, Stack, Validations } from 'aws-cdk-lib';
import * as agentcore from 'aws-cdk-lib/aws-bedrockagentcore';
import type * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import { Construct } from 'constructs';

/** How the gateway reaches documents. */
export type KnowledgeBaseTarget =
  /** Native connector to a Bedrock Managed Knowledge Base; the request interceptor writes its filter. */
  | { readonly kind: 'managed-kb'; readonly knowledgeBaseId: string; readonly forwardUserContext?: boolean }
  /** Sentinel's Lambda target in front of any standard Bedrock Knowledge Base. */
  | { readonly kind: 'lambda-target'; readonly knowledgeBaseId: string; readonly searchType?: 'HYBRID' | 'SEMANTIC' };

export interface OidcIssuer {
  /** OpenID discovery document, e.g. https://cognito-idp.<region>.amazonaws.com/<pool>/.well-known/openid-configuration */
  readonly discoveryUrl: string;
  readonly issuer: string;
  readonly jwksUri: string;
  /** Accepted `aud` values (Okta, Auth0, Entra). */
  readonly allowedAudience?: string[];
  /** Accepted `client_id` values (Cognito access tokens carry no `aud`). */
  readonly allowedClients?: string[];
}

export interface SentinelGatewayProps {
  readonly oidc: OidcIssuer;
  readonly knowledgeBase: KnowledgeBaseTarget;
  /** Identity store: partition key `user_id` (the token's `sub`), attribute `tags` (string set). */
  readonly identityTable: dynamodb.ITable;
  /** Python bundle containing `sentinel` and `sentinel_engine` (see scripts/build_lambda.sh). */
  readonly code: lambda.Code;
  /**
   * Warm instances per function, keeping cold starts off the auth path.
   * Billed while idle, so the default is 0; set 1+ for production.
   */
  readonly provisionedConcurrency?: number;
  readonly memorySize?: number;
  readonly gatewayName?: string;
}

/**
 * AgentCore Gateway with Sentinel as its policy decision point.
 *
 * The gateway's JWT authorizer establishes who is calling. The REQUEST
 * interceptor rebuilds every tool call's arguments from that identity and
 * the caller's live permissions; the RESPONSE interceptor hides control
 * arguments from tools/list and re-checks every returned chunk.
 */
export class SentinelGateway extends Construct {
  readonly gateway: agentcore.Gateway;
  readonly requestInterceptor: lambda.Alias;
  readonly responseInterceptor: lambda.Alias;
  readonly target?: lambda.Alias;

  constructor(scope: Construct, id: string, props: SentinelGatewayProps) {
    super(scope, id);
    const { oidc, knowledgeBase } = props;
    const knowledgeBaseArn = Stack.of(this).formatArn({
      service: 'bedrock',
      resource: 'knowledge-base',
      resourceName: knowledgeBase.knowledgeBaseId,
    });

    const environment: Record<string, string> = {
      SENTINEL_IDENTITY_STORE: 'dynamodb',
      DDB_TABLE_NAME: props.identityTable.tableName,
      SENTINEL_OIDC_ISSUER: oidc.issuer,
      SENTINEL_OIDC_JWKS_URI: oidc.jwksUri,
      SENTINEL_OIDC_AUDIENCE: (oidc.allowedAudience ?? []).join(','),
      SENTINEL_OIDC_ALLOWED_CLIENTS: (oidc.allowedClients ?? []).join(','),
      SENTINEL_KB_USER_CONTEXT: String(knowledgeBase.kind === 'managed-kb' && !!knowledgeBase.forwardUserContext),
    };

    // Seals the caller's identity for the Lambda target, which receives no headers.
    const envelopeKey = new secretsmanager.Secret(this, 'EnvelopeKey', {
      description: 'HMAC key binding a verified caller to one Sentinel tool call',
      generateSecretString: { passwordLength: 64, excludePunctuation: true },
    });
    environment.SENTINEL_ENVELOPE_SECRET_ARN = envelopeKey.secretArn;

    Validations.of(envelopeKey).acknowledge({
      id: 'AwsSolutions-SMG4',
      reason: 'Envelopes live 60 seconds; rotate by putting a new secret value and recycling the functions.',
    });

    const fn = (name: string, handler: string, extra: Record<string, string> = {}): lambda.Alias => {
      const logGroup = new logs.LogGroup(this, `${name}Logs`, { retention: logs.RetentionDays.ONE_MONTH });
      // A role scoped to this function's own log group, instead of AWSLambdaBasicExecutionRole.
      const role = new iam.Role(this, `${name}Role`, {
        assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
      });
      logGroup.grantWrite(role);
      Validations.of(role).acknowledge({
        id: `AwsSolutions-IAM5[Resource::<${Stack.of(this).getLogicalId(logGroup.node.defaultChild as logs.CfnLogGroup)}.Arn>:*]`,
        reason: 'Log streams are created at runtime inside this function’s own log group.',
      });
      const f = new lambda.Function(this, name, {
        runtime: lambda.Runtime.PYTHON_3_14,
        architecture: lambda.Architecture.ARM_64,
        handler,
        code: props.code,
        role,
        logGroup,
        // One JSON record per decision: user, tags, tool, allow/deny (queryable in Logs Insights).
        loggingFormat: lambda.LoggingFormat.JSON,
        applicationLogLevelV2: lambda.ApplicationLogLevel.INFO,
        systemLogLevelV2: lambda.SystemLogLevel.WARN,
        memorySize: props.memorySize ?? 1024,
        timeout: Duration.seconds(10),
        environment: { ...environment, ...extra },
      });
      props.identityTable.grant(f, 'dynamodb:GetItem');
      envelopeKey.grantRead(f);
      const warm = props.provisionedConcurrency ?? 0;
      return f.addAlias('live', warm > 0 ? { provisionedConcurrentExecutions: warm } : {});
    };

    this.requestInterceptor = fn('RequestInterceptor', 'sentinel.adapters.agentcore.request_interceptor.handler');
    this.responseInterceptor = fn('ResponseInterceptor', 'sentinel.adapters.agentcore.response_interceptor.handler');

    this.gateway = new agentcore.Gateway(this, 'Gateway', {
      gatewayName: props.gatewayName,
      description: 'Permission-aware retrieval: Sentinel decides, the gateway enforces',
      protocolConfiguration: agentcore.GatewayProtocol.mcp({
        instructions:
          'Searches only the documents the signed-in user may read. Empty results can mean the answer exists outside their access.',
        supportedVersions: [agentcore.MCPProtocolVersion.MCP_2025_06_18, agentcore.MCPProtocolVersion.MCP_2025_03_26],
      }),
      authorizerConfiguration: agentcore.GatewayAuthorizer.usingCustomJwt({
        discoveryUrl: oidc.discoveryUrl,
        allowedAudience: oidc.allowedAudience,
        allowedClients: oidc.allowedClients,
      }),
      interceptorConfigurations: [
        agentcore.LambdaInterceptor.forRequest(this.requestInterceptor, { passRequestHeaders: true }),
        agentcore.LambdaInterceptor.forResponse(this.responseInterceptor, { passRequestHeaders: true }),
      ],
    });

    if (knowledgeBase.kind === 'lambda-target') {
      const target = fn('SecureSearchTarget', 'sentinel.adapters.agentcore.target.handler', {
        SENTINEL_KNOWLEDGE_STORE: 'bedrock',
        BEDROCK_KB_ID: knowledgeBase.knowledgeBaseId,
        BEDROCK_SEARCH_TYPE: knowledgeBase.searchType ?? 'HYBRID',
      });
      target.addToRolePolicy(
        new iam.PolicyStatement({ actions: ['bedrock:Retrieve'], resources: [knowledgeBaseArn] }),
      );
      this.target = target;
      this.gateway.addLambdaTarget('SecureSearch', {
        gatewayTargetName: 'sentinel',
        description: 'Permission-aware search over the knowledge base',
        lambdaFunction: target,
        toolSchema: agentcore.ToolSchema.fromInline([
          {
            name: 'secure_search',
            description:
              'Search the knowledge base as the signed-in user. Only documents they may read are searched.',
            inputSchema: {
              type: agentcore.SchemaDefinitionType.OBJECT,
              properties: {
                query: { type: agentcore.SchemaDefinitionType.STRING, description: 'What to search for' },
                n_results: { type: agentcore.SchemaDefinitionType.INTEGER, description: 'Results to return (1-20)' },
                // Set by the request interceptor and hidden from tools/list by the response interceptor.
                _sentinel_principal: { type: agentcore.SchemaDefinitionType.STRING },
              },
              required: ['query'],
            },
          },
        ]),
      });
    } else {
      this.gateway.role.addToPrincipalPolicy(
        new iam.PolicyStatement({
          actions: ['bedrock:GetKnowledgeBase', 'bedrock:Retrieve'],
          resources: [knowledgeBaseArn],
        }),
      );
      // Exposed only so the request interceptor may write them; the response
      // interceptor strips both from tools/list, so the model never sees them.
      const overrides: agentcore.CfnGatewayTarget.ConnectorParameterOverrideProperty[] = [
        { path: '$.retrievalQuery.text', visible: true },
        { path: '$.retrievalConfiguration.managedSearchConfiguration.filter', visible: true },
      ];
      if (knowledgeBase.forwardUserContext) {
        overrides.push({ path: '$.userContext', visible: true });
      }
      new agentcore.CfnGatewayTarget(this, 'ManagedKbTarget', {
        gatewayIdentifier: this.gateway.gatewayId,
        name: 'kb',
        description: 'Bedrock Managed Knowledge Base, filtered per caller by Sentinel',
        credentialProviderConfigurations: [{ credentialProviderType: 'GATEWAY_IAM_ROLE' }],
        targetConfiguration: {
          mcp: {
            connector: {
              source: { connectorId: 'bedrock-knowledge-bases' },
              configurations: [
                {
                  name: 'Retrieve',
                  parameterValues: { knowledgeBaseId: knowledgeBase.knowledgeBaseId },
                  parameterOverrides: overrides,
                },
              ],
            },
          },
        },
      });
    }
  }
}
