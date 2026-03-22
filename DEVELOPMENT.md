# Sentinel — Development Guide

This guide covers everything needed to extend Sentinel with custom connectors: implementing the interfaces, wiring them into the server, and writing a test suite that matches the project's conventions.

---

## Extending Sentinel: Custom Connectors

Sentinel is built to be extensible. You can plug in any Identity Provider or Vector Knowledge Base by implementing two small abstract interfaces. No changes to the engine or MCP layer are required — only a new file and a branch in `_build_engine()`.

---

### 1. Identity Connector

The `IdentityConnector` is responsible for the **Permission Handshake**. It fetches the authoritative set of tags for a user from whatever source of truth you use (Okta, Auth0, a custom SQL table, an in-house IAM service, etc.).

```python
# sentinel/connectors/identity/my_provider.py

from sentinel.core.base import IdentityConnector


class MyCustomIdentity(IdentityConnector):
    def __init__(self, api_url: str, api_key: str):
        self.api_url = api_url
        self.api_key = api_key

    async def get_tags(self, user_id: str) -> set[str]:
        """
        Fetch permission tags (e.g. {"dept:finance", "role:admin"})
        for a specific user.

        IMPORTANT: Always fail-closed. Return an empty set if the user
        is not found — never raise, never return a default set.
        The engine treats an empty set as "access denied" and will
        block the query before any knowledge base call is made.
        """
        tags = await my_api.fetch_user_metadata(user_id)
        return set(tags)  # empty set → fail-closed
```

**Contract:**

| Rule | Detail |
|---|---|
| Return type | `set[str]` — tag strings are compared directly against document metadata |
| Unknown user | Return `set()` — do not raise, do not return defaults |
| Async | Must be `async def` — Sentinel's engine `await`s every call |
| Stateless | Do not cache user data between calls |

---

### 2. Knowledge Connector

The `KnowledgeConnector` handles **Enforcement**. It translates the user's tags into a database-native metadata filter and executes the search. It also handles document ingestion with those same tags attached.

```python
# sentinel/connectors/knowledge/my_store.py

from sentinel.core.base import KnowledgeConnector


class MyCustomVectorStore(KnowledgeConnector):
    def __init__(self, db_url: str, api_key: str):
        self.client = MyVectorClient(db_url, api_key)

    async def search(
        self, query: str, tags: set[str], n_results: int = 5
    ) -> list[dict]:
        """
        Execute a tag-filtered vector search.

        The OR policy means: return documents where at least one of the
        user's tags appears in the document's access_tags set.

        Return format — each result must be a dict with exactly:
            {
                "text":     str,    # document content
                "metadata": dict,   # arbitrary key/value pairs
                "score":    float,  # similarity score, higher is better
            }
        """
        # Example: translate tags to your DB's native filter
        tag_filter = {"access_tags": {"$in": list(tags)}}
        raw = await self.client.query(
            query,
            filter=tag_filter,
            limit=n_results,
        )
        return [
            {"text": r.content, "metadata": r.metadata, "score": r.score}
            for r in raw
        ]

    async def ingest(
        self,
        text: str,
        access_tags: list[str],
        doc_id: str,
        metadata: dict | None = None,
    ) -> None:
        """
        Persist a document with its access tags attached as metadata.

        Callers guarantee access_tags is non-empty (enforced by the MCP
        tools layer), but your implementation should be safe regardless.
        """
        meta = dict(metadata or {})
        meta["access_tags"] = ",".join(access_tags)
        vector = await self.embed(text)
        await self.client.upsert(id=doc_id, vector=vector, metadata=meta)
```

**Return format for `search`:**

| Key | Type | Required | Notes |
|---|---|---|---|
| `text` | `str` | ✅ | Raw document text returned to the LLM |
| `metadata` | `dict` | ✅ | Arbitrary key/value pairs; `title` and `access_tags` are conventional |
| `score` | `float` | ✅ | Similarity score; Sentinel's relevance threshold filters on this |

---

### 3. Wiring It Up

Add your connector to `_build_engine()` in `sentinel/main.py`:

```python
def _build_engine() -> SentinelEngine:
    identity_store = os.environ.get("SENTINEL_IDENTITY_STORE", "NOT_SET")
    knowledge_store = os.environ.get("SENTINEL_KNOWLEDGE_STORE", "NOT_SET")

    # --- Identity ---
    if identity_store == "sqlite":
        ...
    elif identity_store == "my_provider":
        from sentinel.connectors.identity.my_provider import MyCustomIdentity
        identity = MyCustomIdentity(
            api_url=os.environ["MY_PROVIDER_URL"],
            api_key=os.environ["MY_PROVIDER_KEY"],
        )
    else:
        raise ValueError(f"Unsupported identity store: '{identity_store}'")

    # --- Knowledge ---
    if knowledge_store == "chroma":
        ...
    elif knowledge_store == "my_store":
        from sentinel.connectors.knowledge.my_store import MyCustomVectorStore
        knowledge = MyCustomVectorStore(
            db_url=os.environ["MY_STORE_URL"],
            api_key=os.environ["MY_STORE_KEY"],
        )
    else:
        raise ValueError(f"Unsupported knowledge store: '{knowledge_store}'")

    return SentinelEngine(identity, knowledge)
```

