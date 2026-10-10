# Copyright (c) 2026 Aashish Ravindran. All rights reserved.
# Use of this software is governed by the Elastic License 2.0
# found in the LICENSE file.

"""Ingest docs/seed into the configured knowledge store, tags and all.

Uses the same SENTINEL_KNOWLEDGE_STORE settings as the server, so it works for
ChromaDB locally and for a Bedrock KB's S3 bucket (documents plus
.metadata.json sidecars carrying each document's access tags).

    SENTINEL_KNOWLEDGE_STORE=chroma uv run python scripts/ingest_seed_docs.py
    SENTINEL_KNOWLEDGE_STORE=bedrock BEDROCK_KB_ID=... BEDROCK_S3_BUCKET=... \\
        uv run python scripts/ingest_seed_docs.py
"""

import asyncio
import os
from pathlib import Path

from sentinel_engine.factory import build_knowledge_from_env

from sentinel.ingest.documents import ingest_documents, load_tagged_documents

SEED_DIR = Path(__file__).parent.parent / "docs" / "seed"


async def main() -> None:
    os.environ.setdefault("SENTINEL_KNOWLEDGE_STORE", "chroma")
    documents = load_tagged_documents(SEED_DIR)
    await ingest_documents(documents, build_knowledge_from_env())
    for doc in documents:
        print(f"  {doc.doc_id:<34} {', '.join(doc.access_tags)}")
    print(f"Ingested {len(documents)} documents into {os.environ['SENTINEL_KNOWLEDGE_STORE']}.")


if __name__ == "__main__":
    asyncio.run(main())
