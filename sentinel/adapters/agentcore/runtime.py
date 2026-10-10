# Copyright (c) 2026 Aashish Ravindran. All rights reserved.
# Use of this software is governed by the Elastic License 2.0
# found in the LICENSE file.

"""Per-process state for the Lambda handlers, built once at cold start."""

import asyncio
import os
from collections.abc import Coroutine, Mapping, Set
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, TypeVar

from sentinel_engine.base import Chunk, KnowledgeConnector, MetadataValue
from sentinel_engine.engine import SentinelEngine
from sentinel_engine.errors import ConfigError
from sentinel_engine.factory import build_identity_from_env, build_knowledge_from_env
from sentinel_engine.oidc import OIDCSettings, TokenVerifier
from sentinel_engine.results import DEFAULT_MIN_RELEVANCE_SCORE

if TYPE_CHECKING:
    from mypy_boto3_secretsmanager import SecretsManagerClient

T = TypeVar("T")


class NoKnowledgeStore(KnowledgeConnector):
    """Interceptors decide access; they never read documents themselves."""

    async def search(self, query: str, tags: Set[str], n_results: int = 5) -> list[Chunk]:
        raise RuntimeError("this function has no knowledge store")

    async def ingest(
        self,
        text: str,
        access_tags: list[str],
        doc_id: str,
        metadata: Mapping[str, MetadataValue] | None = None,
    ) -> None:
        raise RuntimeError("this function has no knowledge store")


def _envelope_key(env: Mapping[str, str]) -> bytes:
    if key := env.get("SENTINEL_ENVELOPE_KEY"):
        return key.encode()
    if arn := env.get("SENTINEL_ENVELOPE_SECRET_ARN"):
        import boto3

        secrets: SecretsManagerClient = boto3.client("secretsmanager")  # pyright: ignore[reportUnknownMemberType]
        return secrets.get_secret_value(SecretId=arn)["SecretString"].encode()
    raise ConfigError("set SENTINEL_ENVELOPE_SECRET_ARN (or SENTINEL_ENVELOPE_KEY for tests)")


@dataclass
class Runtime:
    engine: SentinelEngine
    verifier: TokenVerifier
    envelope_key: bytes
    min_relevance_score: float = DEFAULT_MIN_RELEVANCE_SCORE
    _loop: asyncio.AbstractEventLoop | None = field(default=None, init=False, repr=False)

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> "Runtime":
        knowledge = (
            build_knowledge_from_env(env)
            if env.get("SENTINEL_KNOWLEDGE_STORE")
            else NoKnowledgeStore()
        )
        return cls(
            engine=SentinelEngine(build_identity_from_env(env), knowledge),
            verifier=TokenVerifier(OIDCSettings.from_env(env)),
            envelope_key=_envelope_key(env),
            min_relevance_score=float(
                env.get("MIN_RELEVANCE_SCORE", str(DEFAULT_MIN_RELEVANCE_SCORE))
            ),
        )

    def run(self, coro: Coroutine[Any, Any, T]) -> T:
        """Run on one long-lived loop so warm invocations reuse connections."""
        if self._loop is None:
            self._loop = asyncio.new_event_loop()
        return self._loop.run_until_complete(coro)


_runtime: Runtime | None = None


def get_runtime() -> Runtime:
    global _runtime
    if _runtime is None:
        _runtime = Runtime.from_env()
    return _runtime
