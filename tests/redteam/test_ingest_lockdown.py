"""Only admins write to the knowledge base, and only within tight bounds."""

import base64
from pathlib import Path

import pytest
from fastmcp import Client
from sentinel_engine.engine import SentinelEngine
from sentinel_engine.results import ACCESS_DENIED

from sentinel.adapters.mcp.server import create_server
from sentinel.adapters.mcp.settings import ServerSettings
from tests.support.fakes import DictIdentity, StubBedrockKB
from tests.support.pdf import make_pdf

pytestmark = pytest.mark.redteam

ADMIN_TOOLS = {
    "ingest_document": {"text": "x", "access_tags": ["public"], "doc_id": "planted"},
    "ingest_pdf": {"access_tags": ["public"], "doc_id": "planted", "pdf_base64": "JVBERi0="},
    "check_config": {},
    "list_user_relationships": {"user_id": "charlie"},
}


async def _call(
    user: str,
    tool: str,
    arguments: dict,
    *,
    ingest_dir: Path | None = None,
    identity: DictIdentity | None = None,
    kb: StubBedrockKB | None = None,
) -> str:
    engine = SentinelEngine(identity or DictIdentity(), kb or StubBedrockKB.seeded())
    settings = ServerSettings(
        "stdio", stdio_user=user, ingest_dir=ingest_dir, min_relevance_score=0.0
    )
    async with Client(create_server(engine, settings)) as client:
        result = await client.call_tool(tool, arguments)
    return result.content[0].text


@pytest.mark.parametrize("tool", sorted(ADMIN_TOOLS))
@pytest.mark.parametrize("user", ["intern", "charlie", "ghost"])
async def test_non_admins_cannot_use_admin_tools(tool, user):
    kb = StubBedrockKB.seeded()
    assert await _call(user, tool, ADMIN_TOOLS[tool], kb=kb) == ACCESS_DENIED
    assert len(kb.docs) == 4


@pytest.mark.parametrize("tool", sorted(ADMIN_TOOLS))
async def test_admin_check_fails_closed_when_identity_is_down(tool):
    identity = DictIdentity(fail=True)
    assert await _call("root", tool, ADMIN_TOOLS[tool], identity=identity) == ACCESS_DENIED


async def test_admin_can_ingest_and_tags_are_enforced():
    kb = StubBedrockKB.seeded()
    reply = await _call(
        "root",
        "ingest_document",
        {"text": "Layoff plan CANARY-HR-0042", "access_tags": ["hr"], "doc_id": "hr_plan"},
        kb=kb,
    )
    assert reply == "Document 'hr_plan' ingested."
    leaked = await _call("charlie", "secure_search", {"query": "layoff plan canary"}, kb=kb)
    assert "CANARY-HR-0042" not in leaked


@pytest.mark.parametrize(
    "arguments",
    [
        {"access_tags": ["public"], "doc_id": "../escape"},
        {"access_tags": ["public"], "doc_id": "a/b"},
        {"access_tags": ['finance" OR 1=1'], "doc_id": "x"},
        {"access_tags": ["*"], "doc_id": "x"},
        {"access_tags": [], "doc_id": "x"},
        {"access_tags": ["sentinel_admin"], "doc_id": "x"},
    ],
)
async def test_ingest_rejects_paths_and_bad_tags(arguments):
    kb = StubBedrockKB.seeded()
    reply = await _call("root", "ingest_document", {"text": "x", **arguments}, kb=kb)
    assert reply.startswith("Error:")
    assert len(kb.docs) == 4


@pytest.mark.parametrize("metadata", [{"access_tags": "public"}, {"tag_public": "true"}])
async def test_pdf_metadata_cannot_override_access_tags(metadata):
    pdf = base64.b64encode(make_pdf("Secret salary bands")).decode()
    reply = await _call(
        "root",
        "ingest_pdf",
        {"access_tags": ["finance"], "doc_id": "bands", "pdf_base64": pdf, "metadata": metadata},
    )
    assert reply.startswith("Error:")


@pytest.fixture
def ingest_dir(tmp_path: Path) -> Path:
    inside = tmp_path / "ingest"
    inside.mkdir()
    (inside / "report.pdf").write_bytes(make_pdf("Quarterly report page one", "Page two"))
    (inside / "notes.txt").write_text("not a pdf")
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(make_pdf("Outside the ingest dir"))
    (inside / "link.pdf").symlink_to(outside)
    return inside


async def test_pdf_path_inside_ingest_dir_is_ingested(ingest_dir):
    kb = StubBedrockKB.seeded()
    reply = await _call(
        "root",
        "ingest_pdf",
        {"access_tags": ["finance"], "doc_id": "q_report", "pdf_path": "report.pdf"},
        ingest_dir=ingest_dir,
        kb=kb,
    )
    assert reply == "PDF 'q_report' ingested: 2 pages."
    assert [d.doc_id for d in kb.docs[-2:]] == ["q_report_page_1", "q_report_page_2"]


@pytest.mark.parametrize(
    "pdf_path", ["../outside.pdf", "/etc/passwd", "link.pdf", "notes.txt", "missing.pdf"]
)
async def test_pdf_path_cannot_escape_the_ingest_dir(ingest_dir, pdf_path):
    reply = await _call(
        "root",
        "ingest_pdf",
        {"access_tags": ["public"], "doc_id": "x", "pdf_path": pdf_path},
        ingest_dir=ingest_dir,
    )
    assert reply.startswith("Error:")


async def test_pdf_path_is_disabled_without_an_ingest_dir():
    reply = await _call(
        "root", "ingest_pdf", {"access_tags": ["public"], "doc_id": "x", "pdf_path": "a.pdf"}
    )
    assert "disabled" in reply


async def test_inline_pdf_size_is_capped():
    huge = base64.b64encode(b"%PDF" + b"0" * (1024 * 1024 + 1)).decode()
    reply = await _call(
        "root", "ingest_pdf", {"access_tags": ["public"], "doc_id": "x", "pdf_base64": huge}
    )
    assert "limited" in reply


async def test_check_config_masks_secrets(monkeypatch):
    monkeypatch.setenv("SPICEDB_TOKEN", "super-secret")
    reply = await _call("root", "check_config", {})
    assert "super-secret" not in reply
    assert "SPICEDB_TOKEN=***" in reply
