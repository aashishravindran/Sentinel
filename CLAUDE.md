# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Sentinel is a Python MCP (Model Context Protocol) server implementing **Attribute-Based Access Control (ABAC)** as middleware for RAG (Retrieval-Augmented Generation) pipelines. It sits between MCP clients (Claude Desktop, Cursor) and vector databases, enforcing zero-trust access control by matching user tags to document tags before returning search results.

## Planned Stack

- **Runtime:** Python with [FastMCP](https://github.com/jlowin/fastmcp)
- **Package manager:** `uv` (with `pyproject.toml`)
- **Identity stores:** DynamoDB (prod), SQLite (local dev/testing)
- **Knowledge stores:** AWS Bedrock Knowledge Bases, Pinecone (future)

## Commands (once implemented)

```bash
# Install dependencies
uv sync

# Run the MCP server locally
python -m sentinel_mcp

# Run tests
uv run pytest

# Run a single test
uv run pytest tests/path/to/test_file.py::test_name
```

## Architecture

### Core Access Control Flow

```
Client → secure_search(query, user_id)
       → Identity Store: lookup user tags
       → [Fail-Closed: no tags = deny]
       → Build metadata filter from tags
       → Knowledge Store: filtered vector search
       → Return results to LLM
```

### Key Security Principles

- **Zero Trust / Fail-Closed:** If a user has no tags, access is denied. Never assumes global access.
- **Stateless:** No user data cached between sessions.
- **Intersection Policy:** User must possess at least one tag matching the document's `access_tags` field.

### Planned Module Structure

```
sentinel/
├── main.py              # FastMCP entry point & tool definitions
├── core/
│   ├── base.py          # Abstract Base Classes for connectors
│   └── engine.py        # Orchestrator — ABAC logic, tag intersection
└── connectors/
    ├── identity/
    │   ├── ddb.py        # DynamoDB identity connector
    │   └── sqlite.py     # SQLite identity connector (local dev)
    └── knowledge/
        ├── bedrock.py    # AWS Bedrock KB connector
        └── pinecone.py   # Pinecone connector
```

### Data Models

**Identity Store** — maps `user_id` → `tags` (string set):
```json
{"user_id": "user_123", "tags": ["finance", "public", "project_x"]}
```

**Knowledge Store** — every document chunk must have an `access_tags` metadata field (list of strings). The engine filters on tag intersection.

### Configuration (via environment variables in `mcp.json`)

| Variable | Values | Description |
|---|---|---|
| `SENTINEL_IDENTITY_STORE` | `dynamodb`, `sqlite` | Identity backend |
| `SENTINEL_KNOWLEDGE_STORE` | `bedrock`, `pinecone` | Knowledge backend |
| `DDB_TABLE_NAME` | string | DynamoDB table name |
| `AWS_REGION` | string | AWS region |
| `BEDROCK_KB_ID` | string | Bedrock Knowledge Base ID |

## Design Documents

Full design context lives in `Design/`:
- `Architecture.md.md` — system components and interaction diagram
- `Design.md.md` — data models, security principles, connector contracts
- `Project Structure.md.md` — planned file layout with annotations
- `Tasklist.md.md` — phased implementation roadmap (Phases 1–4)

Start with these before implementing anything to ensure alignment with the intended design.
