# Copyright (c) 2026 Aashish Ravindran. All rights reserved.
# Use of this software is governed by the Elastic License 2.0
# found in the LICENSE file.

"""E2E tests: SpiceDB (identity) + ChromaDB (knowledge).

Requires SpiceDB running with the Sentinel schema and seed data:
    ./spicedb/start.sh

Run with:
    uv run pytest -m e2e tests/e2e/test_e2e_local.py -v
"""

import pytest
import pytest_asyncio

from sentinel.connectors.identity.spicedb import SpiceDBIdentityConnector
from sentinel.connectors.knowledge.chroma import ChromaKnowledgeConnector
from sentinel.core.engine import AccessDeniedError, SentinelEngine

from tests.e2e.conftest import requires_spicedb

# ---------------------------------------------------------------------------
# Seed data — must match spicedb/seed.sh
# ---------------------------------------------------------------------------

SPICEDB_ENDPOINT = "localhost:50051"
SPICEDB_TOKEN = "sentinel-local"

SEED_DOCS = [
    ("e2e_public_overview",  "Company overview open to all staff.",             ["public"]),
    ("e2e_finance_budget",   "2026 budget: $88.9M total opex planned.",         ["finance"]),
    ("e2e_eng_runbook",      "On-call runbook: check Grafana dashboard first.", ["engineering"]),
    ("e2e_internal_roadmap", "Roadmap: Series D in Q3, AI pod in Q1.",          ["finance", "engineering"]),
]

# ---------------------------------------------------------------------------
# Module-scoped fixtures (embedding model loaded once per test session)
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="module")
async def spicedb():
    """Real SpiceDB connector pointed at localhost:50051."""
    return SpiceDBIdentityConnector(SPICEDB_ENDPOINT, SPICEDB_TOKEN, tls=False)


@pytest_asyncio.fixture(scope="module")
async def chroma(tmp_path_factory):
    """Temporary ChromaDB collection seeded with E2E docs."""
    tmp = tmp_path_factory.mktemp("chroma_e2e")
    conn = ChromaKnowledgeConnector(str(tmp), "e2e", "all-MiniLM-L6-v2")
    for doc_id, text, tags in SEED_DOCS:
        await conn.ingest(text, tags, doc_id, {"title": doc_id})
    return conn


@pytest_asyncio.fixture(scope="module")
async def engine(spicedb, chroma):
    """Full SentinelEngine wired to real SpiceDB + temp ChromaDB."""
    return SentinelEngine(spicedb, chroma)


# ---------------------------------------------------------------------------
# SpiceDB identity connector tests
# ---------------------------------------------------------------------------

@requires_spicedb
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_spicedb_alice_tags(spicedb):
    tags = await spicedb.get_tags("alice")
    assert tags == {"finance", "public"}


@requires_spicedb
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_spicedb_bob_tags(spicedb):
    tags = await spicedb.get_tags("bob")
    assert tags == {"public", "engineering"}


@requires_spicedb
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_spicedb_charlie_tags(spicedb):
    tags = await spicedb.get_tags("charlie")
    assert tags == {"finance", "public", "engineering"}


@requires_spicedb
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_spicedb_unknown_user_returns_empty(spicedb):
    tags = await spicedb.get_tags("completely_unknown_user_xyz")
    assert tags == set()


@requires_spicedb
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_spicedb_read_relationships_alice(spicedb):
    rels = await spicedb.read_relationships("alice")
    resource_ids = {r["resource_id"] for r in rels}
    assert resource_ids == {"finance", "public"}
    for r in rels:
        assert r["resource_type"] == "tag"
        assert r["relation"] == "member"


@requires_spicedb
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_spicedb_read_relationships_unknown_user(spicedb):
    rels = await spicedb.read_relationships("completely_unknown_user_xyz")
    assert rels == []


# ---------------------------------------------------------------------------
# Full engine pipeline tests (SpiceDB identity + ChromaDB knowledge)
# ---------------------------------------------------------------------------

@requires_spicedb
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_fail_closed_unknown_user(engine):
    with pytest.raises(AccessDeniedError):
        await engine.secure_search("anything", "unknown_user_xyz")


@requires_spicedb
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_alice_sees_finance_doc(engine):
    results = await engine.secure_search("annual budget opex", "alice", n_results=3)
    retrieved_ids = {r["metadata"]["title"] for r in results}
    assert "e2e_finance_budget" in retrieved_ids


@requires_spicedb
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_alice_cannot_see_engineering_only_doc(engine):
    """Alice (finance, public) should not surface the eng-only runbook."""
    results = await engine.secure_search("on-call runbook Grafana", "alice", n_results=5)
    retrieved_ids = {r["metadata"]["title"] for r in results if r["score"] >= 0.25}
    assert "e2e_eng_runbook" not in retrieved_ids


@requires_spicedb
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_bob_sees_engineering_doc(engine):
    results = await engine.secure_search("on-call runbook Grafana", "bob", n_results=3)
    retrieved_ids = {r["metadata"]["title"] for r in results}
    assert "e2e_eng_runbook" in retrieved_ids


@requires_spicedb
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_or_policy_alice_sees_multi_tag_roadmap(engine):
    """Alice has 'finance' which is one of roadmap's tags — she should see it."""
    results = await engine.secure_search("Series D AI roadmap", "alice", n_results=5)
    retrieved_ids = {r["metadata"]["title"] for r in results if r["score"] >= 0.25}
    assert "e2e_internal_roadmap" in retrieved_ids


@requires_spicedb
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_or_policy_bob_sees_multi_tag_roadmap(engine):
    """Bob has 'engineering' which is one of roadmap's tags — he should see it."""
    results = await engine.secure_search("Series D AI roadmap", "bob", n_results=5)
    retrieved_ids = {r["metadata"]["title"] for r in results if r["score"] >= 0.25}
    assert "e2e_internal_roadmap" in retrieved_ids


@requires_spicedb
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_charlie_sees_all_doc_types(engine):
    """Charlie has all three tags and should be able to retrieve any document."""
    finance = await engine.secure_search("annual budget opex", "charlie", n_results=3)
    eng = await engine.secure_search("on-call runbook Grafana", "charlie", n_results=3)

    finance_ids = {r["metadata"]["title"] for r in finance}
    eng_ids = {r["metadata"]["title"] for r in eng}

    assert "e2e_finance_budget" in finance_ids
    assert "e2e_eng_runbook" in eng_ids
