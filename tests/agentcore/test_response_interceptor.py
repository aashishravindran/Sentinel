import json

import pytest
from sentinel_engine.results import ACCESS_DENIED

from sentinel.adapters.agentcore.envelope import ENVELOPE_ARGUMENT
from sentinel.adapters.agentcore.response_interceptor import intercept_response
from tests.support.fakes import DictIdentity
from tests.support.gateway import (
    KB_TOOL,
    response_body,
    response_event,
    result_text,
    rpc,
    runtime,
    tool_call,
    tool_result,
)
from tests.support.tokens import bearer

LISTING = {
    "jsonrpc": "2.0",
    "id": 1,
    "result": {
        "tools": [
            {
                "name": "kb___Retrieve",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "retrievalQuery": {
                            "type": "object",
                            "properties": {"text": {"type": "string"}},
                        },
                        "retrievalConfiguration": {"type": "object"},
                        "filter": {"type": "object"},
                        "userContext": {"type": "object"},
                    },
                    "required": ["retrievalQuery", "userContext"],
                },
            },
            {"name": "kb___AgenticRetrieveStream", "inputSchema": {"type": "object"}},
            {
                "name": "sentinel___secure_search",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        ENVELOPE_ARGUMENT: {"type": "string"},
                    },
                },
            },
        ]
    },
}


async def test_tools_list_hides_control_arguments_and_streaming_tools():
    event = response_event(rpc("tools/list", {}), LISTING)
    tools = response_body(await intercept_response(event, runtime()))["result"]["tools"]
    assert [t["name"] for t in tools] == ["kb___Retrieve", "sentinel___secure_search"]
    retrieve = tools[0]["inputSchema"]
    assert set(retrieve["properties"]) == {"retrievalQuery"}
    assert retrieve["required"] == ["retrievalQuery"]
    assert set(tools[1]["inputSchema"]["properties"]) == {"query"}


def _retrieved(*tag_sets: str) -> dict:
    return {
        "retrievalResults": [
            {"content": {"text": f"doc {i}"}, "metadata": {"access_tags": tags}}
            for i, tags in enumerate(tag_sets)
        ]
    }


async def test_unauthorized_chunks_are_dropped_from_results():
    request = tool_call(KB_TOOL, {"retrievalQuery": {"text": "q"}})
    response = tool_result(1, _retrieved("public", "finance", "finance,public", ""))
    out = await intercept_response(response_event(request, response, bearer("intern")), runtime())
    kept = json.loads(result_text(response_body(out)))["retrievalResults"]
    assert [r["content"]["text"] for r in kept] == ["doc 0", "doc 2"]


async def test_scope_is_re_resolved_live():
    identity = DictIdentity()
    rt = runtime(identity=identity)
    request = tool_call(KB_TOOL, {"retrievalQuery": {"text": "q"}})
    response = tool_result(1, _retrieved("finance"))
    identity.tags["alice"] = {"public"}  # revoked between request and response
    out = await intercept_response(response_event(request, response, bearer("alice")), rt)
    assert json.loads(result_text(response_body(out)))["retrievalResults"] == []


@pytest.mark.parametrize(
    "response",
    [
        tool_result(1, {"unexpected": "shape"}),
        {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": "free text"}]}},
        {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "image", "data": "..."}]}},
    ],
)
async def test_results_that_cannot_be_checked_are_denied(response):
    request = tool_call(KB_TOOL, {"retrievalQuery": {"text": "q"}})
    out = await intercept_response(response_event(request, response, bearer("alice")), runtime())
    assert result_text(response_body(out)) == ACCESS_DENIED


async def test_streaming_results_are_denied():
    request = tool_call(KB_TOOL, {"retrievalQuery": {"text": "q"}})
    event = response_event(
        request, tool_result(1, _retrieved("public")), bearer("alice"), streaming=True
    )
    assert result_text(response_body(await intercept_response(event, runtime()))) == ACCESS_DENIED


async def test_missing_token_on_the_response_path_is_denied():
    request = tool_call(KB_TOOL, {"retrievalQuery": {"text": "q"}})
    out = await intercept_response(
        response_event(request, tool_result(1, _retrieved("public"))), runtime()
    )
    assert result_text(response_body(out)) == ACCESS_DENIED


async def test_errors_from_upstream_pass_through_unchanged():
    request = tool_call(KB_TOOL, {"retrievalQuery": {"text": "q"}})
    error = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"isError": True, "content": [{"type": "text", "text": "boom"}]},
    }
    out = await intercept_response(response_event(request, error, bearer("alice")), runtime())
    assert response_body(out) == error
