"""Unit: 确定性路由护栏（产品问法 vs 供应商问法）。"""

from rfq_copilot.core.agent.routing_guards import apply_routing_guards


def _u(route: str, **entities: object) -> dict:
    return {"intent": "supplier_search", "route": route, "entities": dict(entities), "confidence": 0.8}


def test_product_question_with_category_switches_to_product_flow() -> None:
    got = apply_routing_guards("旋片式真空泵有哪些？", _u("supplier_flow", product_category="旋片式真空泵"))
    assert got["route"] == "product_flow"
    assert got["intent"] == "product_inquiry"
    assert got["route_guard"] == "product_over_supplier"
    assert got["route_guard_from"] == {"intent": "supplier_search", "route": "supplier_flow"}


def test_supplier_focus_is_respected() -> None:
    for message in ("旋片真空泵有哪些供应商？", "无油真空泵哪家做", "水环泵厂家推荐", "找真空泵渠道"):
        got = apply_routing_guards(message, _u("supplier_flow", product_category="旋片真空泵"))
        assert got["route"] == "supplier_flow", message
        assert "route_guard" not in got


def test_missing_product_category_is_respected() -> None:
    got = apply_routing_guards("有哪些供应商？", _u("supplier_flow"))
    assert got["route"] == "supplier_flow" and "route_guard" not in got


def test_non_product_question_is_respected() -> None:
    got = apply_routing_guards("帮我联系一下供应商", _u("supplier_flow", product_category="真事泵"))
    assert got["route"] == "supplier_flow" and "route_guard" not in got


def test_other_routes_untouched() -> None:
    for route in ("product_flow", "knowledge_flow", "inquiry_flow", "clarify", "handoff_flow"):
        got = apply_routing_guards("旋片式真空泵有哪些？", _u(route, product_category="旋片式真空泵"))
        assert got["route"] == route and "route_guard" not in got


def test_input_not_mutated() -> None:
    original = _u("supplier_flow", product_category="旋片真空泵")
    snapshot = dict(original)
    apply_routing_guards("旋片真空泵有哪些", original)
    assert original == snapshot

# ---------------------------------------------------------------------------
# ADR-0008 D1：选型问法护栏（selection_over_search）
# ---------------------------------------------------------------------------

from rfq_copilot.core.agent.routing_guards import apply_selection_guard  # noqa: E402


def test_selection_question_switches_to_knowledge_flow() -> None:
    """「无油泵和旋片泵怎么选？」是类型级选型咨询 → knowledge_flow（RAG 作答）。"""
    got = apply_selection_guard("无油泵和旋片泵怎么选？", _u("product_flow"))
    assert got["route"] == "knowledge_flow"
    assert got["route_guard"] == "selection_over_search"
    assert got["route_guard_from"]["route"] == "product_flow"


def test_selection_guard_covers_all_search_routes() -> None:
    for route in ("product_flow", "selection_flow", "compare_flow"):
        got = apply_selection_guard("旋片泵和干式螺杆泵有什么区别", _u(route))
        assert got["route"] == "knowledge_flow"


def test_two_product_ids_stay_in_compare_flow() -> None:
    """点名两个具体产品 → compare_flow 合法场景，不拦截。"""
    message = "对比 demo-p-001 和 demo-p-002 哪个好"
    got = apply_selection_guard(message, _u("compare_flow"))
    assert got["route"] == "compare_flow"
    assert "route_guard" not in got


def test_non_selection_question_is_respected() -> None:
    """无选型标记词的路由不受影响。"""
    got = apply_selection_guard("帮我找无油旋片泵", _u("product_flow"))
    assert got["route"] == "product_flow"


def test_knowledge_and_other_routes_not_touched() -> None:
    got = apply_selection_guard("无油泵和旋片泵怎么选？", _u("knowledge_flow"))
    assert got["route"] == "knowledge_flow"
    assert "route_guard" not in got


def test_selection_guard_does_not_mutate_input() -> None:
    original = _u("product_flow")
    snapshot = dict(original)
    apply_selection_guard("无油泵和旋片泵怎么选？", original)
    assert original == snapshot
