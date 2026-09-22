"""SSE mapper: inquiry_confirm draft object flattening + done.follow_ups (contract: 03-api-spec §2)."""

import json

from rfq_copilot.app.sse_mapper import _draft_payload, _follow_ups


def _draft_json(product_id: str | None, quantity: int | None, name: str, phone: str) -> str:
    draft = {
        "product_id": product_id,
        "quantity": quantity,
        "contact": {"name": name, "phone": phone},
    }
    return json.dumps(draft, ensure_ascii=False)


def test_draft_payload_flattens_for_confirmation_card() -> None:
    data = _draft_payload(_draft_json("demo-p-001", 10, "张三", "13800000000"))
    assert data["product_id"] == "demo-p-001"
    assert data["quantity"] == 10
    assert data["contact_name"] == "张三"
    assert data["contact_phone_masked"] == "138****0000"


def test_draft_payload_masks_short_phone_verbatim() -> None:
    data = _draft_payload(_draft_json("demo-p-002", 1, "李四", "123"))
    assert data["contact_phone_masked"] == "123"


def test_draft_payload_invalid_json_returns_empty() -> None:
    assert _draft_payload("not-json{") == {}


def test_draft_payload_non_dict_json_returns_empty() -> None:
    assert _draft_payload("[1, 2]") == {}


def test_draft_payload_empty_string_returns_empty() -> None:
    assert _draft_payload("") == {}


def test_draft_payload_includes_specs_summary_when_params_present() -> None:
    draft = {
        "product_id": None,
        "quantity": None,
        "params": {"pumping_speed": "300 m³/h", "ultimate_vacuum": "5 Pa"},
        "contact": {"name": "张三", "phone": "13800000000"},
    }
    data = _draft_payload(json.dumps(draft, ensure_ascii=False))
    assert data["specs"] == "抽速 300 m³/h；极限真空 5 Pa"


def test_draft_payload_specs_none_without_params() -> None:
    data = _draft_payload(_draft_json("demo-p-001", 10, "张三", "13800000000"))
    assert data["specs"] is None


def test_follow_ups_by_route_capped_at_two() -> None:
    """v1.3 done.follow_ups?：路由命中给 ≤2 条；未登记路由给空（无追问）。"""
    fups = _follow_ups("product_flow")
    assert 1 <= len(fups) <= 2
    assert _follow_ups("status_flow") == []
    assert _follow_ups("") == []
