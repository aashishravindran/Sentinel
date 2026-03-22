# Quickstart

Sentinel MCP supports two backend configurations: **local** (SQLite + ChromaDB) for development, and **AWS** (DynamoDB + Bedrock Knowledge Bases) for production. Both use the same MCP tool interface.

---

## Local Development (SQLite + ChromaDB)

### 1. Install dependencies

```bash
uv sync
```

### 2. Initialize the local database and seed documents

```bash
python scripts/init_db.py
python scripts/ingest_seed_docs.py
```

### 3. Configure your MCP client

Add this to your MCP client configuration (Claude Desktop `claude_desktop_config.json`, Cursor `.cursor/mcp.json`, etc.):

```json
{
  "mcpServers": {
    "sentinel-rag": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "python", "-m", "sentinel.main"],
      "env": {
        "SENTINEL_IDENTITY_STORE": "sqlite",
        "SQLITE_DB_PATH": "/absolute/path/to/data/permissions.db",
        "SENTINEL_KNOWLEDGE_STORE": "chroma",
        "CHROMA_PATH": "/absolute/path/to/data/chroma",
        "CHROMA_COLLECTION": "sentinel",
        "EMBEDDING_MODEL": "all-MiniLM-L6-v2",
        "MIN_RELEVANCE_SCORE": "0.25"
      }
    }
  }
}
```

Replace `/absolute/path/to/` with the actual path to your Sentinel project directory.

### 4. Test it

Open your MCP client and try:
- `secure_search("quarterly revenue", "alice")` — alice has the `finance` tag, so she sees finance docs
- `secure_search("quarterly revenue", "bob")` — bob only has `engineering` and `public`, so finance docs are denied

---

## AWS (DynamoDB + Bedrock Knowledge Bases)

### 1. Install dependencies

```bash
uv sync
```

### 2. Provision AWS infrastructure

> **Important:** `scripts/setup_aws.py` is a development convenience script for quickly standing up a demo environment. For production, provision AWS infrastructure separately using CloudFormation, Terraform, or the AWS console. In particular: the IAM role created by the script has broad permissions and should be scoped down for production use.

```bash
# Copy the example env file and fill in your AWS credentials
cp .env.example .env
# Edit .env — set AWS_PROFILE or AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY

# Provision all resources (DynamoDB, S3, IAM, OpenSearch Serverless, Bedrock KB)
python scripts/setup_aws.py --stack sentinel --region us-east-1

# Seed identity table with test users
python scripts/seed_ddb.py --table sentinel-identity --region us-east-1
```

The setup script prints environment variable values at the end. Copy `BEDROCK_KB_ID`, `BEDROCK_S3_BUCKET`, `BEDROCK_DS_ID`, and `DDB_TABLE_NAME` from its output for the next step.

### 3. Configure your MCP client

The env block supports three authentication methods:

**Option A: AWS named profile (recommended for local development)**
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
        "AWS_PROFILE": "your-profile-name",

        "DDB_TABLE_NAME": "sentinel-identity",

        "BEDROCK_KB_ID": "<from setup_aws.py output>",
        "BEDROCK_S3_BUCKET": "<from setup_aws.py output>",
        "BEDROCK_S3_PREFIX": "documents/",
        "BEDROCK_DS_ID": "<from setup_aws.py output>",

        "BEDROCK_SEARCH_TYPE": "HYBRID",
        "BEDROCK_RERANKING": "false",
        "MIN_RELEVANCE_SCORE": "0.25"
      }
    }
  }
}
```

**Option B: Static access keys (CI, Docker, or environments without ~/.aws)**
```json
"env": {
  "AWS_ACCESS_KEY_ID": "AKIA...",
  "AWS_SECRET_ACCESS_KEY": "...",
  "AWS_REGION": "us-east-1",
  ...
}
```

**Option C: Instance/task role (EC2, ECS, Lambda)**

Omit all AWS auth variables. The SDK will use the instance metadata service automatically.

```json
"env": {
  "AWS_REGION": "us-east-1",
  ...
}
```

### 4. Optional: Enable reranking

Add these to the env block to enable cross-encoder reranking after retrieval:

```json
"BEDROCK_RERANKING": "true",
"BEDROCK_RERANK_MODEL_ARN": "arn:aws:bedrock:us-east-1::foundation-model/amazon.rerank-v1:0",
"BEDROCK_RERANK_OVERSAMPLE": "3"
```

This fetches 3x more candidates from the vector search, then uses the reranking model to select the top N most relevant results.

### 5. Tear down

```bash
python scripts/setup_aws.py --stack sentinel --region us-east-1 --destroy
```

---

## MCP Tools

Once configured, your MCP client exposes three tools:

| Tool | Description |
|---|---|
| `secure_search(query, user_id, n_results=5)` | Search the knowledge base. Returns only documents the user is authorized to see. |
| `ingest_document(text, access_tags, doc_id, title="")` | Ingest a text document with access control tags. |
| `ingest_pdf(access_tags, doc_id, pdf_path="", pdf_base64="", title="", metadata={})` | Ingest a PDF page-by-page. Prefer `pdf_path` over `pdf_base64` to avoid MCP message size limits. |
