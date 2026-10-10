"""Same personas, same documents, identical decisions from every entry point.

Each case runs against an honest store and a leaky one that ignores filters,
so the post-filters in every adapter are exercised too.
"""

import pytest

from tests.conformance.harness import ADAPTERS, DENIED, Backend
from tests.support.fakes import DictIdentity, StubBedrockKB

pytestmark = pytest.mark.conformance

EVERYTHING = "budget opex roadmap series overview calendar runbook grafana"

# persona -> documents they must receive for a query that matches every document
EXPECTED: dict[str, frozenset[str] | str] = {
    "alice": frozenset({"public_overview", "finance_budget", "internal_roadmap"}),
    "bob": frozenset({"public_overview", "eng_runbook", "internal_roadmap"}),
    "charlie": frozenset({"public_overview", "finance_budget", "eng_runbook", "internal_roadmap"}),
    "intern": frozenset({"public_overview"}),
    "ghost": DENIED,
    "root": DENIED,  # admin rights grant no document access
}


@pytest.mark.parametrize("leaky", [False, True], ids=["honest-kb", "leaky-kb"])
@pytest.mark.parametrize("persona", sorted(EXPECTED))
@pytest.mark.parametrize("adapter", sorted(ADAPTERS))
async def test_every_adapter_reaches_the_same_decision(adapter, persona, leaky):
    backend = Backend(DictIdentity(), StubBedrockKB.seeded(leaky=leaky))
    assert await ADAPTERS[adapter](backend, persona, EVERYTHING) == EXPECTED[persona]


@pytest.mark.parametrize("adapter", sorted(ADAPTERS))
async def test_denials_never_reach_the_knowledge_base(adapter):
    backend = Backend(DictIdentity(), StubBedrockKB.seeded())
    assert await ADAPTERS[adapter](backend, "ghost", EVERYTHING) == DENIED
    assert backend.kb.calls == 0


@pytest.mark.parametrize("adapter", sorted(ADAPTERS))
async def test_revocation_applies_on_the_next_call(adapter):
    backend = Backend(DictIdentity(), StubBedrockKB.seeded())
    assert "finance_budget" in await ADAPTERS[adapter](backend, "alice", EVERYTHING)
    backend.identity.tags["alice"] = {"public"}
    assert await ADAPTERS[adapter](backend, "alice", EVERYTHING) == {"public_overview"}


async def test_all_adapters_push_the_same_filter():
    filters = []
    for adapter in sorted(ADAPTERS):
        backend = Backend(DictIdentity(), StubBedrockKB.seeded())
        await ADAPTERS[adapter](backend, "alice", EVERYTHING)
        filters.append(backend.kb.filters)
    assert all(f == filters[0] for f in filters)
    assert filters[0] == [
        {
            "orAll": [
                {"equals": {"key": "tag_finance", "value": True}},
                {"equals": {"key": "tag_public", "value": True}},
            ]
        }
    ]
