"""01-port-spec §6.4 回归：混合检索（向量 + 关键词 RRF）。

- extract_keywords：ASCII 型号 token / CJK 二元组 / 去重保序 / 上限截断。
- rrf_fuse：融合排序与 doc_id 去重的数学确定性。
- InMemoryVectorStore.keyword_search：倒排索引、命中计数、trust 过滤、增删失效。
- PgVectorStore.keyword_search：SQL 形状（ILIKE 转义、trust 分支、空 token 短路）。
- 管线集成：混合模式对 demo 语料 recall 不劣于纯向量单路；型号精确查询必中。
"""

import asyncio
import json
from typing import Any

import pytest

from rfq_copilot.adapters.demo import data as demo_data
from rfq_copilot.core.rag.chunking import Chunk, chunk_document
from rfq_copilot.core.rag.embedding import HashingEmbedder
from rfq_copilot.core.rag.keyword import extract_keywords, rrf_fuse
from rfq_copilot.core.rag.pipeline import RAGPipeline
from rfq_copilot.core.rag.reranker import NoopReranker
from rfq_copilot.core.rag.retrieval_eval import derive_queries, evaluate
from rfq_copilot.core.rag.store import InMemoryVectorStore
from rfq_copilot.ports.knowledge_source import KnowledgeDocument


def _chunk(doc_id: str, title: str = "t", content: str = "c", trust_level: str = "platform") -> Chunk:
    return Chunk(doc_id=doc_id, chunk_index=0, title=title, content=content, trust_level=trust_level)


# ---------------------------------------------------------------------------
# extract_keywords
# ---------------------------------------------------------------------------


def test_extract_keywords_ascii_model_token() -> None:
    tokens = extract_keywords("RV12-76095b 抽速多大")
    assert "rv12-76095b" in tokens


def test_extract_keywords_cjk_bigrams_and_dedupe() -> None:
    tokens = extract_keywords("无油螺杆泵 无油")
    assert "无油" in tokens and "油螺" in tokens and "螺杆" in tokens
    assert tokens.count("无油") == 1  # 去重保序


def test_extract_keywords_cap_and_single_cjk() -> None:
    tokens = extract_keywords("泵", max_tokens=3)
    assert tokens == ["泵"]
    capped = extract_keywords("真空泵选型参数对比表", max_tokens=4)
    assert len(capped) == 4


# ---------------------------------------------------------------------------
# rrf_fuse
# ---------------------------------------------------------------------------


def test_rrf_fuse_order_and_dedupe() -> None:
    a, b, c = _chunk("a"), _chunk("b"), _chunk("c")
    fused = rrf_fuse([a, b], [b, c], top_k=3)
    # a: 1/61 + 0 = 0.0164；b: 1/62 + 1/61 = 0.0325 → b 第一
    assert [ch.doc_id for ch in fused] == ["b", "a", "c"]
    short = rrf_fuse([a, b, c], top_k=2)
    assert len(short) == 2


# ---------------------------------------------------------------------------
# InMemoryVectorStore.keyword_search
# ---------------------------------------------------------------------------


def test_inmemory_keyword_search_and_invalidation() -> None:
    store = InMemoryVectorStore()

    async def seed() -> None:
        docs = [
            KnowledgeDocument(
                doc_id="rv (1/1)",
                title="RV 泵",
                doc_type="product",
                trust_level="merchant",
                content="型号 rv12-76095b 无油螺杆",
            ),
            KnowledgeDocument(
                doc_id="other (1/1)", title="其他", doc_type="product", trust_level="merchant", content="完全无关的内容"
            ),
        ]
        embedder = HashingEmbedder()
        vectors = await embedder.embed([d.content for d in docs])
        await store.add(docs, vectors)

    asyncio.run(seed())
    hits = asyncio.run(store.keyword_search(["rv12", "76095b"], top_k=5))
    assert len(hits) == 1 and hits[0].chunk.doc_id == "rv (1/1)" and hits[0].score == 2.0
    hits2 = asyncio.run(store.keyword_search(["螺杆"], top_k=5))
    assert len(hits2) == 1 and hits2[0].score == 1.0
    empty = asyncio.run(store.keyword_search([], top_k=5))
    assert empty == []
    removed = asyncio.run(store.remove_by_doc_id("rv (1/1)"))
    assert removed == 1
    gone = asyncio.run(store.keyword_search(["rv12"], top_k=5))
    assert gone == []


def test_inmemory_keyword_trust_filter() -> None:
    store = InMemoryVectorStore()

    async def seed() -> None:
        docs = [
            KnowledgeDocument(
                doc_id="p (1/1)", title="泵", doc_type="product", trust_level="merchant", content="无油螺杆泵机组"
            ),
            KnowledgeDocument(
                doc_id="f (1/1)", title="faq", doc_type="platform_faq", trust_level="platform", content="螺杆真空泵原理"
            ),
        ]
        embedder = HashingEmbedder()
        vectors = await embedder.embed([d.content for d in docs])
        await store.add(docs, vectors)

    asyncio.run(seed())
    hits = asyncio.run(store.keyword_search(["螺杆"], top_k=5, trust_levels={"platform"}))
    assert [h.chunk.doc_id for h in hits] == ["f (1/1)"]


