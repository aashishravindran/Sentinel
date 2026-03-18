import asyncio
from typing import List, Dict

import chromadb
from sentence_transformers import SentenceTransformer

from sentinel.core.base import KnowledgeConnector


class ChromaKnowledgeConnector(KnowledgeConnector):
    """
    ChromaDB-backed knowledge store with local sentence-transformer embeddings.

    Tag storage strategy: each access tag is stored as a boolean metadata field
    `tag_{name}: True` alongside a human-readable `access_tags` string.
    This lets ChromaDB's native `$or` filter do the intersection check efficiently.

    Example stored metadata:
        {"tag_finance": True, "tag_public": True, "access_tags": "finance,public", "title": "..."}
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
        """Build a ChromaDB `where` filter that matches any of the user's tags."""
        tag_conditions = [{f"tag_{tag}": {"$eq": True}} for tag in tags]
        if len(tag_conditions) == 1:
            return tag_conditions[0]
        return {"$or": tag_conditions}

    async def search(self, query: str, tags: set[str], n_results: int = 5) -> List[Dict]:
        embedding = await asyncio.to_thread(self._embed, query)
        where = self._build_where_filter(tags)

        try:
            results = await asyncio.to_thread(
                self._collection.query,
                query_embeddings=[embedding],
                n_results=n_results,
                where=where,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as e:
            # ChromaDB raises if n_results > number of matching documents
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

        return [
            {
                "text": doc,
                "metadata": meta,
                # Cosine distance → similarity score
                "score": round(1 - dist, 4),
            }
            for doc, meta, dist in zip(docs, metas, distances)
        ]

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
