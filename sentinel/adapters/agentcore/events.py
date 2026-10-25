# Copyright (c) 2026 Aashish Ravindran. All rights reserved.
# Use of this software is governed by the Elastic License 2.0
# found in the LICENSE file.

"""AgentCore Gateway interceptor event and response shapes (interceptor version 1.0)."""

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, cast

from sentinel_engine.results import ACCESS_DENIED

VERSION = "1.0"
TOOL_NAME_SEPARATOR = "___"


def _as_dict(value: object) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value) if value else {}
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return cast(dict[str, Any], value)


@dataclass(frozen=True)
class GatewayEvent:
    """One interceptor invocation: the MCP request and, for RESPONSE, the reply."""

    request: dict[str, Any]
    headers: Mapping[str, str] = field(default_factory=dict[str, str])
    response: dict[str, Any] | None = None
    response_status: int = 200
    streaming: bool = False

    @property
    def method(self) -> str:
        return str(self.request.get("method", ""))

    @property
    def request_id(self) -> object:
        return self.request.get("id")

    @property
    def params(self) -> dict[str, Any]:
        return _as_dict(self.request.get("params") or {})

    @property
    def tool_name(self) -> str:
        """The tool's own name, without the ``<target>___`` prefix the gateway adds."""
        return str(self.params.get("name", "")).rpartition(TOOL_NAME_SEPARATOR)[2]

    @property
    def arguments(self) -> dict[str, Any]:
        return _as_dict(self.params.get("arguments") or {})

    @property
    def authorization(self) -> str | None:
        return self.headers.get("authorization")


def parse(event: Mapping[str, Any]) -> GatewayEvent:
    mcp = _as_dict(event.get("mcp"))
    request = _as_dict(mcp.get("gatewayRequest"))
    headers = {str(k).lower(): str(v) for k, v in _as_dict(request.get("headers") or {}).items()}
    raw_response = mcp.get("gatewayResponse")
    response = _as_dict(raw_response) if raw_response is not None else None
    response_body = response.get("body") if response else None
    return GatewayEvent(
        request=_as_dict(request.get("body")),
        headers=headers,
        # Notifications are answered with 202 and no body; keep that as "no response body".
        response=_as_dict(response_body) if response_body not in (None, "") else None,
        response_status=int(response.get("statusCode", 200)) if response else 200,
        streaming=bool(response.get("isStreamingResponse")) if response else False,
    )


def forward_request(body: Mapping[str, Any]) -> dict[str, Any]:
    """REQUEST interceptor: let the (possibly rewritten) request continue to the target."""
    return {
        "interceptorOutputVersion": VERSION,
        "mcp": {"transformedGatewayRequest": {"body": dict(body)}},
    }


def respond(body: Mapping[str, Any], status: int = 200) -> dict[str, Any]:
    """Reply to the caller. From a REQUEST interceptor this short-circuits the target."""
    return {
        "interceptorOutputVersion": VERSION,
        "mcp": {"transformedGatewayResponse": {"statusCode": status, "body": dict(body)}},
    }


def deny(request_id: object) -> dict[str, Any]:
    """A generic denial. Reasons are logged, never returned to the model."""
    return respond(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"isError": True, "content": [{"type": "text", "text": ACCESS_DENIED}]},
        }
    )
