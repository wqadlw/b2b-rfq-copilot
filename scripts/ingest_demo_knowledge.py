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

    # QA-0007/0010：验证 VectorStore 协议实现（build_runtime 实际装配的类）
    from rfq_copilot.app.infra_pgvector import PgVectorStore

    vstore = PgVectorStore(dsn)
    await vstore.init_ddl()
    vchunks = [c for d in docs for c in chunk_document(d)]
    vvectors = await embedder.embed([c.content for c in vchunks])
    added = await vstore.add(vchunks, vvectors)
    vhits = await vstore.search(query_vector, top_k=3)
    scored_ok = all(0.0 <= h.score <= 1.0 for h in vhits) and all(h.chunk.trust_level == "platform" for h in vhits)
    total_count = await vstore.count()
    removed = await vstore.remove_by_doc_id(docs[0].doc_id)
    print(f"  PgVectorStore roundtrip: added={added} count={total_count} removed={removed} scores_ok={scored_ok}")
    if not vhits or not scored_ok:
        print("FAIL PgVectorStore search returned no hits / bad scores / trust leak")
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

    async def _run_inmemory() -> None:
        chunks = [chunk for doc in docs for chunk in chunk_document(doc)]
        embedder = HashingEmbedder()
        store = InMemoryVectorStore()
        await store.add(chunks, embedder.embed_sync([c.content for c in chunks]))
        print(f"in-memory ingest: {await store.count()} chunks, dim={len(embedder.embed_sync(['x'])[0])}")

    asyncio.run(_run_inmemory())
    print("note: prod ingests via --pg into PostgreSQL+pgvector (HNSW).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
