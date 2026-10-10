# Copyright (c) 2026 Aashish Ravindran. All rights reserved.
# Use of this software is governed by the Elastic License 2.0
# found in the LICENSE file.

"""Sentinel as an MCP server.

No tool accepts a user ID. The caller is resolved from the transport on every
call, permissions are resolved live, and anything unexpected is a denial.
"""

import io
import logging
import os
from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field
from pypdf import PdfReader
from sentinel_engine.engine import SentinelEngine
from sentinel_engine.errors import AccessDeniedError
from sentinel_engine.factory import build_engine_from_env
from sentinel_engine.principal import Principal
from sentinel_engine.results import ACCESS_DENIED, filter_relevant, format_results

from sentinel.adapters.mcp.identity import build_auth, resolve_principal
from sentinel.adapters.mcp.settings import ServerSettings
from sentinel.adapters.mcp.uploads import decode_inline_pdf, read_pdf_from_ingest_dir

logger = logging.getLogger("sentinel.mcp")

MAX_RESULTS = 20

CONFIG_KEYS = (
    "SENTINEL_TRANSPORT",
    "SENTINEL_IDENTITY_STORE",
    "SENTINEL_KNOWLEDGE_STORE",
    "SENTINEL_INGEST_DIR",
    "SENTINEL_OIDC_ISSUER",
    "SENTINEL_OIDC_JWKS_URI",
    "SENTINEL_OIDC_AUDIENCE",
    "SENTINEL_OIDC_ALLOWED_CLIENTS",
    "SQLITE_DB_PATH",
    "DDB_TABLE_NAME",
    "CHROMA_PATH",
    "CHROMA_COLLECTION",
    "BEDROCK_KB_ID",
    "BEDROCK_S3_BUCKET",
    "BEDROCK_S3_PREFIX",
    "BEDROCK_DS_ID",
    "BEDROCK_SEARCH_TYPE",
    "BEDROCK_RERANKING",
    "AWS_REGION",
    "SPICEDB_ENDPOINT",
    "SPICEDB_TLS",
    "SPICEDB_TIMEOUT_S",
    "IAM_PRINCIPAL_TYPE",
    "IAM_TAG_FORMAT",
    "MIN_RELEVANCE_SCORE",
)
SECRET_KEYS = ("SPICEDB_TOKEN",)


