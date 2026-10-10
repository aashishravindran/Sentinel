# Copyright (c) 2026 Aashish Ravindran. All rights reserved.
# Use of this software is governed by the Elastic License 2.0
# found in the LICENSE file.

"""Sentinel in two minutes, entirely local: no AWS, no API keys.

Runs the real MCP server and the real AgentCore Gateway interceptors against
ChromaDB loaded with docs/seed, with identities from demo/org.json.

    uv run python -m demo.run_demo
"""

import asyncio
import json
import logging
import os
import tempfile
import warnings
from pathlib import Path

# Keep the walkthrough readable: no model download bars or library chatter.
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
os.environ.setdefault("FASTMCP_LOG_LEVEL", "CRITICAL")
warnings.filterwarnings("ignore")

from fastmcp import Client  # noqa: E402
from fastmcp.exceptions import ToolError  # noqa: E402
from fastmcp.server.auth.providers.jwt import RSAKeyPair  # noqa: E402
from sentinel_engine.base import IdentityConnector  # noqa: E402
from sentinel_engine.connectors.knowledge.chroma import ChromaKnowledgeConnector  # noqa: E402
from sentinel_engine.engine import SentinelEngine  # noqa: E402
from sentinel_engine.oidc import OIDCSettings, TokenVerifier  # noqa: E402

from sentinel.adapters.agentcore.events import TOOL_NAME_SEPARATOR  # noqa: E402
from sentinel.adapters.agentcore.request_interceptor import intercept_request  # noqa: E402
from sentinel.adapters.agentcore.response_interceptor import intercept_response  # noqa: E402
from sentinel.adapters.agentcore.runtime import Runtime  # noqa: E402
from sentinel.adapters.agentcore.target import secure_search  # noqa: E402
from sentinel.adapters.mcp.server import create_server  # noqa: E402
from sentinel.adapters.mcp.settings import ServerSettings  # noqa: E402
from sentinel.ingest.documents import ingest_documents, load_tagged_documents  # noqa: E402

ROOT = Path(__file__).parent.parent
QUESTION = "What is our 2026 operating budget?"
ISSUER, AUDIENCE = "https://login.demo.local", "sentinel"
TOOL = f"sentinel{TOOL_NAME_SEPARATOR}secure_search"

BOLD, DIM, GREEN, RED, CYAN, RESET = (
    "\033[1m",
    "\033[2m",
    "\033[32m",
    "\033[31m",
    "\033[36m",
    "\033[0m",
)


class OrgFile(IdentityConnector):
    """Identities from demo/org.json, reread on every lookup like a live store."""

    def __init__(self, path: Path):
        self.path = path

    async def get_tags(self, user_id: str) -> set[str]:
        return set(json.loads(self.path.read_text())["users"].get(user_id, []))


class DecisionLog(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        fields = {
            k: getattr(record, k)
            for k in ("decision", "user", "tags", "kept", "dropped")
            if hasattr(record, k)
        }
        print(f"    {DIM}{record.name.rsplit('.', 1)[-1]} log: {json.dumps(fields)}{RESET}")


def scene(title: str) -> None:
    print(f"\n{BOLD}{CYAN}▸ {title}{RESET}")


def show(answer: str) -> None:
    first = [line for line in answer.split("\n---\n")[0].splitlines() if line.strip()]
    denied = ("do not have access", "Access denied.", "Rejected:")
    colour = RED if any(marker in answer for marker in denied) else GREEN
    print(f"    {colour}{first[0]}{RESET}")
    for line in first[1:3]:
        print(f"    {DIM}{line[:110]}{RESET}")


async def ask_mcp(engine: SentinelEngine, user: str, **extra: object) -> str:
    async with Client(create_server(engine, ServerSettings("stdio", stdio_user=user))) as client:
        try:
            result = await client.call_tool("secure_search", {"query": QUESTION, **extra})
        except ToolError:
            return f"Rejected: secure_search takes no {', '.join(extra)} argument."
    return result.content[0].text


async def ask_gateway(runtime: Runtime, keys: RSAKeyPair, user: str) -> list[str]:
    token = keys.create_token(subject=user, issuer=ISSUER, audience=AUDIENCE)
    headers = {"Authorization": f"Bearer {token}"}
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": TOOL, "arguments": {"query": QUESTION, "user_id": "charlie"}},
    }
    event = {"mcp": {"gatewayRequest": {"headers": headers, "body": body}}}
    out = (await intercept_request(event, runtime))["mcp"]
    if "transformedGatewayResponse" in out:
        return []
    rewritten = out["transformedGatewayRequest"]["body"]
    payload = await secure_search(TOOL, rewritten["params"]["arguments"], runtime)
    reply = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"content": [{"type": "text", "text": json.dumps(payload)}]},
    }
    event = {
        "mcp": {
            "gatewayRequest": {"headers": headers, "body": rewritten},
            "gatewayResponse": {"statusCode": 200, "body": reply},
        }
    }
    final = (await intercept_response(event, runtime))["mcp"]["transformedGatewayResponse"]
    results = json.loads(final["body"]["result"]["content"][0]["text"])["results"]
    return [r["metadata"]["title"] for r in results]


async def main() -> None:
    org = ROOT / "demo" / "org.json"
    with tempfile.TemporaryDirectory() as path:
        knowledge = ChromaKnowledgeConnector(path, "demo", "all-MiniLM-L6-v2")
        await ingest_documents(load_tagged_documents(ROOT / "docs" / "seed"), knowledge)
        engine = SentinelEngine(OrgFile(org), knowledge)

        print(
            f"{BOLD}Sentinel demo{RESET}  {DIM}7 documents · identities from demo/org.json{RESET}"
        )
        print(f'{DIM}Everyone asks: "{QUESTION}"{RESET}')

        scene("MCP · the intern (public documents only)")
        show(await ask_mcp(engine, "intern"))

        scene("MCP · alice (finance)")
        show(await ask_mcp(engine, "alice"))

        scene('MCP · the intern passes user_id="alice", the v1 hole')
        show(await ask_mcp(engine, "intern", user_id="alice"))
        print(f"    {DIM}identity comes from the connection, never from tool arguments{RESET}")

        scene("AgentCore Gateway · same question, interceptors running locally")
        logging.getLogger("sentinel.agentcore").addHandler(DecisionLog())
        logging.getLogger("sentinel.agentcore").setLevel(logging.INFO)
        keys = RSAKeyPair.generate()
        runtime = Runtime(
            engine=engine,
            verifier=TokenVerifier(
                OIDCSettings(issuer=ISSUER, public_key=keys.public_key, audience=(AUDIENCE,))
            ),
            envelope_key=b"demo-envelope-key",
        )
        for user in ("intern", "alice"):
            print(f"  {BOLD}{user}{RESET} (also tries user_id=charlie)")
            titles = await ask_gateway(runtime, keys, user)
            colour = GREEN if any("Finance" in t for t in titles) else RED
            print(f"    {colour}results: {', '.join(titles) or 'none'}{RESET}")

        print(f"\n{BOLD}Same engine, same decisions, whichever way the agent connects.{RESET}")


if __name__ == "__main__":
    asyncio.run(main())
