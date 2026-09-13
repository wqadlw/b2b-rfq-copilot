"""RAG pipeline: query → embed → store search → rerank → isolated context + citations.

Every stage emits a structured trace event (M1 acceptance: full chain visible in logs).
"""

import structlog

from rfq_copilot.core.rag.chunking import Chunk
from rfq_copilot.core.rag.citation import render_context
from rfq_copilot.core.rag.embedding import EmbeddingClient
from rfq_copilot.core.rag.reranker import Reranker
from rfq_copilot.core.rag.store import VectorStore

logger = structlog.get_logger(__name__)

RECALL_TOP_K = 20
FINAL_TOP_K = 5


class RAGPipeline:
    def __init__(self, embedder: EmbeddingClient, store: VectorStore, reranker: Reranker) -> None:
        self._embedder = embedder
        self._store = store
        self._reranker = reranker

    async def ingest(self, chunks: list[Chunk]) -> int:
        vectors = await self._embedder.embed([c.content for c in chunks])
        count = self._store.add(chunks, vectors)
        logger.info("rag.ingest", chunks=count, dim=len(vectors[0]) if vectors else 0)
        return count

    async def search(self, query: str, top_k: int = FINAL_TOP_K) -> list[Chunk]:
        """Recall (top 20) → rerank → final top 5. Output schema carries trust_level."""
        query_vector = (await self._embedder.embed([query]))[0]
        candidates = self._store.search(query_vector, top_k=RECALL_TOP_K)
        logger.info(
            "rag.retrieve",
            query_len=len(query),
            recall=len(candidates),
            trust=[s.chunk.trust_level for s in candidates[:5]],
        )
        ranked = self._reranker.rerank(query, [s.chunk for s in candidates])
        final = ranked[:top_k]
        logger.info("rag.rerank", final=[c.doc_id for c in final])
        return final

    def remove_doc(self, doc_id: str) -> int:
        """Remove all chunks for a doc_id (delegates to store)."""
        return self._store.remove_by_doc_id(doc_id)

    async def context_for(self, query: str, top_k: int = FINAL_TOP_K) -> tuple[str, list[Chunk]]:
        """Search + render trust-isolated context blocks (platform/merchant separated)."""
        chunks = await self.search(query, top_k)
        return render_context(chunks), chunks
