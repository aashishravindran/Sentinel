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

Add this to your MCP client configuration (Claude Desktop `claude_desktop_config.json`, Cursor `.cursor/mcp.json`, etc.).

Replace `/absolute/path/to/Sentinel` with the actual path to your cloned Sentinel directory (e.g. `/Users/yourname/Projects/Sentinel`).

```json
{
  "mcpServers": {
    "sentinel-rag": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "python", "-m", "sentinel.main"],
      "cwd": "/absolute/path/to/Sentinel",
      "env": {
        "SENTINEL_IDENTITY_STORE": "sqlite",
        "SQLITE_DB_PATH": "/absolute/path/to/Sentinel/data/permissions.db",
        "SENTINEL_KNOWLEDGE_STORE": "chroma",
        "CHROMA_PATH": "/absolute/path/to/Sentinel/data/chroma",
        "CHROMA_COLLECTION": "sentinel",
        "EMBEDDING_MODEL": "all-MiniLM-L6-v2",
        "MIN_RELEVANCE_SCORE": "0.25"
      }
    }
  }
}
```

> **Why `cwd`?** MCP clients launch the server process from their own working directory, not yours. Setting `cwd` to the Sentinel repo root ensures `uv` picks up the correct `pyproject.toml` and the `sentinel` module is on the path.

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

Replace `/absolute/path/to/Sentinel` with the path to your cloned repo in all blocks below.

