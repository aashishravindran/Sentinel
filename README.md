# Sentinel

[![License: EL2](https://img.shields.io/badge/License-Elastic_2.0-blue.svg)](LICENSE)

> **Compliance-as-Code for AI.** Sentinel is a security middleware layer that enforces per-user access control on RAG pipelines — so your LLM only ever sees what it's allowed to know.

> **License:** Sentinel is licensed under the [Elastic License 2.0](LICENSE). You may self-host and modify it freely. You may **not** offer it as a hosted or managed service to third parties.

---

## The Problem: The "RAG Leak"

Current RAG implementations suffer from a critical security gap: **the LLM has no concept of Row-Level Security (RLS).**

- **Stateless Models** — LLMs don't know who is asking the question unless you hardcode it.
- **Metadata Drift** — Syncing user permissions into vector database metadata is a synchronisation nightmare.
- **The Hallucination Risk** — You cannot "prompt-engineer" an AI to ignore private data it has already retrieved.

The moment a document enters the LLM's context window, the security boundary is gone.

---

## The Solution: Sentinel Middleware

Sentinel moves the security boundary **outside the model**. It sits between the AI and the data, performing a real-time **Permission Handshake** before a single byte of data is retrieved.

```
sequenceDiagram
    participant AI as Claude / Cursor
    participant S as Sentinel MCP
    participant IV as Identity Vault (DDB / SQLite)
    participant KB as Knowledge Base (Bedrock / Chroma)

    AI->>S: secure_search(query, user_id)
    S->>IV: get_tags(user_id)
    IV-->>S: ["finance", "public"]
    S->>S: Synthesize metadata filter
    S->>KB: Filtered vector search (tags: finance OR public)
    KB-->>S: Authorised chunks only
    S-->>AI: Redacted context
```

**1. Unified Identity Vault** — Connect to your existing DynamoDB or SQLite permission tables. Sentinel fetches a user's Access Tags at the moment of the query.

**2. Stateless Logic** — Sentinel holds no data. It translates high-level user identities into database-specific metadata filters (AWS Bedrock, ChromaDB, Pinecone) on the fly.

**3. Fail-Closed Security** — If the Identity Vault doesn't explicitly grant a tag, Sentinel returns an empty result set. The AI never sees what it isn't allowed to know.

---

## Key Features

- **Protocol Native** — Built on the [Model Context Protocol (MCP)](https://modelcontextprotocol.io) for instant integration with Claude Desktop, Cursor, and any MCP-compatible IDE.
- **Plug-and-Play Connectors** — AWS DynamoDB (identity) and Amazon Bedrock Knowledge Bases (knowledge), with SQLite + ChromaDB for local development.
- **Enterprise-Grade RAG** — Hybrid search (BM25 + semantic vector) and optional cross-encoder reranking out of the box. Currently only on AWS Bedrock Connector
- **Domain Agnostic** — Designed for Healthcare, Legal, and Finance. Leave the domain expertise to the data; leave the security to Sentinel.

---

## How It Works

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
    │       └── tags → DB-native metadata filter
    │
    ├─► Knowledge Store (Bedrock / ChromaDB)
    │       └── filtered hybrid search → authorised chunks
    │
    └─► Formatted context returned to LLM
```

### Security Principles

| Principle | Behaviour |
|---|---|
| **Zero Trust** | Never assumes a `user_id` has global access |
| **Fail-Closed** | No tags = access denied before any KB call is made |
| **Stateless** | No user data cached between MCP sessions |
| **OR Policy** | Document returned if user holds ≥1 matching tag |
| **Environment-Driven** | All secrets injected via `mcp.json` — nothing hardcoded |

---
## 🔌 Ecosystem & Roadmap

Sentinel is designed to be a plug-and-play security layer for any RAG stack. By decoupling the **Identity Provider** from the **Knowledge Base**, Sentinel ensures your security logic remains stateless, portable, and planet-scale.

### 🟢 Currently Available
These connectors are production-ready and can be used for local development or AWS-native deployments.

| Category | Connector | Description |
| :--- | :--- | :--- |
| **Identity** | `SQLiteConnector` | Local-first identity store for development, prototyping, and CI/CD testing. |
| **Identity** | `DynamoDBConnector` | High-performance AWS integration using **GSIs** for sub-10ms attribute-based lookups. |
| **Knowledge** | `ChromaConnector` | Open-source vector database for local-first or self-hosted Agentic workflows. |
| **Knowledge** | `BedrockConnector` | Native integration for teams leveraging **Knowledge Bases for Amazon Bedrock**. |

---

### 🟡 Coming Soon 
We are actively expanding the ecosystem to support industry-standard managed services and complex relationship graphs.

#### **Identity Connectors**
* **SpiceDB (Zanzibar-scale):** Our first **Relationship-Based (ReBAC)** connector. This allows Sentinel to resolve deep, nested hierarchies (e.g., *User A → Member of Team B → Owner of Project C*) by querying a SpiceDB cluster in real-time.
* **Okta/Auth0:** Native OIDC integration to map enterprise JWT claims directly to vector metadata filters.

#### **Knowledge Connectors**
* **Pinecone Serverless:** Direct integration with Pinecone’s high-performance metadata filtering engine. This enables security enforcement at the index level for millions of documents with sub-50ms latency.
* **Elasticsearch/OpenSearch:** Support for hybrid search (BM25 + Vector) with native DLS (Document Level Security) mapping.

---

### 🛡️ The Sentinel Promise: Zero-Data Persistence
Regardless of the connector used, Sentinel follows a strict **"Fetch, Filter, Flush"** lifecycle:
1. **Fetch:** Retrieve user attributes or group memberships from the `IdentityConnector`.
2. **Filter:** Synthesize a Boolean metadata tree (AND/OR/NOT).
3. **Retrieve:** Execute a secured, filtered query via the `KnowledgeConnector`.
4. **Flush:** Drop the context. Sentinel stores no user data, ensuring a truly stateless security boundary.




## Quick Start

### Local (SQLite + ChromaDB)

```bash
uv sync
python scripts/init_db.py
python scripts/ingest_seed_docs.py
```

```json
{
  "mcpServers": {
    "sentinel-rag": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "python", "-m", "sentinel.main"],
      "env": {
        "SENTINEL_IDENTITY_STORE": "sqlite",
        "SQLITE_DB_PATH": "/path/to/data/permissions.db",
        "SENTINEL_KNOWLEDGE_STORE": "chroma",
        "CHROMA_PATH": "/path/to/data/chroma",
        "CHROMA_COLLECTION": "sentinel",
        "EMBEDDING_MODEL": "all-MiniLM-L6-v2"
      }
    }
  }
}
```

### AWS (DynamoDB + Bedrock)

```json
{
  "mcpServers": {
    "sentinel-rag": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "python", "-m", "sentinel.main"],
      "env": {
        "SENTINEL_IDENTITY_STORE": "dynamodb",
        "SENTINEL_KNOWLEDGE_STORE": "bedrock",
        "AWS_REGION": "us-east-1",
        "AWS_PROFILE": "your-profile",
        "DDB_TABLE_NAME": "your-identity-table",
        "BEDROCK_KB_ID": "your-kb-id",
        "BEDROCK_S3_BUCKET": "your-kb-bucket",
        "BEDROCK_DS_ID": "your-datasource-id",
        "BEDROCK_SEARCH_TYPE": "HYBRID"
      }
    }
  }
}
```

See [QUICKSTART.md](QUICKSTART.md) for full setup instructions, all three AWS auth options, and reranking configuration.

---

## MCP Tools

| Tool | Description |
|---|---|
| `secure_search(query, user_id)` | Search the KB — returns only documents the user is authorised to see |
| `ingest_document(text, access_tags, doc_id)` | Ingest a text document with access control tags |
| `ingest_pdf(access_tags, doc_id, pdf_path)` | Ingest a PDF page-by-page with access tags and optional metadata |

---

## Project Structure

```
sentinel/
├── main.py                         # FastMCP entry point — tool definitions
├── core/
│   ├── base.py                     # Abstract connectors (IdentityConnector, KnowledgeConnector)
│   └── engine.py                   # Orchestrator — ABAC logic, fail-closed enforcement
└── connectors/
    ├── identity/
    │   ├── sqlite.py               # SQLite (local dev)
    │   └── ddb.py                  # DynamoDB (production)
    └── knowledge/
        ├── chroma.py               # ChromaDB (local dev)
        └── bedrock.py              # AWS Bedrock KB (production)
