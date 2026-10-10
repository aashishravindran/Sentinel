# Copyright (c) 2026 Aashish Ravindran. All rights reserved.
# Use of this software is governed by the Elastic License 2.0
# found in the LICENSE file.

"""In-memory stand-ins for the identity store and a Bedrock knowledge base.

``StubBedrockKB`` evaluates the same filter JSON Bedrock receives, so tests
exercise the real filter builders rather than a shortcut.
"""

import re
from collections.abc import Mapping, Set
from dataclasses import dataclass, field
from typing import Any

from sentinel_engine.base import Chunk, IdentityConnector, KnowledgeConnector
from sentinel_engine.filters import build_bedrock_filter, build_vector_search_config
from sentinel_engine.ingest.stamp import stamp_metadata, validate_doc_id

PERSONAS: dict[str, set[str]] = {
    "alice": {"finance", "public"},
    "bob": {"engineering", "public"},
    "charlie": {"finance", "engineering", "public"},
    "intern": {"public"},
    "ghost": set(),
    "root": {"sentinel_admin"},
}

SEED_DOCS: list[tuple[str, str, list[str]]] = [
    ("public_overview", "Company overview and holiday calendar open to all staff.", ["public"]),
    ("finance_budget", "2026 budget: $88.9M total opex planned. CANARY-FIN-7731", ["finance"]),
    ("eng_runbook", "On-call runbook: check the Grafana dashboard first.", ["engineering"]),
    ("internal_roadmap", "Roadmap: Series D in Q3, AI pod in Q1.", ["finance", "engineering"]),
]


class DictIdentity(IdentityConnector):
    def __init__(self, tags: Mapping[str, Set[str]] | None = None, *, fail: bool = False):
        self.tags = {user: set(t) for user, t in (tags or PERSONAS).items()}
        self.fail = fail
        self.calls: list[str] = []

    async def get_tags(self, user_id: str) -> set[str]:
        self.calls.append(user_id)
        if self.fail:
            raise ConnectionError("identity store unavailable")
        return set(self.tags.get(user_id, set()))


def evaluate_filter(node: Mapping[str, Any], metadata: Mapping[str, Any]) -> bool:
    """The subset of the Bedrock filter language Sentinel emits."""
    if "equals" in node:
        return metadata.get(node["equals"]["key"]) == node["equals"]["value"]
    if "orAll" in node:
        return any(evaluate_filter(child, metadata) for child in node["orAll"])
    if "andAll" in node:
        return all(evaluate_filter(child, metadata) for child in node["andAll"])
    raise ValueError(f"unsupported filter node: {sorted(node)}")


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


@dataclass
class StoredDoc:
    doc_id: str
    text: str
    metadata: dict[str, Any]


@dataclass
class StubBedrockKB(KnowledgeConnector):
    """Keyword-scored KB that applies Bedrock filter JSON to stamped metadata.

    ``leaky=True`` ignores the filter, to prove the post-filters catch a
    misconfigured store. ``filters`` records every filter the KB received.
    """

    leaky: bool = False
    docs: list[StoredDoc] = field(default_factory=list[StoredDoc])
    filters: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])

    @classmethod
    def seeded(cls, *, leaky: bool = False) -> "StubBedrockKB":
        kb = cls(leaky=leaky)
        for doc_id, text, tags in SEED_DOCS:
            kb.add(doc_id, text, tags)
        return kb

    def add(self, doc_id: str, text: str, tags: list[str], extra: Mapping[str, Any] | None = None):
        metadata = stamp_metadata(tags, {"title": doc_id, **(extra or {})})
        self.docs.append(StoredDoc(validate_doc_id(doc_id), text, metadata))

    def retrieve(
        self, query: str, retrieval_filter: Mapping[str, Any] | None, n: int
    ) -> list[Chunk]:
        self.filters.append(dict(retrieval_filter or {}))
        query_words = _words(query)
        hits: list[Chunk] = []
        for doc in self.docs:
            if not self.leaky and (
                retrieval_filter is None or not evaluate_filter(retrieval_filter, doc.metadata)
            ):
                continue
            overlap = len(query_words & _words(doc.text)) / max(len(query_words), 1)
            hits.append({"text": doc.text, "metadata": dict(doc.metadata), "score": overlap})
        return sorted(hits, key=lambda c: c["score"], reverse=True)[:n]

    @property
    def calls(self) -> int:
        return len(self.filters)

    async def search(self, query: str, tags: Set[str], n_results: int = 5) -> list[Chunk]:
        config = build_vector_search_config(tags, n_results)
        return self.retrieve(query, config["vectorSearchConfiguration"]["filter"], n_results)

    async def ingest(
        self,
        text: str,
        access_tags: list[str],
        doc_id: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        self.add(doc_id, text, access_tags, metadata)


__all__ = [
    "PERSONAS",
    "SEED_DOCS",
    "DictIdentity",
    "StubBedrockKB",
    "build_bedrock_filter",
    "evaluate_filter",
]
