"""The MCP server takes identity from the transport, never from tool arguments."""

import pytest
from fastmcp import Client
from fastmcp.utilities.tests import run_server_async
from sentinel_engine.engine import SentinelEngine
from sentinel_engine.errors import ConfigError, IdentityError
from sentinel_engine.results import ACCESS_DENIED

from sentinel.adapters.mcp.server import create_server
from sentinel.adapters.mcp.settings import ServerSettings
from tests.support.fakes import DictIdentity, StubBedrockKB
from tests.support.tokens import OIDC, token_for

QUERY = "2026 budget opex roadmap overview"


def _engine() -> SentinelEngine:
    return SentinelEngine(DictIdentity(), StubBedrockKB.seeded())


def _stdio(user: str) -> ServerSettings:
    return ServerSettings("stdio", stdio_user=user, min_relevance_score=0.0)


HTTP = ServerSettings("http", oidc=OIDC, min_relevance_score=0.0)


async def _search_stdio(user: str, **arguments: object) -> str:
    async with Client(create_server(_engine(), _stdio(user))) as client:
        result = await client.call_tool("secure_search", {"query": QUERY, **arguments})
    return result.content[0].text


async def test_stdio_user_sees_their_documents():
    text = await _search_stdio("alice")
    assert "CANARY-FIN-7731" in text
    assert "Grafana" not in text


async def test_stdio_intern_does_not_see_finance():
    text = await _search_stdio("intern")
    assert "CANARY-FIN-7731" not in text
    assert "holiday calendar" in text


async def test_unknown_stdio_user_is_denied():
    assert await _search_stdio("ghost") == ACCESS_DENIED


def test_stdio_without_a_user_refuses_to_start():
    with pytest.raises(ConfigError):
        ServerSettings.from_env({"SENTINEL_TRANSPORT": "stdio"})


def test_stdio_user_must_be_a_valid_subject():
    with pytest.raises(IdentityError):
        ServerSettings("stdio", stdio_user="*")


def test_http_without_oidc_refuses_to_start():
    with pytest.raises(ConfigError):
        ServerSettings.from_env({"SENTINEL_TRANSPORT": "http"})


async def test_secure_search_has_no_identity_argument():
    async with Client(create_server(_engine(), _stdio("alice"))) as client:
        tools = {t.name: t for t in await client.list_tools()}
    assert set(tools["secure_search"].inputSchema["properties"]) == {"query", "n_results"}


async def _search_http(token: str | None) -> str:
    server = create_server(_engine(), HTTP)
    async with run_server_async(server) as url, Client(url, auth=token) as client:
        result = await client.call_tool("secure_search", {"query": QUERY})
    return result.content[0].text


async def test_http_user_comes_from_the_token():
    text = await _search_http(token_for("alice"))
    assert "CANARY-FIN-7731" in text


async def test_http_without_a_token_is_rejected():
    with pytest.raises(Exception, match=r"401|Unauthorized|auth"):
        await _search_http(None)


async def test_http_expired_token_is_rejected():
    with pytest.raises(Exception, match=r"401|Unauthorized|auth"):
        await _search_http(token_for("alice", expires_in_seconds=-3600))


async def test_http_wildcard_subject_is_denied():
    assert await _search_http(token_for("*")) == ACCESS_DENIED


async def test_http_client_id_does_not_become_the_user():
    text = await _search_http(token_for("intern", client_id="charlie", azp="charlie"))
    assert "CANARY-FIN-7731" not in text
