"""Refuse-to-fabricate policies derived from manifest capabilities (port-spec §5)."""

from dataclasses import dataclass

from rfq_copilot.core.manifest import Manifest

# intent labels that trigger each disabled capability's refusal (port-spec §5)
TRIGGER_INTENTS: dict[str, set[str]] = {
    "pricing": {"price_inquiry", "discount_inquiry"},
    "lead_time": {"lead_time_inquiry"},
    "stock": {"stock_inquiry"},
}

# canonical T(c) templates; pricing has a shown-price variant (verbatim echo + footnote)
TEMPLATES: dict[str, str] = {
    "pricing": "产品页未展示公开价格，建议您提交询价，供应商会尽快报价。",
    "lead_time": "货期需供应商确认。您可以提交询价，供应商会在后台回复交期。",
    "stock": "库存请以供应商确认为准，建议提交询价核实。",
}
SHOWN_PRICE_FOOTNOTE = "具体成交价以供应商报价为准。"


@dataclass(frozen=True)
class RefusalPolicy:
    capability: str
    trigger_intents: frozenset[str]


def derive_refusal_policies(manifest: Manifest) -> dict[str, RefusalPolicy]:
    """One policy per disabled capability, deterministically derived."""
    return {
        capability: RefusalPolicy(capability=capability, trigger_intents=frozenset(TRIGGER_INTENTS[capability]))
        for capability in manifest.disabled_capabilities()
    }


def refusal_answer(capability: str, shown_price_text: str | None = None) -> str:
    """Deterministic template answer T(c). Pricing echoes a shown price verbatim, never computes."""
    if capability == "pricing" and shown_price_text:
        return f"页面标价为 {shown_price_text}，{SHOWN_PRICE_FOOTNOTE}"
    return TEMPLATES[capability]
