"""v1's hole: the model chose user_id. v2 must ignore or reject any attempt to."""

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from sentinel_engine.engine import SentinelEngine

from sentinel.adapters.mcp.server import create_server
from sentinel.adapters.mcp.settings import ServerSettings
from tests.support.fakes import DictIdentity, StubBedrockKB

pytestmark = pytest.mark.redteam

SPOOF_ARGUMENTS = [
    {"user_id": "charlie"},
    {"user_id": "root"},
    {"principal": "charlie"},
    {"userContext": {"userId": "charlie"}},
    {"filter": {"equals": {"key": "tag_finance", "value": True}}},
]


@pytest.mark.parametrize("extra", SPOOF_ARGUMENTS)
async def test_intern_cannot_borrow_another_identity(extra):
    kb = StubBedrockKB.seeded()
    server = create_server(
        SentinelEngine(DictIdentity(), kb),
        ServerSettings("stdio", stdio_user="intern", min_relevance_score=0.0),
    )
    async with Client(server) as client:
        try:
            result = await client.call_tool(
                "secure_search", {"query": "budget opex canary", **extra}
            )
            text = result.content[0].text
        except ToolError:
            text = ""
    assert "CANARY-FIN-7731" not in text
    assert all(f == {"equals": {"key": "tag_public", "value": True}} for f in kb.filters)
