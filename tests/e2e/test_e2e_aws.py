# Copyright (c) 2026 Aashish Ravindran. All rights reserved.
# Use of this software is governed by the Elastic License 2.0
# found in the LICENSE file.

"""E2E tests: DynamoDB (identity) + Bedrock Knowledge Bases (knowledge).

Requires AWS env vars:
    DDB_TABLE_NAME, BEDROCK_KB_ID, BEDROCK_S3_BUCKET, AWS_REGION

Assumes the DynamoDB table contains at least:
    alice  -> {finance, public}
    bob    -> {public, engineering}

Run with:
    uv run pytest -m e2e tests/e2e/test_e2e_aws.py -v

Note: Bedrock KB sync after ingest can take 1–5 minutes, so these tests
verify the search pipeline works end-to-end without asserting on specific
ingested content.
"""

import os

import pytest
import pytest_asyncio

from sentinel.connectors.identity.ddb import DynamoDBIdentityConnector
from sentinel.connectors.knowledge.bedrock import BedrockKnowledgeConnector
from sentinel.core.engine import AccessDeniedError, SentinelEngine

from tests.e2e.conftest import requires_aws


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="module")
async def ddb():
    return DynamoDBIdentityConnector(
        table_name=os.environ["DDB_TABLE_NAME"],
        region=os.environ.get("AWS_REGION", "us-east-1"),
    )


@pytest_asyncio.fixture(scope="module")
async def bedrock():
    return BedrockKnowledgeConnector(
        kb_id=os.environ["BEDROCK_KB_ID"],
        s3_bucket=os.environ["BEDROCK_S3_BUCKET"],
        s3_prefix=os.environ.get("BEDROCK_S3_PREFIX", "documents/"),
        data_source_id=os.environ.get("BEDROCK_DS_ID", ""),
        region=os.environ.get("AWS_REGION", "us-east-1"),
        search_type=os.environ.get("BEDROCK_SEARCH_TYPE", "HYBRID"),
        reranking=os.environ.get("BEDROCK_RERANKING", "false").lower() == "true",
    )


@pytest_asyncio.fixture(scope="module")
async def engine(ddb, bedrock):
    return SentinelEngine(ddb, bedrock)


# ---------------------------------------------------------------------------
# DynamoDB identity tests
# ---------------------------------------------------------------------------

@requires_aws
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_ddb_alice_tags(ddb):
    tags = await ddb.get_tags("alice")
    assert "finance" in tags
    assert "public" in tags


@requires_aws
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_ddb_bob_tags(ddb):
    tags = await ddb.get_tags("bob")
    assert "public" in tags
    assert "engineering" in tags


@requires_aws
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_ddb_unknown_user_returns_empty(ddb):
    tags = await ddb.get_tags("completely_unknown_user_xyz")
    assert tags == set()


# ---------------------------------------------------------------------------
# Full engine pipeline tests (DynamoDB + Bedrock)
# ---------------------------------------------------------------------------

@requires_aws
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_fail_closed_unknown_user(engine):
    """Unknown users must be denied before any Bedrock call is made."""
    with pytest.raises(AccessDeniedError):
        await engine.secure_search("anything", "completely_unknown_user_xyz")


@requires_aws
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_alice_search_does_not_raise(engine):
    """Alice (finance, public) can call secure_search without error.

    The KB may return zero results if no matching docs exist — that is
    acceptable; this test validates the full pipeline runs without exceptions.
    """
    results = await engine.secure_search("financial report revenue", "alice", n_results=3)
    assert isinstance(results, list)
    for r in results:
        assert "text" in r
        assert "score" in r
        assert "metadata" in r


@requires_aws
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_bob_search_does_not_raise(engine):
    """Bob (public, engineering) can call secure_search without error."""
    results = await engine.secure_search("service deployment architecture", "bob", n_results=3)
    assert isinstance(results, list)


@requires_aws
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_bedrock_result_scores_are_valid(engine):
    """Every result returned by Bedrock must have a score in [0, 1]."""
    results = await engine.secure_search("company overview", "alice", n_results=5)
    for r in results:
        assert 0.0 <= r["score"] <= 1.0, f"Unexpected score: {r['score']}"


@requires_aws
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_access_control_filters_results(engine):
    """Results returned to alice must not contain engineering-only documents."""
    results = await engine.secure_search("on-call runbook kubernetes", "alice", n_results=5)
    for r in results:
        meta = r["metadata"]
        # If the doc has explicit access_tags metadata from Bedrock, verify alice can see it
        raw_tags = meta.get("access_tags", "")
        if raw_tags:
            doc_tags = set(raw_tags.split(","))
            alice_tags = {"finance", "public"}
            assert doc_tags & alice_tags, (
                f"Doc with tags {doc_tags} was returned to alice who only has {alice_tags}"
            )
