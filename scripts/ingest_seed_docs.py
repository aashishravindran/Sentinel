#!/usr/bin/env python3
"""
Ingest seed documents into ChromaDB.

Reads every .md file in docs/seed/, extracts its access_tags from the
trailing HTML comment `<!-- access_tags: tag1,tag2 -->`, and ingests it.

Usage:
    python scripts/ingest_seed_docs.py
"""
import asyncio
import os
import re
from pathlib import Path

from sentinel.connectors.knowledge.chroma import ChromaKnowledgeConnector

TAG_PATTERN = re.compile(r"<!--\s*access_tags:\s*([^-]+?)\s*-->")
SEED_DIR = Path(__file__).parent.parent / "docs" / "seed"


def extract_tags(content: str) -> list[str]:
    match = TAG_PATTERN.search(content)
    if not match:
        raise ValueError("No <!-- access_tags: ... --> comment found in document.")
    return [t.strip() for t in match.group(1).split(",") if t.strip()]


async def ingest_all() -> None:
    chroma_path = os.environ.get("CHROMA_PATH", "./data/chroma")
    collection = os.environ.get("CHROMA_COLLECTION", "sentinel")
    embedding_model = os.environ.get("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

    connector = ChromaKnowledgeConnector(chroma_path, collection, embedding_model)

    md_files = sorted(SEED_DIR.glob("*.md"))
    if not md_files:
        print(f"No .md files found in {SEED_DIR}")
        return

    print(f"Found {len(md_files)} documents. Ingesting...\n")

    for path in md_files:
        content = path.read_text()
        try:
            tags = extract_tags(content)
        except ValueError as e:
            print(f"  SKIP  {path.name} — {e}")
            continue

        doc_id = path.stem
        title = path.stem.replace("_", " ").title()

        await connector.ingest(
            text=content,
            access_tags=tags,
            doc_id=doc_id,
            metadata={"title": title, "source": str(path)},
        )
        print(f"  OK    {path.name}  →  tags: {tags}")

    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(ingest_all())
