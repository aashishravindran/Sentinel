# Sentinel RAG

Sentinel is a stateless MCP (Model Context Protocol) middleware server that enforces **Attribute-Based Access Control (ABAC)** on RAG (Retrieval-Augmented Generation) pipelines. It acts as a security layer between MCP clients (Claude Desktop, Cursor) and your vector databases — ensuring users only retrieve documents they are authorized to see.

## The Problem

Standard RAG pipelines have no concept of per-user access control. When a user queries a knowledge base, they get back everything the vector search returns — regardless of whether they should see it. Sentinel fixes this by intercepting every query and filtering results based on the user's permissions before anything is returned to the LLM.

## How It Works

Sentinel decouples **who can see what** (Identity Store) from **what is stored** (Knowledge Store).

```
Client (Claude Desktop / Cursor)
    │
    ▼
secure_search(query, user_id)
    │
    ├─► Identity Store (DynamoDB / SQLite)
    │       └── get_tags(user_id) → {"finance", "project_x"}
    │
    │   [Fail-Closed: if tags = ∅ → deny, no KB call made]
    │
    ├─► Query Synthesis
    │       └── tags → DB-specific metadata filter
    │
    ├─► Knowledge Store (Bedrock / Pinecone)
    │       └── filtered ANN search → matching chunks
    │
    └─► Formatted context string returned to LLM
```

### Security Principles

- **Zero Trust:** Never assumes a `user_id` has global access.
- **Fail-Closed:** If a user has no tags, access is denied and no knowledge store call is made.
- **Stateless:** No user data is cached between MCP sessions.
- **Intersection Policy:** A document is returned only if the user holds at least one tag present in the document's `access_tags` metadata field.
- **Environment-Driven:** All secrets and endpoints are injected via `mcp.json` environment variables — nothing is hardcoded.

## Data Models

### Identity Store

Maps `user_id` → a set of permission tags. Supported backends: **DynamoDB** (prod), **SQLite** (local dev).

```
user_id   │ tags
──────────┼─────────────────────────────
user_123  │ ["finance", "public", "project_x"]
user_456  │ ["public"]
```

### Knowledge Store

Every document chunk **must** contain an `access_tags` metadata field (list of strings). Sentinel translates the user's tag set into a database-native metadata filter before executing the vector search.

Example Bedrock filter:
```json
{"equals": {"attr": "access_tag", "value": "finance"}}
```

## Project Structure

```
sentinel-rag/
├── pyproject.toml                  # uv/poetry dependencies
├── .env                            # Local dev variables (not for prod)
├── sentinel/
│   ├── main.py                     # FastMCP entry point & tool definitions
│   ├── core/
│   │   ├── base.py                 # Abstract Base Classes (IdentityConnector, KnowledgeConnector)
│   │   └── engine.py               # Orchestrator — ABAC logic, tag intersection, fail-closed
│   └── connectors/
│       ├── identity/
│       │   ├── sqlite.py           # SQLite connector (aiosqlite)
│       │   └── ddb.py              # DynamoDB connector (aioboto3)
│       └── knowledge/
│           ├── bedrock.py          # AWS Bedrock Knowledge Bases connector
│           └── pinecone.py         # Pinecone connector (future)
├── schema/
│   └── init_db.sql                 # SQLite schema for local testing
└── tests/
```

## Connector Interfaces

```python
class IdentityConnector(ABC):
    @abstractmethod
    async def get_tags(self, user_id: str) -> set[str]:
        """Fetch the permission tags for a user from the identity store."""

class KnowledgeConnector(ABC):
    @abstractmethod
    async def search(self, query: str, tags: set[str]) -> List[Dict]:
        """Execute a metadata-filtered vector search."""
```

## Setup & Integration

### 1. Install dependencies

```bash
uv sync
```

### 2. Configure `mcp.json`

Add Sentinel as an MCP server in your client's `mcp.json`. Toggle between backends using environment variables:

