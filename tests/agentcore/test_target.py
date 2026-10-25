import time

import pytest
from sentinel_engine.errors import IdentityError
from sentinel_engine.results import ACCESS_DENIED

from sentinel.adapters.agentcore.envelope import ENVELOPE_ARGUMENT, open_envelope, seal
from sentinel.adapters.agentcore.target import run_tool
from tests.support.gateway import ENVELOPE_KEY, LAMBDA_TOOL, runtime


def _arguments(user: str, query: str = "budget opex canary", n: int = 5, **overrides) -> dict:
    signed = {"query": query, "n_results": n}
    return {**signed, ENVELOPE_ARGUMENT: seal(user, signed, ENVELOPE_KEY), **overrides}


async def test_target_searches_as_the_sealed_user():
    payload = await run_tool(LAMBDA_TOOL, _arguments("alice"), runtime())
    assert any("CANARY-FIN-7731" in r["text"] for r in payload["results"])


async def test_direct_invocation_without_envelope_is_denied():
    payload = await run_tool(LAMBDA_TOOL, {"query": "budget", "n_results": 5}, runtime())
    assert payload == {"results": [], "message": ACCESS_DENIED}


async def test_envelope_cannot_be_reused_for_another_query():
    arguments = _arguments("alice", query="holiday calendar")
    arguments["query"] = "budget opex canary"
    payload = await run_tool(LAMBDA_TOOL, arguments, runtime())
    assert payload["results"] == []


async def test_forged_envelope_is_denied():
    signed = {"query": "budget", "n_results": 5}
    forged = seal("charlie", signed, b"attacker-guess")
    payload = await run_tool(LAMBDA_TOOL, {**signed, ENVELOPE_ARGUMENT: forged}, runtime())
    assert payload["results"] == []


async def test_unknown_tool_name_is_denied():
    payload = await run_tool("sentinel___drop_tables", _arguments("alice"), runtime())
    assert payload["results"] == []


def test_envelope_expires():
    signed = {"query": "q", "n_results": 1}
    envelope = seal("alice", signed, ENVELOPE_KEY, ttl_seconds=60, now=time.time() - 120)
    with pytest.raises(IdentityError):
        open_envelope(envelope, signed, ENVELOPE_KEY)


@pytest.mark.parametrize("envelope", [None, "", "a.b.c", "nodot", 42])
def test_malformed_envelopes_are_rejected(envelope):
    with pytest.raises(IdentityError):
        open_envelope(envelope, {}, ENVELOPE_KEY)


async def test_what_can_i_access_returns_the_sealed_users_live_tags():
    arguments = {ENVELOPE_ARGUMENT: seal("alice", {}, ENVELOPE_KEY)}
    payload = await run_tool("sentinel___what_can_i_access", arguments, runtime())
    assert payload == {"user": "alice", "tags": ["finance", "public"]}


async def test_what_can_i_access_requires_an_envelope():
    payload = await run_tool("sentinel___what_can_i_access", {}, runtime())
    assert payload["message"] == ACCESS_DENIED
