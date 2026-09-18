"""Vector store protocol + in-memory implementation (demo/CI; prod = app/infra_pgvector).

QA-0007/0010：协议统一为 async（pgvector 需真 IO），两种实现均满足 VectorStore，
build_runtime 按 Settings.rag_store 装配——"生产=pgvector HNSW"自此是接线的现实而非承诺。
"""

from dataclasses import dataclass, field
from typing import Protocol

from rfq_copilot.core.rag.chunking import Chunk
from rfq_copilot.core.rag.embedding import cosine


@dataclass(frozen=True)
class ScoredChunk:
    chunk: Chunk
    score: float


class VectorStore(Protocol):
    async def add(self, chunks: list[Chunk], vectors: list[list[float]]) -> int: ...

    async def search(
        self, query_vector: list[float], top_k: int = 5, trust_levels: set[str] | None = None
    ) -> list[ScoredChunk]: ...

    async def remove_by_doc_id(self, doc_id: str) -> int: ...

    async def count(self) -> int: ...


@dataclass
class InMemoryVectorStore:
    """Cosine over all chunks（demo/CI 规模 ≤ 数百 chunk；prod 走 PgVectorStore HNSW）。"""

    rows: list[tuple[Chunk, list[float]]] = field(default_factory=list)

    async def add(self, chunks: list[Chunk], vectors: list[list[float]]) -> int:
        if len(chunks) != len(vectors):
            raise ValueError("chunks/vectors length mismatch")
        self.rows.extend(zip(chunks, vectors, strict=True))
        return len(chunks)

    async def search(
        self, query_vector: list[float], top_k: int = 5, trust_levels: set[str] | None = None
    ) -> list[ScoredChunk]:
        scored = [
            ScoredChunk(chunk=chunk, score=cosine(query_vector, vec))
            for chunk, vec in self.rows
            if trust_levels is None or chunk.trust_level in trust_levels
        ]
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored[:top_k]

    async def remove_by_doc_id(self, doc_id: str) -> int:
        """Remove all chunks belonging to a document; returns count removed."""
        before = len(self.rows)
        self.rows = [(c, v) for c, v in self.rows if c.doc_id != doc_id]
        return before - len(self.rows)

    async def count(self) -> int:
        return len(self.rows)
