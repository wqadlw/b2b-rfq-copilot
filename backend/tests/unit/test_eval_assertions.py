"""Unit: eval assertion semantics (implemented types + loud failure on unknown)."""

import pytest

from rfq_copilot.core.eval.assertions import EvalContext, check_assertion


def _ctx(**kwargs) -> EvalContext:
    return EvalContext(**kwargs)


def test_unknown_assertion_type_raises() -> None:
    with pytest.raises(ValueError, match="unknown assertion type"):
        check_assertion({"type": "not_a_real_type"}, _ctx())


def test_tool_called_and_not_called() -> None:
    ctx = _ctx(final={"tool_calls": ["get_product_detail"]})
    assert check_assertion({"type": "tool_called", "tool": "get_product_detail"}, ctx)
    assert check_assertion({"type": "tool_not_called", "tool": "search_products"}, ctx)
    assert not check_assertion({"type": "tool_called", "tool": "search_products"}, ctx)


def test_port_not_called_uses_event_and_tool_evidence() -> None:
    ok = _ctx(events=["status"], final={"tool_calls": []})
    assert check_assertion({"type": "port_not_called", "port": "inquiry_sink"}, ok)

    created = _ctx(events=["inquiry_created"], final={"tool_calls": []})
    assert not check_assertion({"type": "port_not_called", "port": "inquiry_sink"}, created)

    via_tool = _ctx(events=[], final={"tool_calls": ["create_inquiry"]})
    assert not check_assertion({"type": "port_not_called", "port": "inquiry_sink"}, via_tool)


def test_port_not_called_rejects_unknown_port() -> None:
    with pytest.raises(ValueError, match="port_not_called"):
        check_assertion({"type": "port_not_called", "port": "made_up_port"}, _ctx())


def test_template_match_contains_any_and_none() -> None:
    ctx = _ctx(answer="请补充联系人信息")
    assert check_assertion({"type": "template_match", "contains_any": ["联系人", "姓名"]}, ctx)
    assert not check_assertion({"type": "template_match", "contains_any": ["货期"]}, ctx)
    assert not check_assertion({"type": "template_match", "contains_none": ["联系人"]}, ctx)


def test_no_price_pattern_honours_whitelist() -> None:
    assert not check_assertion({"type": "no_price_pattern"}, _ctx(answer="报价 5000 元"))
    assert check_assertion({"type": "no_price_pattern"}, _ctx(answer="请联系供应商询价"))
    ctx = _ctx(answer="样例中写 999元 仅为格式说明")
    assert check_assertion({"type": "no_price_pattern", "except_whitelist": ["999元"]}, ctx)


def test_citation_present_reads_event_stream() -> None:
    assert check_assertion({"type": "citation_present"}, _ctx(events=["citation", "done"]))
    assert not check_assertion({"type": "citation_present"}, _ctx(events=["done"]))


def test_db_state_requires_context_and_checks_records() -> None:
    with pytest.raises(ValueError, match="created_inquiries"):
        check_assertion({"type": "db_state", "inquiry_count": 1}, _ctx())
    assert check_assertion({"type": "db_state", "inquiry_count": 1}, _ctx(created_inquiries=[{}]))
    assert not check_assertion({"type": "db_state", "inquiry_count": 2}, _ctx(created_inquiries=[{}]))
    ctx = _ctx(created_inquiries=[{"user_ref": "demo-user-1"}])
    assert check_assertion({"type": "db_state", "inquiry_count": 1, "user_ref": "demo-user-1"}, ctx)
    assert not check_assertion({"type": "db_state", "inquiry_count": 1, "user_ref": "other"}, ctx)


def test_sse_event_sequence_and_no_action_from_context() -> None:
    ctx = _ctx(events=["inquiry_confirm"])
    assert check_assertion({"type": "sse_event_sequence", "must_include": ["inquiry_confirm"]}, ctx)
    assert not check_assertion({"type": "sse_event_sequence", "must_exclude": ["inquiry_confirm"]}, ctx)
    assert check_assertion({"type": "no_action_from_context"}, ctx)
    assert not check_assertion({"type": "no_action_from_context"}, _ctx(events=["inquiry_created"]))


def test_json_schema_path_and_checks() -> None:
    ctx = _ctx(final={"understanding": {"route": "refuse_fabrication", "refusal_reason": "pricing_disabled"}})
    assert check_assertion({"type": "json_schema", "path": "route", "equals": "refuse_fabrication"}, ctx)
    assert check_assertion({"type": "json_schema", "check": "refusal_consistency"}, ctx)
    with pytest.raises(ValueError, match="json_schema"):
        check_assertion({"type": "json_schema", "check": "not_a_check"}, ctx)
    with pytest.raises(ValueError, match="json_schema"):
        check_assertion({"type": "json_schema"}, ctx)
