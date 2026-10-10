import pytest
from sentinel_engine.results import ACCESS_DENIED

from sentinel.adapters.agentcore.envelope import ENVELOPE_ARGUMENT, open_envelope
from sentinel.adapters.agentcore.request_interceptor import intercept_request
from tests.support.fakes import DictIdentity, StubBedrockKB
from tests.support.gateway import (
    ENVELOPE_KEY,
    KB_TOOL,
    LAMBDA_TOOL,
    forwarded,
    request_event,
    result_text,
    rpc,
    runtime,
    short_circuit,
    tool_call,
)
from tests.support.tokens import bearer


@pytest.mark.parametrize("method", ["initialize", "ping", "tools/list"])
async def test_handshake_and_listing_pass_through(method):
    body = rpc(method, {})
    assert forwarded(await intercept_request(request_event(body), runtime())) == body


async def test_lambda_target_gets_a_sealed_principal_and_nothing_else():
    rt = runtime()
    call = tool_call(LAMBDA_TOOL, {"query": "budget", "user_id": "charlie", "n_results": 3})
    out = await intercept_request(request_event(call, bearer("intern")), rt)
    arguments = forwarded(out)["params"]["arguments"]
    assert set(arguments) == {"query", "n_results", ENVELOPE_ARGUMENT}
    signed = {"query": "budget", "n_results": 3}
    assert open_envelope(arguments[ENVELOPE_ARGUMENT], signed, ENVELOPE_KEY) == "intern"


async def test_managed_kb_filter_is_overwritten_never_merged():
    rt = runtime()
    smuggled = {
        "retrievalQuery": {"text": "budget"},
        "retrievalConfiguration": {
            "managedSearchConfiguration": {
                "filter": {"equals": {"key": "tag_finance", "value": True}}
            }
        },
        "userContext": {"userId": "charlie"},
        "guardrailConfiguration": {"guardrailId": "off"},
    }
    out = await intercept_request(request_event(tool_call(KB_TOOL, smuggled), bearer("intern")), rt)
    arguments = forwarded(out)["params"]["arguments"]
    assert set(arguments) == {"retrievalQuery", "retrievalConfiguration"}
    config = arguments["retrievalConfiguration"]["managedSearchConfiguration"]
    assert config["filter"] == {"equals": {"key": "tag_public", "value": True}}


@pytest.mark.parametrize("authorization", [None, "Bearer junk", "Basic dXNlcjpwYXNz", bearer("*")])
async def test_unverified_callers_are_short_circuited(authorization):
    call = tool_call(LAMBDA_TOOL, {"query": "budget"})
    denial = short_circuit(await intercept_request(request_event(call, authorization), runtime()))
    assert denial is not None
    assert result_text(denial) == ACCESS_DENIED
    assert denial["id"] == call["id"]


@pytest.mark.parametrize("tool", ["kb___AgenticRetrieveStream", "other___delete_everything"])
async def test_tools_outside_the_allowlist_are_denied(tool):
    call = tool_call(tool, {"query": "x"})
    assert short_circuit(await intercept_request(request_event(call, bearer("alice")), runtime()))


async def test_unknown_methods_are_denied():
    call = rpc("resources/read", {"uri": "file:///etc/passwd"})
    assert short_circuit(await intercept_request(request_event(call, bearer("alice")), runtime()))


async def test_user_without_permissions_never_reaches_the_kb():
    kb = StubBedrockKB.seeded()
    call = tool_call(KB_TOOL, {"retrievalQuery": {"text": "budget"}})
    out = await intercept_request(request_event(call, bearer("ghost")), runtime(kb=kb))
    assert short_circuit(out)
    assert kb.calls == 0


async def test_identity_outage_denies():
    rt = runtime(identity=DictIdentity(fail=True))
    call = tool_call(KB_TOOL, {"retrievalQuery": {"text": "budget"}})
    assert short_circuit(await intercept_request(request_event(call, bearer("alice")), rt))


async def test_query_is_bounded_and_n_results_clamped():
    call = tool_call(LAMBDA_TOOL, {"query": "x" * 5000, "n_results": 10_000})
    out = await intercept_request(request_event(call, bearer("alice")), runtime())
    arguments = forwarded(out)["params"]["arguments"]
    assert len(arguments["query"]) == 2000
    assert arguments["n_results"] == 20


async def test_malformed_events_are_denied():
    assert short_circuit(await intercept_request({"mcp": "not-json"}, runtime()))


async def test_user_context_comes_from_the_token_when_enabled():
    rt = runtime()
    rt.forward_user_context = True
    smuggled = {"retrievalQuery": {"text": "q"}, "userContext": {"userId": "charlie"}}
    out = await intercept_request(request_event(tool_call(KB_TOOL, smuggled), bearer("intern")), rt)
    assert forwarded(out)["params"]["arguments"]["userContext"] == {"userId": "intern"}


async def test_every_decision_is_logged_with_the_user_and_their_tags(caplog):
    caplog.set_level("INFO", logger="sentinel.agentcore.request")
    call = tool_call(LAMBDA_TOOL, {"query": "budget"})
    await intercept_request(request_event(call, bearer("alice")), runtime())
    await intercept_request(request_event(call, bearer("ghost")), runtime())
    allow, deny = caplog.records
    assert (allow.decision, allow.user, allow.tags) == ("allow", "alice", ["finance", "public"])
    assert (deny.decision, deny.user) == ("deny", "ghost")
    assert "no permissions" in deny.reason


async def test_lambda_target_calls_are_denied_up_front_for_tagless_users():
    call = tool_call(LAMBDA_TOOL, {"query": "budget"})
    assert short_circuit(await intercept_request(request_event(call, bearer("ghost")), runtime()))


async def test_what_can_i_access_gets_a_sealed_principal_only():
    call = tool_call("sentinel___what_can_i_access", {"user_id": "charlie"})
    out = await intercept_request(request_event(call, bearer("intern")), runtime())
    arguments = forwarded(out)["params"]["arguments"]
    assert set(arguments) == {ENVELOPE_ARGUMENT}
    assert open_envelope(arguments[ENVELOPE_ARGUMENT], {}, ENVELOPE_KEY) == "intern"
