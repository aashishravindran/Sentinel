# Copyright (c) 2026 Aashish Ravindran. All rights reserved.
# Use of this software is governed by the Elastic License 2.0
# found in the LICENSE file.

"""Recall@k: filter inside the vector query (Sentinel) vs. filter the results afterwards.

Post-filtering retrieves the global top-k and drops what the user may not
read, so a user who can see a small slice of the corpus gets few or no
results. Pushing the filter into the query searches only their slice.

Synthetic corpus: every department writes about every topic. A query asks
about one topic as a member of one department; the relevant documents are
that department's documents on that topic.

    uv run python -m tests.load.recall --departments 10 --per-topic 5 --k 5
"""

import argparse
import asyncio
import itertools
import statistics
import tempfile

from sentinel_engine.connectors.knowledge.chroma import ChromaKnowledgeConnector

TOPICS = {
    "budget": "annual budget, operating expenses and headcount cost forecast",
    "oncall": "on-call rotation, incident paging and runbook escalation steps",
    "hiring": "hiring plan, open requisitions and interview loop calibration",
    "security": "security review, access audits and vulnerability remediation",
    "roadmap": "product roadmap, quarterly milestones and launch sequencing",
}


async def main(departments: int, per_topic: int, k: int) -> None:
    depts = [f"dept{i:02d}" for i in range(departments)]
    with tempfile.TemporaryDirectory() as path:
        kb = ChromaKnowledgeConnector(path, "recall", "all-MiniLM-L6-v2")
        relevant: dict[tuple[str, str], set[str]] = {}
        for dept, (topic, text), n in itertools.product(depts, TOPICS.items(), range(per_topic)):
            doc_id = f"{dept}_{topic}_{n}"
            await kb.ingest(f"{dept} {text}, revision {n}.", [dept], doc_id, {"title": doc_id})
            relevant.setdefault((dept, topic), set()).add(doc_id)

        pre: list[float] = []
        post: list[float] = []
        everyone = set(depts)
        for (dept, topic), wanted in relevant.items():
            query = TOPICS[topic]  # users ask about the topic, not their department
            denominator = min(k, len(wanted))
            pushed = await kb.search(query, {dept}, k)
            pre.append(len({c["metadata"]["title"] for c in pushed} & wanted) / denominator)
            global_top = await kb.search(query, everyone, k)
            kept = {
                c["metadata"]["title"] for c in global_top if c["metadata"]["access_tags"] == dept
            }
            post.append(len(kept & wanted) / denominator)

    corpus = departments * len(TOPICS) * per_topic
    print(f"corpus={corpus} docs, {departments} departments, k={k}, queries={len(pre)}")
    print("| strategy | mean recall@k |\n|---|---:|")
    print(f"| filter in the query (Sentinel) | {statistics.mean(pre):.2f} |")
    print(f"| retrieve top-k, then filter | {statistics.mean(post):.2f} |")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--departments", type=int, default=10)
    parser.add_argument("--per-topic", type=int, default=5)
    parser.add_argument("--k", type=int, default=5)
    args = parser.parse_args()
    asyncio.run(main(args.departments, args.per_topic, args.k))
