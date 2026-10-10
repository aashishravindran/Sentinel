# Project Structure

## Overview

Sentinel makes AI agents retrieve only what their human may read. It has two adapters over
one policy engine:

- **MCP server** (`sentinel/adapters/mcp`): identity from the transport (stdio launcher or a
  verified JWT `sub` over HTTP), never from tool arguments.
- **AgentCore Gateway** (`sentinel/adapters/agentcore`): REQUEST/RESPONSE interceptor Lambdas
  and a Lambda target, deployed by the TypeScript CDK construct in `infra/cdk`.

The engine, connectors, filter builders, OIDC verification and ingest stamping live in
**sentinel-engine** (github.com/aashishravindran/sentinel-engine, package `sentinel_engine`),
pinned by git tag in `[tool.uv.sources]`.

## Layout

```
sentinel/
  main.py                       # shim: python -m sentinel.main → adapters.mcp.server.main
  adapters/mcp/                 # settings.py (transport identity), identity.py, server.py (tools), uploads.py
  adapters/agentcore/           # events.py, request_interceptor.py, response_interceptor.py, target.py, envelope.py, runtime.py
  ingest/                       # documents.py (tagged Markdown ingest), identity_sync.py (DDB org sync)
infra/cdk/                      # SentinelGateway + SentinelManagedKb constructs, demo stack, jest tests
spicedb/                        # schema.zed (teams, tags, platform admin), seed.sh, validation.yaml
demo/                           # run_demo.py (local end-to-end), org.json, demo.tape
scripts/                        # build_lambda.sh, ingest_seed_docs.py, sync_identity.py, init_db.py, setup_aws.py
tests/
  support/                      # fakes (DictIdentity, StubBedrockKB), test OIDC issuer, Gateway event builders
  agentcore/                    # interceptor and target unit tests
  conformance/                  # same decisions across all four entry points
  redteam/                      # leak set, token matrix, spoofing, ingest lockdown
  load/                         # bench_layers.py, recall.py (scripts, not collected)
  e2e/                          # live SpiceDB / AWS (skipped unless available)
docs/                           # adr/, threat-model.md, benchmarks.md, assets/, seed/
```

## Conventions

- Identity is never a tool argument. Adapters build a `Principal` from the transport.
- Every failure denies with one generic message (`sentinel_engine.results.ACCESS_DENIED`);
  reasons go to logs.
- Filters come only from `sentinel_engine.filters`; ingest metadata only from
  `sentinel_engine.ingest.stamp`.
- `ruff` (line length 100) and `pyright --strict` must pass; red-team leak rate must be 0.
