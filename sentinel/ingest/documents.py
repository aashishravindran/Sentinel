# Copyright (c) 2026 Aashish Ravindran. All rights reserved.
# Use of this software is governed by the Elastic License 2.0
# found in the LICENSE file.

"""Load tagged Markdown documents and ingest them into any knowledge store.

A document declares who may read it in an HTML comment the renderer hides:

    <!-- access_tags: finance, engineering -->
"""

import re
from dataclasses import dataclass
from pathlib import Path

from sentinel_engine.base import KnowledgeConnector

ACCESS_TAGS_COMMENT = re.compile(r"<!--\s*access_tags:\s*([^>]*?)\s*-->")


@dataclass(frozen=True)
class TaggedDocument:
    doc_id: str
    title: str
    text: str
    access_tags: list[str]
    source: Path


def load_tagged_documents(directory: Path) -> list[TaggedDocument]:
    """Every ``*.md`` file in *directory*. A file without an access_tags comment is an error."""
    documents: list[TaggedDocument] = []
    for path in sorted(directory.glob("*.md")):
        text = path.read_text()
        match = ACCESS_TAGS_COMMENT.search(text)
        if match is None:
            raise ValueError(f"{path.name} has no <!-- access_tags: ... --> comment")
        tags = [t.strip() for t in match.group(1).split(",") if t.strip()]
        title = path.stem.replace("_", " ").title()
        documents.append(TaggedDocument(path.stem, title, text, tags, path))
    return documents


async def ingest_documents(documents: list[TaggedDocument], knowledge: KnowledgeConnector) -> None:
    for doc in documents:
        await knowledge.ingest(doc.text, doc.access_tags, doc.doc_id, {"title": doc.title})
