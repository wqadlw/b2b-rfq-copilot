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
from rfq_copilot.core.rag.store import ScoredChunk
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
            for stmt in DDL_STATEMENTS:
                await conn.execute(stmt)
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


DDL_STATEMENTS: tuple[str, ...] = (
    "CREATE EXTENSION IF NOT EXISTS vector",
    """CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id VARCHAR(64) NOT NULL,
    chunk_index INT NOT NULL,
    title VARCHAR(256) NOT NULL,
    content TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    embedding vector(1024) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)""",
    """CREATE INDEX IF NOT EXISTS knowledge_chunks_hnsw ON knowledge_chunks
    USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)""",
    "CREATE INDEX IF NOT EXISTS knowledge_chunks_metadata_gin ON knowledge_chunks USING gin (metadata)",
)


class PgVectorStore:
    """VectorStore 协议的 pgvector 实现（QA-0007/0010：真装配进 build_runtime）。

    与 InMemoryVectorStore 同一协议（async add/search/remove_by_doc_id/count）；
    HNSW 索引在 init_ddl 建立，检索由 pgvector `<=>` 余弦距离排序——不再是全库 Python 扫描。
    连接策略：每调用一连接（与既有 PgVectorKnowledgeSource 一致；规模化后可换连接池）。
    """

    def __init__(self, dsn: str) -> None:
        if not dsn:
            raise ConfigError("PgVectorStore requires a PostgreSQL DSN")
        self._dsn = dsn

    async def init_ddl(self) -> None:
        import asyncpg

        conn = await asyncpg.connect(self._dsn)
        try:
            for stmt in DDL_STATEMENTS:
                await conn.execute(stmt)
        finally:
            await conn.close()
        logger.info("pgvector_store.ddl.ready")

    async def add(self, chunks: list[Chunk], vectors: list[list[float]]) -> int:
        import asyncpg

        if len(chunks) != len(vectors):
            raise ValueError("chunks/vectors length mismatch")
        conn = await asyncpg.connect(self._dsn)
        try:
            total = 0
            for chunk, vector in zip(chunks, vectors, strict=True):
                metadata = {
                    "trust_level": chunk.trust_level,
                    "supplier_id": chunk.supplier_id,
                    "product_id": chunk.product_id,
                    "title": chunk.title,
                }
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
            return total
        finally:
            await conn.close()

    async def search(
        self, query_vector: list[float], top_k: int = 5, trust_levels: set[str] | None = None
    ) -> list[ScoredChunk]:
        import asyncpg

        literal = _vector_literal(query_vector)
        conn = await asyncpg.connect(self._dsn)
        try:
            if trust_levels:
                rows = await conn.fetch(
                    """SELECT doc_id, chunk_index, title, content, metadata,
                    1 - (embedding <=> $1::vector) AS score
                    FROM knowledge_chunks
                    WHERE metadata->>'trust_level' = ANY($2::text[])
                    ORDER BY embedding <=> $1::vector LIMIT $3""",
                    literal,
                    sorted(trust_levels),
                    top_k,
                )
            else:
                rows = await conn.fetch(
                    """SELECT doc_id, chunk_index, title, content, metadata,
                    1 - (embedding <=> $1::vector) AS score
                    FROM knowledge_chunks
                    ORDER BY embedding <=> $1::vector LIMIT $2""",
                    literal,
                    top_k,
                )
        finally:
            await conn.close()
        scored = [ScoredChunk(chunk=_chunk_from_row(row), score=float(row["score"])) for row in rows]
        logger.info("pgvector_store.search", hits=len(scored))
        return scored

    async def remove_by_doc_id(self, doc_id: str) -> int:
        import asyncpg

        conn = await asyncpg.connect(self._dsn)
        try:
            status = await conn.execute("DELETE FROM knowledge_chunks WHERE doc_id = $1", doc_id)
            # asyncpg 返回 "DELETE n" 状态串
            return int(status.split()[-1]) if status else 0
        finally:
            await conn.close()

    async def count(self) -> int:
        import asyncpg

        conn = await asyncpg.connect(self._dsn)
        try:
            value = await conn.fetchval("SELECT count(*) FROM knowledge_chunks")
            return int(value)
        finally:
            await conn.close()
