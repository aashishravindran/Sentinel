## 1. System Overview

Sentinel RAG is a **Stateless MCP Middleware** that enforces Attribute-Based Access Control (ABAC) on Retrieval-Augmented Generation. It decouples the "Who can see what" (Identity Store) from the "What is stored" (Knowledge Store).

## 2. Component Diagram

- **MCP Client:** (Claude Desktop/Cursor) Provides the `query` and `user_id`.
    
- **Sentinel MCP (The Brain):** Orchestrates the handshake between Identity and Knowledge.
    
- **Identity Store (The Vault):** External DB (DDB/SQLite) mapping `user_id` to `List[Tags]`.
    
- **Knowledge Store (The Library):** Vector DB (Bedrock/Pinecone) containing documents with `metadata.tags`.
    

## 3. The Sentinel Handshake (Sequence)

1. **Request:** `secure_search(query, user_id)`
    
2. **Identity Lookup:** Sentinel calls `IdentityStore.get_tags(user_id)`.
    
3. **Policy Enforcement:** If tags are empty, **Fail-Closed** (Return "Access Denied").
    
4. **Query Synthesis:** Sentinel generates a DB-specific metadata filter:
    
    - _Bedrock:_ `{"equals": {"attr": "access_tag", "value": "tag_name"}}`
        
5. **Retrieval:** Knowledge Store executes the filtered ANN search.
    
6. **Response:** Sentinel formats chunks into a context string for the LLM.