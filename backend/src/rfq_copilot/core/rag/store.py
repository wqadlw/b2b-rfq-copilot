"""Vector store protocol + in-memory implementation (demo/CI; prod = app/infra_pgvector)."""

from dataclasses import dataclass, field
from typing import Protocol

from rfq_copilot.core.rag.chunking import Chunk
from rfq_copilot.core.rag.embedding import cosine


@dataclass(frozen=True)
class ScoredChunk:
    chunk: Chunk
    score: float


class VectorStore(Protocol):
    def add(self, chunks: list[Chunk], vectors: list[list[float]]) -> int: ...

    def search(
        self, query_vector: list[float], top_k: int = 5, trust_levels: set[str] | None = None
    ) -> list[ScoredChunk]: ...

    def count(self) -> int: ...


@dataclass
class InMemoryVectorStore:
    """Cosine over all chunks (demo scale ≤ hundreds); prod uses pgvector HNSW."""

    rows: list[tuple[Chunk, list[float]]] = field(default_factory=list)

    def add(self, chunks: list[Chunk], vectors: list[list[float]]) -> int:
        if len(chunks) != len(vectors):
            raise ValueError("chunks/vectors length mismatch")
        self.rows.extend(zip(chunks, vectors, strict=True))
        return len(chunks)

    def search(
        self, query_vector: list[float], top_k: int = 5, trust_levels: set[str] | None = None
    ) -> list[ScoredChunk]:
        scored = [
            ScoredChunk(chunk=chunk, score=cosine(query_vector, vec))
            for chunk, vec in self.rows
            if trust_levels is None or chunk.trust_level in trust_levels
        ]
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored[:top_k]

    def count(self) -> int:
        return len(self.rows)
