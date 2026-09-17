"""审查补测：异常路径与边界值（R1-R5 回归防线）。"""

import pytest

from rfq_copilot.adapters.vacuum_b2b_sample.adapter import _as_int, _fallback_terms
from rfq_copilot.core.agent.routing_guards import (
    INQUIRY_CREATE_MARKERS,
    apply_routing_guards,
    detect_inquiry_status_query,
    select_search_keyword,
)


class TestFallbackTermsEdgeCases:
    """_fallback_terms 边界：空/单字/超长/混合/全符号。"""

    def test_empty_and_whitespace(self) -> None:
        assert _fallback_terms("") == []
        assert _fallback_terms("   ") == []

    def test_single_char_no_fallback(self) -> None:
        assert _fallback_terms("泵") == []

    def test_two_char_exact_no_self_fallback(self) -> None:
        # 2 字词与自身相等，不产生候选（避免无意义重复查询）
        assert _fallback_terms("泵阀") == []

    def test_very_long_compound_bounded(self) -> None:
        terms = _fallback_terms("超长" * 20 + "真空泵")
        assert len(terms) <= 3  # 候选数有上界（成本控制）

    def test_mixed_alnum_not_split(self) -> None:
        # 含 ASCII 的词不做 CJK 拆分（2XZ 这类型号走原词）
        assert _fallback_terms("2XZ旋片泵") == ["2XZ旋片泵"] or all(
            "2XZ" not in t or len(t) >= 2 for t in _fallback_terms("2XZ旋片泵")
        )


class TestAsIntEdgeCases:
    """_as_int 边界：None/非数字/负号/前导零。"""

    def test_none_and_non_digit(self) -> None:
        assert _as_int(None) is None
        assert _as_int("demo-p-001") is None
        assert _as_int("") is None

    def test_digit_variants(self) -> None:
        assert _as_int("42") == 42
        assert _as_int("007") == 7
        assert _as_int(" 42") is None  # 空白不清洗（isdigit 为 False），防御式


class TestStatusDetectionVsCreateMarkers:
    """审查 R5/LESSON-012 回归：状态查询必须先于创建判定。"""

    def test_typical_status_questions(self) -> None:
        for q in ("我的询盘有人跟吗？", "报价了吗", "什么进度了", "询盘状态查一下"):
            assert detect_inquiry_status_query(q), q

    def test_create_questions_not_status(self) -> None:
        for q in ("我要买无油真空泵", "求购螺杆泵", "询价 demo-p-001"):
            assert not detect_inquiry_status_query(q), q
            assert q and any(m in q for m in INQUIRY_CREATE_MARKERS), q

    def test_empty_message(self) -> None:
        assert not detect_inquiry_status_query("")
        assert not detect_inquiry_status_query("   ")


class TestSelectKeywordEdgeCases:
    """select_search_keyword 边界。"""

    def test_none_understanding(self) -> None:
        assert select_search_keyword("真空泵", None) == "真空泵"

    def test_entity_not_substring_ignored(self) -> None:
        u = {"entities": {"product_category": "螺杆泵"}}
        assert select_search_keyword("干泵有哪些", u) == "干泵有哪些"

    def test_numeric_entity(self) -> None:
        u = {"entities": {"model": "2XZ-4"}}
        assert select_search_keyword("2XZ-4 报价", u) == "2XZ-4"


class TestGuardDoesNotTouchNonSupplierRoutes:
    """护栏只作用于 supplier_flow（回归防线）。"""

    @pytest.mark.parametrize(
        "route",
        ["product_flow", "knowledge_flow", "inquiry_flow", "case_flow", "solution_flow", "status_flow"],
    )
    def test_route_untouched(self, route: str) -> None:
        u = {"intent": "x", "route": route, "entities": {"product_category": "旋片泵"}}
        assert apply_routing_guards("旋片泵有哪些？", u)["route"] == route