scripts/
├── setup_aws.py                    # Demo provisioning script (not for production)
├── seed_ddb.py                     # Seed DynamoDB with test users
├── init_db.py                      # Initialise local SQLite DB
└── ingest_seed_docs.py             # Bulk-ingest local seed documents
```

---

## Access Control in Practice

### What's in the knowledge base

| Document | Tags | Who can access |
|---|---|---|
| Aashish Ravindran Resume | `recruitment`, `private` | Users with `recruitment` or `private` |
| Q4 2025 Financial Report | `finance` | Users with `finance` |
| Engineering Runbook | `engineering` | Users with `engineering` |
| Company Overview | `public` | Everyone |

### Identity store (DynamoDB)

| User | Tags |
|---|---|
| `aashish` | `recruitment`, `private` |
| `alice` | `finance`, `public` |
| `bob` | `engineering`, `public` |
| `charlie` | `finance`, `engineering`, `public` |

### Example: Aashish asks about his own resume

```
secure_search("AWS experience", user_id="aashish")
```

1. Identity store returns `{"recruitment", "private"}` for `aashish`
2. Sentinel builds filter: `tag_recruitment = true OR tag_private = true`
3. Bedrock retrieves the resume — it matches on `tag_private`
4. Result returned to the LLM ✅

```
[1] Aashish Ravindran Resume (score: 0.82)
...experience with AWS Bedrock, DynamoDB, OpenSearch Serverless...
```

### Example: Alice asks the same question

```
secure_search("AWS experience", user_id="alice")
```

1. Identity store returns `{"finance", "public"}` for `alice`
2. Sentinel builds filter: `tag_finance = true OR tag_public = true`
3. Bedrock finds no documents matching those tags that are relevant to the query
4. Alice gets nothing — not because the query failed, but because she was never authorised to see it ✅

```
You do not have access to documents relevant to this query.
The information may exist but is not within your permitted scope.
```

The resume was never retrieved. Alice's LLM context was never contaminated with data she shouldn't see. No prompt engineering can change this — the filter runs before retrieval.

### Example: Unknown user

```
secure_search("company overview", user_id="unknown_user")
```

1. Identity store returns `∅` — user not found
2. Sentinel **fail-closes** immediately — no knowledge base call is made
3. `Access Denied` returned before a single vector search executes ✅

---

## Research & Lineage

Sentinel is inspired by the **Relationship-Based Access Control (ReBAC)** paradigm and the architectural principles laid out in Google's **Zanzibar** paper. While Zanzibar is designed for planet-scale authorisation (10M+ QPS), Sentinel brings those core security principles to the **Agentic RAG** ecosystem.

> *"Sentinel acts as a Lightweight Handshake — providing the security of a ReBAC system without the infrastructure overhead of a full Zanzibar implementation."*

### Key References

- **Zanzibar: Google's Consistent, Global Authorization System** (Pang et al., USENIX ATC 2019)
  [Read the paper →](https://www.usenix.org/system/files/atc19-pang.pdf)
  *How Google manages billions of permissions across Drive, YouTube, and Cloud at 10M+ QPS.*

- **Related implementations:** [SpiceDB](https://github.com/authzed/spicedb), [OpenFGA](https://openfga.dev/) — production ReBAC systems that inspired Sentinel's stateless, tag-intersection model.

Traditional RAG fails at the retrieval layer by being identity-blind. By implementing a **Stateless Middleware** — as suggested by modern ReBAC implementations — Sentinel ensures security is enforced *before* the LLM sees a single byte of data.

---

## Why Sentinel?

Sentinel isn't just a search tool — it's a **Compliance-as-Code** layer for AI. It allows CISOs to say **yes** to Generative AI by providing a hard security boundary that agents cannot bypass, prompt-engineer around, or hallucinate past.

---

## License

Sentinel is licensed under the [Elastic License 2.0](LICENSE).

You are free to use, modify, and self-host Sentinel. You may **not** offer Sentinel (or a substantially similar derivative) as a hosted or managed service to third parties without a separate commercial agreement.

Copyright (c) 2026 Aashish Ravindran. All rights reserved.
