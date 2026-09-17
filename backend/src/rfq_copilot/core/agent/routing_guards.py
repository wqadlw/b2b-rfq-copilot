"""Deterministic routing guardrails applied after the LLM intent classifier.

Reference pattern: "post-LLM guardrail with hard-rule overrides" — the classifier keeps
nuanced judgment for ambiguous cases; a deterministic layer corrects the specific
mis-classifications that are reproducible and semantically wrong. (Temporal AI Cookbook:
Guardrails with hard rules; Elastic Search Labs: the LLM's role is intent extraction,
execution is guarded deterministically.)

Observed defect (2026-09-16, real model): "旋片式真空泵有哪些？" and "无油真空泵有哪些？"
were classified as supplier_search → users asking to see products got a supplier list
instead. Re-running the same sentence produced different routes (model variance), so the
fix must be deterministic, not prompt-only.

Guard rule (narrow by design):
    route == "supplier_flow"
    AND entities contain a product category
    AND the message asks a product-shaped question ("有哪些/型号/规格/推荐…")
    AND the message does NOT focus on suppliers ("供应商/厂家/哪家/渠道…")
    → switch to product_flow, recording the correction in the understanding payload.

The guard never touches other routes, never invents entities, and leaves an auditable
trace (``route_guard`` / ``route_guard_from``) for evals and analytics.
"""

from __future__ import annotations

from typing import Any

# 产品问法：用户在问"有什么 / 哪些 / 型号 / 规格 / 推荐 / 选型"
PRODUCT_QUESTION_MARKERS: tuple[str, ...] = (
    "有哪些",
    "有什么",
    "哪些型号",
    "什么型号",
    "什么规格",
    "哪些规格",
    "推荐",
    "选型",
    "怎么选",
    "对比",
    "介绍",
)

# 供应商聚焦：用户明确在问"谁供 / 哪家 / 渠道"
SUPPLIER_FOCUS_MARKERS: tuple[str, ...] = (
    "供应商",
    "供应厂",
    "厂家",
    "生产商",
    "制造商",
    "哪家",
    "哪个公司",
    "渠道",
    "代理",
    "经销商",
    "谁做",
    "谁家",
)

GUARD_NAME = "product_over_supplier"

# 询盘创建关键词（单一事实源）：graph 短路与游客 gate 共用
INQUIRY_CREATE_MARKERS: tuple[str, ...] = ("询盘", "询价", "要买", "求购")


def _has_product_category(entities: dict[str, Any] | None) -> bool:
    if not entities:
        return False
    for key in ("product_category", "category", "product_name", "product", "model"):
        value = entities.get(key)
        if isinstance(value, str) and value.strip():
            return True
        if isinstance(value, list) and any(str(v).strip() for v in value):
            return True
    return False


def apply_routing_guards(message: str, understanding: dict[str, Any]) -> dict[str, Any]:
    """Return ``understanding`` possibly corrected by the deterministic guard.

    Pure function: same input → same output; never mutates the caller's dict.
    """
    route = str(understanding.get("route") or "")
    if route != "supplier_flow":
        return understanding
    text = message or ""
    if any(marker in text for marker in SUPPLIER_FOCUS_MARKERS):
        return understanding  # 用户确实在问供应商 → 尊重分类器
    if not _has_product_category(understanding.get("entities")):
        return understanding  # 没有产品品类实体 → 无从判断，尊重分类器
    if not any(marker in text for marker in PRODUCT_QUESTION_MARKERS):
        return understanding

    corrected = dict(understanding)
    corrected["route"] = "product_flow"
    corrected["intent"] = "product_inquiry"
    corrected["route_guard"] = GUARD_NAME
    corrected["route_guard_from"] = {
        "intent": understanding.get("intent"),
        "route": understanding.get("route"),
    }
    return corrected


# ---------------------------------------------------------------------------
# 检索关键词优选（同一"LLM 之后确定性调整"家族）
# ---------------------------------------------------------------------------

# 实体字段优先级：品类 > 产品名 > 型号
_ENTITY_KEYS: tuple[str, ...] = ("product_category", "product_name", "product", "model")


def select_search_keyword(message: str, understanding: dict[str, Any] | None) -> str:
    """为产品检索挑选关键词：优先取分类器抽取的品类/产品实体，退回原消息。

    背景（2026-09-16 实测）：产品流程此前固定用 ``message[:40]`` 整句去搜，
    站点整串匹配会因问句词（"有哪些？"）零结果；而理解节点其实已经抽出了
    「旋片式真空泵」这样的品类实体。

    防陈旧实体劫持：多轮槽位合并会保留历史实体，因此只接受"实体文本出现在
    当前消息中（或消息出现在实体中）"的实体——保证关键词与用户本轮所说一致。
    """
    text = (message or "").strip()
    entities = (understanding or {}).get("entities") or {}
    for key in _ENTITY_KEYS:
        value = entities.get(key)
        candidates: list[str] = []
        if isinstance(value, str):
            candidates = [value]
        elif isinstance(value, list):
            candidates = [item for item in value if isinstance(item, str)]
        for candidate in candidates:
            keyword = candidate.strip()
            if not keyword:
                continue
            if keyword in text or text in keyword:
                return keyword[:40]
    return text[:40]


def detect_inquiry_status_query(message: str) -> bool:
    """询盘状态查询判定："我的询盘" / "有人跟" / "报价了吗" / "进度" 等追问。

    调用顺序约束：调用方须在本判定**之后**才做询盘创建判定——
    "我的询盘有人跟吗"含"询盘"二字，若先跑创建判定会被误当新询盘（实测踩坑）。
    """
    text = (message or "").strip()
    if not text:
        return False
    markers = (
        "我的询盘",
        "我的询价",
        "有人跟",
        "有人回复",
        "有回复吗",
        "报价了吗",
        "报价了没",
        "什么进度",
        "进度怎么",
        "进展",
        "处理了吗",
        "受理了吗",
        "询盘状态",
        "询价状态",
    )
    return any(marker in text for marker in markers)
