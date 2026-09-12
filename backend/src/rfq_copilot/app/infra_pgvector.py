"""Production knowledge store backed by PostgreSQL + pgvector.

Composition-root wiring per CODE_ORGANIZATION section 4.4 — core stays storage-free.
Values travel exclusively through asyncpg bind parameters; vectors arrive as
json-serialized numeric arrays.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from rfq_copilot.core.rag.chunking import Chunk, chunk_document
from rfq_copilot.core.rag.embedding import EmbeddingClient
from rfq_copilot.ports.errors import ConfigError, UpstreamInvalidResponseError
from rfq_copilot.ports.knowledge_source import KnowledgeDocument, KnowledgeSourcePort

logger = structlog.get_logger(__name__)

VALID_TRUST = {"platform", "merchant", "ugc"}


def _vector_literal(vector: list[float]) -> str:
    return json.dumps([round(float(v), 8) for v in vector])


def _chunk_from_row(row: Any) -> Chunk:
    metadata = row["metadata"]
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    trust = metadata.get("trust_level")
    if trust not in VALID_TRUST:
        raise UpstreamInvalidResponseError(f"chunk {row['doc_id']} missing trust metadata")
    return Chunk(
        doc_id=row["doc_id"],
        chunk_index=row["chunk_index"],
        title=row["title"],
        content=row["content"],
        trust_level=trust,
        supplier_id=metadata.get("supplier_id"),
        product_id=metadata.get("product_id"),
    )


class PgVectorKnowledgeSource(KnowledgeSourcePort):
    def __init__(self, dsn: str, embedder: EmbeddingClient) -> None:
        self._dsn = dsn
        self._embedder = embedder

    async def init_ddl(self) -> None:
        import asyncpg

        conn = await asyncpg.connect(self._dsn)
        try:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            await conn.execute(
                """CREATE TABLE IF NOT EXISTS knowledge_chunks (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                doc_id VARCHAR(64) NOT NULL,
                chunk_index INT NOT NULL,
                title VARCHAR(256) NOT NULL,
                content TEXT NOT NULL,
                metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                embedding vector(1024) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )"""
            )
            await conn.execute(
                """CREATE INDEX IF NOT EXISTS knowledge_chunks_hnsw ON knowledge_chunks
                USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"""
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS knowledge_chunks_metadata_gin ON knowledge_chunks USING gin (metadata)"
            )
        finally:
            await conn.close()
        logger.info("pgvector.ddl.ready")

    async def ingest(self, docs: list[KnowledgeDocument]) -> int:
        import asyncpg

        for doc in docs:
            if doc.trust_level not in VALID_TRUST:
                raise ConfigError(f"trust_level invalid for {doc.doc_id}: refusing to ingest")
        conn = await asyncpg.connect(self._dsn)
        try:
            total = 0
            for doc in docs:
                chunks = chunk_document(doc)
                metadata = {
                    "source_type": doc.trust_level,
                    "trust_level": doc.trust_level,
                    "supplier_id": doc.supplier_id,
                    "product_id": doc.product_id,
                    "title": doc.title,
                }
                vectors = await self._embedder.embed([c.content for c in chunks])
                for chunk, vector in zip(chunks, vectors, strict=True):
                    await conn.execute(
                        """INSERT INTO knowledge_chunks
                        (doc_id, chunk_index, title, content, metadata, embedding)
                        VALUES ($1, $2, $3, $4, $5::jsonb, $6::vector)""",
                        chunk.doc_id,
                        chunk.chunk_index,
                        chunk.title,
                        chunk.content,
                        json.dumps(metadata),
                        _vector_literal(vector),
                    )
                    total += 1
            logger.info("pgvector.ingest", docs=len(docs), chunks=total)
            return total
        finally:
            await conn.close()

    async def search(
        self, query_vector: list[float], top_k: int = 20, trust_levels: set[str] | None = None
    ) -> list[Chunk]:
        import asyncpg

        literal = _vector_literal(query_vector)
        conn = await asyncpg.connect(self._dsn)
        try:
            if trust_levels:
                rows = await conn.fetch(
                    """SELECT doc_id, chunk_index, title, content, metadata FROM knowledge_chunks
                    WHERE metadata->>'trust_level' = ANY($1::text[])
                    ORDER BY embedding <=> $2::vector LIMIT $3""",
                    sorted(trust_levels),
                    literal,
                    top_k,
                )
            else:
                rows = await conn.fetch(
                    """SELECT doc_id, chunk_index, title, content, metadata FROM knowledge_chunks
                    ORDER BY embedding <=> $1::vector LIMIT $2""",
                    literal,
                    top_k,
                )
        finally:
            await conn.close()
        chunks = [_chunk_from_row(row) for row in rows]
        logger.info("pgvector.search", hits=len(chunks))
        return chunks

    def iter_documents(self, scope: Any = None) -> Any:
        raise NotImplementedError("pgvector store is write/search; documents come from adapters")

    def fingerprint(self) -> str:
        return "pgvector"
