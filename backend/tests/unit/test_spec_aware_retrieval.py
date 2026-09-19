"""01-port-spec §6.4.1 回归：规格过滤（spec-aware retrieval）。

- 数据面：KnowledgeDocument.params → chunk_document 透传 → 导出脚本产品块落 params。
- 过滤语义：chunk_matches_spec 数值硬条件 + 缺参数不可判定跳过 + 无油词面回退。
- 回落保护：过滤后候选不足 → 整体回落未过滤结果。
- graph 接线：knowledge_flow 从 entities 派生 SpecCriteria（is_empty 不过滤）。
"""

import asyncio
import importlib.util
import sys
from pathlib import Path as _Path
from typing import Any

_SCRIPT = _Path(__file__).resolve().parents[3] / "scripts" / "vacuum_b2b_export.py"
_spec = importlib.util.spec_from_file_location("vacuum_b2b_export", _SCRIPT)
assert _spec is not None and _spec.loader is not None
vacuum_b2b_export = importlib.util.module_from_spec(_spec)
sys.modules["vacuum_b2b_export"] = vacuum_b2b_export
_spec.loader.exec_module(vacuum_b2b_export)
from pathlib import Path  # noqa: E402

from rfq_copilot.core.rag.chunking import chunk_document  # noqa: E402
from rfq_copilot.core.rag.embedding import HashingEmbedder  # noqa: E402
from rfq_copilot.core.rag.pipeline import RAGPipeline  # noqa: E402
from rfq_copilot.core.rag.reranker import NoopReranker  # noqa: E402
from rfq_copilot.core.rag.spec_matcher import (  # noqa: E402
    SpecCriteria,
    chunk_matches_spec,
    extract_spec_criteria,
)
from rfq_copilot.core.rag.store import InMemoryVectorStore  # noqa: E402
from rfq_copilot.ports.knowledge_source import KnowledgeDocument  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "site"


def _chunk(params: dict[str, str] | None, content: str = "产品正文") -> Any:
    from rfq_copilot.core.rag.chunking import Chunk

    return Chunk(doc_id="d", chunk_index=0, title="产品", content=content, trust_level="merchant", params=params)


# ---------------------------------------------------------------------------
# 数据面
# ---------------------------------------------------------------------------


def test_params_threaded_through_chunking() -> None:
    doc = KnowledgeDocument(
        doc_id="p (1/1)",
        title="泵",
        doc_type="product",
        trust_level="merchant",
        content="正文",
        params={"抽速": "120 L/s", "无油": "是"},
    )
    chunks = chunk_document(doc)
    assert all(c.params == {"抽速": "120 L/s", "无油": "是"} for c in chunks)
    no_params = chunk_document(
        KnowledgeDocument(doc_id="f", title="f", doc_type="platform_faq", trust_level="platform", content="x")
    )
    assert all(c.params is None for c in no_params)


def test_export_products_carry_params() -> None:
    output = vacuum_b2b_export.build_documents(FIXTURES)
    products = [d for d in output.documents if d.doc_type == "product"]
    assert products, "fixture 必须产出产品文档"
    with_params = [d for d in products if d.params]
    assert with_params, "产品文档应携带结构化参数"
    assert all(isinstance(v, str) for d in with_params for v in (d.params or {}).values())


# ---------------------------------------------------------------------------
# 过滤语义
# ---------------------------------------------------------------------------


def test_chunk_matches_spec_pumping_speed() -> None:
    criteria = SpecCriteria(pumping_speed_min=100.0)
    assert chunk_matches_spec(_chunk({"抽速": "120 L/s"}), criteria) is True
    assert chunk_matches_spec(_chunk({"抽速": "65 L/s"}), criteria) is False
    # 缺参数 → 不可判定，不排除（回落保护由 pipeline 层负责）
    assert chunk_matches_spec(_chunk(None), criteria) is True
    assert chunk_matches_spec(_chunk({"功率": "1.5kW"}), criteria) is True


def test_chunk_matches_spec_oil_free_and_vacuum() -> None:
    oil = SpecCriteria(oil_free=True)
    assert chunk_matches_spec(_chunk({"无油": "是"}), oil) is True
    assert chunk_matches_spec(_chunk(None, content="无油螺杆泵工作原理"), oil) is True
    assert chunk_matches_spec(_chunk(None, content="旋片泵油润滑结构"), oil) is False
    vac = SpecCriteria(ultimate_vacuum_max=0.001)
    assert chunk_matches_spec(_chunk({"极限真空": "0.0005 Pa"}), vac) is True
    assert chunk_matches_spec(_chunk({"极限真空": "0.01 Pa"}), vac) is False


def test_extract_spec_criteria_from_entities() -> None:
    criteria = extract_spec_criteria({"抽速": "150 m³/h", "无油": "true", "x_region": "山东"})
    assert criteria.pumping_speed_min == 150.0
    assert criteria.oil_free is True
    assert criteria.extra == {"x_region": "山东"}
    assert criteria.is_empty is False


# ---------------------------------------------------------------------------
# 管线：过滤 + 回落保护
# ---------------------------------------------------------------------------


def _pipeline(docs: list[KnowledgeDocument], hybrid: bool = False) -> RAGPipeline:
    pipeline = RAGPipeline(
        embedder=HashingEmbedder(), store=InMemoryVectorStore(), reranker=NoopReranker(), hybrid=hybrid
    )
    chunks = [chunk for doc in docs for chunk in chunk_document(doc)]
    asyncio.run(pipeline.ingest(chunks))
    return pipeline


def test_pipeline_spec_filter_prefers_matching_chunks() -> None:
    docs = [
        KnowledgeDocument(
            doc_id="fast (1/1)",
            title="大泵",
            doc_type="product",
            trust_level="merchant",
            content="抽速 300 的大型真空泵设备介绍与选型要点",
            params={"抽速": "300 L/s"},
        ),
        KnowledgeDocument(
            doc_id="slow (1/1)",
            title="小泵",
            doc_type="product",
            trust_level="merchant",
            content="抽速 15 的小型真空泵设备介绍与选型要点",
            params={"抽速": "15 L/s"},
        ),
    ]
    pipeline = _pipeline(docs)
    spec = SpecCriteria(pumping_speed_min=100.0)
    final = asyncio.run(pipeline.search("抽速300的真空泵设备介绍", top_k=1, spec=spec))
    assert final[0].doc_id.startswith("fast")


def test_pipeline_spec_filter_fallback_when_insufficient() -> None:
    docs = [
        KnowledgeDocument(
            doc_id="a (1/1)",
            title="大泵",
            doc_type="product",
            trust_level="merchant",
            content="抽速300大型真空泵设备介绍",
            params={"抽速": "300 L/s"},
        ),
        KnowledgeDocument(
            doc_id="b (1/1)",
            title="慢速泵",
            doc_type="product",
            trust_level="merchant",
            content="抽速15小型真空泵设备介绍",
            params={"抽速": "15 L/s"},
        ),
        KnowledgeDocument(
            doc_id="c (1/1)",
            title="慢速泵二",
            doc_type="product",
            trust_level="merchant",
            content="抽速15小型真空泵设备介绍之二",
            params={"抽速": "15 L/s"},
        ),
    ]
    pipeline = _pipeline(docs)
    spec = SpecCriteria(pumping_speed_min=100.0)
    # top_k=3 > 过滤后候选 1 → 回落不过滤，返回 3 条
    final = asyncio.run(pipeline.search("真空泵设备介绍", top_k=3, spec=spec))
    assert len(final) == 3
