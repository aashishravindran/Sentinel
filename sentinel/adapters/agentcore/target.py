# Copyright (c) 2026 Aashish Ravindran. All rights reserved.
# Use of this software is governed by the Elastic License 2.0
# found in the LICENSE file.

"""Lambda target exposing ``secure_search`` and ``what_can_i_access`` behind AgentCore Gateway.

Used with any knowledge base the native connector cannot reach (for example a
standard, non-managed Bedrock KB). The caller comes from the principal
envelope the request interceptor sealed; a call without a valid envelope,
including a direct invocation, is denied.
"""

import logging
from collections.abc import Mapping
from typing import Any, cast

from sentinel_engine.errors import AccessDeniedError
from sentinel_engine.principal import Principal
from sentinel_engine.results import ACCESS_DENIED, filter_relevant

from sentinel.adapters.agentcore.envelope import ENVELOPE_ARGUMENT, open_envelope
from sentinel.adapters.agentcore.events import TOOL_NAME_SEPARATOR
from sentinel.adapters.agentcore.runtime import Runtime, get_runtime

logger = logging.getLogger("sentinel.agentcore.target")


async def run_tool(tool_name: str, arguments: dict[str, Any], runtime: Runtime) -> dict[str, Any]:
    """Run one gateway tool call for the caller sealed in its principal envelope."""
    tool = tool_name.rpartition(TOOL_NAME_SEPARATOR)[2]
    try:
        signed = {k: v for k, v in arguments.items() if k != ENVELOPE_ARGUMENT}
        user_id = open_envelope(arguments.get(ENVELOPE_ARGUMENT), signed, runtime.envelope_key)
        if tool == "what_can_i_access":
            scope = await runtime.engine.resolve_scope(user_id)
            return {"user": user_id, "tags": sorted(scope)}
        if tool != "secure_search":
            raise AccessDeniedError(f"unknown tool {tool_name!r}")
        chunks = await runtime.engine.secure_search(
            str(signed["query"]), Principal(user_id, "gateway"), int(signed["n_results"])
        )
    except (AccessDeniedError, KeyError, TypeError, ValueError) as exc:
        logger.warning("target denied: %s: %s", type(exc).__name__, exc)
        return {"results": [], "message": ACCESS_DENIED}
    relevant = filter_relevant(chunks, runtime.min_relevance_score)
    return {
        "results": [
            {"text": c["text"], "score": c["score"], "metadata": c["metadata"]} for c in relevant
        ]
    }


def _tool_name(context: Any) -> str:
    client_context = getattr(context, "client_context", None)
    custom = cast(Mapping[str, Any], getattr(client_context, "custom", None) or {})
    return str(custom.get("bedrockAgentCoreToolName", ""))


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    runtime = get_runtime()
    return runtime.run(run_tool(_tool_name(context), event, runtime))
