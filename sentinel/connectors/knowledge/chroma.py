import asyncio
from typing import List, Dict

import chromadb
from sentence_transformers import SentenceTransformer

from sentinel.core.base import KnowledgeConnector


class ChromaKnowledgeConnector(KnowledgeConnector):
    """
    ChromaDB-backed knowledge store with local sentence-transformer embeddings.

    Access control uses a two-stage filter:
      1. Pre-filter (ChromaDB $or): candidate retrieval — keeps docs that share
         at least one tag with the user, cutting the result set down cheaply.
      2. Post-filter (AND semantics): drops any doc whose full access_tags set
         is not a subset of the user's tags. A document tagged [finance, engineering]
         requires the user to hold BOTH tags, not just one.

    Tag storage: each access tag is a boolean metadata field `tag_{name}: True`,
    plus a human-readable `access_tags` comma-separated string for post-filtering.

    Example stored metadata:
        {"tag_finance": True, "tag_engineering": True, "access_tags": "finance,engineering"}
    """

    def __init__(self, path: str, collection_name: str, embedding_model: str):
        self._model = SentenceTransformer(embedding_model)
        self._client = chromadb.PersistentClient(path=path)
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def _embed(self, text: str) -> list[float]:
        return self._model.encode(text).tolist()

    def _build_where_filter(self, tags: set[str]) -> dict:
        """OR pre-filter: retrieve docs that share at least one tag with the user."""
        tag_conditions = [{f"tag_{tag}": {"$eq": True}} for tag in tags]
        if len(tag_conditions) == 1:
            return tag_conditions[0]
        return {"$or": tag_conditions}

    def _authorized(self, meta: dict, user_tags: set[str]) -> bool:
        """AND post-filter: all of the document's tags must be present in user_tags."""
        raw = meta.get("access_tags", "")
        doc_tags = {t.strip() for t in raw.split(",") if t.strip()}
        return doc_tags.issubset(user_tags)

    async def search(self, query: str, tags: set[str], n_results: int = 5) -> List[Dict]:
        embedding = await asyncio.to_thread(self._embed, query)
        where = self._build_where_filter(tags)

        # Fetch extra candidates to account for AND post-filter dropping some
        fetch = n_results * 3
        try:
            results = await asyncio.to_thread(
                self._collection.query,
                query_embeddings=[embedding],
                n_results=fetch,
                where=where,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as e:
            if "Number of requested results" in str(e):
                results = await asyncio.to_thread(
                    self._collection.query,
                    query_embeddings=[embedding],
                    n_results=1,
                    where=where,
                    include=["documents", "metadatas", "distances"],
                )
            else:
                raise

        docs = results["documents"][0]
        metas = results["metadatas"][0]
        distances = results["distances"][0]

        authorized = [
            {
                "text": doc,
                "metadata": meta,
                "score": round(1 - dist, 4),
            }
            for doc, meta, dist in zip(docs, metas, distances)
            if self._authorized(meta, tags)
        ]

        return authorized[:n_results]

    async def ingest(
        self,
        text: str,
        access_tags: list[str],
        doc_id: str,
        metadata: dict | None = None,
    ) -> None:
        embedding = await asyncio.to_thread(self._embed, text)

        meta = dict(metadata or {})
        for tag in access_tags:
            meta[f"tag_{tag}"] = True
        meta["access_tags"] = ",".join(access_tags)

        await asyncio.to_thread(
            self._collection.upsert,
            ids=[doc_id],
            embeddings=[embedding],
            documents=[text],
            metadatas=[meta],
        )
