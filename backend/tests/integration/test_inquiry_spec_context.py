"""P1-4 询盘工况带入：spec_match 提取的规格跨轮累积，询盘时并入 params 与确认话术。"""

from types import SimpleNamespace

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from conftest import make_deps, understanding
from rfq_copilot.core.agent.graph import build_graph


class _EmptyCatalog:
    """空产品目录：spec_match 走 no-match 分支即可，重点验证 spec_context 流转。"""

    async def search(self, query):  # noqa: ANN001, ANN202
        return SimpleNamespace(items=[])

    async def get_detail(self, product_id):  # noqa: ANN001, ANN202
        return None


def _make_graph(scripted):
    deps, ports = make_deps(scripted=scripted)
    deps.catalog = _EmptyCatalog()
    graph = build_graph(deps, checkpointer=MemorySaver())
    return graph, deps, ports


async def test_spec_context_flows_into_inquiry_params() -> None:
    scripted = [
        understanding("spec_inquiry", "spec_match_flow", entities={"pumping_speed": "300 m3/h"}),
        understanding("product_inquiry", "inquiry_flow"),
    ]
    graph, _deps, ports = _make_graph(scripted)
    config = {"configurable": {"thread_id": "p14a"}}
    await graph.ainvoke({"session_id": "p14a", "message": "我需要抽速 300 m3/h 的泵"}, config)
    first = await graph.ainvoke(
        {
            "session_id": "p14a",
            "message": "帮我发起询盘",
            "contact": {"name": "张三", "phone": "13800000000"},
        },
        config,
    )
    # 确认面板载荷（interrupt pending）带工况；确认话术同源 spec_bits
    import json as _json

    pending = first["__interrupt__"][0].value
    assert "pumping_speed" in pending["draft_json"]
    assert _json.loads(pending["draft_json"])["params"].get("pumping_speed") == "300 m3/h"
    second = await graph.ainvoke(Command(resume={"action": "confirm_inquiry"}), config)
    assert "inquiry_created" in [e for e, _ in second["events"]]
    assert len(ports.store.inquiries) == 1
    # 工况落入询盘单（供应商拿得到，不再是空参数单）
    assert ports.store.inquiries[0]["params"].get("pumping_speed") == "300 m3/h"


async def test_current_turn_entities_override_accumulated_context() -> None:
    """同句改口：快捷路由确定性扫描捕获"抽速 500 m3/h"，覆盖历史 context 的 300。"""
    scripted = [
        understanding("spec_inquiry", "spec_match_flow", entities={"pumping_speed": "300 m3/h"}),
        understanding("product_inquiry", "inquiry_flow"),  # 快捷路由 0-token，不消费此条
    ]
    graph, _deps, ports = _make_graph(scripted)
    config = {"configurable": {"thread_id": "p14b"}}
    await graph.ainvoke({"session_id": "p14b", "message": "我需要抽速 300 m3/h 的泵"}, config)
    await graph.ainvoke(
        {
            "session_id": "p14b",
            "message": "改成抽速 500 m3/h，帮我发起询盘",
            "contact": {"name": "李四", "phone": "13900000000"},
        },
        config,
    )
    await graph.ainvoke(Command(resume={"action": "confirm_inquiry"}), config)
    assert ports.store.inquiries[0]["params"].get("pumping_speed") == "500 m3/h"  # 当前轮优先


async def test_inquiry_without_specs_unchanged() -> None:
    scripted = [understanding("product_inquiry", "inquiry_flow")]
    graph, _deps, ports = _make_graph(scripted)
    config = {"configurable": {"thread_id": "p14c"}}
    first = await graph.ainvoke(
        {
            "session_id": "p14c",
            "message": "询盘 demo-p-001",
            "contact": {"name": "王五", "phone": "13900000000"},
        },
        config,
    )
    assert "confirm_id" in first["__interrupt__"][0].value  # 正常进确认门
    await graph.ainvoke(Command(resume={"action": "confirm_inquiry"}), config)
    assert len(ports.store.inquiries) == 1
