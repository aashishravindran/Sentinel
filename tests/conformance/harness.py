# Copyright (c) 2026 Aashish Ravindran. All rights reserved.
# Use of this software is governed by the Elastic License 2.0
# found in the LICENSE file.

"""Run one search as a persona through each Sentinel entry point.

Every adapter shares one engine, one identity store and one knowledge base,
so any difference in outcome is a difference in the adapter itself.
"""

import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastmcp import Client
from fastmcp.utilities.tests import run_server_async
from sentinel_engine.engine import SentinelEngine
from sentinel_engine.results import ACCESS_DENIED

from sentinel.adapters.mcp.server import create_server
from sentinel.adapters.mcp.settings import ServerSettings
from tests.support.fakes import DictIdentity, StubBedrockKB
from tests.support.gateway import KB_TOOL, LAMBDA_TOOL, call_through_gateway, runtime
from tests.support.tokens import OIDC, bearer, token_for

DENIED = "denied"
Outcome = frozenset[str] | str
MCP_RESULT_TITLE = re.compile(r"^\[\d+\] (\S+)", re.MULTILINE)


@dataclass
class Backend:
    identity: DictIdentity
    kb: StubBedrockKB

    @property
    def engine(self) -> SentinelEngine:
        return SentinelEngine(self.identity, self.kb)


def _from_mcp_text(text: str) -> Outcome:
    if text == ACCESS_DENIED:
        return DENIED
    return frozenset(MCP_RESULT_TITLE.findall(text))


def _from_gateway(body: dict) -> Outcome:
    result = body["result"]
    if result.get("isError"):
        return DENIED
    payload = json.loads(result["content"][0]["text"])
    if payload.get("message") == ACCESS_DENIED:
        return DENIED
    items = payload.get("results", payload.get("retrievalResults", []))
    return frozenset(item["metadata"]["title"] for item in items)


async def mcp_stdio(backend: Backend, persona: str, query: str) -> Outcome:
    settings = ServerSettings("stdio", stdio_user=persona, min_relevance_score=0.0)
    async with Client(create_server(backend.engine, settings)) as client:
        result = await client.call_tool("secure_search", {"query": query, "n_results": 20})
    return _from_mcp_text(result.content[0].text)


async def mcp_http(backend: Backend, persona: str, query: str) -> Outcome:
    settings = ServerSettings("http", oidc=OIDC, min_relevance_score=0.0)
    server = create_server(backend.engine, settings)
    async with run_server_async(server) as url, Client(url, auth=token_for(persona)) as client:
        result = await client.call_tool("secure_search", {"query": query, "n_results": 20})
    return _from_mcp_text(result.content[0].text)


async def gateway_lambda_target(backend: Backend, persona: str, query: str) -> Outcome:
    rt = runtime(backend.identity, backend.kb)
    args = {"query": query, "n_results": 20}
    return _from_gateway(await call_through_gateway(rt, LAMBDA_TOOL, args, bearer(persona)))


async def gateway_managed_kb(backend: Backend, persona: str, query: str) -> Outcome:
    rt = runtime(backend.identity, backend.kb)
    args = {"retrievalQuery": {"text": query}}
    return _from_gateway(await call_through_gateway(rt, KB_TOOL, args, bearer(persona)))


ADAPTERS: dict[str, Callable[[Backend, str, str], Awaitable[Outcome]]] = {
    "mcp-stdio": mcp_stdio,
    "mcp-http": mcp_http,
    "gateway-lambda-target": gateway_lambda_target,
    "gateway-managed-kb": gateway_managed_kb,
}
