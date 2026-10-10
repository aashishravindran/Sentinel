# Copyright (c) 2026 Aashish Ravindran. All rights reserved.
# Use of this software is governed by the Elastic License 2.0
# found in the LICENSE file.

"""RESPONSE interceptor: hide control arguments and re-check every returned chunk.

``tools/list``: strip arguments the model must never set (``filter``,
``userContext``, the principal envelope) and drop streaming tools.

``tools/call``: re-verify the caller, resolve their scope live, and drop any
chunk they may not read. This holds even if the target or knowledge base
ignored the filter. A result that cannot be parsed and checked is denied.
"""

import json
import logging
from collections.abc import Set
from typing import Any, cast

from sentinel_engine.filters import chunk_authorized

from sentinel.adapters.agentcore.envelope import ENVELOPE_ARGUMENT
from sentinel.adapters.agentcore.events import GatewayEvent, deny, parse, respond
from sentinel.adapters.agentcore.runtime import Runtime, get_runtime

logger = logging.getLogger("sentinel.agentcore.response")

HIDDEN_ARGUMENTS = frozenset(
    {"filter", "userContext", "retrievalConfiguration", "rerankingConfiguration", ENVELOPE_ARGUMENT}
)
HIDDEN_TOOL_SUFFIXES = ("AgenticRetrieveStream",)
RESULT_LISTS = ("retrievalResults", "results")


def strip_hidden_arguments(schema: Any) -> Any:
    if isinstance(schema, list):
        return [strip_hidden_arguments(item) for item in cast(list[Any], schema)]
    if not isinstance(schema, dict):
        return schema
    cleaned: dict[str, Any] = {}
    for key, value in cast(dict[str, Any], schema).items():
        if key == "properties" and isinstance(value, dict):
            properties = cast(dict[str, Any], value)
            cleaned[key] = {
                name: strip_hidden_arguments(prop)
                for name, prop in properties.items()
                if name not in HIDDEN_ARGUMENTS
            }
        elif key == "required" and isinstance(value, list):
            cleaned[key] = [n for n in cast(list[Any], value) if n not in HIDDEN_ARGUMENTS]
        else:
            cleaned[key] = strip_hidden_arguments(value)
    return cleaned


def sanitize_tool_list(body: dict[str, Any]) -> dict[str, Any]:
    result = dict(body.get("result") or {})
    tools: list[dict[str, Any]] = [
        {**tool, "inputSchema": strip_hidden_arguments(tool.get("inputSchema", {}))}
        for tool in result.get("tools", [])
        if not str(tool.get("name", "")).endswith(HIDDEN_TOOL_SUFFIXES)
    ]
    return {**body, "result": {**result, "tools": tools}}


def _authorized_payload(text: str, scope: Set[str]) -> str:
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("tool result is not a JSON object")
    payload = cast(dict[str, Any], payload)
    lists = [key for key in RESULT_LISTS if isinstance(payload.get(key), list)]
    if not lists:
        raise ValueError("tool result has no recognizable result list")
    for key in lists:
        payload[key] = [
            item
            for item in cast(list[Any], payload[key])
            if isinstance(item, dict)
            and chunk_authorized(cast(dict[str, Any], item).get("metadata") or {}, scope)
        ]
    return json.dumps(payload)


async def recheck_tool_result(
    event: GatewayEvent, body: dict[str, Any], runtime: Runtime
) -> dict[str, Any]:
    result = dict(body.get("result") or {})
    if result.get("isError"):
        return body
    principal = runtime.verifier.verify_authorization_header(event.authorization, "gateway")
    scope = await runtime.engine.resolve_scope(principal.user_id)
    content: list[dict[str, Any]] = []
    for item in result.get("content", []):
        if item.get("type") != "text":
            raise ValueError(f"cannot verify {item.get('type')!r} content")
        content.append({**item, "text": _authorized_payload(item["text"], scope)})
    result.pop("structuredContent", None)
    return {**body, "result": {**result, "content": content}}


async def intercept_response(raw_event: dict[str, Any], runtime: Runtime) -> dict[str, Any]:
    request_id: object = None
    try:
        event = parse(raw_event)
        request_id = event.request_id
        body = event.response or {}
        if event.method == "tools/list":
            return respond(sanitize_tool_list(body), event.response_status)
        if event.method != "tools/call":
            return respond(body, event.response_status)
        if event.streaming:
            raise PermissionError("streaming tool results cannot be re-checked")
        return respond(await recheck_tool_result(event, body, runtime), event.response_status)
    except Exception as exc:
        logger.warning("response denied: %s: %s", type(exc).__name__, exc)
        return deny(request_id)


def handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    runtime = get_runtime()
    return runtime.run(intercept_response(event, runtime))
