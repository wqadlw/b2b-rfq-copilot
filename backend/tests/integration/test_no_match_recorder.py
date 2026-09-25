"""no_match 缺口事件记录（spec 02 §1.2，N2）：graph 两处精确分支的集成验证。

记录器经 GraphDeps.no_match_recorder 注入（SSE 事件名冻结契约 QA-0006，不走事件通道）。
"""

import pytest

from conftest import make_deps, understanding
from rfq_copilot.core.agent.graph import build_graph
from rfq_copilot.core.rag.embedding import HashingEmbedder
from rfq_copilot.core.rag.pipeline import RAGPipeline
from rfq_copilot.core.rag.reranker import NoopReranker
from rfq_copilot.core.rag.store import InMemoryVectorStore

pytestmark = pytest.mark.asyncio


async def test_product_flow_zero_result_records_no_match() -> None:
    deps, _ = make_deps(scripted=[understanding("product_inquiry", "product_flow")])
    events: list[dict] = []
    deps.no_match_recorder = events.append
    graph = build_graph(deps)
    final = await graph.ainvoke({"session_id": "s1", "message": "磁悬浮泵"})
    assert "暂未找到匹配产品" in final["answer"]
    assert len(events) == 1
    record = events[0]
    assert record["route"] == "product_flow"
    assert record["session_id"] == "s1"
    assert record["question"] == "磁悬浮泵"


async def test_knowledge_flow_zero_recall_records_no_match() -> None:
    # 第二个脚本项 = respond 节点的流式回答（knowledge_flow 走 LLM stream_text）
    deps, _ = make_deps(scripted=[understanding("product_inquiry", "knowledge_flow"), {"text_chunks": ["回答。"]}])
    events: list[dict] = []
    deps.no_match_recorder = events.append
    # 空库：任何查询零召回
    deps.rag = RAGPipeline(embedder=HashingEmbedder(), store=InMemoryVectorStore(), reranker=NoopReranker())
    graph = build_graph(deps)
    await graph.ainvoke({"session_id": "s2", "message": "帮我讲讲磁悬浮泵的原理"})
    assert len(events) == 1
    record = events[0]
    assert record["route"] == "knowledge_flow"
    assert record["keyword"]  # 检索词随事件透出（供缺口聚类）


async def test_product_flow_with_results_records_nothing() -> None:
    deps, _ = make_deps(scripted=[understanding("product_inquiry", "product_flow")])
    events: list[dict] = []
    deps.no_match_recorder = events.append
    graph = build_graph(deps)
    await graph.ainvoke({"session_id": "s3", "message": "旋片真空泵"})
    assert events == []
