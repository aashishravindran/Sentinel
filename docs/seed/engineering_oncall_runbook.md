# On-Call Runbook

**INTERNAL — Engineering Only**

## First Response Checklist

When paged, run through this in order before escalating:

1. Check the **Grafana dashboard** (`grafana.internal/d/prod-overview`) for the affected service
2. Check **CloudWatch Logs** for error spikes in the last 15 minutes
3. Check **SQS queue depth** — if workflow-engine queues exceed 50K messages, scale up workers manually via `kubectl scale`
4. Check for recent deployments in **ArgoCD** — if a deploy happened < 30 min ago, roll back first, investigate second

## Common Incidents & Fixes

### High API Latency (p99 > 1s)

**Likely causes:**
- Aurora connection pool exhausted — check `db.connections` metric in CloudWatch
- Redis cache cold — check hit rate in ElastiCache metrics
- Downstream connector timeout cascading — check connector-service error logs

**Fix:**
```bash
# Scale up acme-api if CPU > 90%
kubectl scale deployment acme-api --replicas=10 -n production

# Force Redis cache warm for top 100 orgs
kubectl exec -it $(kubectl get pod -l app=insights-service -o name | head -1) -- python scripts/warm_cache.py
```

### Workflow Execution Stuck

**Symptom:** Workflows show status `RUNNING` for > 10 minutes with no progress.

**Likely cause:** Dead-letter queue (DLQ) is full or a poison pill message is blocking a worker.

**Fix:**
```bash
# Check DLQ depth
aws sqs get-queue-attributes --queue-url $DLQ_URL --attribute-names ApproximateNumberOfMessages

# Purge DLQ (ONLY after saving message samples to S3 for debugging)
aws sqs purge-queue --queue-url $DLQ_URL
```

### Connector Auth Failures (401s)

**Likely cause:** OAuth token expired and refresh failed (Secrets Manager rate limit or upstream outage).

**Fix:**
1. Check connector-service logs for `token_refresh_failed`
2. Manually rotate the token for the affected connector in the admin UI (`admin.acme.internal/connectors`)
3. If upstream is down, set the connector to `DEGRADED` mode — this surfaces a warning to users without failing workflows

## Escalation Path

| Severity | Response Time | Who to Page |
|---|---|---|
| P0 (full outage) | 5 min | Primary + Secondary + Eng Manager |
| P1 (degraded, <20% errors) | 15 min | Primary on-call |
| P2 (non-customer-facing) | 60 min | Primary on-call (async Slack) |

## Post-Incident

All P0/P1 incidents require a blameless post-mortem doc in Notion within 5 business days. Use the template at `Engineering > Incidents > Post-Mortem Template`.

<!-- access_tags: engineering -->
