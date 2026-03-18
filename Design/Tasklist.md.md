# Tasklist.md (Implementation Guide)

**Instructions for Claude:** Implement the Sentinel RAG MCP server using Python and `FastMCP`.

### Phase 1: Core Framework (The Plumbing)

- [ ] Create `sentinel/core/base.py` containing the `IdentityConnector` and `KnowledgeConnector` abstract classes.
    
- [ ] Create `sentinel/core/engine.py` (The Orchestrator) that implements the logic: `tags = await id_store.get_tags(user_id) -> await kb_store.search(query, tags)`.
    
- [ ] Implement `sentinel/main.py` using `FastMCP` to define the `secure_search` tool.
    

### Phase 2: Identity Connectors (The Vaults)

- [ ] **SQLite Implementation:** Build `sentinel/connectors/identity/sqlite.py`. Use `aiosqlite`. Table: `permissions` with columns `user_id` and `tag`.
    
- [ ] **DynamoDB Implementation:** Build `sentinel/connectors/identity/ddb.py`. Use `aioboto3`. Fetch item by `user_id` and return the `tags` String Set.
    

### Phase 3: Knowledge Connectors (The Search)

- [ ] **Bedrock Implementation:** Build `sentinel/connectors/knowledge/bedrock.py`. Use `boto3` (Bedrock Agent Runtime).
    
- [ ] **Metadata Logic:** Implement the translation of Python `set` tags into Bedrock's `retrievalConfiguration` filter JSON.
    

### Phase 4: Integration & UX

- [ ] Implement "Fail-Closed" logic: if `get_tags` returns an empty set, the search should not even trigger an API call to the Knowledge Store.
    
- [ ] Create an example `mcp.json` showing how to toggle between `sqlite` and `dynamodb` using `SENTINEL_IDENTITY_STORE` environment variable.
    

### Phase 5: Ingestion Tool (The On-Ramp)

- [ ] Create `sentinel/tools/ingest.py` — a CLI/MCP tool for ingesting documents into the knowledge store with `access_tags` metadata attached.

- [ ] Accept inputs: document path (or raw text), list of `access_tags`, and target knowledge store backend.

- [ ] **Tag Validation:** Before ingesting, verify that all provided tags exist in the Identity Store to prevent orphan tags that no user can ever match.

- [ ] **Bedrock Ingestion Path:** Upload source document to S3, then trigger a Bedrock KB sync with `access_tags` embedded in the document metadata.

- [ ] **Local Ingestion Path (dev):** Chunk the document and insert into a local vector store with correct `access_tags` metadata — for testing without AWS dependencies.

- [ ] **Dry-Run Mode:** Add a `--dry-run` flag that previews what metadata would be attached and what validation checks would run, without committing the ingestion.

---

### Final Next Step for You:

You can now copy these three blocks into a new prompt for a coding-focused LLM (like Claude 3.5 Sonnet) and say:

> "Based on the attached Architecture, Design, and Tasklist, please generate the full Python implementation for the Sentinel RAG MCP server. Start with Phase 1 and 2."

**Would you like me to generate a sample `permissions.db` (SQLite) initialization script so you can test Phase 2 immediately?**