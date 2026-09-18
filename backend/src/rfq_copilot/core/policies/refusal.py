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


# ===== QA-0004：单一确定性拒绝决策（gate 与 graph 共用，杜绝镜像 marker 漂移）=====
# 触发词表此前在 main._is_zero_token_intent 与 graph._understanding_from_tools 各持一份
# 手抄镜像，能力开启时两份判定不一致 → 游客价格问句穿透到 LLM（成本+编造双红线）。
# 现收敛为本函数：由 manifest 派生的拒绝策略 + 唯一触发词表，一处判定，两处消费。
INTENT_MARKERS: dict[str, tuple[str, ...]] = {
    "price_inquiry": ("多少钱", "价格", "报价", "区间", "元"),
    "discount_inquiry": ("折扣", "优惠"),
    "lead_time_inquiry": ("货期", "交期", "交货", "多久", "几周", "能到"),
    "stock_inquiry": ("有货", "库存", "现货"),
}

CAPABILITY_REFUSAL_REASON: dict[str, str] = {
    "pricing": "pricing_disabled",
    "lead_time": "lead_time_disabled",
    "stock": "stock_disabled",
}


@dataclass(frozen=True)
class CapabilityRefusal:
    """一次能力禁用拒绝命中：intent / capability / graph 拒绝原因码。"""

    intent: str
    capability: str
    reason: str


def detect_capability_refusal(
    message: str,
    refusal_policies: dict[str, RefusalPolicy],
) -> CapabilityRefusal | None:
    """确定性判定：消息是否命中「已禁用能力」的拒绝触发词。

    消费方：
    - graph._understanding_from_tools → 命中即走 refuse_fabrication（0 token）
    - app.main 游客门 → 仅当命中（graph 必然 0 token 模板拒绝）才放行进 graph；
      能力开启（无策略）时游客一律 login_required，绝不触达 LLM。
    """
    policy_by_intent = {intent: cap for cap, policy in refusal_policies.items() for intent in policy.trigger_intents}
    for intent, capability in policy_by_intent.items():
        if any(m in message for m in INTENT_MARKERS.get(intent, ())):
            reason = CAPABILITY_REFUSAL_REASON.get(capability, f"{capability}_disabled")
            return CapabilityRefusal(intent=intent, capability=capability, reason=reason)
    return None


def refusal_answer(capability: str, shown_price_text: str | None = None) -> str:
    """Deterministic template answer T(c). Pricing echoes a shown price verbatim, never computes."""
    if capability == "pricing" and shown_price_text:
        return f"页面标价为 {shown_price_text}，{SHOWN_PRICE_FOOTNOTE}"
    return TEMPLATES[capability]
