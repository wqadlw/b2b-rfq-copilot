"""06-eval-spec §7 回归：检索侧评测（RAGAS 确定性代理）。

- golden 派生：按 doc_type 模板、per_doc 截断、空标题跳过、基 id 剥后缀。
- 指标数学：recall@5 / precision@5 / mrr 在 stub search 上可精确断言。
- 集成冒烟：demo 语料全链路（ingest → derive → evaluate）recall@5 > 0.5。
"""

import importlib.util
import sys
from pathlib import Path as _Path

_SCRIPT = _Path(__file__).resolve().parents[3] / "scripts" / "run_retrieval_eval.py"
_spec = importlib.util.spec_from_file_location("run_retrieval_eval", _SCRIPT)
assert _spec is not None and _spec.loader is not None
run_retrieval_eval = importlib.util.module_from_spec(_spec)
sys.modules["run_retrieval_eval"] = run_retrieval_eval
_spec.loader.exec_module(run_retrieval_eval)

from rfq_copilot.adapters.demo import data as demo_data  # noqa: E402
from rfq_copilot.core.rag.chunking import Chunk, chunk_document  # noqa: E402
from rfq_copilot.core.rag.embedding import HashingEmbedder  # noqa: E402
from rfq_copilot.core.rag.pipeline import RAGPipeline  # noqa: E402
from rfq_copilot.core.rag.reranker import NoopReranker  # noqa: E402
from rfq_copilot.core.rag.retrieval_eval import (  # noqa: E402
    base_doc_id,
    derive_queries,
    evaluate,
    render_report,
)
from rfq_copilot.core.rag.store import InMemoryVectorStore  # noqa: E402
from rfq_copilot.ports.knowledge_source import KnowledgeDocument  # noqa: E402


def _doc(doc_id: str, title: str, doc_type: str = "platform_faq") -> KnowledgeDocument:
    return KnowledgeDocument(
        doc_id=doc_id, title=title, doc_type=doc_type, trust_level="platform", content=f"{title} 的正文内容"
    )


# ---------------------------------------------------------------------------
# base id / derive
# ---------------------------------------------------------------------------


def test_base_doc_id_strips_chunk_suffix() -> None:
    assert base_doc_id("offline-product-x (2/2)") == "offline-product-x"
    assert base_doc_id("offline-product-x") == "offline-product-x"


def test_derive_queries_templates_per_doc_type() -> None:
    docs = [
        _doc("p1", "工业冷水机", doc_type="product"),
        _doc("s1 (1/2)", "医药无菌真空系统", doc_type="selection_guide"),
        _doc("f1", "罗茨泵频繁跳闸", doc_type="platform_faq"),
    ]
    cases = derive_queries(docs, per_doc=2)
    queries = {c.query for c in cases}
    assert "工业冷水机 的参数和价格是多少" in queries
    assert "有没有 工业冷水机 这款产品" in queries
    assert "医药无菌真空系统 怎么选型" in queries
    assert "罗茨泵频繁跳闸 怎么解决" in queries
    expected_bases = {c.expected_base for c in cases}
    assert expected_bases == {"p1", "s1", "f1"}


def test_derive_queries_caps_per_doc_and_skips_empty_title() -> None:
    docs = [_doc("p1", "产品甲", doc_type="product"), _doc("p2", "", doc_type="product")]
    cases = derive_queries(docs, per_doc=1)
    assert len(cases) == 1 and all(c.source_doc_id == "p1" for c in cases)


# ---------------------------------------------------------------------------
# metrics math on stub search
# ---------------------------------------------------------------------------


def _chunk(doc_id: str) -> Chunk:
    return Chunk(doc_id=doc_id, chunk_index=0, title="t", content="c", trust_level="platform")


async def _stub_search(queue: dict[str, list[str]]):
    async def search(query: str) -> list[Chunk]:
        return [_chunk(doc_id) for doc_id in queue[query]]

    return search


def test_evaluate_metrics_math() -> None:
    cases = derive_queries(
        [_doc("keep (1/1)", "产品甲", doc_type="product"), _doc("miss", "产品乙", doc_type="product")],
        per_doc=1,
    )
    queue = {
        "产品甲 的参数和价格是多少": ["keep (2/2)", "noise-a", "noise-b", "noise-c", "noise-d"],
        "产品乙 的参数和价格是多少": ["noise-a", "noise-b", "noise-c", "noise-d", "noise-e"],
    }

    async def search(query: str) -> list[Chunk]:
        return [_chunk(d) for d in queue[query]]

    import asyncio

    report = asyncio.run(evaluate(search, cases, k=5))
    assert report.cases == 2
    assert report.recall == 0.5
    assert report.precision == 0.1  # 1/5 与 0/5 的均值
    assert report.mrr == 0.5  # 首位命中 rank=1 → 1.0；未命中 → 0；均值 0.5
    assert report.misses and report.misses[0] == "产品乙 的参数和价格是多少"
    assert report.by_doc_type["product"]["cases"] == 2


def test_render_report_includes_source_and_disclaimer() -> None:
    cases = derive_queries([_doc("p1", "产品甲", doc_type="product")], per_doc=1)

    async def search(query: str) -> list[Chunk]:
        return [_chunk("p1 (1/1)"), _chunk("noise")]

    import asyncio

    report = asyncio.run(evaluate(search, cases, k=5))
    text = render_report(report, "离线快照 .ai/private/rag_data（857 篇）")
    assert "语料来源：离线快照 .ai/private/rag_data（857 篇）" in text
    assert "recall@5: 1.0000" in text
    assert "下界口径" in text


# ---------------------------------------------------------------------------
# integration smoke on demo corpus (deterministic, 0 token)
# ---------------------------------------------------------------------------


def test_demo_corpus_retrieval_recall_floor() -> None:
    docs = list(demo_data.DOCS)
    cases = derive_queries(docs, per_doc=1)

    async def run() -> float:
        pipeline = RAGPipeline(embedder=HashingEmbedder(), store=InMemoryVectorStore(), reranker=NoopReranker())
        chunks = [chunk for doc in docs for chunk in chunk_document(doc)]
        await pipeline.ingest(chunks)
        report = await evaluate(pipeline.search, cases, k=5)
        return report.recall

    import asyncio

    recall = asyncio.run(run())
    assert cases, "demo 语料派生不得为空"
    assert recall > 0.5, f"demo 语料 recall@5 跌破集成下限：{recall:.4f}"


def test_script_sample_is_deterministic() -> None:
    docs = [_doc(f"d{i}", f"标题{i}") for i in range(10)]
    a = run_retrieval_eval._sample(docs, 4)
    b = run_retrieval_eval._sample(docs, 4)
    assert [d.doc_id for d in a] == [d.doc_id for d in b] and len(a) == 4
    assert run_retrieval_eval._sample(docs, 0) == docs
