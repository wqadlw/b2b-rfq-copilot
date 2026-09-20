"""Unit: spec_match_flow 图级路由测试——05-structured-output-spec v1.1 激活的死链路由。

复用 conftest 的 FakeLLM/make_deps 惯例；高速泵桩目录用于命中 100 m³/h 硬条件
（demo 数据抽速上限 21 m³/h，100 的正向匹配在 demo 数据上必然走无匹配兜底）。
"""

import pytest

from conftest import make_deps, understanding
from rfq_copilot.core.agent.graph import build_graph, parse_understanding
from rfq_copilot.ports.product_catalog import (
    PriceDisplay,
    ProductSearchQuery,
    ProductSearchResult,
    ProductSummary,
)

_HIGH_SPEED_PUMP = ProductSummary(
    id="demo-p-901",
    name="demo 高速泵 120 型",
    category_name="真空泵",
    brand_name="demo 品牌",
    supplier_id="demo-s-001",
    supplier_name="demo 供应商 1",
    specs={"抽速": "120 m³/h"},
    price_display=PriceDisplay(mode="contact", text="请联系供应商询价"),
    url="/products/demo-p-901",
)
_SLOW_PUMP = ProductSummary(
    id="demo-p-902",
    name="demo 低速泵 080 型",
    category_name="真空泵",
    brand_name="demo 品牌",
    supplier_id="demo-s-001",
    supplier_name="demo 供应商 1",
    specs={"抽速": "80 m³/h"},
    price_display=PriceDisplay(mode="contact", text="请联系供应商询价"),
    url="/products/demo-p-902",
)


class _ScriptedCatalog:
    """最小目录桩：注入一台抽速 120 m³/h 的泵，使 100 m³/h 硬条件可正向命中。"""

    async def search(self, query: ProductSearchQuery) -> ProductSearchResult:
        return ProductSearchResult(items=[_SLOW_PUMP, _HIGH_SPEED_PUMP], total=2)

    async def get_detail(self, product_id: str) -> None:
        return None  # spec_match 分支不消费 detail；仅为满足 manifest 的 detail 特性注册


def test_parse_understanding_accepts_spec_match_flow() -> None:
    raw = {
        "intent": "spec_inquiry",
        "confidence": 0.95,
        "route": "spec_match_flow",
        "entities": {"pumping_speed": "100 m3/h"},
    }
    u = parse_understanding(raw)
    assert u["route"] == "spec_match_flow"  # 死链已解除：不再被强制降级为 clarify
    assert u["needs_clarification"] is False


async def test_spec_match_flow_reaches_respond_and_matches() -> None:
    deps, _ = make_deps(
        scripted=[understanding("spec_inquiry", "spec_match_flow", entities={"pumping_speed": "100 m3/h"})]
    )
    deps.catalog = _ScriptedCatalog()
    graph = build_graph(deps)
    final = await graph.ainvoke({"session_id": "sm1", "message": "我需要抽速 100 m3/h 以上的泵"})
    assert "spec_match" in final["tool_calls"]
    assert "匹配到" in final["answer"] and "卡片" in final["answer"]
    # 新设计：产品数据交给卡片事件，文本不再复读产品名（数据/文本分层）
    card_names = [payload["name"] for kind, payload in final["events"] if kind == "card"]
    assert "demo 高速泵 120 型" in card_names


async def test_spec_match_flow_empty_entities_clarifies() -> None:
    deps, _ = make_deps(scripted=[understanding("spec_inquiry", "spec_match_flow")])
    graph = build_graph(deps)
    final = await graph.ainvoke({"session_id": "sm2", "message": "帮我匹配一台泵"})
    assert "spec_match" in final["tool_calls"]
    assert "请告诉我您需要的规格参数" in final["answer"]


async def test_spec_match_flow_no_match_falls_back_to_closest() -> None:
    deps, _ = make_deps(
        scripted=[understanding("spec_inquiry", "spec_match_flow", entities={"pumping_speed": "999 m3/h"})]
    )
    graph = build_graph(deps)
    final = await graph.ainvoke({"session_id": "sm3", "message": "我需要抽速 999 m3/h 的泵"})
    assert "spec_match" in final["tool_calls"]
    assert "接近的产品" in final["answer"]


async def test_spec_match_flow_matches_real_demo_data() -> None:
    deps, _ = make_deps(
        scripted=[understanding("spec_inquiry", "spec_match_flow", entities={"pumping_speed": "10 m3/h"})]
    )
    graph = build_graph(deps)
    final = await graph.ainvoke({"session_id": "sm4", "message": "我需要抽速 10 m3/h 以上的泵"})
    assert "spec_match" in final["tool_calls"]
    assert "匹配到" in final["answer"] and "卡片" in final["answer"]
    card_names = [payload["name"] for kind, payload in final["events"] if kind == "card"]
    assert any("demo 设备" in name for name in card_names)


# ---------------------------------------------------------------------------
# ADR-0008 D2：knowledge_flow 回答注入对话历史
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_knowledge_answer_includes_conversation_history() -> None:
    """knowledge_flow 的回答 LLM user 段必须包含历史轮次（多轮指代可解析）。"""
    deps, _ = make_deps(
        scripted=[
            understanding("spec_inquiry", "knowledge_flow"),
            {"text_chunks": ["无油泵免维护，适合洁净环境。"]},
        ]
    )
    # 预置两轮历史（本轮 user 消息由 understand 节点自行 append）
    deps.store.append_message("kh1", "user", "什么是无油泵？")
    deps.store.append_message("kh1", "assistant", "无油泵是不使用真空油的泵型。")
    graph = build_graph(deps)
    await graph.ainvoke({"session_id": "kh1", "message": "它适合什么场景？"})
    # FakeLLM.calls: [(understand system, user), (answer system, user)]
    answer_user = deps.llm.calls[-1][1]
    assert "【对话历史（最近轮次）】" in answer_user
    assert "什么是无油泵？" in answer_user  # 上一轮问题在历史里
    assert "【问题】它适合什么场景？" in answer_user


@pytest.mark.asyncio
async def test_knowledge_answer_first_turn_has_no_history_block() -> None:
    """首轮（无历史）不输出空历史段——保持 prompt 干净。"""
    deps, _ = make_deps(
        scripted=[
            understanding("spec_inquiry", "knowledge_flow"),
            {"text_chunks": ["首轮回答。"]},
        ]
    )
    graph = build_graph(deps)
    await graph.ainvoke({"session_id": "kh2", "message": "真空泵怎么选？"})
    answer_user = deps.llm.calls[-1][1]
    assert "【对话历史" not in answer_user
    assert "【问题】真空泵怎么选？" in answer_user
