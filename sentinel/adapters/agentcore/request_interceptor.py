# Copyright (c) 2026 Aashish Ravindran. All rights reserved.
# Use of this software is governed by the Elastic License 2.0
# found in the LICENSE file.

"""REQUEST interceptor: rewrite every tool call so the model cannot widen access.

For each ``tools/call`` the caller is taken from the verified bearer token and
the arguments are rebuilt from scratch. Nothing the model sent survives except
the query text, so a model-supplied ``filter``, ``userContext`` or user ID is
discarded, never merged.
"""

import logging
from typing import Any, cast

from sentinel_engine.filters import build_managed_search_config

from sentinel.adapters.agentcore.envelope import ENVELOPE_ARGUMENT, seal
from sentinel.adapters.agentcore.events import GatewayEvent, deny, forward_request, parse
from sentinel.adapters.agentcore.runtime import Runtime, get_runtime

logger = logging.getLogger("sentinel.agentcore.request")

PASSTHROUGH_METHODS = frozenset({"initialize", "ping", "tools/list"})
MAX_QUERY_CHARS = 2000
DEFAULT_RESULTS = 5
MAX_RESULTS = 20


def _query(event: GatewayEvent) -> str:
    args = event.arguments
    text = args.get("query") if event.tool_name == "secure_search" else None
    if event.tool_name == "Retrieve":
        retrieval_query = args.get("retrievalQuery")
        text = (
            cast(dict[str, Any], retrieval_query).get("text")
            if isinstance(retrieval_query, dict)
            else None
        )
    if not isinstance(text, str) or not text.strip():
        raise ValueError("query text is required")
    return text.strip()[:MAX_QUERY_CHARS]


def _n_results(event: GatewayEvent) -> int:
    requested = event.arguments.get("n_results", DEFAULT_RESULTS)
    if isinstance(requested, bool) or not isinstance(requested, int):
        return DEFAULT_RESULTS
    return max(1, min(requested, MAX_RESULTS))


async def rewrite_arguments(event: GatewayEvent, runtime: Runtime) -> dict[str, Any]:
    principal = runtime.verifier.verify_authorization_header(event.authorization, "gateway")
    query, n_results = _query(event), _n_results(event)

    if event.tool_name == "secure_search":
        arguments: dict[str, Any] = {"query": query, "n_results": n_results}
        arguments[ENVELOPE_ARGUMENT] = seal(principal.user_id, arguments, runtime.envelope_key)
        return arguments

    if event.tool_name == "Retrieve":
        scope = await runtime.engine.resolve_scope(principal.user_id)
        return {
            "retrievalQuery": {"text": query},
            "retrievalConfiguration": build_managed_search_config(scope, n_results),
            "userContext": {"userId": principal.user_id},
        }

    # AgenticRetrieveStream streams past the interceptors; every other tool is unknown.
    raise PermissionError(f"tool {event.tool_name!r} is not allowed through Sentinel")


async def intercept_request(raw_event: dict[str, Any], runtime: Runtime) -> dict[str, Any]:
    request_id: object = None
    try:
        event = parse(raw_event)
        request_id = event.request_id
        if event.method in PASSTHROUGH_METHODS or event.method.startswith("notifications/"):
            return forward_request(event.request)
        if event.method != "tools/call":
            raise PermissionError(f"method {event.method!r} is not allowed")
        arguments = await rewrite_arguments(event, runtime)
        params = {**event.params, "arguments": arguments}
        return forward_request({**event.request, "params": params})
    except Exception as exc:
        logger.warning("request denied: %s: %s", type(exc).__name__, exc)
        return deny(request_id)


def handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    runtime = get_runtime()
    return runtime.run(intercept_request(event, runtime))
