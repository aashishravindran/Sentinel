from abc import ABC, abstractmethod
from typing import List, Dict


class IdentityConnector(ABC):
    @abstractmethod
    async def get_tags(self, user_id: str) -> set[str]:
        """Fetch permission tags for a user from the identity store."""


class KnowledgeConnector(ABC):
    @abstractmethod
    async def search(self, query: str, tags: set[str], n_results: int = 5) -> List[Dict]:
        """Execute a tag-filtered vector search. Only returns documents whose
        access_tags intersect with the provided tags."""

    @abstractmethod
    async def ingest(
        self,
        text: str,
        access_tags: list[str],
        doc_id: str,
        metadata: dict | None = None,
    ) -> None:
        """Store a document with access_tags metadata attached."""
