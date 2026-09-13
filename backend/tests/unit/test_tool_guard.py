"""T-013/T-014 补充测试：工具结果截断 + finish_reason 监控 + 前缀缓存对齐。"""

from rfq_copilot.core.eval.tool_guard import check_finish_reason, truncate_tool_result


def test_truncate_short_result_passthrough():
    assert truncate_tool_result("短结果", "search_products") == "短结果"


def test_truncate_long_result_appends_marker():
    long_text = "x" * 5000
    result = truncate_tool_result(long_text, "search_products", max_chars=100)
    assert len(result) < 200  # 100 + marker
    assert "截断" in result


def test_finish_reason_length_is_badcase():
    assert check_finish_reason("length", "s1") is True
    assert check_finish_reason("stop", "s1") is False
    assert check_finish_reason(None, "s1") is False
