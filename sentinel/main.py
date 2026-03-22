# Copyright (c) 2026 Aashish Ravindran. All rights reserved.
# Use of this software is governed by the Elastic License 2.0
# found in the LICENSE file.

import base64
import io
import os

from fastmcp import FastMCP, Context

# Minimum cosine similarity for a result to be considered relevant.
# Below this threshold the query topic is not covered by docs the user can access,
# so we return a clear "no access" message rather than feeding the LLM low-signal
# content that leads to hallucination.
MIN_RELEVANCE_SCORE = float(os.environ.get("MIN_RELEVANCE_SCORE", "0.25"))

from sentinel.core.engine import SentinelEngine, AccessDeniedError
from sentinel.connectors.identity.sqlite import SQLiteIdentityConnector
from sentinel.connectors.knowledge.chroma import ChromaKnowledgeConnector


def _build_engine() -> SentinelEngine:
    identity_store = os.environ.get("SENTINEL_IDENTITY_STORE", "NOT_SET")
    knowledge_store = os.environ.get("SENTINEL_KNOWLEDGE_STORE", "NOT_SET")

    if identity_store == "sqlite":
        db_path = os.environ.get("SQLITE_DB_PATH", "./data/permissions.db")
        identity = SQLiteIdentityConnector(db_path)
    elif identity_store == "dynamodb":
        from sentinel.connectors.identity.ddb import DynamoDBIdentityConnector
        table_name = os.environ["DDB_TABLE_NAME"]
        region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
        identity = DynamoDBIdentityConnector(table_name, region)
    else:
        raise ValueError(f"Unsupported identity store: '{identity_store}'")

    if knowledge_store == "chroma":
        chroma_path = os.environ.get("CHROMA_PATH", "./data/chroma")
        collection = os.environ.get("CHROMA_COLLECTION", "sentinel")
        embedding_model = os.environ.get("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
        knowledge = ChromaKnowledgeConnector(chroma_path, collection, embedding_model)
    elif knowledge_store == "bedrock":
        from sentinel.connectors.knowledge.bedrock import BedrockKnowledgeConnector
        kb_id = os.environ["BEDROCK_KB_ID"]
        s3_bucket = os.environ["BEDROCK_S3_BUCKET"]
        s3_prefix = os.environ.get("BEDROCK_S3_PREFIX", "documents/")
        data_source_id = os.environ.get("BEDROCK_DS_ID", "")
        region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
        search_type = os.environ.get("BEDROCK_SEARCH_TYPE", "HYBRID")
        reranking = os.environ.get("BEDROCK_RERANKING", "false").lower() == "true"
        rerank_model_arn = os.environ.get("BEDROCK_RERANK_MODEL_ARN", "")
        rerank_oversample = int(os.environ.get("BEDROCK_RERANK_OVERSAMPLE", "3"))
        knowledge = BedrockKnowledgeConnector(
            kb_id, s3_bucket, s3_prefix, data_source_id, region,
            search_type=search_type,
            reranking=reranking,
            rerank_model_arn=rerank_model_arn,
            rerank_oversample=rerank_oversample,
        )
    else:
        raise ValueError(f"Unsupported knowledge store: '{knowledge_store}'")

    return SentinelEngine(identity, knowledge)


mcp = FastMCP("sentinel-rag")
engine = _build_engine()


@mcp.tool()
async def secure_search(query: str, user_id: str, ctx: Context, n_results: int = 5) -> str:
    """
    Search the knowledge base and return only documents the user is authorized to see.
    Results are filtered by the user's permission tags — users without any tags are denied.
    """
    ks = os.environ.get("SENTINEL_KNOWLEDGE_STORE", "NOT_SET")
    is_store = os.environ.get("SENTINEL_IDENTITY_STORE", "NOT_SET")
    await ctx.info(f"secure_search | user={user_id} query={query!r} n={n_results} knowledge={ks} identity={is_store}")

    try:
        results = await engine.secure_search(query, user_id, n_results)
    except AccessDeniedError as e:
        await ctx.warning(f"access denied | user={user_id} reason={e}")
        return f"Access Denied: {e}"

    relevant = [r for r in results if r["score"] >= MIN_RELEVANCE_SCORE]
    await ctx.info(f"secure_search | {len(results)} retrieved, {len(relevant)} above threshold={MIN_RELEVANCE_SCORE}")

    if not relevant:
        return (
            "You do not have access to documents relevant to this query. "
            "The information may exist but is not within your permitted scope."
        )

    formatted = []
    for i, r in enumerate(relevant, 1):
        title = r["metadata"].get("title", "")
        header = f"[{i}] {title}" if title else f"[{i}]"
        formatted.append(f"{header} (score: {r['score']})\n{r['text']}")

    return "\n\n---\n\n".join(formatted)


@mcp.tool()
async def ingest_document(
    text: str,
    access_tags: list[str],
    doc_id: str,
    ctx: Context,
    title: str = "",
) -> str:
    """
    Ingest a document into the knowledge base with the specified access tags.
    Only users whose permission tags intersect with access_tags will be able to retrieve it.
    """
    ks = os.environ.get("SENTINEL_KNOWLEDGE_STORE", "NOT_SET")
    is_store = os.environ.get("SENTINEL_IDENTITY_STORE", "NOT_SET")
    bucket = os.environ.get("BEDROCK_S3_BUCKET", "NOT_SET")
    profile = os.environ.get("AWS_PROFILE", "NOT_SET")
    await ctx.info(f"ingest_document | doc={doc_id} tags={access_tags} knowledge={ks} identity={is_store} bucket={bucket} profile={profile}")

    if not access_tags:
        return "Error: access_tags cannot be empty. Every document must have at least one tag."

    metadata = {"title": title} if title else {}
    await engine.ingest(text, access_tags, doc_id, metadata)
    return f"Document '{doc_id}' ingested successfully."


@mcp.tool()
async def ingest_pdf(
    access_tags: list[str],
    doc_id: str,
    ctx: Context,
    pdf_path: str = "",
    pdf_base64: str = "",
    title: str = "",
    metadata: dict | None = None,
) -> str:
    """
    Ingest a PDF into the knowledge base with the specified access tags.

    The PDF is extracted page-by-page; each page is stored as a separate chunk
    with ID '{doc_id}_page_{n}'. Only users whose permission tags intersect
    with access_tags will be able to retrieve any chunk.

    Provide exactly one of:
      pdf_path:   absolute path to the PDF file on the server's filesystem.
                  Preferred — avoids MCP message size limits entirely.
      pdf_base64: base64-encoded PDF bytes. Only suitable for very small PDFs
                  (<1MB) due to MCP message size constraints.

    access_tags: list of tags controlling who can access this document.
    doc_id:      unique identifier for this document (used as chunk ID prefix).
    title:       optional human-readable title stored in chunk metadata.
    metadata:    optional dict of additional metadata stored on every page chunk
                 e.g. {"author": "Alice", "department": "finance", "source": "gdrive://..."}
                 Values must be strings. Page-level keys (page, total_pages) are
                 added automatically and will override any keys of the same name.
    """
    ks = os.environ.get("SENTINEL_KNOWLEDGE_STORE", "NOT_SET")
    is_store = os.environ.get("SENTINEL_IDENTITY_STORE", "NOT_SET")
    await ctx.info(f"ingest_pdf | doc={doc_id} tags={access_tags} source={'path' if pdf_path else 'base64'} knowledge={ks} identity={is_store}")

    if not access_tags:
        return "Error: access_tags cannot be empty. Every document must have at least one tag."

    if not pdf_path and not pdf_base64:
        return "Error: provide either pdf_path or pdf_base64."

    try:
        from pypdf import PdfReader
    except ImportError:
        return (
            "Error: pypdf is not installed. "
            "Add it to your dependencies: uv add pypdf"
        )

    if pdf_path:
        try:
            pdf_bytes = open(pdf_path, "rb").read()
        except OSError as e:
            return f"Error reading pdf_path: {e}"
    else:
        try:
            pdf_bytes = base64.b64decode(pdf_base64)
        except Exception:
            return "Error: pdf_base64 is not valid base64-encoded content."

    reader = PdfReader(io.BytesIO(pdf_bytes))
    if len(reader.pages) == 0:
        return "Error: PDF contains no pages."

    base_meta = {k: str(v) for k, v in (metadata or {}).items()}
    base_meta["title"] = title or doc_id

    ingested = 0
    errors = []
    for n, page in enumerate(reader.pages, 1):
        text = (page.extract_text() or "").strip()
        if not text:
            continue  # skip blank pages

        chunk_id = f"{doc_id}_page_{n}"
        chunk_meta = {**base_meta, "page": n, "total_pages": len(reader.pages)}
        try:
            await engine.ingest(text, access_tags, chunk_id, chunk_meta)
            ingested += 1
        except Exception as e:
            errors.append(f"page {n}: {e}")

    await ctx.info(f"ingest_pdf | doc={doc_id} pages_ok={ingested} pages_failed={len(errors)}")

    if errors:
        return (
            f"PDF '{doc_id}' partially ingested: {ingested} pages succeeded. "
            f"Errors: {'; '.join(errors)}"
        )
    return f"PDF '{doc_id}' ingested successfully: {ingested} pages with tags {access_tags}."


@mcp.tool()
async def check_config(ctx: Context) -> str:
    """
    Return the exact runtime values of all Sentinel environment variables.
    Use this to audit which backend is active and verify configuration.
    """
    vars = {
        "SENTINEL_IDENTITY_STORE": os.environ.get("SENTINEL_IDENTITY_STORE", "NOT_SET"),
        "SENTINEL_KNOWLEDGE_STORE": os.environ.get("SENTINEL_KNOWLEDGE_STORE", "NOT_SET"),
        "SQLITE_DB_PATH": os.environ.get("SQLITE_DB_PATH", "NOT_SET"),
        "DDB_TABLE_NAME": os.environ.get("DDB_TABLE_NAME", "NOT_SET"),
        "CHROMA_PATH": os.environ.get("CHROMA_PATH", "NOT_SET"),
        "CHROMA_COLLECTION": os.environ.get("CHROMA_COLLECTION", "NOT_SET"),
        "BEDROCK_KB_ID": os.environ.get("BEDROCK_KB_ID", "NOT_SET"),
        "BEDROCK_S3_BUCKET": os.environ.get("BEDROCK_S3_BUCKET", "NOT_SET"),
        "BEDROCK_S3_PREFIX": os.environ.get("BEDROCK_S3_PREFIX", "NOT_SET"),
        "BEDROCK_DS_ID": os.environ.get("BEDROCK_DS_ID", "NOT_SET"),
        "BEDROCK_SEARCH_TYPE": os.environ.get("BEDROCK_SEARCH_TYPE", "NOT_SET"),
        "BEDROCK_RERANKING": os.environ.get("BEDROCK_RERANKING", "NOT_SET"),
        "BEDROCK_RERANK_MODEL_ARN": os.environ.get("BEDROCK_RERANK_MODEL_ARN", "NOT_SET"),
        "BEDROCK_RERANK_OVERSAMPLE": os.environ.get("BEDROCK_RERANK_OVERSAMPLE", "NOT_SET"),
        "AWS_REGION": os.environ.get("AWS_REGION", "NOT_SET"),
        "AWS_DEFAULT_REGION": os.environ.get("AWS_DEFAULT_REGION", "NOT_SET"),
        "AWS_PROFILE": os.environ.get("AWS_PROFILE", "NOT_SET"),
        "MIN_RELEVANCE_SCORE": os.environ.get("MIN_RELEVANCE_SCORE", "NOT_SET"),
    }
    await ctx.info("check_config called")
    lines = [f"{k}={v}" for k, v in vars.items()]
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run()
