"""Integration: 护栏在真实图流程里生效（脚本化分类器输出）。"""

import pytest

from conftest import make_deps, understanding
from rfq_copilot.core.agent.graph import build_graph

pytestmark = pytest.mark.asyncio


async def test_guard_reroutes_supplier_classification_to_products() -> None:
    deps, _ = make_deps(
        scripted=[understanding("supplier_search", "supplier_flow", entities={"product_category": "旋片式真空泵"})]
    )
    graph = build_graph(deps)
    final = await graph.ainvoke({"session_id": "guard-1", "message": "旋片式真空泵有哪些？"})
    assert final["route"] == "product_flow"
    assert "search_products" in final["tool_calls"]
    assert final["understanding"]["route_guard"] == "product_over_supplier"


async def test_guard_leaves_supplier_question_alone() -> None:
    deps, _ = make_deps(
        scripted=[understanding("supplier_search", "supplier_flow", entities={"product_category": "旋片真空泵"})]
    )
    graph = build_graph(deps)
    final = await graph.ainvoke({"session_id": "guard-2", "message": "旋片真空泵有哪些供应商？"})
    assert final["route"] == "supplier_flow"
    assert "get_suppliers" in final["tool_calls"]