Then set the env vars in your MCP config:

```json
"env": {
  "SENTINEL_IDENTITY_STORE": "my_provider",
  "MY_PROVIDER_URL": "https://...",
  "MY_PROVIDER_KEY": "...",
  "SENTINEL_KNOWLEDGE_STORE": "my_store",
  "MY_STORE_URL": "https://...",
  "MY_STORE_KEY": "..."
}
```

---

## Unit Testing a Custom Connector

Sentinel uses `pytest` with `pytest-asyncio` in `auto` mode. Tests live in `tests/`. The project convention is to test connectors in isolation with mocked external dependencies, and test the full pipeline via the engine with real (but ephemeral) backends.

### Setup

```bash
uv sync --extra dev
uv run pytest            # run all unit tests
uv run pytest -m e2e     # run end-to-end tests (require live backends)
```

### Testing an Identity Connector

Mock your external API and verify the two critical behaviours: known users return the right tags, unknown users return an empty set.

```python
# tests/test_identity_my_provider.py

from unittest.mock import AsyncMock, patch
import pytest
from sentinel.connectors.identity.my_provider import MyCustomIdentity


@pytest.fixture
def connector():
    return MyCustomIdentity(api_url="https://fake", api_key="test-key")


@pytest.mark.asyncio
async def test_known_user_returns_tags(connector):
    with patch.object(connector, "_fetch", new=AsyncMock(return_value=["finance", "public"])):
        tags = await connector.get_tags("alice")
    assert tags == {"finance", "public"}


@pytest.mark.asyncio
async def test_unknown_user_returns_empty_set(connector):
    with patch.object(connector, "_fetch", new=AsyncMock(return_value=[])):
        tags = await connector.get_tags("nobody")
    assert tags == set()


@pytest.mark.asyncio
async def test_api_error_returns_empty_set(connector):
    """Fail-closed: any error from the upstream API must result in an empty set."""
    with patch.object(connector, "_fetch", new=AsyncMock(side_effect=Exception("timeout"))):
        tags = await connector.get_tags("alice")
    assert tags == set()
```

> **Tip:** The third test (`api_error_returns_empty_set`) is worth adding to every identity connector. If your upstream API is unavailable, you want Sentinel to deny access rather than silently grant it.

### Testing a Knowledge Connector

Test the search filter logic and the ingestion path. Mock the underlying vector database client to keep tests fast and dependency-free.

```python
# tests/test_knowledge_my_store.py

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from sentinel.connectors.knowledge.my_store import MyCustomVectorStore


@pytest.fixture
def connector():
    return MyCustomVectorStore(db_url="https://fake", api_key="test-key")


def _raw_result(text, score, tags):
    r = MagicMock()
    r.content = text
    r.score = score
    r.metadata = {"access_tags": ",".join(tags)}
    return r


@pytest.mark.asyncio
async def test_search_returns_correct_format(connector):
    raw = [_raw_result("Budget report 2026", 0.85, ["finance"])]
    with patch.object(connector.client, "query", new=AsyncMock(return_value=raw)):
        results = await connector.search("budget", tags={"finance"})

    assert len(results) == 1
    assert results[0]["text"] == "Budget report 2026"
    assert results[0]["score"] == 0.85
    assert "metadata" in results[0]


@pytest.mark.asyncio
async def test_search_passes_tag_filter(connector):
    """The OR filter must include every tag the user holds."""
    with patch.object(connector.client, "query", new=AsyncMock(return_value=[])) as mock_query:
        await connector.search("anything", tags={"finance", "public"})

    call_kwargs = mock_query.call_args[1]
    passed_filter = call_kwargs["filter"]
    assert set(passed_filter["access_tags"]["$in"]) == {"finance", "public"}


@pytest.mark.asyncio
async def test_ingest_attaches_access_tags(connector):
    with patch.object(connector.client, "upsert", new=AsyncMock()) as mock_upsert:
        await connector.ingest("Some text", ["finance"], "doc-1", {"title": "Report"})

    meta = mock_upsert.call_args[1]["metadata"]
    assert "finance" in meta["access_tags"]
```

### Testing the Full Pipeline (Engine Tests)

