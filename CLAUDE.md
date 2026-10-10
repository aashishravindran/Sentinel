# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Sentinel makes AI agents retrieve only what their human may read. Two adapters, the MCP
server and AgentCore Gateway interceptors, share one policy engine from the sibling repo
`../sentinel-engine` (package `sentinel_engine`). Identity always comes from the transport
(stdio launcher or verified JWT `sub`), never from tool arguments; permissions are resolved
live (SpiceDB, DynamoDB, SQLite, IAM) and pushed into the vector query as a filter.

See `.claude/skills/project-structure.md` for the layout and conventions.

## Commands

```bash
uv sync                                              # needs ../sentinel-engine checked out
SENTINEL_STDIO_USER=alice SENTINEL_IDENTITY_STORE=sqlite SENTINEL_KNOWLEDGE_STORE=chroma \
  uv run python -m sentinel.main                     # MCP server (stdio)
uv run python -m demo.run_demo                       # local end-to-end demo
uv run pytest -m "not e2e and not aws and not load"  # unit, conformance, red team
uv run ruff check . && uv run pyright                # lint, strict types
./scripts/build_lambda.sh && (cd infra/cdk && npm test && npx cdk synth -c knowledgeBaseId=X -c knowledgeBaseKind=standard)
```

## Key Security Principles

- **Identity from the transport:** no tool accepts a user ID; `sub` is the user, `client_id` never is.
- **Fail closed:** no tags, identity errors, bad tokens and unparseable results all deny.
- **Live scope:** nothing cached; revocation applies on the next call.
- **Filter in the query, then re-check:** one filter builder for every store; results post-filtered.

## Design Documents

Current design: `docs/adr/`, `docs/threat-model.md`, `docs/benchmarks.md`. Historical v1 notes in `Design/`:
- `Architecture.md.md` — system components, connector architecture, search pipeline diagrams
- `Design.md.md` — data models, security principles, connector contracts
- `Project Structure.md.md` — file layout with annotations
- `Tasklist.md.md` — phased implementation roadmap

## Session Log

### 2026-03-21
Added AWS backend support: DynamoDB identity connector, Bedrock Knowledge Bases connector with hybrid search (dense + BM25) and optional reranking, PDF ingestion via pypdf, and AWS infrastructure provisioning script. Updated architecture docs and added QUICKSTART.md with setup guides for both local and AWS configurations.

### 2026-10-09
Sentinel v2: identity bound to the transport (v1 trusted a model-supplied `user_id`); engine
and connectors extracted to `sentinel-engine`; admin tools role-gated; SpiceDB team
inheritance; AgentCore Gateway adapter (interceptors, Lambda target, principal envelope) with
a TypeScript CDK construct; conformance, red-team and benchmark suites; ADRs and threat model.
