"""QA-0003 回归：确认门行内编辑 resume 透传（draft_override → 白名单合并 → 落库）。

修复缺陷：前端 api.ts 发送 draft_override，但 ChatRequest 无该字段（extra=ignore 静默丢）、
main.py resume Command 不透传 → 行内编辑端到端不可达。修复后 ChatRequest 增补字段、
resume 携带透传（白名单合并规则见 docs/specs/03-api-spec「行内编辑回传」）。
"""

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from conftest import make_deps, understanding
from rfq_copilot.core.agent.graph import build_graph

pytestmark = pytest.mark.asyncio


async def test_resume_draft_override_quantity_applied() -> None:
    """QA 席建议断言：resume 带 draft_override.quantity=20 → inquiry_created 数量 20。"""
    deps, ports = make_deps(scripted=[understanding("product_inquiry", "inquiry_flow")])
    graph = build_graph(deps, checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "qa0003-a"}}
    await graph.ainvoke(
        {
            "session_id": "qa0003-a",
            "message": "询价 demo-p-001，10 台。",
            "quantity": 10,
            "product_id": "demo-p-001",
            "contact": {"name": "张三", "phone": "13800000000"},
        },
        config,
    )
    final = await graph.ainvoke(
        Command(resume={"action": "confirm_inquiry", "draft_override": {"quantity": 20}}),
        config,
    )
    assert "inquiry_created" in [e for e, _ in final["events"]]
    assert len(ports.store.inquiries) == 1
    assert ports.store.inquiries[0]["quantity"] == 20  # 行内编辑生效（原草稿 10）


async def test_resume_draft_override_invalid_values_ignored() -> None:
    """白名单外/不合法值静默忽略：quantity=-1 与未知键不落库、不炸流。"""
    deps, ports = make_deps(scripted=[understanding("product_inquiry", "inquiry_flow")])
    graph = build_graph(deps, checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "qa0003-b"}}
    await graph.ainvoke(
        {
            "session_id": "qa0003-b",
            "message": "询价 demo-p-001，10 台。",
            "quantity": 10,
            "product_id": "demo-p-001",
            "contact": {"name": "张三", "phone": "13800000000"},
        },
        config,
    )
    final = await graph.ainvoke(
        Command(
            resume={
                "action": "confirm_inquiry",
                "draft_override": {"quantity": -1, "hack_field": "<script>", "contact_name": "  "},
            }
        ),
        config,
    )
    assert "inquiry_created" in [e for e, _ in final["events"]]
    assert len(ports.store.inquiries) == 1
    assert ports.store.inquiries[0]["quantity"] == 10  # 非法 override 未生效
    assert ports.store.inquiries[0]["contact"]["name"] == "张三"  # 空白名未覆盖


async def test_resume_without_override_keeps_draft() -> None:
    """不携带 draft_override = 原草稿直接确认，行为不变（向后兼容）。"""
    deps, ports = make_deps(scripted=[understanding("product_inquiry", "inquiry_flow")])
    graph = build_graph(deps, checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "qa0003-c"}}
    await graph.ainvoke(
        {
            "session_id": "qa0003-c",
            "message": "询价 demo-p-001，10 台。",
            "quantity": 10,
            "product_id": "demo-p-001",
            "contact": {"name": "张三", "phone": "13800000000"},
        },
        config,
    )
    final = await graph.ainvoke(Command(resume={"action": "confirm_inquiry"}), config)
    assert "inquiry_created" in [e for e, _ in final["events"]]
    assert ports.store.inquiries[0]["quantity"] == 10