The most valuable tests run your connector through `SentinelEngine` to verify the full access control pipeline. Use `pytest_asyncio` fixtures to set up lightweight in-process state.

```python
# tests/test_engine_my_connector.py

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock

from sentinel.core.engine import SentinelEngine, AccessDeniedError
from sentinel.connectors.identity.my_provider import MyCustomIdentity
from sentinel.connectors.knowledge.my_store import MyCustomVectorStore


@pytest_asyncio.fixture
async def engine():
    identity = MyCustomIdentity(api_url="https://fake", api_key="key")
    knowledge = MyCustomVectorStore(db_url="https://fake", api_key="key")

    # Wire in fixed responses so tests are deterministic
    identity.get_tags = AsyncMock(side_effect=lambda uid: {
        "alice": {"finance", "public"},
        "bob":   {"engineering"},
    }.get(uid, set()))

    knowledge.search = AsyncMock(return_value=[
        {"text": "Budget doc", "metadata": {"access_tags": "finance"}, "score": 0.9}
    ])

    return SentinelEngine(identity, knowledge)


@pytest.mark.asyncio
async def test_fail_closed_unknown_user(engine):
    with pytest.raises(AccessDeniedError):
        await engine.secure_search("anything", "unknown")


@pytest.mark.asyncio
async def test_known_user_gets_results(engine):
    results = await engine.secure_search("budget", "alice")
    assert len(results) == 1
    assert results[0]["text"] == "Budget doc"


@pytest.mark.asyncio
async def test_kb_never_called_for_unknown_user(engine):
    """Fail-closed: the knowledge base must not be queried when access is denied."""
    try:
        await engine.secure_search("anything", "unknown")
    except AccessDeniedError:
        pass
    engine.knowledge.search.assert_not_called()
```

### End-to-End Tests (Live Backends)

For connectors that talk to a real service, add E2E tests under `tests/e2e/`. Use a skip marker so they're excluded from normal CI runs:

```python
# tests/e2e/test_e2e_my_connector.py

import os
import pytest
import pytest_asyncio

from sentinel.connectors.identity.my_provider import MyCustomIdentity
from sentinel.core.engine import AccessDeniedError, SentinelEngine

requires_my_provider = pytest.mark.skipif(
    not os.environ.get("MY_PROVIDER_URL"),
    reason="MY_PROVIDER_URL not set — skipping live E2E tests",
)


@pytest_asyncio.fixture(scope="module")
async def connector():
    return MyCustomIdentity(
        api_url=os.environ["MY_PROVIDER_URL"],
        api_key=os.environ["MY_PROVIDER_KEY"],
    )


@requires_my_provider
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_known_user_returns_tags(connector):
    tags = await connector.get_tags("alice")
    assert isinstance(tags, set)
    assert len(tags) > 0


@requires_my_provider
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_unknown_user_returns_empty(connector):
    tags = await connector.get_tags("completely_unknown_xyz")
    assert tags == set()
```

Run E2E tests separately:

```bash
MY_PROVIDER_URL=https://... MY_PROVIDER_KEY=... uv run pytest -m e2e
```

---

## Test Conventions

| Convention | Detail |
|---|---|
| All test files in `tests/` | Unit tests; run automatically by `uv run pytest` |
| E2E tests in `tests/e2e/` | Tagged `@pytest.mark.e2e`; skipped unless `-m e2e` is passed |
| Skip live backends gracefully | Use `pytest.mark.skipif` with an env var or port probe — never fail hard |
| Use `pytest_asyncio.fixture` | For any fixture that does `await` — not plain `pytest.fixture` |
| Module-scoped fixtures for heavy setup | E.g. loading embedding models; use `scope="module"` to avoid reloading per test |
| `tmp_path` / `tmp_path_factory` for storage | Never write test data to `./data/` — always use pytest's temp directories |
| Fail-closed is a required test | Every identity connector must have a test asserting `get_tags(unknown) == set()` |

---

## Project Layout for New Connectors

```
sentinel/connectors/
├── identity/
│   ├── sqlite.py          # reference: minimal sync-style connector
│   ├── ddb.py             # reference: AWS async connector
│   ├── spicedb.py         # reference: gRPC streaming connector
│   └── my_provider.py     # your new identity connector
└── knowledge/
    ├── chroma.py          # reference: local embedding + vector store
    ├── bedrock.py         # reference: cloud API with metadata filters
    └── my_store.py        # your new knowledge connector

tests/
├── test_identity_my_provider.py     # unit tests (mocked)
└── e2e/
    └── test_e2e_my_connector.py     # live backend tests (skipped in CI)
```

The existing connectors (`sqlite.py`, `spicedb.py`, `chroma.py`) are the best reference implementations — each demonstrates a different integration style (sync DB, gRPC streaming, REST/cloud SDK).
