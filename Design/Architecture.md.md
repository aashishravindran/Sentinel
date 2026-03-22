## 1. System Overview

Sentinel RAG is a **Stateless MCP Middleware** that enforces Attribute-Based Access Control (ABAC) on Retrieval-Augmented Generation. It decouples the "Who can see what" (Identity Store) from the "What is stored" (Knowledge Store).

## 2. Component Diagram

- **MCP Client:** (Claude Desktop/Cursor/Claude Code) Provides the `query` and `user_id`.

- **Sentinel MCP (The Brain):** Orchestrates the handshake between Identity and Knowledge.

- **Identity Store (The Vault):** External DB (DDB/SQLite) mapping `user_id` to `List[Tags]`.

- **Knowledge Store (The Library):** Vector DB (Bedrock/Pinecone/ChromaDB) containing documents with `metadata.access_tags`.


## 3. The Sentinel Handshake (Sequence)

1. **Request:** `secure_search(query, user_id)`

2. **Identity Lookup:** Sentinel calls `IdentityStore.get_tags(user_id)`.

3. **Policy Enforcement:** If tags are empty, **Fail-Closed** (Return "Access Denied"). No KB call is made.

4. **Tag Filter:** Sentinel generates a DB-specific metadata filter (OR policy — user needs any one of the doc's tags):
    - _ChromaDB:_ `{"$or": [{"tag_finance": true}, {"tag_public": true}]}`
    - _Bedrock:_ `{"equals": {"attr": "access_tag", "value": "tag_name"}}`

5. **Retrieval:** Knowledge Store executes the filtered ANN search, returning only documents the user is permitted to see.

6. **Relevance Scoring:** Each returned document is scored via cosine similarity between the query embedding and the document embedding. This is **not an access control step** — the tag filter already enforced access. The score answers: *"Of the documents this user is allowed to see, is any of them actually about what they asked?"*

7. **Threshold Filter:** Results below `MIN_RELEVANCE_SCORE` (default 0.25) are dropped. If nothing passes, Sentinel returns a clear "no access" message rather than feeding the LLM low-signal documents that cause hallucination.

8. **Response:** Sentinel formats surviving chunks into a context string for the LLM.


## 4. Relevance Score vs Access Control

These are two independent mechanisms and must not be confused:

| | Tag Filter | Relevance Score |
|---|---|---|
| **Purpose** | Access control — who sees what | Result quality — is this relevant to the query |
| **Mechanism** | ChromaDB `where` clause (binary in/out) | Cosine similarity between query and doc embeddings |
| **When applied** | Before retrieval | After retrieval, on permitted docs only |
| **Failure mode** | Doc excluded entirely | Doc dropped, "no access" message returned |
| **Security role** | Yes — enforces ABAC | No — purely anti-hallucination |

A document scoring 0.10 was already authorised by the tag filter; it is dropped only because it is not relevant to the query, not because the user lacks permission.


## 5. Embedding Models: Dense vs Sparse (Future Consideration)

The current implementation uses a **dense embedding model** (`all-MiniLM-L6-v2`). Understanding the tradeoff matters for how relevance scores behave across different query types:

**Dense models** (current — `all-MiniLM-L6-v2`, OpenAI `text-embedding-3`)
- Encode semantic meaning into a fixed-length vector (384D for MiniLM)
- Good at synonyms and paraphrase: "Q4 revenue" ≈ "fourth quarter earnings"
- Can miss exact keyword matches; score depends on training distribution
- Single score per (query, doc) pair

**Sparse models** (BM25, TF-IDF)
- Score based on term frequency and document frequency
- Excellent at exact keyword matching; predictable and interpretable
- Blind to synonyms or intent
- Historically the backbone of search engines (Elasticsearch, Lucene)

**Why this matters for Sentinel:** a dense-only pipeline can return a low score for a highly relevant document simply because the query phrasing differs from the training data. A sparse model would catch exact matches the dense model misses. This motivates the hybrid retrieval approach planned in Phase 6.


## 6. Connector Architecture

Sentinel supports two complete backend configurations. Each pairs an identity connector (who are you?) with a knowledge connector (what can you see?).

### 6a. Local Development — SQLite + ChromaDB

```
MCP Client
  │
  └─► sentinel.main.py (_build_engine)
        │
        ├─► SQLiteIdentityConnector          ← data/permissions.db
        │     user_id → tags (JSON column)
        │
        └─► ChromaKnowledgeConnector         ← data/chroma/
              all-MiniLM-L6-v2 embeddings (384D)
              where clause: {"$or": [{"tag_X": true}, ...]}
              Dense vector search only (HNSW)
```

- **Identity:** SQLite file at `SQLITE_DB_PATH`. Schema: `users(user_id TEXT PK, tags TEXT)` where tags is a JSON array.
- **Knowledge:** Local ChromaDB with sentence-transformers `all-MiniLM-L6-v2` for embeddings. OR-policy filtering via Chroma `where` clause with boolean tag attributes.
- **Setup:** `python scripts/init_db.py` creates the DB and seeds users. `python scripts/ingest_seed_docs.py` loads sample documents.

### 6b. AWS Production — DynamoDB + Bedrock Knowledge Bases

```
MCP Client
  │
  └─► sentinel.main.py (_build_engine)
        │
        ├─► DynamoDBIdentityConnector        ← DynamoDB table
        │     user_id (PK) → tags (String Set)
        │     aioboto3 async client
        │
        └─► BedrockKnowledgeConnector        ← Bedrock KB + OpenSearch Serverless
              │
              ├─ Search: bedrock-agent-runtime.retrieve()
              │    overrideSearchType: HYBRID (dense + BM25 via RRF)
              │    OR-filter: {"orAll": [{"equals": {"key": "tag_X", "value": true}}]}
              │    Optional: reranking via amazon.rerank-v1:0 cross-encoder
              │
              └─ Ingest: S3 put_object + .metadata.json sidecar
                   bedrock-agent.start_ingestion_job() triggers KB sync
```

**Search pipeline detail:**

```
secure_search(query, user_id)
  │
  ├─ DynamoDB: get_tags(user_id) → {"finance", "public"}
  │    (fail-closed if empty)
  │
  ├─ Build OR metadata filter:
  │    {"orAll": [{"equals": {"key": "tag_finance", "value": true}},
  │               {"equals": {"key": "tag_public",  "value": true}}]}
  │
  ├─ bedrock-agent-runtime.retrieve()
  │    ├─ HYBRID search: dense vector (Titan Embed v2, 1024D) + BM25 keyword
  │    ├─ Reciprocal Rank Fusion merges results
  │    └─ Optional: cross-encoder reranking (oversample N×, then reduce)
  │
  ├─ Relevance threshold filter (MIN_RELEVANCE_SCORE, default 0.25)
  │
  └─ Return formatted results to LLM
```

**Ingestion pipeline detail:**

```
ingest_document / ingest_pdf
  │
  ├─ (ingest_pdf only) Extract pages via pypdf → per-page chunks
  │
  ├─ S3: put_object(documents/{doc_id}.txt)         — document text
  ├─ S3: put_object(documents/{doc_id}.txt.metadata.json)  — sidecar
  │       {"metadataAttributes": {"tag_finance": true, "tag_public": true,
  │                               "access_tags": "finance,public", ...}}
  │
  └─ bedrock-agent.start_ingestion_job()   — triggers KB sync
       (OpenSearch Serverless indexes the new document)
```

**AWS infrastructure (provisioned by `scripts/setup_aws.py`):**

| Resource | Service | Purpose |
|---|---|---|
| Identity table | DynamoDB | `user_id` → `tags` (String Set) |
| Document bucket | S3 | Stores `.txt` documents + `.metadata.json` sidecars |
| KB service role | IAM | Trusted by Bedrock; grants S3 + AOSS + embed access |
| Vector collection | OpenSearch Serverless | Hybrid knn + BM25 index |
| Knowledge Base | Bedrock | Orchestrates embedding + vector storage |
| Data Source | Bedrock | S3 → KB ingestion pipeline |

### 6c. Connector Interface

Both backends implement the same abstract interfaces (`sentinel/core/base.py`):

```
IdentityConnector (ABC)
  async get_tags(user_id: str) → set[str]

KnowledgeConnector (ABC)
  async search(query: str, tags: set[str], n_results: int) → List[Dict]
  async ingest(text: str, access_tags: list[str], doc_id: str, metadata: dict) → None
```

The `SentinelEngine` (`sentinel/core/engine.py`) is backend-agnostic — it only calls these interfaces. Switching backends is a configuration change in `.mcp.json`, not a code change.


## 7. Hybrid Search (Implemented via Bedrock)

The Bedrock connector implements the hybrid RAG pipeline described in Phase 6 of the original design:

```
Query
  │
  ├─► Dense Vector Search    (Titan Embed v2 — semantic recall)
  │
  ├─► BM25 / Sparse Search   (OpenSearch keyword — exact match recall)
  │
  └─► RRF Fusion             (Reciprocal Rank Fusion — merge ranked lists)
          │
          ├─► Optional: Reranking (amazon.rerank-v1:0 cross-encoder)
          │
          └─► Access-controlled, relevance-filtered results → LLM
```

All retrieval stages operate **within the tag-filtered scope** — BM25 and dense search only run over documents the user is authorised to see. The filter is applied at the OpenSearch query level, not post-retrieval.
