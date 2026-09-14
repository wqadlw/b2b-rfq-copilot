"""SSE mapper: inquiry_confirm draft object flattening (contract: 03-api-spec §2)."""

import json

from rfq_copilot.app.sse_mapper import _draft_payload


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
