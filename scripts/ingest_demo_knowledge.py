"""Ingest demo knowledge into the RAG store.

Default: in-memory store (demo/CI, hashing embeddings).
``--pg --dsn ...``: real pgvector acceptance — DDL + ingest + filtered search verification.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend" / "src"))

from rfq_copilot.adapters.demo import data as demo_data  # noqa: E402
from rfq_copilot.core.rag.chunking import chunk_document  # noqa: E402
from rfq_copilot.core.rag.embedding import HashingEmbedder  # noqa: E402
from rfq_copilot.core.rag.store import InMemoryVectorStore  # noqa: E402


def _docs() -> list:
    return list(demo_data.DOCS) + list(demo_data.POISON_DOCS)


async def _run_pg(dsn: str) -> int:
    from rfq_copilot.app.infra_pgvector import PgVectorKnowledgeSource

    embedder = HashingEmbedder()
    store = PgVectorKnowledgeSource(dsn=dsn, embedder=embedder)
    await store.init_ddl()
    docs = _docs()
    total = await store.ingest(docs)

    query_vector = (await embedder.embed(["无油泵怎么选？"]))[0]
    all_hits = await store.search(query_vector, top_k=5)
    platform_hits = await store.search(query_vector, top_k=5, trust_levels={"platform"})
    dims = len(query_vector)
    print(f"pgvector acceptance: ingested {total} chunks from {len(docs)} docs (dim={dims})")
    print(f"  search top5 trust: {[c.trust_level for c in all_hits]}")
    print(f"  platform-filtered hits: {[c.doc_id for c in platform_hits]}")
    if dims != 1024:
        print("FAIL embedding dim != 1024")
        return 1
    if any(c.trust_level != "platform" for c in platform_hits):
        print("FAIL trust filter returned non-platform chunks")
        return 1
    print("pgvector acceptance: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pg", action="store_true", help="ingest into PostgreSQL+pgvector")
    parser.add_argument("--dsn", default="postgresql://rfq:rfq@localhost:5432/rfq")
    args = parser.parse_args()

    docs = _docs()
    by_trust: dict[str, int] = {}
    for doc in docs:
        by_trust[doc.trust_level] = by_trust.get(doc.trust_level, 0) + 1
    poisoned = ", ".join(d.doc_id for d in demo_data.POISON_DOCS)
    print(f"demo knowledge: {len(docs)} docs ({by_trust}); poisoned samples: {poisoned}")

    if args.pg:
        return asyncio.run(_run_pg(args.dsn))

    chunks = [chunk for doc in docs for chunk in chunk_document(doc)]
    embedder = HashingEmbedder()
    store = InMemoryVectorStore()
    store.add(chunks, embedder.embed_sync([c.content for c in chunks]))
    print(f"in-memory ingest: {store.count()} chunks, dim={len(embedder.embed_sync(['x'])[0])}")
    print("note: prod ingests via --pg into PostgreSQL+pgvector (HNSW).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
