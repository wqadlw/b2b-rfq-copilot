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


# ---------------------------------------------------------------------------
# B5：select_search_keyword 头二字放宽（LLM 规范化实体 vs 用户口语说法）
# ---------------------------------------------------------------------------

from rfq_copilot.core.agent.routing_guards import select_search_keyword  # noqa: E402


def test_normalized_category_entity_accepted_via_head_bigram() -> None:
    """用户说「无油泵」，LLM 规范化实体为「无油真空泵」→ 采纳实体（勿整句搜索）。"""
    understanding = {"entities": {"product_category": "无油真空泵"}}
    got = select_search_keyword("有哪些无油泵适合实验室？", understanding)
    assert got == "无油真空泵"


def test_exact_containment_still_preferred() -> None:
    understanding = {"entities": {"product_category": "旋片泵"}}
    got = select_search_keyword("帮我找旋片泵", understanding)
    assert got == "旋片泵"


def test_stale_entity_with_unrelated_head_rejected() -> None:
    """陈旧实体的头二字不在本轮消息中 → 拒绝，退回原消息。"""
    understanding = {"entities": {"product_category": "罗茨泵"}}
    got = select_search_keyword("有哪些无油泵适合实验室？", understanding)
    assert got == "有哪些无油泵适合实验室？"


def test_no_entities_falls_back_to_message() -> None:
    assert select_search_keyword("有哪些无油泵？", None) == "有哪些无油泵？"


# ---------------------------------------------------------------------------
# ADR-0009 D4：场景类追问护栏（scenario_over_clarify）
# ---------------------------------------------------------------------------

from rfq_copilot.core.agent.routing_guards import apply_scenario_followup_guard  # noqa: E402

_HIST = [
    {"role": "user", "content": "什么是罗茨泵？"},
    {"role": "assistant", "content": "罗茨泵是一种容积式真空泵。"},
]


def test_scenario_followup_switches_to_knowledge_flow() -> None:
    got = apply_scenario_followup_guard("它适合什么场景？", _u("selection_flow"), _HIST)
    assert got["route"] == "knowledge_flow"
    assert got["route_guard"] == "scenario_over_clarify"
    assert got["route_guard_from"]["route"] == "selection_flow"


def test_scenario_guard_covers_marker_variants() -> None:
    for msg in ("它用在哪？", "罗茨泵的应用场景是什么", "这泵适合什么行业？"):
        got = apply_scenario_followup_guard(msg, _u("selection_flow"), _HIST)
        assert got["route"] == "knowledge_flow"


def test_scenario_guard_requires_history() -> None:
    """首轮场景问题（无历史）不拦——留给意图分类器。"""
    got = apply_scenario_followup_guard("罗茨泵适合什么场景？", _u("selection_flow"), [])
    assert got["route"] == "selection_flow"
    assert "route_guard" not in got


def test_scenario_guard_requires_product_context_in_history() -> None:
    """历史无产品语境（闲聊）不拦。"""
    chat_hist = [{"role": "user", "content": "你好"}, {"role": "assistant", "content": "您好！"}]
    got = apply_scenario_followup_guard("它适合什么场景？", _u("selection_flow"), chat_hist)
    assert got["route"] == "selection_flow"


def test_scenario_guard_only_touches_selection_flow() -> None:
    for route in ("product_flow", "compare_flow", "knowledge_flow"):
        got = apply_scenario_followup_guard("它适合什么场景？", _u(route), _HIST)
        assert got["route"] == route
        assert "route_guard" not in got


def test_scenario_guard_respects_existing_guard() -> None:
    u = {**_u("selection_flow"), "route_guard": "selection_over_search"}
    got = apply_scenario_followup_guard("它适合什么场景？", u, _HIST)
    assert got["route_guard"] == "selection_over_search"  # 不覆盖前序护栏


def test_scenario_guard_does_not_mutate_input() -> None:
    u = _u("selection_flow")
    snapshot = dict(u)
    apply_scenario_followup_guard("它适合什么场景？", u, _HIST)
    assert u == snapshot
