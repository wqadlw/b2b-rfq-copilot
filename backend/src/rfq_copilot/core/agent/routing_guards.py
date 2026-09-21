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

import re
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

# ---------------------------------------------------------------------------
# 选型问法护栏（ADR-0008 D1）：类型级选型咨询 → knowledge_flow（RAG 选型指南作答）
# ---------------------------------------------------------------------------

# 类型级选型/对比咨询标记（问的是"类与类之间怎么选"，不是找具体产品）
SELECTION_CONSULT_MARKERS: tuple[str, ...] = (
    "怎么选",
    "如何选",
    "怎么挑选",
    "如何挑选",
    "哪个好",
    "哪种好",
    "有什么区别",
    "有啥区别",
    "的区别",
    "优缺点",
    "选哪个",
)

# 产品编号形态（compare_flow 的合法输入；出现两个编号 = 真产品对比，不拦截）。
# 与 graph.compare_flow 的提取共用本模式：demo 桩 demo-p-* 与真实站点数字主键（≥3 位）。
# （2026-09-21 实测真实目录 ID 为 312/180 等数字，compare_flow 曾硬编码 demo-p-\d+ 致线上不可用。）
PRODUCT_ID_PATTERN = re.compile(r"[a-z0-9]+-p-\d+|\d{3,}")

SELECTION_GUARD_NAME = "selection_over_search"


def apply_selection_guard(message: str, understanding: dict[str, Any]) -> dict[str, Any]:
    """类型级选型咨询误入产品搜索/对比路由时，改道 knowledge_flow（ADR-0008 D1）。

    窄口径三条件同时满足才触发：
    route ∈ {product_flow, selection_flow, compare_flow}
    AND 消息命中选型咨询标记
    AND 消息不含两个产品编号（真产品对比不受影响）。
    纯函数；记录 route_guard 审计轨迹。
    """
    route = str(understanding.get("route") or "")
    if route not in {"product_flow", "selection_flow", "compare_flow"}:
        return understanding
    text = (message or "").strip()
    if not any(marker in text for marker in SELECTION_CONSULT_MARKERS):
        return understanding
    if len(PRODUCT_ID_PATTERN.findall(text)) >= 2:
        return understanding  # 点名了两个具体产品 → compare_flow 的合法场景

    corrected = dict(understanding)
    corrected["route"] = "knowledge_flow"
    corrected["intent"] = "selection_inquiry"
    corrected["route_guard"] = SELECTION_GUARD_NAME
    corrected["route_guard_from"] = {
        "intent": understanding.get("intent"),
        "route": understanding.get("route"),
    }
    return corrected


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

    头二字放宽（2026-09-20 实测 B5）：LLM 会把用户的口语说法规范化成品类词
    ——说「无油泵」而实体是「无油真空泵」，逐字比对不中 → 实体被弃 → 整句
    去 LIKE 搜索必零结果。故补充：实体的**首二字限定词头**（"无油"）出现在
    当前消息中也采纳；陈旧实体（与本轮无关的品类）头二字通常不会出现，仍被拦。
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
            # B5 放宽：首二字限定词头命中即采纳（"无油真空泵" vs 用户说"无油泵"）
            if len(keyword) >= 2 and keyword[:2] in text:
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


# ---------------------------------------------------------------------------
# ADR-0009 D4：场景类追问护栏（scenario_over_clarify）
# ---------------------------------------------------------------------------

SCENARIO_MARKERS = (
    "适合什么",
    "什么场景",
    "应用场景",
    "用在哪",
    "用在什么",
    "哪个行业",
    "什么行业",
    "适用范围",
    "哪些场合",
)

_PRODUCT_CONTEXT_WORDS = ("泵", "机组")


def apply_scenario_followup_guard(
    message: str, understanding: dict[str, Any], history: list[dict[str, Any]]
) -> dict[str, Any]:
    """场景类追问误入 selection_flow「补工况」兜底 → 改道 knowledge_flow（ADR-0009 D4）。

    实测：user 问「什么是罗茨泵？」后追问「它适合什么场景？」——意图 LLM 借历史
    正确解析了指代，却判 selection_inquiry → selection_flow 无规格数据时输出
    「请补充更多信息…」。用户问的是知识，应 Retrieve-Then-Ask（先检索作答）。

    窄口径：仅 selection_flow + 场景标记词 + 历史含产品语境（泵/机组）三条件齐备；
    首轮场景问题（无历史）不拦，留给意图分类器。
    """
    if understanding.get("route_guard"):
        return understanding
    if understanding.get("route") != "selection_flow":
        return understanding
    text = (message or "").strip()
    if not any(marker in text for marker in SCENARIO_MARKERS):
        return understanding
    if not history:
        return understanding
    joined = "".join(str(m.get("content", "")) for m in history)
    if not any(word in joined for word in _PRODUCT_CONTEXT_WORDS):
        return understanding
    return {
        **understanding,
        "route": "knowledge_flow",
        "route_guard": "scenario_over_clarify",
        "route_guard_from": {"route": understanding.get("route")},
    }
