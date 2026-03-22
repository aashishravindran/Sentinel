# Project Structure

## Project Overview

Sentinel is a Python MCP (Model Context Protocol) server that enforces Attribute-Based Access Control (ABAC) as middleware for RAG pipelines. It sits between MCP clients (Claude Desktop, Cursor, Claude Code) and vector databases, ensuring users only see documents they are authorized to access by matching user tags against document tags.

## Directory Structure

```
sentinel/                  # Main Python package
  main.py                  # FastMCP entry point, tool definitions (secure_search, ingest_document, ingest_pdf)
  core/
    base.py                # Abstract base classes: IdentityConnector, KnowledgeConnector
    engine.py              # SentinelEngine — ABAC orchestrator, tag intersection logic
  connectors/
    identity/
      sqlite.py            # SQLite identity connector (local dev)
      ddb.py               # DynamoDB identity connector (AWS, aioboto3)
    knowledge/
      chroma.py            # ChromaDB knowledge connector (local dev, sentence-transformers)
      bedrock.py           # AWS Bedrock KB connector (hybrid search, reranking, S3 ingestion)

scripts/                   # Utility scripts
  init_db.py               # Initialize SQLite DB with seed users
  ingest_seed_docs.py      # Load sample documents into local ChromaDB
  setup_aws.py             # Provision full AWS stack (DDB, S3, IAM, AOSS, Bedrock KB)
  seed_ddb.py              # Seed DynamoDB identity table with test users

tests/                     # Test suite
  (integration tests)

Design/                    # Architecture and design documents
  Architecture.md.md       # System components, diagrams, connector architecture
  Design.md.md             # Data models, security principles, connector contracts
  Project Structure.md.md  # Planned file layout
  Tasklist.md.md           # Phased implementation roadmap

data/                      # Runtime data (gitignored contents)
  permissions.db           # SQLite identity store (local dev)
  chroma/                  # ChromaDB vector store (local dev)
```

## Key Files

| File | Purpose |
|---|---|
| `sentinel/main.py` | MCP server entry point; defines `secure_search`, `ingest_document`, `ingest_pdf` tools |
| `sentinel/core/engine.py` | Backend-agnostic ABAC engine — calls identity + knowledge connectors |
| `sentinel/core/base.py` | ABC interfaces that all connectors implement |
| `sentinel/connectors/knowledge/bedrock.py` | Bedrock KB with hybrid search, reranking, S3+sidecar ingestion |
| `sentinel/connectors/identity/ddb.py` | DynamoDB identity lookup via aioboto3 |
| `scripts/setup_aws.py` | One-shot AWS provisioning (dev/demo only, not production-grade) |
| `.mcp.json` | MCP client configuration (backend selection + env vars) |
| `QUICKSTART.md` | Setup guide for local and AWS backends |
| `RESULTS.md` | Integration test results |

## Tech Stack

- **Runtime:** Python 3.12+, FastMCP
- **Package manager:** uv (pyproject.toml)
- **Local backends:** SQLite (identity), ChromaDB + sentence-transformers (knowledge)
- **AWS backends:** DynamoDB (identity), Bedrock Knowledge Bases + OpenSearch Serverless (knowledge)
- **AWS SDK:** aioboto3 (async, runtime), boto3 (sync, scripts)
- **PDF processing:** pypdf
- **Embeddings:** all-MiniLM-L6-v2 (local), Amazon Titan Embed Text v2 (AWS)
- **Testing:** pytest

## Conventions

- **Commit style:** Conventional commits (`feat(scope): description`)
- **Access control policy:** OR-policy (user needs any one of the document's tags)
- **Fail-closed:** No tags = access denied, never assume global access
- **Connector pattern:** Abstract base class in `core/base.py`, implementations in `connectors/`
- **Config:** Environment variables passed via `.mcp.json` env block
- **Tag storage:** Boolean attributes `tag_{name}: true` in metadata (both Chroma and Bedrock)
