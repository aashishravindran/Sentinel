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


## 6. Planned: Full Hybrid RAG Pipeline (Phase 6)

The current implementation is a **single-stage dense vector search**. A production-grade RAG pipeline would add:

```
Query
  │
  ├─► Query Transformation   (rewrite/expand query before retrieval)
  │
  ├─► Dense Vector Search    (ANN on embeddings — semantic recall)
  │
  ├─► BM25 / Sparse Search   (keyword recall — catches exact matches)
  │
  └─► RRF Fusion             (Reciprocal Rank Fusion — merge ranked lists)
          │
          └─► Re-ranked, access-controlled results → LLM
```

All retrieval stages must operate **within the tag-filtered scope** — BM25 and dense search only run over documents the user is authorised to see.
