> **Historical (v1) design notes.** Current behavior is described in the [README](../README.md), the [ADRs](../docs/adr/) and the [threat model](../docs/threat-model.md). In particular, v2 no longer accepts `user_id` from the model ([ADR 0001](../docs/adr/0001-identity-from-transport.md)).


sentinel-rag/
├── .env                  # Local development variables (not for prod)
├── pyproject.toml        # uv/poetry dependencies
├── README.md             # Integration & setup documentation
├── sentinel/
│   ├── __init__.py
│   ├── main.py           # FastMCP entry point & tool definitions
│   ├── core/
│   │   ├── __init__.py
│   │   ├── base.py       # Abstract Base Classes (Identity/Knowledge)
│   │   └── engine.py     # The "Orchestrator" (The RRF & RLS logic)
│   └── connectors/
│       ├── __init__.py
│       ├── identity/
│       │   ├── ddb.py    # DynamoDB Identity Connector
│       │   └── sqlite.py # SQLite Identity Connector
│       └── knowledge/
│           ├── bedrock.py # Bedrock KB Connector
│           └── pinecone.py# (Future) Pinecone Connector
├── schema/
│   └── init_db.sql       # SQLite schema for local testing
└── tests/                # Unit tests for conflict resolution logic