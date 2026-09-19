"""Vector store protocol + in-memory implementation (demo/CI; prod = app/infra_pgvector).

QA-0007/0010：协议统一为 async（pgvector 需真 IO），两种实现均满足 VectorStore，
build_runtime 按 Settings.rag_store 装配——"生产=pgvector HNSW"自此是接线的现实而非承诺。
"""

from dataclasses import dataclass, field
from typing import Protocol

from rfq_copilot.core.rag.chunking import Chunk
from rfq_copilot.core.rag.embedding import cosine
from rfq_copilot.core.rag.keyword import extract_keywords


@dataclass(frozen=True)
class ScoredChunk:
    chunk: Chunk
    score: float


class VectorStore(Protocol):
    async def add(self, chunks: list[Chunk], vectors: list[list[float]]) -> int: ...

    async def search(
        self, query_vector: list[float], top_k: int = 5, trust_levels: set[str] | None = None
    ) -> list[ScoredChunk]: ...

    async def keyword_search(
        self, tokens: list[str], top_k: int = 10, trust_levels: set[str] | None = None
    ) -> list[ScoredChunk]:
        """关键词通道（01-port-spec §6.4）：tokens 由 extract_keywords 产出（唯一事实源）。"""
        ...

    async def remove_by_doc_id(self, doc_id: str) -> int:
        """移除文档家族：doc_id 精确匹配 + 其分块后缀 ` (i/n)`（03-api-spec 知识维护段）。"""
        ...

    async def count(self) -> int: ...


@dataclass
class InMemoryVectorStore:
    """Cosine over all chunks（demo/CI 规模 ≤ 数百 chunk；prod 走 PgVectorStore HNSW）。

    关键词通道（§6.4）：惰性倒排索引——首次 keyword_search 时建，add/remove 失效。
    """

    rows: list[tuple[Chunk, list[float]]] = field(default_factory=list)
    _inverted: dict[str, set[int]] | None = None

    def _index(self) -> dict[str, set[int]]:
        if self._inverted is None:
            index: dict[str, set[int]] = {}
            for i, (chunk, _) in enumerate(self.rows):
                for token in set(extract_keywords(f"{chunk.title}\n{chunk.content}")):
                    index.setdefault(token, set()).add(i)
            self._inverted = index
        return self._inverted

    def _invalidate(self) -> None:
        self._inverted = None

    async def add(self, chunks: list[Chunk], vectors: list[list[float]]) -> int:
        if len(chunks) != len(vectors):
            raise ValueError("chunks/vectors length mismatch")
        self.rows.extend(zip(chunks, vectors, strict=True))
        self._invalidate()
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

    async def keyword_search(
        self, tokens: list[str], top_k: int = 10, trust_levels: set[str] | None = None
    ) -> list[ScoredChunk]:
        if not tokens:
            return []
        index = self._index()
        counts: dict[int, int] = {}
        for token in tokens:
            for i in index.get(token, ()):
                if trust_levels is None or self.rows[i][0].trust_level in trust_levels:
                    counts[i] = counts.get(i, 0) + 1
        scored = [
            ScoredChunk(chunk=self.rows[i][0], score=float(hits))
            for i, hits in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
        ]
        return scored[:top_k]

    async def remove_by_doc_id(self, doc_id: str) -> int:
        """移除文档家族：精确 doc_id + ` (i/n)` 分块后缀（wrap_chunks 命名约定）。"""
        before = len(self.rows)
        family = doc_id + " ("
        self.rows = [(c, v) for c, v in self.rows if c.doc_id != doc_id and not c.doc_id.startswith(family)]
        self._invalidate()
        return before - len(self.rows)

    async def count(self) -> int:
        return len(self.rows)
