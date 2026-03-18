# Tasklist.md (Implementation Guide)

---

### Phase 1: Core Framework (The Plumbing) ✅ Complete

- [x] Create `sentinel/core/base.py` containing the `IdentityConnector` and `KnowledgeConnector` abstract classes.

- [x] Create `sentinel/core/engine.py` (The Orchestrator) that implements the logic: `tags = await id_store.get_tags(user_id) -> await kb_store.search(query, tags)`.

- [x] Implement `sentinel/main.py` using `FastMCP` to define the `secure_search` tool.


### Phase 2: Identity Connectors (The Vaults) — Partial

- [x] **SQLite Implementation:** `sentinel/connectors/identity/sqlite.py`. Uses `aiosqlite`. Table: `permissions` with columns `user_id` and `tag`. Seeded via `scripts/init_db.py`.

- [ ] **DynamoDB Implementation:** Build `sentinel/connectors/identity/ddb.py`. Use `aioboto3`. Fetch item by `user_id` and return the `tags` String Set.


### Phase 3: Knowledge Connectors (The Search) — Partial

- [x] **ChromaDB Implementation:** `sentinel/connectors/knowledge/chroma.py`. Uses local `sentence-transformers` (`all-MiniLM-L6-v2`) for dense embeddings. Tags stored as boolean metadata fields for native `$or` filtering. Relevance score is cosine similarity — used post-retrieval as an anti-hallucination quality gate, not as an access control mechanism.

- [ ] **Bedrock Implementation:** Build `sentinel/connectors/knowledge/bedrock.py`. Use `boto3` (Bedrock Agent Runtime).

- [ ] **Bedrock Metadata Logic:** Implement the translation of Python `set` tags into Bedrock's `retrievalConfiguration` filter JSON.


### Phase 4: Integration & UX ✅ Complete

- [x] **Fail-Closed enforcement:** if `get_tags` returns an empty set, `AccessDeniedError` is raised and no KB call is made.

- [x] **Relevance threshold (`MIN_RELEVANCE_SCORE=0.25`):** results below the threshold are dropped after retrieval. If nothing passes, Sentinel returns a clear "no access" message instead of feeding the LLM low-signal documents that cause hallucination. Configurable via env var.

- [x] **OR access policy:** a document tagged `[finance, engineering]` is accessible to any user holding `finance` OR `engineering`. Implemented via ChromaDB `$or` metadata filter.

- [x] `mcp.json.example` and `.mcp.json` (project-scoped) showing env var configuration for both SQLite and ChromaDB backends.

- [x] `schema/init_db.sql` and `scripts/init_db.py` for SQLite setup with seed users.

- [x] **Integration test suite** (`tests/`) — 17 tests covering fail-closed, OR policy, relevance threshold, per-user retrieval, and upsert. All passing.


### Phase 5: Ingestion Tool (The On-Ramp) — Partial

- [x] **`ingest_document` MCP tool** in `sentinel/main.py` — callable directly from any MCP client to ingest text with `access_tags` and optional title metadata.

- [x] **`scripts/ingest_seed_docs.py`** — reads `.md` files from `docs/seed/`, extracts `access_tags` from trailing HTML comment, and ingests into ChromaDB. Used to load the 7 seed documents.

- [x] **Seed documents** (`docs/seed/`) — 7 `.md` files spanning `public`, `finance`, `engineering`, and `finance+engineering` access tiers for end-to-end testing.

- [ ] **Tag Validation:** Before ingesting, verify that all provided tags exist in the Identity Store to prevent orphan tags that no user can ever match.

- [ ] **Bedrock Ingestion Path:** Upload source document to S3, then trigger a Bedrock KB sync with `access_tags` embedded in the document metadata.

- [ ] **Dry-Run Mode:** Add a `--dry-run` flag that previews what metadata would be attached and what validation checks would run, without committing the ingestion.


### Phase 6: Hybrid RAG Pipeline (Query Transformation + BM25 + RRF)

The current implementation is a single-stage dense vector search. This phase upgrades it to a full retrieval pipeline. All stages must operate within the tag-filtered scope — access control is enforced before any retrieval runs.

- [ ] **Query Transformation:** Before retrieval, rewrite or expand the user's query (e.g. via LLM call) to improve recall — handle abbreviations, typos, and under-specified queries.

- [ ] **BM25 / Sparse Search:** Add a keyword-based retrieval stage alongside the dense vector search. BM25 catches exact term matches that dense models miss due to embedding space distance. Implement as a second retrieval path over the same tag-filtered document set.

- [ ] **Reciprocal Rank Fusion (RRF):** Merge the ranked lists from dense search and BM25 into a single result list using RRF scoring (`1 / (k + rank)`). RRF is robust to score scale differences between sparse and dense retrievers.

- [ ] **Dense vs Sparse Evaluation:** Benchmark retrieval quality across query types (keyword-heavy vs semantic/paraphrase) to understand where each model wins. Document findings.

- [ ] **Re-ranking (optional):** Add a cross-encoder re-ranker (e.g. `cross-encoder/ms-marco-MiniLM-L-6-v2`) as a final stage to re-score the fused top-K results with higher accuracy before returning to the LLM.

---

### Phase 7: Future Connectors

- [ ] Pinecone knowledge connector
- [ ] DynamoDB identity connector
- [ ] ChromaDB → Bedrock migration path
