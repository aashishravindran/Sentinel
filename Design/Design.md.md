## 1. Data Models

### Identity Schema (SQLite/DDB)

- **Partition Key:** `user_id` (String)
    
- **Attribute:** `tags` (SS - String Set)
    
- _Example:_ `{"user_123": ["finance", "public", "project_x"]}`
    

### Knowledge Metadata Schema

- Every document/chunk MUST contain an `access_tags` field.

- Sentinel enforces an **OR policy**: User must possess at least one tag present on the document to retrieve it (intersection of user tags and doc tags must be non-empty).

- Access control (tag filter) and result quality (relevance score) are separate mechanisms. The tag filter is the security boundary. The relevance score (`MIN_RELEVANCE_SCORE`, default 0.25) is applied after retrieval to drop documents that are authorised but not relevant to the query — preventing LLM hallucination from low-signal results. It does not grant or deny access.
    

## 2. Interface Definitions (Python)

Python

```
class IdentityConnector(ABC):
    @abstractmethod
    async def get_tags(self, user_id: str) -> set[str]:
        """Fetch tags from the vault."""

class KnowledgeConnector(ABC):
    @abstractmethod
    async def search(self, query: str, tags: set[str]) -> List[Dict]:
        """Execute filtered vector search."""
```

## 3. Security Principles

- **Zero Trust:** The MCP server never trusts the `user_id` to have global access.
    
- **Statelessness:** No user data is cached between MCP sessions.
    
- **Environment-Driven:** All "Secrets" and "Endpoints" are injected via `mcp.json` environment variables.
    

###  4. Sample MCP.json 
```
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
