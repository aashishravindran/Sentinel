# Copyright (c) 2026 Aashish Ravindran. All rights reserved.
# Use of this software is governed by the Elastic License 2.0
# found in the LICENSE file.

"""Build AgentCore Gateway interceptor events and drive a call end to end, locally.

Event shapes follow the AgentCore Gateway interceptor contract (version 1.0).
"""

import json
from typing import Any

from sentinel_engine.engine import SentinelEngine
from sentinel_engine.oidc import TokenVerifier

from sentinel.adapters.agentcore.request_interceptor import intercept_request
from sentinel.adapters.agentcore.response_interceptor import intercept_response
from sentinel.adapters.agentcore.runtime import Runtime
from sentinel.adapters.agentcore.target import secure_search
from tests.support.fakes import DictIdentity, StubBedrockKB
from tests.support.tokens import OIDC

ENVELOPE_KEY = b"test-envelope-key"
LAMBDA_TOOL = "sentinel___secure_search"
KB_TOOL = "kb___Retrieve"


def runtime(identity: DictIdentity | None = None, kb: StubBedrockKB | None = None) -> Runtime:
    return Runtime(
        engine=SentinelEngine(identity or DictIdentity(), kb or StubBedrockKB.seeded()),
        verifier=TokenVerifier(OIDC),
        envelope_key=ENVELOPE_KEY,
        min_relevance_score=0.0,
    )


def rpc(method: str, params: dict[str, Any] | None = None, request_id: int = 1) -> dict[str, Any]:
    body: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        body["params"] = params
    return body


def tool_call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return rpc("tools/call", {"name": name, "arguments": arguments})


def request_event(body: dict[str, Any], authorization: str | None = None) -> dict[str, Any]:
    headers = {"Authorization": authorization} if authorization else {}
    return {
        "interceptorInputVersion": "1.0",
        "mcp": {
            "rawGatewayRequest": {"body": json.dumps(body)},
            "gatewayRequest": {
                "path": "/mcp",
                "httpMethod": "POST",
                "headers": headers,
                "body": body,
            },
        },
    }


def response_event(
    request: dict[str, Any],
    response: dict[str, Any],
    authorization: str | None = None,
    *,
    streaming: bool = False,
) -> dict[str, Any]:
    event = request_event(request, authorization)
    event["mcp"]["gatewayResponse"] = {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": response,
        "isStreamingResponse": streaming,
    }
    return event


def tool_result(request_id: object, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {"isError": False, "content": [{"type": "text", "text": json.dumps(payload)}]},
    }


def short_circuit(output: dict[str, Any]) -> dict[str, Any] | None:
    response = output["mcp"].get("transformedGatewayResponse")
    return response["body"] if response else None


def forwarded(output: dict[str, Any]) -> dict[str, Any]:
    return output["mcp"]["transformedGatewayRequest"]["body"]


def response_body(output: dict[str, Any]) -> dict[str, Any]:
    return output["mcp"]["transformedGatewayResponse"]["body"]


def result_text(body: dict[str, Any]) -> str:
    return body["result"]["content"][0]["text"]


async def call_through_gateway(
    rt: Runtime, tool: str, arguments: dict[str, Any], authorization: str | None
) -> dict[str, Any]:
    """REQUEST interceptor -> target (Lambda or Managed KB stub) -> RESPONSE interceptor."""
    request = tool_call(tool, arguments)
    out = await intercept_request(request_event(request, authorization), rt)
    if (denied := short_circuit(out)) is not None:
        return denied
    rewritten = forwarded(out)
    args = rewritten["params"]["arguments"]
    if tool == LAMBDA_TOOL:
        payload = await secure_search(tool, args, rt)
    else:
        kb = rt.engine.knowledge
        assert isinstance(kb, StubBedrockKB)
        config = args["retrievalConfiguration"]["managedSearchConfiguration"]
        chunks = kb.retrieve(
            args["retrievalQuery"]["text"], config["filter"], config["numberOfResults"]
        )
        payload = {"retrievalResults": [{"content": {"text": c["text"]}, **c} for c in chunks]}
    response = tool_result(request["id"], payload)
    final = await intercept_response(response_event(rewritten, response, authorization), rt)
    return response_body(final)
