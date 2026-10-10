from pathlib import Path

import pytest

from sentinel.ingest.documents import ingest_documents, load_tagged_documents
from sentinel.ingest.identity_sync import plan_sync
from tests.support.fakes import StubBedrockKB

SEED = Path(__file__).parent.parent / "docs" / "seed"


def test_seed_documents_all_declare_access_tags():
    docs = {d.doc_id: d.access_tags for d in load_tagged_documents(SEED)}
    assert docs["finance_budget_2026"] == ["finance"]
    assert docs["internal_2026_roadmap"] == ["finance", "engineering"]
    assert len(docs) == 7


def test_untagged_document_is_rejected(tmp_path):
    (tmp_path / "orphan.md").write_text("# No tags here")
    with pytest.raises(ValueError, match=r"orphan\.md"):
        load_tagged_documents(tmp_path)


async def test_seed_documents_ingest_with_stamped_tags():
    kb = StubBedrockKB()
    await ingest_documents(load_tagged_documents(SEED), kb)
    stamped = {d.doc_id: d.metadata["access_tags"] for d in kb.docs}
    assert stamped["internal_2026_roadmap"] == "engineering,finance"


def test_sync_plan_writes_only_changes():
    plan = plan_sync(
        {"a": {"public"}, "b": {"finance"}}, {"a": {"public"}, "b": {"hr"}, "c": {"x"}}
    )
    assert plan.put == {"b": frozenset({"hr"}), "c": frozenset({"x"})}
    assert plan.delete == frozenset()


def test_sync_plan_prunes_only_when_asked():
    assert plan_sync({"gone": {"public"}}, {}, prune=True).delete == {"gone"}


@pytest.mark.parametrize("desired", [{"*": {"public"}}, {"a": set()}, {"a": {"bad tag"}}])
def test_sync_plan_rejects_bad_entries(desired):
    with pytest.raises(ValueError):
        plan_sync({}, desired)
