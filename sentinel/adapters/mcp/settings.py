# Copyright (c) 2026 Aashish Ravindran. All rights reserved.
# Use of this software is governed by the Elastic License 2.0
# found in the LICENSE file.

"""How the MCP server learns who its caller is, fixed at startup.

stdio: the user is whoever launched the server (``SENTINEL_STDIO_USER``).
http:  every request carries a bearer token from the configured OIDC issuer.

Missing settings stop the server from starting. There is no default user and
no unauthenticated HTTP mode.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sentinel_engine.errors import ConfigError
from sentinel_engine.oidc import OIDCSettings
from sentinel_engine.principal import validate_subject
from sentinel_engine.results import DEFAULT_MIN_RELEVANCE_SCORE

Transport = Literal["stdio", "http"]


@dataclass(frozen=True)
class ServerSettings:
    transport: Transport
    stdio_user: str | None = None
    oidc: OIDCSettings | None = None
    host: str = "127.0.0.1"
    port: int = 8000
    ingest_dir: Path | None = None
    min_relevance_score: float = DEFAULT_MIN_RELEVANCE_SCORE

    def __post_init__(self) -> None:
        if self.transport == "stdio":
            if self.stdio_user is None:
                raise ConfigError("SENTINEL_STDIO_USER is required for the stdio transport")
            validate_subject(self.stdio_user)
        elif self.oidc is None:
            raise ConfigError("SENTINEL_OIDC_* settings are required for the http transport")

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> "ServerSettings":
        transport = env.get("SENTINEL_TRANSPORT", "stdio")
        if transport not in ("stdio", "http"):
            raise ConfigError(f"SENTINEL_TRANSPORT must be stdio or http, got {transport!r}")
        ingest_dir = env.get("SENTINEL_INGEST_DIR")
        return cls(
            transport=transport,
            stdio_user=env.get("SENTINEL_STDIO_USER") or None,
            oidc=OIDCSettings.from_env(env) if transport == "http" else None,
            host=env.get("SENTINEL_HTTP_HOST", "127.0.0.1"),
            port=int(env.get("SENTINEL_HTTP_PORT", "8000")),
            ingest_dir=Path(ingest_dir) if ingest_dir else None,
            min_relevance_score=float(
                env.get("MIN_RELEVANCE_SCORE", str(DEFAULT_MIN_RELEVANCE_SCORE))
            ),
        )
