"""Unit: spec_match_flow 图级路由测试——05-structured-output-spec v1.1 激活的死链路由。

复用 conftest 的 FakeLLM/make_deps 惯例；高速泵桩目录用于命中 100 m³/h 硬条件
（demo 数据抽速上限 21 m³/h，100 的正向匹配在 demo 数据上必然走无匹配兜底）。
"""

import pytest

from conftest import make_deps, understanding
from rfq_copilot.core.agent.graph import build_graph, parse_understanding
from rfq_copilot.ports.product_catalog import (
    PriceDisplay,
    ProductDetail,
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
    card_names = [payload.get("name") for kind, payload in final["events"] if kind == "card"]
    assert "demo 高速泵 120 型" in card_names


async def test_spec_match_flow_empty_entities_clarifies() -> None:
    deps, _ = make_deps(scripted=[understanding("spec_inquiry", "spec_match_flow")])
    graph = build_graph(deps)
    final = await graph.ainvoke({"session_id": "sm2", "message": "帮我匹配一台泵"})
    assert "spec_match" in final["tool_calls"]
    assert "三个关键参数" in final["answer"] and "选型向导" in final["answer"]  # 教育式追问（04-prompt-spec v1.1）


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
    card_names = [payload.get("name") for kind, payload in final["events"] if kind == "card"]
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


# ---------------------------------------------------------------------------
# ADR-0009 D5：knowledge_flow 指代追问检索改写（实体补写）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_knowledge_retrieval_enriches_category_for_anaphora(monkeypatch) -> None:
    """「它适合什么场景？」+ 槽位实体罗茨泵 → 检索词补写品类（原样检索零语义）。"""
    deps, _ = make_deps(
        scripted=[
            understanding("spec_inquiry", "knowledge_flow", entities={"product_category": "罗茨泵"}),
            {"text_chunks": ["罗茨泵适合中低压差、大流量的场合。"]},
        ]
    )
    captured: list[str] = []
    original_search = deps.rag.search

    async def spy(query: str, top_k: int | None = None, spec: object = None):
        captured.append(query)
        return await original_search(query, top_k=top_k, spec=spec)

    monkeypatch.setattr(deps.rag, "search", spy)
    deps.store.append_message("d51", "user", "什么是罗茨泵？")
    deps.store.append_message("d51", "assistant", "罗茨泵是容积式真空泵。")
    graph = build_graph(deps)
    await graph.ainvoke({"session_id": "d51", "message": "它适合什么场景？"})
    assert captured, "knowledge_flow 未触发检索"
    assert "它适合什么场景" in captured[0]
    assert "罗茨泵" in captured[0]


@pytest.mark.asyncio
async def test_knowledge_retrieval_not_enriched_for_fresh_topic(monkeypatch) -> None:
    """不含指代词/场景标记的新话题 → 不补写（防陈旧实体污染检索）。"""
    deps, _ = make_deps(
        scripted=[
            understanding("spec_inquiry", "knowledge_flow", entities={"product_category": "罗茨泵"}),
            {"text_chunks": ["罗茨泵适合中低压差、大流量的场合。"]},
        ]
    )
    captured: list[str] = []
    original_search = deps.rag.search

    async def spy(query: str, top_k: int | None = None, spec: object = None):
        captured.append(query)
        return await original_search(query, top_k=top_k, spec=spec)

    monkeypatch.setattr(deps.rag, "search", spy)
    graph = build_graph(deps)
    await graph.ainvoke({"session_id": "d52", "message": "真空泵油雾分离器怎么换？"})
    assert captured
    assert captured[0] == "真空泵油雾分离器怎么换？"


async def test_spec_match_flow_emits_product_compare_card() -> None:
    deps, _ = make_deps(
        scripted=[understanding("spec_inquiry", "spec_match_flow", entities={"pumping_speed": "10 m3/h"})]
    )
    deps.catalog = _ScriptedCatalog()
    graph = build_graph(deps)
    final = await graph.ainvoke({"session_id": "sm5", "message": "我需要抽速 10 m3/h 以上的泵"})
    compare_cards = [p for k, p in final["events"] if k == "card" and p.get("kind") == "product_compare"]
    assert len(compare_cards) == 1
    card = compare_cards[0]
    assert card["criteria_summary"] == ["抽速 ≥ 10 m³/h"]
    assert card["products"], "对比卡必须带产品列"
    assert all(p["matched_on"] for p in card["products"])  # matched_on 全 grounded 非空
    assert card["rows"][0]["ok"] == [True] * len(card["products"])  # 硬条件排除语义 → 在榜全满足
    # 与产品卡并存（既有产品卡不互替）
    product_cards = [p for k, p in final["events"] if k == "card" and p.get("kind") == "product"]
    assert product_cards


async def test_spec_match_flow_empty_entities_educational_followup() -> None:
    """教育式追问：三要素讲解 + 每项示例格式 + 向导引导（04-prompt-spec v1.1）。"""
    deps, _ = make_deps(scripted=[understanding("spec_inquiry", "spec_match_flow")])
    graph = build_graph(deps)
    final = await graph.ainvoke({"session_id": "sm6", "message": "我要选泵"})
    assert final["route"] == "spec_match_flow"
    answer = final["answer"]
    # 三要素逐项带单位与示例格式
    assert "抽速" in answer and "m³/h" in answer and "如：抽速 ≥ 300 m³/h" in answer
    assert "极限真空" in answer and "Pa" in answer and "如：极限真空 ≤ 10 Pa" in answer
    assert "无油" in answer
    # 引导出口：向导表单 + 口语化描述
    assert "选型向导" in answer and "用途" in answer
    # 追问不开匹配：无产品搜索
    assert "search_products" not in final["tool_calls"] and "spec_match" in final["tool_calls"]


# ---------------------------------------------------------------------------
# compare_flow 数字产品 ID（2026-09-21 线上实测：真实目录主键为 312/180 等数字，
# 旧实现硬编码 demo-p-\d+ 致线上点名对比必失败；提取模式与路由守卫统一）
# ---------------------------------------------------------------------------

_NUM_A = ProductDetail(
    id="312",
    name="demo 分子泵机组 312",
    category_name="真空机组",
    brand_name="demo 品牌",
    supplier_id="demo-s-001",
    supplier_name="demo 供应商 1",
    specs={"抽速": "120 m³/h", "极限真空": "0.005 Pa"},
    price_display=PriceDisplay(mode="shown", text="¥1000.00"),
    url="/products/312",
    description="demo",
    params={},
)
_NUM_B = ProductDetail(
    id="180",
    name="demo 罗茨机组 180",
    category_name="真空机组",
    brand_name="demo 品牌",
    supplier_id="demo-s-001",
    supplier_name="demo 供应商 1",
    specs={"抽速": "80 m³/h", "极限真空": "0.01 Pa"},
    price_display=PriceDisplay(mode="contact", text="请联系供应商询价"),
    url="/products/180",
    description="demo",
    params={},
)


class _NumericDetailCatalog(_ScriptedCatalog):
    async def get_detail(self, product_id: str):
        return {"312": _NUM_A, "180": _NUM_B}.get(product_id)


async def test_compare_flow_accepts_numeric_product_ids() -> None:
    deps, _ = make_deps(scripted=[understanding("product_inquiry", "compare_flow", entities={})])
    deps.catalog = _NumericDetailCatalog()
    graph = build_graph(deps)
    final = await graph.ainvoke({"session_id": "cm1", "message": "对比 312 和 180"})
    compare_cards = [p for k, p in final["events"] if k == "card" and p.get("kind") == "product_compare"]
    assert len(compare_cards) == 1
    card = compare_cards[0]
    assert [p["name"] for p in card["products"]] == ["demo 分子泵机组 312", "demo 罗茨机组 180"]
    assert any(row["label"] == "抽速" for row in card["rows"])
    assert "参数对比" in final["answer"]


# ---------------------------------------------------------------------------
# P1-3 机组组合建议：高真空/大抽速工况 → RAG 摘录（grounded，不生成）
# ---------------------------------------------------------------------------

from rfq_copilot.core.rag.chunking import Chunk  # noqa: E402


class _StubRag:
    """最小 RAG 桩：记录检索词，固定返回一条平台级选型指南块。"""

    def __init__(self) -> None:
        self.last_query = ""

    async def search(self, query: str, top_k: int = 5, spec=None):
        self.last_query = query
        return [
            Chunk(
                doc_id="offline-solutions-1",
                chunk_index=0,
                title="高真空机组选型指南",
                content="高真空工况通常需要罗茨泵搭配前级泵组成机组，罗茨泵不能直接排气，需按前级抽速配比选择。",
                trust_level="platform",
            )
        ]


async def test_spec_match_high_vacuum_appends_system_suggestion() -> None:
    deps, _ = make_deps(
        scripted=[understanding("spec_inquiry", "spec_match_flow", entities={"ultimate_vacuum": "0.5 Pa"})]
    )
    deps.catalog = _ScriptedCatalog()
    rag = _StubRag()
    deps.rag = rag
    graph = build_graph(deps)
    final = await graph.ainvoke({"session_id": "sg1", "message": "我需要极限真空 0.5 Pa 的泵"})
    assert "search_knowledge" in final["tool_calls"]
    assert "系统建议" in final["answer"] and "罗茨" in final["answer"]
    assert "以供应商方案为准" in final["answer"]  # 中立免责句
    assert any(p.get("title") == "高真空机组选型指南" for k, p in final["events"] if k == "citation")
    assert "高真空" in rag.last_query  # 检索词随工况聚焦


async def test_spec_match_normal_spec_no_suggestion() -> None:
    deps, _ = make_deps(
        scripted=[understanding("spec_inquiry", "spec_match_flow", entities={"pumping_speed": "100 m3/h"})]
    )
    deps.catalog = _ScriptedCatalog()
    rag = _StubRag()
    deps.rag = rag
    graph = build_graph(deps)
    final = await graph.ainvoke({"session_id": "sg2", "message": "我需要抽速 100 m3/h 以上的泵"})
    assert "search_knowledge" not in final["tool_calls"]  # 非高真空/大抽速 → 不触发
    assert "系统建议" not in final["answer"]