def create_server(engine: SentinelEngine, settings: ServerSettings) -> FastMCP:
    auth = build_auth(settings.oidc) if settings.oidc else None
    mcp = FastMCP("sentinel-rag", auth=auth)

    async def require_admin() -> Principal:
        principal = resolve_principal(settings)
        if not await engine.is_admin(principal):
            logger.warning("admin tool denied for user=%s", principal.user_id)
            raise AccessDeniedError("admin rights required")
        return principal

    @mcp.tool
    async def secure_search(
        query: str,
        n_results: Annotated[int, Field(ge=1, le=MAX_RESULTS)] = 5,
    ) -> str:
        """Search the knowledge base as the signed-in user.

        Only documents the user may read are searched. The user is taken from the
        connection, not from arguments.
        """
        try:
            principal = resolve_principal(settings)
            chunks = await engine.secure_search(query, principal, n_results)
        except AccessDeniedError as exc:
            logger.info("secure_search denied: %s", exc)
            return ACCESS_DENIED
        relevant = filter_relevant(chunks, settings.min_relevance_score)
        logger.info(
            "secure_search user=%s retrieved=%d relevant=%d",
            principal.user_id,
            len(chunks),
            len(relevant),
        )
        return format_results(relevant)

    @mcp.tool
    async def what_can_i_access() -> str:
        """List the access tags the signed-in user holds right now.

        Informational only: use it to explain empty search results. Access is
        enforced on every search regardless of what this returns.
        """
        try:
            scope = await engine.resolve_scope(resolve_principal(settings).user_id)
        except AccessDeniedError:
            return "You currently have no access to any documents."
        return f"You can read documents tagged: {', '.join(sorted(scope))}."

    @mcp.tool
    async def ingest_document(
        text: str, access_tags: list[str], doc_id: str, title: str = ""
    ) -> str:
        """Admin only. Add a document readable by holders of any of access_tags."""
        try:
            admin = await require_admin()
            await engine.ingest(text, access_tags, doc_id, {"title": title} if title else None)
        except AccessDeniedError:
            return ACCESS_DENIED
        except ValueError as exc:
            return f"Error: {exc}"
        logger.info("ingest_document doc=%s tags=%s by=%s", doc_id, access_tags, admin.user_id)
        return f"Document '{doc_id}' ingested."

    @mcp.tool
    async def ingest_pdf(
        access_tags: list[str],
        doc_id: str,
        pdf_path: str = "",
        pdf_base64: str = "",
        title: str = "",
        metadata: dict[str, str] | None = None,
    ) -> str:
        """Admin only. Add a PDF, one chunk per page, readable by holders of any of access_tags.

        Provide exactly one of:
          pdf_path:   path relative to the server's SENTINEL_INGEST_DIR.
          pdf_base64: base64 PDF bytes, up to 1 MB.
        """
        try:
            admin = await require_admin()
            if bool(pdf_path) == bool(pdf_base64):
                raise ValueError("provide exactly one of pdf_path or pdf_base64")
            pdf_bytes = (
                read_pdf_from_ingest_dir(pdf_path, settings.ingest_dir)
                if pdf_path
                else decode_inline_pdf(pdf_base64)
            )
            pages = PdfReader(io.BytesIO(pdf_bytes)).pages
            base_meta = {**(metadata or {}), "title": title or doc_id}
            ingested = 0
            for n, page in enumerate(pages, 1):
                text = (page.extract_text() or "").strip()
                if not text:
                    continue
                page_meta = {**base_meta, "page": n, "total_pages": len(pages)}
                await engine.ingest(text, access_tags, f"{doc_id}_page_{n}", page_meta)
                ingested += 1
        except AccessDeniedError:
            return ACCESS_DENIED
        except ValueError as exc:
            return f"Error: {exc}"
        logger.info("ingest_pdf doc=%s pages=%d by=%s", doc_id, ingested, admin.user_id)
        return f"PDF '{doc_id}' ingested: {ingested} pages."

    @mcp.tool
    async def list_user_relationships(user_id: str) -> str:
        """Admin only. Audit a user's SpiceDB relationships."""
        try:
            await require_admin()
        except AccessDeniedError:
            return ACCESS_DENIED
        read_relationships = getattr(engine.identity, "read_relationships", None)
        if read_relationships is None:
            return "Error: relationship auditing requires SENTINEL_IDENTITY_STORE=spicedb."
        rels = await read_relationships(user_id)
        if not rels:
            return f"No relationships found for user '{user_id}'."
        lines = [f"Relationships for user '{user_id}':"]
        for rel in sorted(rels, key=lambda r: r["resource_id"]):
            lines.append(f"  {rel['resource_type']}:{rel['resource_id']}  {rel['relation']}")
        return "\n".join(lines)

    @mcp.tool
    async def check_config() -> str:
        """Admin only. Show which backends this server is running with."""
        try:
            await require_admin()
        except AccessDeniedError:
            return ACCESS_DENIED
        lines = [f"{key}={os.environ.get(key, 'NOT_SET')}" for key in CONFIG_KEYS]
        lines += [f"{key}={'***' if os.environ.get(key) else 'NOT_SET'}" for key in SECRET_KEYS]
        return "\n".join(lines)

    return mcp


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = ServerSettings.from_env()
    mcp = create_server(build_engine_from_env(), settings)
    if settings.transport == "http":
        mcp.run(transport="http", host=settings.host, port=settings.port)
    else:
        mcp.run()
