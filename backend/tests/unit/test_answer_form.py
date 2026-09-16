"""Unit: 回答形式辅助（规格数值人性化 / 卡片载荷）。"""

from rfq_copilot.core.agent.graph import _humanize_spec_value, _product_cards_payload


def test_humanize_strips_trailing_zeros() -> None:
    assert _humanize_spec_value("1500.00 m³/h") == "1500 m³/h"
    assert _humanize_spec_value("0.0100 Pa") == "0.01 Pa"
    assert _humanize_spec_value("5.0000 Pa") == "5 Pa"
    assert _humanize_spec_value("10 m³/h") == "10 m³/h"  # 整数不动
    assert _humanize_spec_value("120.5 L/s") == "120.5 L/s"
    assert _humanize_spec_value("请联系供应商询价") == "请联系供应商询价"  # 非数值透传


class _FakePrice:
    def __init__(self, mode: str, text: str) -> None:
        self.mode = mode
        self.text = text


class _FakeItem:
    def __init__(self, pid: str, name: str, specs: dict) -> None:
        self.id = pid
        self.name = name
        self.supplier_name = "示例供应商"
        self.url = f"/products/{pid}"
        self.specs = specs
        self.price_display = _FakePrice("contact", "请联系供应商询价")


def test_product_cards_payload_humanizes_specs_and_registers_shown_price() -> None:
    whitelist: set[str] = set()
    items = [_FakeItem("1", "旋片真空泵", {"抽速": "1500.00 m³/h", "极限真空": "0.0100 Pa"})]
    cards, count = _product_cards_payload(items, whitelist)
    assert count == 1
    assert cards[0]["specs"] == {"抽速": "1500 m³/h", "极限真空": "0.01 Pa"}
    assert whitelist == set()  # contact 价格不进白名单