**Option A: AWS named profile (recommended for local development)**
```json
{
  "mcpServers": {
    "sentinel-rag": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "python", "-m", "sentinel.main"],
      "cwd": "/absolute/path/to/Sentinel",
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
{
  "mcpServers": {
    "sentinel-rag": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "python", "-m", "sentinel.main"],
      "cwd": "/absolute/path/to/Sentinel",
      "env": {
        "SENTINEL_IDENTITY_STORE": "dynamodb",
        "SENTINEL_KNOWLEDGE_STORE": "bedrock",

        "AWS_REGION": "us-east-1",
        "AWS_ACCESS_KEY_ID": "AKIA...",
        "AWS_SECRET_ACCESS_KEY": "...",

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

**Option C: Instance/task role (EC2, ECS, Lambda)**

Omit all AWS auth variables — the SDK resolves credentials from the instance metadata service automatically.

```json
{
  "mcpServers": {
    "sentinel-rag": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "python", "-m", "sentinel.main"],
      "cwd": "/absolute/path/to/Sentinel",
      "env": {
        "SENTINEL_IDENTITY_STORE": "dynamodb",
        "SENTINEL_KNOWLEDGE_STORE": "bedrock",

        "AWS_REGION": "us-east-1",

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

## AWS (IAM Tags + Bedrock Knowledge Bases)

Use this configuration when you want to derive user permissions directly from IAM user or role tags — no separate identity table (DynamoDB) required. The IAM connector reads tags from the principal making the request and maps them to Sentinel access tags.

**`IAM_TAG_FORMAT` — choosing what part of the IAM tag becomes the Sentinel tag:**

| Format | IAM tag | Sentinel tag | Document `access_tags` |
|---|---|---|---|
| `value` (simplest) | `Project = finance` | `finance` | `["finance"]` |
| `key` | `Project = finance` | `Project` | `["Project"]` |
| `key:value` (most precise) | `Project = finance` | `Project:finance` | `["Project:finance"]` |

- **`value`** — shortest tags, easiest to read, but collisions are possible if two different keys share the same value (e.g. `Team = 4` and `ClearanceLevel = 4` both become `4`).
- **`key`** — useful when the key itself is the permission group and values are irrelevant (e.g. a tag `finance = true` grants the `finance` permission).
- **`key:value`** — fully qualified, no collisions. Recommended when IAM tags mix many different key namespaces.

### 1. Tag your IAM principals

Attach tags to IAM users or roles that correspond to document access groups:

```
Project   = finance
Team      = platform
ClearanceLevel = 3
```

To scope which tags Sentinel sees, set `IAM_TAG_KEY_PREFIX` (e.g. `Sentinel/`) so only tags prefixed with `Sentinel/` are used, with the prefix stripped before matching.

### 2. Provision Bedrock infrastructure

```bash
python scripts/setup_aws.py --stack sentinel --region us-east-1
```

The setup script prints `BEDROCK_KB_ID`, `BEDROCK_S3_BUCKET`, and `BEDROCK_DS_ID`. Copy those for the next step. You do **not** need to seed a DynamoDB identity table.

### 3. Configure your MCP client

**Option A: AWS named profile (recommended for local development)**
```json
{
  "mcpServers": {
    "sentinel-rag": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "python", "-m", "sentinel.main"],
      "cwd": "/absolute/path/to/Sentinel",
      "env": {
        "SENTINEL_IDENTITY_STORE": "iam",
        "SENTINEL_KNOWLEDGE_STORE": "bedrock",

        "AWS_REGION": "us-east-1",
        "AWS_PROFILE": "your-profile-name",

        "IAM_PRINCIPAL_TYPE": "user",
        "IAM_TAG_FORMAT": "value",

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

**Option B: Static access keys (CI, Docker)**
```json
{
  "mcpServers": {
    "sentinel-rag": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "python", "-m", "sentinel.main"],
      "cwd": "/absolute/path/to/Sentinel",
      "env": {
        "SENTINEL_IDENTITY_STORE": "iam",
        "SENTINEL_KNOWLEDGE_STORE": "bedrock",

        "AWS_REGION": "us-east-1",
        "AWS_ACCESS_KEY_ID": "AKIA...",
        "AWS_SECRET_ACCESS_KEY": "...",

        "IAM_PRINCIPAL_TYPE": "user",
        "IAM_TAG_FORMAT": "value",

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

**Option C: Instance/task role (EC2, ECS, Lambda)**

Set `IAM_PRINCIPAL_TYPE=role` and pass the role name as `user_id` in `secure_search`. Omit all static AWS auth variables.

```json
{
  "mcpServers": {
    "sentinel-rag": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "python", "-m", "sentinel.main"],
      "cwd": "/absolute/path/to/Sentinel",
      "env": {
        "SENTINEL_IDENTITY_STORE": "iam",
        "SENTINEL_KNOWLEDGE_STORE": "bedrock",

        "AWS_REGION": "us-east-1",

        "IAM_PRINCIPAL_TYPE": "role",
        "IAM_TAG_FORMAT": "value",

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

### 4. Optional: scope tags with a prefix

To avoid clashing with non-Sentinel IAM tags, use a dedicated key prefix:

```json
"IAM_TAG_KEY_PREFIX": "Sentinel/",
"IAM_TAG_FORMAT": "value"
```

Then tag your principals as `Sentinel/Project = finance` — only keys starting with `Sentinel/` are included, and the prefix is stripped before matching, so documents still use `access_tags=["finance"]`.

### 5. Ingest documents with matching tags

`access_tags` on a document must use the **same format** you configured in `IAM_TAG_FORMAT`. The three formats map like this:

**`IAM_TAG_FORMAT=value`**

IAM principal tagged `Project = finance`:
```
ingest_document(text=..., access_tags=["finance"], doc_id="q4-report")
```

**`IAM_TAG_FORMAT=key`**

IAM principal tagged `finance = true` (key carries the meaning):
```
ingest_document(text=..., access_tags=["finance"], doc_id="q4-report")
```

**`IAM_TAG_FORMAT=key:value`**

IAM principal tagged `Project = finance`:
```
ingest_document(text=..., access_tags=["Project:finance"], doc_id="q4-report")
```

Use `key:value` when multiple keys could produce the same value and you need to avoid false matches. A document tagged `["Project:finance"]` will **not** match a user who has `Team = finance` formatted as `key:value` (`Team:finance`), even though the value is the same.

### 6. Tear down

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
