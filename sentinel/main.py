import os

from fastmcp import FastMCP

from sentinel.core.engine import SentinelEngine, AccessDeniedError
from sentinel.connectors.identity.sqlite import SQLiteIdentityConnector
from sentinel.connectors.knowledge.chroma import ChromaKnowledgeConnector


def _build_engine() -> SentinelEngine:
    identity_store = os.environ.get("SENTINEL_IDENTITY_STORE", "sqlite")
    knowledge_store = os.environ.get("SENTINEL_KNOWLEDGE_STORE", "chroma")

    if identity_store == "sqlite":
        db_path = os.environ.get("SQLITE_DB_PATH", "./data/permissions.db")
        identity = SQLiteIdentityConnector(db_path)
    else:
        raise ValueError(f"Unsupported identity store: '{identity_store}'")

    if knowledge_store == "chroma":
        chroma_path = os.environ.get("CHROMA_PATH", "./data/chroma")
        collection = os.environ.get("CHROMA_COLLECTION", "sentinel")
        embedding_model = os.environ.get("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
        knowledge = ChromaKnowledgeConnector(chroma_path, collection, embedding_model)
    else:
        raise ValueError(f"Unsupported knowledge store: '{knowledge_store}'")

    return SentinelEngine(identity, knowledge)


mcp = FastMCP("sentinel-rag")
engine = _build_engine()


@mcp.tool()
async def secure_search(query: str, user_id: str, n_results: int = 5) -> str:
    """
    Search the knowledge base and return only documents the user is authorized to see.
    Results are filtered by the user's permission tags — users without any tags are denied.
    """
    try:
        results = await engine.secure_search(query, user_id, n_results)
    except AccessDeniedError as e:
        return f"Access Denied: {e}"

    if not results:
        return "No results found within your authorized scope."

    formatted = []
    for i, r in enumerate(results, 1):
        title = r["metadata"].get("title", "")
        header = f"[{i}] {title}" if title else f"[{i}]"
        formatted.append(f"{header} (score: {r['score']})\n{r['text']}")

    return "\n\n---\n\n".join(formatted)


@mcp.tool()
async def ingest_document(
    text: str,
    access_tags: list[str],
    doc_id: str,
    title: str = "",
) -> str:
    """
    Ingest a document into the knowledge base with the specified access tags.
    Only users whose permission tags intersect with access_tags will be able to retrieve it.
    """
    if not access_tags:
        return "Error: access_tags cannot be empty. Every document must have at least one tag."

    metadata = {"title": title} if title else {}
    await engine.ingest(text, access_tags, doc_id, metadata)
    return f"Document '{doc_id}' ingested successfully with tags: {access_tags}"


if __name__ == "__main__":
    mcp.run()