```json
{
  "mcpServers": {
    "sentinel-rag": {
      "command": "python",
      "args": ["-m", "sentinel_mcp"],
      "env": {
        "SENTINEL_IDENTITY_STORE": "dynamodb",
        "DDB_TABLE_NAME": "UserPermissions-Prod",
        "AWS_REGION": "us-west-2",
        "SENTINEL_KNOWLEDGE_STORE": "bedrock",
        "BEDROCK_KB_ID": "ABC123XYZ"
      }
    }
  }
}
```

For local development with SQLite:
```json
{
  "env": {
    "SENTINEL_IDENTITY_STORE": "sqlite",
    "SQLITE_DB_PATH": "./schema/permissions.db",
    "SENTINEL_KNOWLEDGE_STORE": "bedrock",
    "BEDROCK_KB_ID": "ABC123XYZ"
  }
}
```

### Environment Variables

| Variable | Values | Description |
|---|---|---|
| `SENTINEL_IDENTITY_STORE` | `dynamodb`, `sqlite` | Identity backend to use |
| `SENTINEL_KNOWLEDGE_STORE` | `bedrock`, `pinecone` | Knowledge backend to use |
| `DDB_TABLE_NAME` | string | DynamoDB table name |
| `AWS_REGION` | string | AWS region for DynamoDB/Bedrock |
| `BEDROCK_KB_ID` | string | Bedrock Knowledge Base ID |
| `SQLITE_DB_PATH` | file path | Path to local SQLite permissions DB |

### 3. Run locally

```bash
python -m sentinel_mcp
```

### 4. Run tests

```bash
uv run pytest

# Run a single test
uv run pytest tests/path/to/test_file.py::test_name
```

## Roadmap

### Phase 1 — Core Framework
- [ ] `sentinel/core/base.py` — `IdentityConnector` and `KnowledgeConnector` ABCs
- [ ] `sentinel/core/engine.py` — Orchestrator: `get_tags` → tag intersection → `search`
- [ ] `sentinel/main.py` — FastMCP server with `secure_search` tool definition

### Phase 2 — Identity Connectors
- [ ] `sentinel/connectors/identity/sqlite.py` — `aiosqlite`-based connector; `permissions` table with `user_id` and `tag` columns
- [ ] `sentinel/connectors/identity/ddb.py` — `aioboto3`-based connector; fetch item by `user_id`, return `tags` String Set

### Phase 3 — Knowledge Connectors
- [ ] `sentinel/connectors/knowledge/bedrock.py` — AWS Bedrock Agent Runtime connector
- [ ] Metadata filter translation: Python `set[str]` → Bedrock `retrievalConfiguration` filter JSON

### Phase 4 — Integration & UX
- [ ] Fail-Closed enforcement: if `get_tags` returns `∅`, skip knowledge store call entirely
- [ ] Example `mcp.json` configs for both `sqlite` and `dynamodb` identity backends
- [ ] `schema/init_db.sql` — SQLite schema and seed data for local testing

### Phase 5 — Ingestion Tool
- [ ] `sentinel/tools/ingest.py` — CLI/MCP tool to ingest documents into the knowledge store with `access_tags` metadata attached
- [ ] Accept input: document path (or text), target tags, and destination knowledge store
- [ ] Validate that all provided tags exist in the Identity Store before ingestion (no orphan tags)
- [ ] Bedrock ingestion: upload source doc to S3, sync to Bedrock KB with `access_tags` in metadata
- [ ] SQLite/local ingestion path for development: chunk document and insert into a local vector store with correct metadata
- [ ] Dry-run mode: preview what metadata would be attached without committing the ingestion

### Phase 6 — Future
- [ ] Pinecone knowledge connector
- [ ] ChromaDB knowledge connector
- [ ] Multi-tag OR / AND policy modes
- [ ] Audit logging per query
