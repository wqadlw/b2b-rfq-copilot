"""RAG pipeline: query → embed → store search → rerank → isolated context + citations.

Every stage emits a structured trace event (M1 acceptance: full chain visible in logs).
"""

from collections.abc import Callable

import structlog

from rfq_copilot.core.rag.chunking import Chunk
from rfq_copilot.core.rag.citation import render_context
from rfq_copilot.core.rag.embedding import EmbeddingClient
from rfq_copilot.core.rag.keyword import extract_keywords, rrf_fuse, rrf_fuse_scored
from rfq_copilot.core.rag.reranker import Reranker
from rfq_copilot.core.rag.spec_matcher import SpecCriteria, chunk_matches_spec
from rfq_copilot.core.rag.store import InMemoryVectorStore, ScoredChunk, VectorStore

logger = structlog.get_logger(__name__)

RECALL_TOP_K = 20
FINAL_TOP_K = 5


class AdminUnsupported(RuntimeError):
    """运营只读端点在当前存储后端上不可用（spec 02：v1 仅 inmemory）。"""


class RAGPipeline:
    def __init__(
        self,
        embedder: EmbeddingClient,
        store: VectorStore,
        reranker: Reranker,
        hybrid: bool = True,
        hit_recorder: Callable[[list[str]], None] | None = None,
    ) -> None:
        self._embedder = embedder
        self._store = store
        self._reranker = reranker
        self._hybrid = hybrid  # 01-port-spec §6.4：向量+关键词 RRF 融合
        # spec 02 §2.5：命中统计钩子——search() final top-k 的去重 doc_id；
        # test-retrieval 走 search_scored，不触发（测试召回不得污染运营统计）
        self._hit_recorder = hit_recorder

    async def ingest(self, chunks: list[Chunk]) -> int:
        vectors = await self._embedder.embed([c.content for c in chunks])
        count = await self._store.add(chunks, vectors)
        logger.info("rag.ingest", chunks=count, dim=len(vectors[0]) if vectors else 0)
        return count

    async def search(self, query: str, top_k: int = FINAL_TOP_K, spec: SpecCriteria | None = None) -> list[Chunk]:
        """Recall (top 20 ×2 通道) → RRF 融合 → spec 过滤（带回落）→ rerank → final top 5."""
        query_vector = (await self._embedder.embed([query]))[0]
        candidates = await self._store.search(query_vector, top_k=RECALL_TOP_K)
        if self._hybrid:
            keyword_hits = await self._store.keyword_search(extract_keywords(query), top_k=RECALL_TOP_K)
            fused = rrf_fuse([s.chunk for s in candidates], [s.chunk for s in keyword_hits], top_k=RECALL_TOP_K)
        else:
            fused = [s.chunk for s in candidates]
        spec_applied = False
        spec_pool_before = len(fused)
        if spec is not None and not spec.is_empty:
            filtered = [c for c in fused if chunk_matches_spec(c, spec)]
            # §6.4.1 回落保护：过滤后候选不足则整体回落未过滤结果——宁可放宽不可答空
            if len(filtered) >= min(top_k, len(fused)) and filtered:
                fused = filtered
                spec_applied = True
            # QA-0031：回落必须可见——是否真应用了过滤、过滤前后池子多大，全部落日志
        logger.info(
            "rag.retrieve",
            query_len=len(query),
            recall=len(candidates),
            hybrid=self._hybrid,
            spec_requested=bool(spec is not None and not spec.is_empty),
            spec_applied=spec_applied,
            spec_pool_before=spec_pool_before,
            spec_pool_after=len(fused),
            trust=[c.trust_level for c in fused[:5]],
        )
        ranked = self._reranker.rerank(query, fused)
        final = ranked[:top_k]
        logger.info("rag.rerank", final=[c.doc_id for c in final])
        if self._hit_recorder is not None and final:
            # spec 02 §2.5：按首现顺序去重后交给命中统计（dict.fromkeys 保序去重）
            self._hit_recorder(list(dict.fromkeys(c.doc_id for c in final)))
        return final

    async def search_scored(
        self, query: str, top_k: int = FINAL_TOP_K, spec: SpecCriteria | None = None
    ) -> list[ScoredChunk]:
        """带 RRF 分数的检索（spec 02 §2.4 test-retrieval 专用）。

        与 search() 同管线（embed → 双通道 → RRF 融合 → spec 过滤带回落 → rerank），
        但保留融合分且**不触发命中统计**。score 是 RRF 分（Σ1/(60+rank)），非余弦相似度。
        """
        query_vector = (await self._embedder.embed([query]))[0]
        candidates = await self._store.search(query_vector, top_k=RECALL_TOP_K)
        if self._hybrid:
            keyword_hits = await self._store.keyword_search(extract_keywords(query), top_k=RECALL_TOP_K)
            fused = rrf_fuse_scored(
                [s.chunk for s in candidates], [s.chunk for s in keyword_hits], top_k=RECALL_TOP_K
            )
        else:
            fused = [(s.chunk, s.score) for s in candidates]
        if spec is not None and not spec.is_empty:
            filtered = [(c, score) for c, score in fused if chunk_matches_spec(c, spec)]
            if len(filtered) >= min(top_k, len(fused)) and filtered:
                fused = filtered  # §6.4.1 回落保护：与 search() 同规则
        score_by_doc: dict[str, float] = {}
        ordered_chunks: list[Chunk] = []
        for chunk, score in fused:
            score_by_doc.setdefault(chunk.doc_id, score)
            ordered_chunks.append(chunk)
        ranked = self._reranker.rerank(query, ordered_chunks)[:top_k]
        return [ScoredChunk(chunk=c, score=score_by_doc.get(c.doc_id, 0.0)) for c in ranked]

    async def corpus(self) -> list[Chunk]:
        """只读端点数据源（spec 02 §2.0）：全量分块快照。仅 inmemory 支持。"""
        if not isinstance(self._store, InMemoryVectorStore):
            raise AdminUnsupported(f"corpus() 仅支持 inmemory store（当前 {type(self._store).__name__}）")
        return [chunk for chunk, _ in self._store.rows]

    async def remove_doc(self, doc_id: str) -> int:
        """Remove all chunks for a doc_id (delegates to store)."""
        return await self._store.remove_by_doc_id(doc_id)

    async def context_for(
        self, query: str, top_k: int = FINAL_TOP_K, spec: SpecCriteria | None = None
    ) -> tuple[str, list[Chunk]]:
        """Search + render trust-isolated context blocks (platform/merchant separated)."""
        chunks = await self.search(query, top_k, spec=spec)
        return render_context(chunks), chunks
