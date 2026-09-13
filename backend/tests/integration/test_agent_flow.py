"""Integration: agent graph flows — refusal, confirmation gate, poisoning isolation."""

import contextlib

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

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


async def test_confirmation_gate_interrupt_and_resume() -> None:
    deps, ports = make_deps(scripted=[understanding("product_inquiry", "inquiry_flow")])
    graph = build_graph(deps, checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "s4"}}
    first = await graph.ainvoke(
        {
            "session_id": "s4",
            "message": "询价 demo-p-001，10 台。",
            "quantity": 10,
            "product_id": "demo-p-001",
            "contact": {"name": "张三", "phone": "13800000000"},
        },
        config,
    )
    interrupts = first.get("__interrupt__") or []
    assert interrupts, "expected graph to pause on confirmation gate"
    assert interrupts[0].value["confirm_id"]
    assert ports.store.inquiries == []  # gate holds: nothing written before explicit confirm

    second = await graph.ainvoke(Command(resume={"action": "confirm_inquiry"}), config)
    assert "inquiry_created" in [e for e, _ in second["events"]]
    assert len(ports.store.inquiries) == 1


async def test_confirmation_cancel_writes_nothing() -> None:
    deps, ports = make_deps(scripted=[understanding("product_inquiry", "inquiry_flow")])
    graph = build_graph(deps, checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "s5"}}
    await graph.ainvoke(
        {
            "session_id": "s5",
            "message": "询价 demo-p-001，10 台。",
            "quantity": 10,
            "product_id": "demo-p-001",
            "contact": {"name": "张三", "phone": "13800000000"},
        },
        config,
    )
    final = await graph.ainvoke(Command(resume={"action": "cancel_inquiry"}), config)
    assert "inquiry_created" not in [e for e, _ in final["events"]]
    assert "已取消" in final["answer"]
    assert ports.store.inquiries == []


async def test_confirmation_idempotent_after_completion() -> None:
    deps, ports = make_deps(scripted=[understanding("product_inquiry", "inquiry_flow")])
    graph = build_graph(deps, checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "s6"}}
    state = {
        "session_id": "s6",
        "message": "询价 demo-p-001，10 台。",
        "quantity": 10,
        "product_id": "demo-p-001",
        "contact": {"name": "张三", "phone": "13800000000"},
    }
    await graph.ainvoke(state, config)
    await graph.ainvoke(Command(resume={"action": "confirm_inquiry"}), config)
    # resuming a completed thread must not create a second inquiry
    with contextlib.suppress(Exception):  # langgraph raises when no interrupt is pending
        await graph.ainvoke(Command(resume={"action": "confirm_inquiry"}), config)
    assert len(ports.store.inquiries) == 1


async def test_multi_turn_memory_accumulates_history() -> None:
    scripted = [
        understanding("product_inquiry", "product_flow"),
        understanding("product_inquiry", "product_flow"),
        understanding("product_inquiry", "inquiry_flow"),
    ]
    deps, _ = make_deps(scripted=scripted)
    graph = build_graph(deps)
    await graph.ainvoke({"session_id": "s7", "message": "找无油泵"}, {"configurable": {"thread_id": "x"}})
    await graph.ainvoke({"session_id": "s7", "message": "抽速 100 的"}, {"configurable": {"thread_id": "x"}})
    assert len(deps.store.messages("s7")) == 2  # 用户侧消息由 understand 节点落库；助手侧在 mapper
    assert len(deps.llm.calls) == 2
    second_prompt = deps.llm.calls[1][1]
    assert "找无油泵" in second_prompt  # 前轮内容进入后续提示词 = 实体累积


async def test_product_flow_cites_and_neutral() -> None:
    deps, _ = make_deps(scripted=[understanding("product_inquiry", "product_flow")])
    graph = build_graph(deps)
    final = await graph.ainvoke({"session_id": "s6", "message": "有哪些真空泵？"})
    assert "search_products" in final["tool_calls"]
    assert "并列供参考" in final["answer"]


async def test_poisoned_knowledge_content_never_enters_answer() -> None:
    scripted = [
        understanding("product_inquiry", "knowledge_flow"),
        {"text_chunks": ["无油泵适合实验室与洁净车间，需关注抽速与极限真空的匹配。"]},
    ]
    deps, _ = make_deps(scripted=scripted)
    graph = build_graph(deps)
    final = await graph.ainvoke({"session_id": "s7", "message": "无油泵采购避坑"})
    assert "全站最优" not in final["answer"]
    assert "6,800" not in final["answer"]
    citation_events = [e for e, _ in final["events"] if e == "citation"]
    assert citation_events, "citation 事件必须存在（信任分级来源标注）"


async def test_handoff_event_emitted() -> None:
    scripted = [understanding("complaint", "handoff_flow", needs_human=True, human_reason="complaint")]
    deps, _ = make_deps(scripted=scripted)
    graph = build_graph(deps)
    final = await graph.ainvoke({"session_id": "s8", "message": "我要投诉！"})
    assert ("handoff", {"reason": "complaint", "priority": "high"}) in final["events"]
