# System Architecture

**INTERNAL — Engineering Only**

## Overview

Acme's backend is a service-oriented architecture running on AWS. Services communicate over gRPC internally and expose REST/GraphQL externally. All services are containerised (Docker) and orchestrated via EKS.

## Core Services

### acme-api (Gateway)
- **Language:** Go
- **Role:** Public-facing API gateway. Handles auth (JWT validation via Cognito), rate limiting, and request routing to downstream services.
- **Scaling:** Horizontal, target 70% CPU, min 3 replicas.

### workflow-engine
- **Language:** Rust
- **Role:** Executes workflow DAGs. Stateless workers pull jobs from SQS. Each job is a serialised DAG node.
- **Storage:** Workflow definitions in DynamoDB; execution state in Redis (TTL 24h).
- **Scaling:** 5–80 replicas based on SQS queue depth.

### connector-service
- **Language:** Python (FastAPI)
- **Role:** Manages OAuth token lifecycle and executes connector actions (e.g. create Salesforce record, send Slack message). Secrets stored in AWS Secrets Manager.
- **Scaling:** Horizontal; one pod per connector type to isolate blast radius.

### insights-service
- **Language:** Python
- **Role:** Aggregates workflow execution data into materialized views. Reads from the analytics DynamoDB table, writes to Redshift via COPY.
- **Schedule:** Near-realtime via Kinesis Firehose for hot data; nightly batch for historical rollups.

## Data Layer

| Store | Technology | Used For |
|---|---|---|
| Primary DB | Aurora PostgreSQL (Serverless v2) | User, org, billing records |
| Workflow State | DynamoDB | Workflow definitions & run history |
| Cache | ElastiCache (Redis) | Session state, job locks |
| Blob Storage | S3 | Connector payloads, file attachments |
| Analytics | Redshift | Reporting and Insights product |
| Search | OpenSearch | Full-text search across workflow names/logs |

## Deployment Pipeline

1. PR merged to `main` → GitHub Actions runs unit + integration tests
2. Docker image built and pushed to ECR
3. ArgoCD detects new image tag → rolls out to staging automatically
4. Manual promotion to production via ArgoCD UI (requires 2 approvals)

## On-Call

- Rotation managed in PagerDuty; 1 primary + 1 secondary per week
- Runbooks live in Notion under Engineering > On-Call
- SLO: 99.9% uptime on acme-api; p99 latency < 500ms

<!-- access_tags: engineering -->
