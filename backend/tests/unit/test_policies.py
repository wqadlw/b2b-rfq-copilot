"""Policy layer tests: refusal derivation + output filter (poisoning/price safety)."""

from conftest import make_deps
from rfq_copilot.core.policies.output_filter import filter_output
from rfq_copilot.core.policies.refusal import refusal_answer


def test_disabled_capabilities_derive_policies() -> None:
    deps, _ = make_deps()
    assert set(deps.refusal_policies) == {"pricing", "lead_time", "stock"}
    assert "price_inquiry" in deps.refusal_policies["pricing"].trigger_intents


def test_pricing_refusal_template() -> None:
    text = refusal_answer("pricing")
    assert "提交询价" in text
    assert "¥" not in text and "元" not in text


def test_pricing_shown_price_verbatim_echo() -> None:
    text = refusal_answer("pricing", shown_price_text="¥3,000")
    assert "¥3,000" in text and "以供应商报价为准" in text


def test_tool_registry_omits_disabled_capability_tools() -> None:
    deps, _ = make_deps()
    tools = deps.tool_registry()
    assert "search_products" in tools and "create_inquiry" in tools
    # pricing/lead_time/stock are capabilities: no such tools exist at all
    assert "estimate_price" not in tools and "get_lead_time" not in tools


def test_output_filter_masks_price_and_poison_phrases() -> None:
    text = "本店最优，全网最低价 6,800 元。"
    out, violated = filter_output(text)
    assert violated
    assert "本店最优" not in out and "6,800" not in out


def test_output_filter_whitelists_page_price() -> None:
    out, violated = filter_output("页面标价 ¥3,000。", frozenset({"¥3,000"}))
    assert not violated and "¥3,000" in out
