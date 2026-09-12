"""Integration: agent graph flows — refusal, confirmation gate, poisoning isolation."""

import pytest

from conftest import make_deps, understanding
from rfq_copilot.core.agent.graph import build_graph

pytestmark = pytest.mark.asyncio


async def test_price_fabrication_refused_deterministically() -> None:
    deps, _ = make_deps()  # deterministic shortcut: no LLM needed
    graph = build_graph(deps)
    final = await graph.ainvoke({"session_id": "s1", "message": "这台泵多少钱？给我个区间"})
    assert "提交询价" in final["answer"]
    assert "¥" not in final["answer"] and "元" not in final["answer"]
    assert final["tool_calls"] == []


async def test_lead_time_refused_deterministically() -> None:
    deps, _ = make_deps()
    graph = build_graph(deps)
    final = await graph.ainvoke({"session_id": "s2", "message": "这个多久能交货？"})
    assert "货期需供应商确认" in final["answer"]


async def test_inquiry_missing_required_fields_clarifies() -> None:
    deps, ports = make_deps(scripted=[understanding("product_inquiry", "inquiry_flow")])
    graph = build_graph(deps)
    final = await graph.ainvoke(
        {"session_id": "s3", "message": "我要询价 demo-p-001，10 台。", "quantity": 10, "product_id": "demo-p-001"}
    )
    assert "联系人" in final["answer"] or "联系方式" in final["answer"]
    assert ports.store.inquiries == []


async def test_confirmation_gate_full_flow() -> None:
    deps, ports = make_deps(scripted=[understanding("product_inquiry", "inquiry_flow")])
    graph = build_graph(deps)
    first = await graph.ainvoke(
        {
            "session_id": "s4",
            "message": "询价 demo-p-001，10 台。",
            "quantity": 10,
            "product_id": "demo-p-001",
            "contact": {"name": "张三", "phone": "13800000000"},
        }
    )
    names = [e for e, _ in first["events"]]
    assert "inquiry_confirm" in names and "inquiry_created" not in names
    assert ports.store.inquiries == []  # gate holds: nothing written before explicit confirm

    second = await graph.ainvoke({"session_id": "s4", "message": "", "action": "confirm_inquiry"})
    assert "inquiry_created" in [e for e, _ in second["events"]]
    assert len(ports.store.inquiries) == 1


async def test_confirmation_replay_is_idempotent() -> None:
    deps, ports = make_deps(scripted=[understanding("product_inquiry", "inquiry_flow")])
    graph = build_graph(deps)
    await graph.ainvoke(
        {
            "session_id": "s5",
            "message": "询价 demo-p-001，10 台。",
            "quantity": 10,
            "product_id": "demo-p-001",
            "contact": {"name": "张三", "phone": "13800000000"},
        }
    )
    await graph.ainvoke({"session_id": "s5", "message": "", "action": "confirm_inquiry"})
    await graph.ainvoke({"session_id": "s5", "message": "", "action": "confirm_inquiry"})
    assert len(ports.store.inquiries) == 1


async def test_product_flow_cites_and_neutral() -> None:
    deps, _ = make_deps(scripted=[understanding("product_inquiry", "product_flow")])
    graph = build_graph(deps)
    final = await graph.ainvoke({"session_id": "s6", "message": "有哪些真空泵？"})
    assert "search_products" in final["tool_calls"]
    assert "并列供参考" in final["answer"]


async def test_poisoned_knowledge_content_never_enters_answer() -> None:
    scripted = [understanding("product_inquiry", "knowledge_flow")]
    deps, _ = make_deps(scripted=scripted)
    graph = build_graph(deps)
    final = await graph.ainvoke({"session_id": "s7", "message": "无油泵采购避坑"})
    assert "全站最优" not in final["answer"]
    assert "6,800" not in final["answer"]
    assert "[1]" in final["answer"]  # short-ID citation present
    assert "（merchant）" in final["answer"] or "（platform）" in final["answer"]  # trust labeled


async def test_handoff_event_emitted() -> None:
    scripted = [understanding("complaint", "handoff_flow", needs_human=True, human_reason="complaint")]
    deps, _ = make_deps(scripted=scripted)
    graph = build_graph(deps)
    final = await graph.ainvoke({"session_id": "s8", "message": "我要投诉！"})
    assert ("handoff", {"reason": "complaint", "priority": "high"}) in final["events"]