# ---------------------------------------------------------------------------
# PgVectorStore.keyword_search SQL shape
# ---------------------------------------------------------------------------


def test_pgvector_keyword_search_sql_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    from rfq_copilot.app.infra_pgvector import PgVectorStore

    captured: dict[str, Any] = {}

    class FakeConn:
        async def fetch(self, sql: str, *args: Any) -> list[dict[str, Any]]:
            captured["sql"], captured["args"] = sql, args
            return [
                {
                    "doc_id": "rv (1/1)",
                    "chunk_index": 0,
                    "title": "RV 泵",
                    "content": "型号 rv12-76095b",
                    "metadata": json.dumps({"trust_level": "merchant"}),
                }
            ]

        async def close(self) -> None:
            return None

    async def _connect(_dsn: str) -> FakeConn:
        return FakeConn()

    import asyncpg

    monkeypatch.setattr(asyncpg, "connect", _connect)
    store = PgVectorStore("postgresql://x")
    hits = asyncio.run(store.keyword_search(["rv12-76095b", "百分%号_下划线"], top_k=10))
    assert len(hits) == 1 and hits[0].chunk.doc_id == "rv (1/1)"
    patterns = captured["args"][0]
    assert "%rv12-76095b%" in patterns and "%百分\\%号\\_下划线%" in patterns
    empty = asyncio.run(store.keyword_search([], top_k=10))
    assert empty == []


# ---------------------------------------------------------------------------
# pipeline integration
# ---------------------------------------------------------------------------


def test_pipeline_hybrid_not_worse_on_demo_corpus() -> None:
    docs = list(demo_data.DOCS)
    cases = derive_queries(docs, per_doc=1)

    async def recall_for(hybrid: bool) -> float:
        pipeline = RAGPipeline(
            embedder=HashingEmbedder(), store=InMemoryVectorStore(), reranker=NoopReranker(), hybrid=hybrid
        )
        chunks = [chunk for doc in docs for chunk in chunk_document(doc)]
        await pipeline.ingest(chunks)
        report = await evaluate(pipeline.search, cases, k=5)
        return report.recall

    hybrid_recall = asyncio.run(recall_for(hybrid=True))
    vector_recall = asyncio.run(recall_for(hybrid=False))
    assert hybrid_recall >= vector_recall - 1e-9, (
        f"混合检索劣化：hybrid={hybrid_recall:.4f} < vector={vector_recall:.4f}"
    )


def test_pipeline_hybrid_hits_exact_model_query() -> None:
    docs = [
        KnowledgeDocument(
            doc_id="rv (1/1)",
            title="RV 系列旋片泵",
            doc_type="product",
            trust_level="merchant",
            content="产品名称：RV 系列旋片泵\n型号：rv12-76095b\n主要参数：抽速 12 L/s",
        ),
        KnowledgeDocument(
            doc_id="filler (1/1)",
            title="同类泵型",
            doc_type="product",
            trust_level="merchant",
            content="旋片泵 抽速 极限真空 性能参数介绍 旋片泵 抽速 极限真空 性能参数介绍",
        ),
        KnowledgeDocument(
            doc_id="filler2 (1/1)",
            title="另一款泵",
            doc_type="product",
            trust_level="merchant",
            content="旋片真空泵 选型指南 抽速曲线 极限真空度 旋片真空泵 选型指南",
        ),
        KnowledgeDocument(
            doc_id="filler3 (1/1)",
            title="维护手册",
            doc_type="platform_faq",
            trust_level="platform",
            content="真空泵日常维护 更换泵油 清洗泵腔 检查密封件 真空泵日常维护",
        ),
        KnowledgeDocument(
            doc_id="filler4 (1/1)",
            title="行业应用",
            doc_type="platform_faq",
            trust_level="platform",
            content="真空技术在制药与食品行业的应用案例 真空技术在制药与食品行业的应用案例",
        ),
        KnowledgeDocument(
            doc_id="filler5 (1/1)",
            title="选型问答",
            doc_type="platform_faq",
            trust_level="platform",
            content="如何根据抽速选择真空泵 如何根据抽速选择真空泵 如何根据抽速选择真空泵",
        ),
    ]

    async def hits(hybrid: bool) -> bool:
        pipeline = RAGPipeline(
            embedder=HashingEmbedder(), store=InMemoryVectorStore(), reranker=NoopReranker(), hybrid=hybrid
        )
        chunks = [chunk for doc in docs for chunk in chunk_document(doc)]
        await pipeline.ingest(chunks)
        final = await pipeline.search("rv12-76095b 的参数", top_k=5)
        return any(c.doc_id.startswith("rv") for c in final)

    assert asyncio.run(hits(hybrid=True)) is True
