"""Minimal LangGraph agent (M0/M1): understand → deterministic route → respond.

M2 will expand: real answer generation, checkpointer, full tool loop. Policy layer
(refusal/output-filter/confirmation-gate) and the M1 RAG pipeline are wired here.
"""

import hashlib
import inspect
import json
import re
from dataclasses import dataclass
from typing import Annotated, Any, TypedDict

import structlog
from langgraph.config import get_stream_writer
from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from rfq_copilot.core.agent.llm import LLMClient
from rfq_copilot.core.agent.routing_guards import (
    INQUIRY_CREATE_MARKERS,
    PRODUCT_ID_PATTERN,
    SCENARIO_MARKERS,
    SPEC_ROUTE_GUARDS,
    apply_routing_guards,
    apply_scenario_followup_guard,
    apply_selection_guard,
    detect_inquiry_status_query,
    select_search_keyword,
)
from rfq_copilot.core.manifest import Manifest
from rfq_copilot.core.memory import SessionStore
from rfq_copilot.core.policies.faq_matcher import FaqMatcher
from rfq_copilot.core.policies.output_filter import filter_output
from rfq_copilot.core.policies.refusal import RefusalPolicy, detect_capability_refusal, refusal_answer
from rfq_copilot.core.policies.supplier_match import match_suppliers
from rfq_copilot.core.prompts import PromptRegistry
from rfq_copilot.core.rag.citation import validate_citations
from rfq_copilot.core.rag.compare import build_compare_matrix, render_compare_answer
from rfq_copilot.core.rag.pipeline import RAGPipeline
from rfq_copilot.core.rag.spec_matcher import (
    extract_spec_criteria,
    fmt_num,
    match_products,
    scan_spec_entities,
    spec_entities_from,
    spec_summary,
)
from rfq_copilot.ports.errors import ConfigError, CopilotError
from rfq_copilot.ports.industry_knowledge import CasesPort, SolutionsPort
from rfq_copilot.ports.inquiry_sink import AiExtract, Contact, InquiryDraft, InquirySinkPort
from rfq_copilot.ports.lead_distribution import LeadDistributionPort
from rfq_copilot.ports.product_catalog import ProductCatalogPort, ProductSearchQuery
from rfq_copilot.ports.supplier_directory import SupplierDirectoryPort, SupplierSearchQuery

MAX_SEARCH_ITEMS = 10

INTENT_ENUM = frozenset(
    {
        "product_inquiry",
        "spec_inquiry",
        "selection_inquiry",
        "price_inquiry",
        "sample_request",
        "lead_time_inquiry",
        "stock_inquiry",
        "customization_request",
        "supplier_search",
        "certification_inquiry",
        "complaint",
        "human_request",
        "solution_inquiry",
        "case_inquiry",
        "status_inquiry",
        "unknown",
    }
)
logger = structlog.get_logger(__name__)
REFUSAL_REASON_TO_CAPABILITY = {
    "pricing_disabled": "pricing",
    "lead_time_disabled": "lead_time",
    "stock_disabled": "stock",
    "content_policy": "pricing",
}
VALID_ROUTES = frozenset(
    {
        "product_flow",
        "selection_flow",
        "spec_match_flow",
        "supplier_flow",
        "compare_flow",
        "knowledge_flow",
        "inquiry_flow",
        "handoff_flow",
        "solution_flow",
        "case_flow",
        "status_flow",
        "clarify",
        "refuse_fabrication",
    }
)


def _humanize_spec_value(spec_value: str) -> str:
    """规格数值去尾零：'1500.00 m³/h' → '1500 m³/h'，'0.0100 Pa' → '0.01 Pa'。"""
    text = str(spec_value).strip()
    match = re.match(r"^([0-9]+(?:\.[0-9]+)?)(.*)$", text)
    if not match:
        return text
    number, unit = match.group(1), match.group(2)
    if "." in number:
        number = number.rstrip("0").rstrip(".")
    return f"{number}{unit}"


def _product_cards_payload(items: list[Any], whitelist: set[str]) -> tuple[list[dict[str, Any]], int]:
    """构造产品卡片事件 + 返回展示数量（含价格白名单登记）。"""
    cards: list[dict[str, Any]] = []
    for item in items:
        price = item.price_display.text
        if item.price_display.mode == "shown":
            whitelist.add(price.strip())
        cards.append(
            {
                "kind": "product",
                "name": item.name,
                "supplier": item.supplier_name,
                "brand": item.brand_name,
                "category": item.category_name,
                "price": price,
                "url": item.url,
                "specs": {key: _humanize_spec_value(value) for key, value in list(item.specs.items())[:3]},
            },
        )
    return cards, len(items)


def _product_compare_payload(matched: list[tuple[Any, float, list[str]]], criteria: Any) -> dict[str, Any]:
    """规格匹配对比卡（03-api-spec v1.1 `kind: product_compare`）。

    行=用户数值条件（附需求口径），列=各产品参数原文；ok 恒 true（硬条件排除
    语义保证在榜产品全部满足）；匹配依据 matched_on 由 matcher 生成（grounded）。
    """
    criteria_summary: list[str] = []
    if criteria.pumping_speed_min is not None:
        criteria_summary.append(f"抽速 ≥ {fmt_num(criteria.pumping_speed_min)} m³/h")
    if criteria.ultimate_vacuum_max is not None:
        criteria_summary.append(f"极限真空 ≤ {fmt_num(criteria.ultimate_vacuum_max)} Pa")
    if criteria.oil_free:
        criteria_summary.append("无油")

    products: list[dict[str, Any]] = []
    speed_values: list[str] = []
    vacuum_values: list[str] = []
    for product, _score, entries in matched[:3]:
        price_text = product.price_display.text if product.price_display.mode == "shown" else "请联系供应商询价"
        products.append(
            {
                "name": product.name,
                "supplier": product.supplier_name,
                "price": price_text,
                "url": product.url,
                "matched_on": entries,
            }
        )
        speed_values.append(str(product.specs.get("抽速") or product.specs.get("pumping_speed") or "—"))
        vacuum_values.append(str(product.specs.get("极限真空") or product.specs.get("ultimate_vacuum") or "—"))

    rows: list[dict[str, Any]] = []
    if criteria.pumping_speed_min is not None:
        rows.append(
            {
                "label": f"抽速（需 ≥ {fmt_num(criteria.pumping_speed_min)} m³/h）",
                "values": speed_values,
                "ok": [True] * len(products),
            }
        )
    if criteria.ultimate_vacuum_max is not None:
        rows.append(
            {
                "label": f"极限真空（需 ≤ {fmt_num(criteria.ultimate_vacuum_max)} Pa）",
                "values": vacuum_values,
                "ok": [True] * len(products),
            }
        )
    return {
        "kind": "product_compare",
        "title": "按您的规格条件对比",
        "criteria_summary": criteria_summary,
        "products": products,
        "rows": rows,
    }


def _compare_matrix_payload(details: list[Any]) -> dict[str, Any]:
    """点名两产品对比卡：复用 build_compare_matrix（中立并列，不判优劣）。"""
    matrix = build_compare_matrix(details)
    products = [
        {
            "name": p.name,
            "supplier": p.supplier_name,
            "price": p.price_display.text if p.price_display.mode == "shown" else "请联系供应商询价",
            "url": p.url,
        }
        for p in details
    ]
    rows = [
        {
            "label": row.label,
            "values": row.values,
            **({"direction_hint": row.direction_hint} if row.direction_hint else {}),
        }
        for row in matrix.rows
    ]
    return {"kind": "product_compare", "title": "产品参数对比", "products": products, "rows": rows}


def _merge_lists(left: list[Any] | None, right: list[Any] | None) -> list[Any]:
    """Reducer: nodes append to event/tool channels instead of replacing them."""
    return (left or []) + (right or [])


class AgentState(TypedDict, total=False):
    session_id: str
    user_ref: str | None
    message: str
    action: str | None
    contact: dict[str, Any] | None
    quantity: int | None
    product_id: str | None
    understanding: dict[str, Any]
    route: str
    answer: str
    events: Annotated[list[tuple[str, dict[str, Any]]], _merge_lists]
    tool_calls: Annotated[list[str], _merge_lists]
    spec_context: dict[str, str]  # 跨轮规格累积（P1-4）：spec_match 提取，询盘时带入 params


@dataclass
class GraphDeps:
    manifest: Manifest
    llm: LLMClient
    prompts: PromptRegistry
    refusal_policies: dict[str, RefusalPolicy]
    store: SessionStore
    faq_matcher: FaqMatcher | None = None
    catalog: ProductCatalogPort | None = None
    suppliers: SupplierDirectoryPort | None = None
    rag: RAGPipeline | None = None
    inquiry_sink: InquirySinkPort | None = None
    lead_distribution: LeadDistributionPort | None = None
    solutions: SolutionsPort | None = None  # 行业方案目录（端口；离线 JSON 适配器实现）
    cases: CasesPort | None = None  # 客户案例目录（端口；离线 JSON 适配器实现）
    inquiry_status: Any | None = None  # 询盘状态查询（InquiryStatusPort；真通道专用）
    # spec 02 §1.2（N2）：缺口事件记录器（app 层注入；core 不知存储。缺省 None 零影响）
    no_match_recorder: Any | None = None

    def tool_registry(self) -> dict[str, Any]:
        """Tools physically registered from manifest; disabled capabilities never appear here."""
        tools: dict[str, Any] = {}
        pc = self.manifest.ports.product_catalog
        if pc.enabled and self.catalog is not None:
            if "search" in pc.features:
                tools["search_products"] = self.catalog.search
            if "detail" in pc.features:
                tools["get_product_detail"] = self.catalog.get_detail
        if self.manifest.ports.supplier_directory.enabled and self.suppliers is not None:
            tools["get_suppliers"] = self.suppliers.search
        if self.manifest.ports.knowledge_source.enabled and self.rag is not None:
            tools["search_knowledge"] = self.rag.search
        if self.manifest.ports.inquiry_sink.enabled and self.inquiry_sink is not None:
            tools["create_inquiry"] = self.inquiry_sink.create
        if self.manifest.ports.lead_distribution.enabled and self.lead_distribution is not None:
            tools["submit_lead_candidate"] = self.lead_distribution.submit
        return tools


def parse_understanding(raw: dict[str, Any]) -> dict[str, Any]:
    """Validate + consistency-fix the understanding node output (05-structured-output-spec)."""
    intent = raw.get("intent") if raw.get("intent") in INTENT_ENUM else "unknown"
    try:
        confidence = float(raw.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = min(1.0, max(0.0, confidence))
    refusal_reason = raw.get("refusal_reason")
    if refusal_reason is not None and refusal_reason not in REFUSAL_REASON_TO_CAPABILITY:
        refusal_reason = None
    needs_human = bool(raw.get("needs_human")) or confidence < 0.6
    human_reason = raw.get("human_reason")
    if needs_human and not human_reason:
        human_reason = "low_confidence"
    entities = raw.get("entities") if isinstance(raw.get("entities"), dict) else {}
    route = raw.get("route")
    if refusal_reason is not None:
        route = "refuse_fabrication"
    elif intent == "unknown" or confidence < 0.6 or route not in VALID_ROUTES:
        route = "clarify"
    return {
        "intent": intent,
        "confidence": confidence,
        "entities": entities,
        "missing_fields": list(raw.get("missing_fields") or []),
        "route": route,
        "needs_clarification": route == "clarify",
        "needs_human": needs_human,
        "human_reason": human_reason,
        "refusal_reason": refusal_reason,
    }


async def _call_tool(fn: Any, /, *args: Any, **kwargs: Any) -> Any:
    """Ports may be sync (demo) or async (HTTP): normalise both."""
    out = fn(*args, **kwargs)
    if inspect.isawaitable(out):
        out = await out
    return out


def _refusal_node(deps: GraphDeps) -> Any:
    async def node(state: AgentState) -> dict[str, Any]:
        understanding = state.get("understanding", {})
        capability = REFUSAL_REASON_TO_CAPABILITY.get(understanding.get("refusal_reason") or "", "pricing")
        policy = deps.refusal_policies.get(capability)
        # capability became enabled since derivation; fail safe to generic refusal
        answer = "该信息需以供应商确认为准。" if policy is None else refusal_answer(capability)
        return {"route": "refuse_fabrication", "answer": answer}

    return node


def _handoff_node(deps: GraphDeps) -> Any:
    async def node(state: AgentState) -> dict[str, Any]:
        u = state.get("understanding", {})
        reason = u.get("human_reason") or "user_request"
        priority = "high" if reason in {"complaint", "legal"} else "normal"
        answer = "这个问题我已为您标记人工跟进，销售会尽快与您联系。"
        events: list[tuple[str, dict[str, Any]]] = [
            ("handoff", {"reason": reason, "priority": priority}),
        ]
        wechat = deps.manifest.chat.wechat
        if wechat.qrcode_url:
            contact = wechat.contact_name or "专属工程师"
            answer += f"您也可以扫码添加{contact}，一对一快速响应，见下方二维码。"
            events.append(
                (
                    "wechat_guidance",
                    {
                        "guidance": wechat.guidance_text or "扫码添加专属工程师一对一快速响应",
                        "qrcode_url": wechat.qrcode_url,
                        "contact_name": wechat.contact_name or "专属工程师",
                    },
                )
            )
        return {
            "route": "handoff_flow",
            "answer": answer,
            "events": events,
        }

    return node


def _respond_node(deps: GraphDeps) -> Any:
    async def node(state: AgentState) -> dict[str, Any]:
        route = state.get("route", "clarify")
        message = state.get("message", "")
        events: list[tuple[str, dict[str, Any]]] = []
        tool_calls: list[str] = []
        whitelist: set[str] = set()
        tools = deps.tool_registry()
        spec_ctx: dict[str, str] = dict(state.get("spec_context") or {})

        if route == "faq_answer":
            # QA-0011：FAQ 命中答案在 understand 节点已生成（0 token 直达），
            # 此处必须直取直返；此前无此分支，落 else 被澄清模板覆盖。
            answer = str(state.get("answer") or "")
            answer, _ = filter_output(answer, frozenset())
            return {"route": route, "answer": answer, "events": events, "tool_calls": tool_calls}

        if route == "spec_match_flow" and deps.rag is not None:
            # 规格匹配：从实体中提取规格条件，按参数过滤产品
            tool_calls.append("spec_match")
            events.append(("tool_call", {"tool": "spec_match", "status": "running"}))
            criteria = extract_spec_criteria(state.get("understanding", {}).get("entities", {}))
            if criteria.is_empty:
                # 教育式追问（04-prompt-spec v1.1"规格匹配缺参"行）：讲三要素 + 示例格式
                # + 向导引导；一次给全（选型字段强相关，拆多轮流失率高——显式例外）。
                answer = (
                    "选真空泵主要看三个关键参数，告诉我已知的部分即可：\n"
                    "1. 抽速（单位 m³/h，部分厂商用 L/s）——决定抽气快慢，如：抽速 ≥ 300 m³/h\n"
                    "2. 极限真空（单位 Pa，数值越低抽得越深）——如：极限真空 ≤ 10 Pa\n"
                    "3. 是否无油——半导体、食品、实验室等工况通常要求无油机型\n"
                    "也可以点输入框上方「选型」→「选型向导」填表单，或直接说用途（如：实验室小腔体抽真空），我来帮您匹配。"
                )
                return {"route": route, "answer": answer, "events": events, "tool_calls": tool_calls}
            # 搜索所有产品后按规格过滤
            spec_ctx.update(spec_entities_from(state.get("understanding", {}).get("entities", {})))
            from rfq_copilot.ports.product_catalog import ProductSearchQuery as _PSQ

            search_fn = tools.get("search_products") or (deps.catalog.search if deps.catalog else None)
            if search_fn is None:
                answer = "当前环境未接入产品库，无法进行规格匹配。"
                return {"route": route, "answer": answer, "events": events, "tool_calls": tool_calls}
            result = await _call_tool(search_fn, _PSQ(keyword="", page_size=20))
            events.append(("tool_call", {"tool": "spec_match", "status": "done"}))
            matched = match_products(result.items if hasattr(result, "items") else [], criteria)
            if not matched:
                no_match_head = "暂未找到完全匹配您规格的产品。以下是接近的产品："
                tail = "您可以提交询盘，供应商会推荐接近的型号。"
                close = "\n".join(f"- {p.name}（{p.supplier_name}）" for p in result.items[:3])
                answer = no_match_head + "\n" + close + "\n" + tail
                answer += await _vacuum_system_suggestion(deps.rag, criteria, tool_calls, events)
            else:
                # 文本只做引导（数据交给卡片，与 product_flow 同理念，杜绝文本复读卡片内容）；
                # 产品卡统一走 _product_cards_payload（补 brand/category，消除双份构造），
                # 末尾追加 product_compare 对比卡（03-api-spec v1.1）。
                top_matched = matched[:3]
                for product, _score, _entries in top_matched:
                    events.append(("citation", {"title": product.name, "url": product.url, "trust": "merchant"}))
                cards, _shown_count = _product_cards_payload([p for p, _s, _e in top_matched], whitelist)
                for card in cards:
                    events.append(("card", card))
                events.append(("card", _product_compare_payload(top_matched, criteria)))
                answer = (
                    f"根据您的规格需求，匹配到 {len(matched)} 款产品（已按匹配度排序，见下方卡片）。"
                    "想看某款的详细参数、对比机型，或直接发起询盘，告诉我即可。"
                )
                answer += await _vacuum_system_suggestion(deps.rag, criteria, tool_calls, events)
        elif route == "solution_flow" and deps.solutions is not None:
            tool_calls.append("get_solution")
            events.append(("tool_call", {"tool": "get_solution", "status": "running"}))
            entities = (state.get("understanding") or {}).get("entities") or {}
            industry = entities.get("industry") or (deps.solutions.detect_query(message) if deps.solutions else None)
            solution = deps.solutions.by_industry(industry) if industry else None
            events.append(("tool_call", {"tool": "get_solution", "status": "done"}))
            if solution is None:
                answer = "该行业暂无已发布方案。您可以先看产品，或直接提交询盘让供应商出方案。"
                return {"route": route, "answer": answer, "events": events, "tool_calls": tool_calls}
            for supplier in solution.suppliers[:3]:
                events.append(("citation", {"title": supplier, "trust": "merchant"}))
            events.append(
                (
                    "card",
                    {
                        "kind": "solution",
                        "title": solution.name,
                        "industry": solution.industry_name,
                        "subtitle": solution.subtitle,
                        "pain_points": solution.pain_points[:3],
                        "topology": solution.topology,
                        "budget": solution.budget_text,
                        "suppliers": solution.suppliers[:3],
                        "url": solution.url,
                    },
                )
            )
            answer = (
                f"「{solution.industry_name}」行业已有一套成熟方案：{solution.name}。"
                "卡片内含痛点分析与设备拓扑，点击可查看完整方案。"
            )
        elif route == "case_flow" and deps.cases is not None:
            tool_calls.append("get_cases")
            events.append(("tool_call", {"tool": "get_cases", "status": "running"}))
            case_entities = (state.get("understanding") or {}).get("entities") or {}
            case_industry = case_entities.get("industry") or (
                deps.cases.detect_query(message)[0] if deps.cases else None
            )
            case_hits = deps.cases.by_industry_slug(case_industry)[:3]
            events.append(("tool_call", {"tool": "get_cases", "status": "done"}))
            if not case_hits:
                answer = "暂无已发布案例。您可以先看产品参数，或直接提交询盘。"
                return {"route": route, "answer": answer, "events": events, "tool_calls": tool_calls}
            for case in case_hits:
                events.append(("citation", {"title": case.title, "url": case.url, "trust": "platform"}))
                events.append(
                    (
                        "card",
                        {
                            "kind": "case",
                            "title": case.title,
                            "industry": case.industry_name,
                            "customer": case.customer_name,
                            "metrics": case.metrics,
                            "result": case.result,
                            "has_whitepaper": case.has_whitepaper,
                            "supplier": case.supplier,
                            "url": case.url,
                        },
                    )
                )
            case_scope = f"「{case_hits[0].industry_name}」行业" if case_industry else ""
            answer = (
                f"找到 {len(case_hits)} 个{case_scope}交付案例（卡片含量化指标与客户成效）。白皮书可在案例页留资下载。"
            )
        elif route == "status_flow" and deps.inquiry_status is not None:
            tool_calls.append("inquiry_status")
            events.append(("tool_call", {"tool": "inquiry_status", "status": "running"}))
            status_payload = await deps.inquiry_status.by_session(state["session_id"])
            events.append(("tool_call", {"tool": "inquiry_status", "status": "done"}))
            status_items = status_payload.get("items") or []
            if not status_items:
                answer = "当前会话还没有询盘记录。您可以先挑选产品发起询盘。"
                return {"route": route, "answer": answer, "events": events, "tool_calls": tool_calls}
            for item in status_items[:5]:
                events.append(
                    (
                        "card",
                        {
                            "kind": "inquiry_status",
                            "inquiry_id": str(item["inquiry_id"]),
                            "title": item["title"],
                            "status_text": item["status_text"],
                            "quote_count": item.get("quote_count") or 0,
                            "created_at": item.get("created_at"),
                        },
                    )
                )
            status_lines = [
                f"  · [{item['inquiry_id']}] {item['title']}｜{item['status_text']}"
                + (f"｜已收 {item['quote_count']} 份报价" if item.get("quote_count") else "")
                for item in status_items[:5]
            ]
            answer = f"本会话共 {len(status_items)} 条询盘：\n" + "\n".join(status_lines)
        elif route in {"product_flow", "selection_flow"} and "search_products" in tools:
            events.append(("tool_call", {"tool": "search_products", "status": "running"}))
            tool_calls.append("search_products")
            keyword = select_search_keyword(message, state.get("understanding"))
            result = await _call_tool(
                tools["search_products"], ProductSearchQuery(keyword=keyword, page_size=MAX_SEARCH_ITEMS)
            )
            events.append(("tool_call", {"tool": "search_products", "status": "done"}))
            # 回答形式（ChatGPT/Perplexity 卡片模式）：数据交给卡片，文本只做简短引导，
            # 不再逐条复读卡片内容（此前名称/供应商/参数/URL 全部重复一遍，可读性差）。
            # 同名去重：站点数据存在同名多 listing（如"2BE系列"×4），展示层只留首个
            seen_names: set[str] = set()
            deduped: list[Any] = []
            for item in result.items:
                if item.name in seen_names:
                    continue
                seen_names.add(item.name)
                deduped.append(item)
            shown = deduped[:MAX_SEARCH_ITEMS]
            for item in shown:
                events.append(("citation", {"title": item.name, "url": item.url, "trust": "merchant"}))
            cards, _shown_count = _product_cards_payload(shown, whitelist)
            for card in cards:
                events.append(("card", card))
            if shown:
                keyword_text = f"与「{keyword}」相关的" if keyword else ""
                answer = (
                    f"为您找到 {_shown_count} 款{keyword_text}产品，点击卡片可查看参数与详情。"
                    "如需精确匹配，可告诉我目标真空度或抽速，也可以直接发起询盘。"
                )
            else:
                # spec 02 §1.2（N2）：零命中是知识缺口信号——注入记录器落 no_match 事件
                if deps.no_match_recorder is not None:
                    deps.no_match_recorder(
                        {
                            "session_id": state["session_id"],
                            "question": message,
                            "route": "product_flow",
                            "keyword": keyword,
                        }
                    )
                answer = "暂未找到匹配产品，您可以换个说法（如「无油旋片泵」），或直接提交询盘让供应商来找您。"
        elif route == "knowledge_flow" and deps.rag is not None:
            tool_calls.append("search_knowledge")
            events.append(("tool_call", {"tool": "search_knowledge", "status": "running"}))
            # 01-port-spec §6.4.1：understanding.entities → SpecCriteria 规格过滤（回落保护在 pipeline 内）
            spec = extract_spec_criteria((state.get("understanding") or {}).get("entities") or {})
            # ADR-0009 D5：指代追问的检索改写——"它适合什么场景？"零语义，向量召回必差。
            # 仅当消息含指代词/场景标记时，用槽位合并解析出的品类实体补写检索词
            # （软信号：只加检索词，不决定查询；新话题不含指代词则不补写，防陈旧污染）。
            retrieval_query = state.get("message", "")
            if any(w in retrieval_query for w in ("它", "这个", "该", "这种", "此", *SCENARIO_MARKERS)):
                entities = (state.get("understanding") or {}).get("entities") or {}
                category = entities.get("product_category")
                if isinstance(category, list):
                    category = next((c for c in category if isinstance(c, str)), "")
                if isinstance(category, str) and category.strip() and category.strip() not in retrieval_query:
                    retrieval_query = f"{retrieval_query} {category.strip()}"
            context, chunks = await deps.rag.context_for(retrieval_query, spec=None if spec.is_empty else spec)
            events.append(("retrieval", {"count": len(chunks), "trust": [c.trust_level for c in chunks]}))
            # spec 02 §1.2（N2）：知识零召回也是缺口信号（改写后的检索词作 keyword 供聚类）
            if not chunks and deps.no_match_recorder is not None:
                deps.no_match_recorder(
                    {
                        "session_id": state["session_id"],
                        "question": message,
                        "route": "knowledge_flow",
                        "keyword": retrieval_query,
                    }
                )
            for i, c in enumerate(chunks, start=1):
                events.append(
                    (
                        "citation",
                        {"index": i, "title": c.title, "trust": c.trust_level, **({"url": c.url} if c.url else {})},
                    )
                )
            # 真流式 LLM 回答：token 经 custom 通道实时推送（sse_mapper 转发 answer_delta）
            writer = get_stream_writer()
            answer_system = (
                deps.prompts.render(
                    "base_constitution", display_name=deps.manifest.display_name, suggested_questions=[]
                )
                + "\n\n"
                + deps.prompts.render("security_constitution")
            )
            answer_system += "\n\n" + deps.prompts.render("citation_required_answer")
            # ADR-0008 D2：回答 LLM 注入最近 4 轮对话（每条截断 120 字符）——
            # 多轮指代（"它多少钱""第一个呢"）此前只进了意图提取，回答层完全失忆。
            answer_history = deps.store.messages(state["session_id"])[-9:-1]  # 去掉本轮 user 消息
            history_text = "\n".join(f"{m.get('role', '')}: {str(m.get('content', ''))[:120]}" for m in answer_history)
            answer_user = (
                (f"【对话历史（最近轮次）】\n{history_text}\n\n" if history_text.strip() else "")
                + "【问题】"
                + message
                + "\n\n【资料】\n"
                + context
            )
            pieces: list[str] = []
            try:
                async for token in deps.llm.stream_text(answer_system, answer_user):
                    pieces.append(token)
                    writer({"answer_delta": token})
            except CopilotError as exc:
                logger.warning("answer.stream.failed", error=str(exc))
            answer = "".join(pieces)
            if not answer.strip():
                # 模型空答兜底：退回引用列表模板
                lines = [f"[{i + 1}] {c.title}（{c.trust_level}）" for i, c in enumerate(chunks)]
                answer = "根据站内资料：\n" + "\n".join(lines)
            _, invalid = validate_citations(answer, len(chunks))
            if invalid:
                logger.warning("citation.invalid", invalid=invalid)  # 流式后校验：违规引用记 trace
            answer += "\n如需进一步确认，欢迎提交询盘。"
        elif route == "supplier_flow" and "get_suppliers" in tools and deps.suppliers is not None:
            # 详情分支：问句点名公司名（前 6 字匹配）→ get_detail 档案卡
            _detail = None
            for _s in getattr(deps.suppliers, "_suppliers", []) or []:
                if _s.name[:6] and _s.name[:6] in message:
                    _detail = await deps.suppliers.get_detail(_s.id)
                    break
            if _detail is not None:
                tool_calls.append("get_suppliers")
                events.append(("tool_call", {"tool": "get_suppliers", "status": "running"}))
                events.append(("tool_call", {"tool": "get_suppliers", "status": "done"}))
                events.append(("citation", {"title": _detail.name, "url": _detail.url, "trust": "merchant"}))
                intro_src = _detail.description or ""
                events.append(
                    (
                        "card",
                        {
                            "kind": "supplier",
                            "name": _detail.name,
                            "region": _detail.region,
                            "certs": list(_detail.certifications),
                            "main_products": list(_detail.main_products),
                            "description": intro_src,
                            "url": _detail.url,
                        },
                    )
                )
                intro = _detail.description or "该公司档案完善中。"
                certs = "、".join(_detail.certifications) if _detail.certifications else "认证信息完善中"
                region = _detail.region or "地区未标注"
                cats = "、".join(_detail.main_products[:4]) if _detail.main_products else "真空设备"
                answer = (
                    f"{_detail.name}（{region}｜{certs}）\n\n"
                    f"公司简介：{intro}\n\n"
                    f"主营：{cats}\n\n"
                    "如需询价或了解更多，可提交询盘，供应商会主动与您联系。"
                )
                return {"route": route, "answer": answer, "events": events, "tool_calls": tool_calls}
            # 未点名公司 → 走列表
            # 供应商智能推荐：评分驱动筛选与匹配原因；呈现并列陈述（port-spec §3.2 中立性）
            tool_calls.append("get_suppliers")
            events.append(("tool_call", {"tool": "get_suppliers", "status": "running"}))
            entities = state.get("understanding", {}).get("entities", {})
            category = entities.get("product_category")
            region = entities.get("region") or entities.get("x_region")
            result = await _call_tool(
                tools["get_suppliers"],
                SupplierSearchQuery(keyword=str(category) if category else None),
            )
            events.append(("tool_call", {"tool": "get_suppliers", "status": "done"}))
            sup_matched = match_suppliers(
                result.items,
                category=str(category) if category else None,
                region=str(region) if region else None,
            )
            relevant = sup_matched
            lines = ["以下是为您找到的供应商（并列供参考，可按需联系）："]
            for m in relevant[:MAX_SEARCH_ITEMS]:
                cert_text = "、".join(m.supplier.certifications) if m.supplier.certifications else "无认证信息"
                region_text = m.supplier.region or "地区未标注"
                reason_text = "；".join(m.reasons) if m.reasons else "按站点默认排序"
                lines.append(f"- {m.supplier.name}（{region_text}｜{cert_text}）—— 匹配参考：{reason_text}")
                events.append(
                    (
                        "citation",
                        {"title": m.supplier.name, "url": m.supplier.url, "trust": "platform"},
                    )
                )
                events.append(
                    (
                        "card",
                        {
                            "kind": "supplier",
                            "name": m.supplier.name,
                            "region": m.supplier.region,
                            "certs": list(m.supplier.certifications),
                            "main_products": list(m.supplier.main_products),
                            "description": "；".join(m.reasons) if m.reasons else "按站点默认排序",
                            "url": m.supplier.url,
                        },
                    )
                )
            answer = "\n".join(lines)
        elif route == "compare_flow" and "get_product_detail" in tools:
            # 产品对比：两个 get_detail → 对比矩阵；中立并列，不判优劣（port-spec §3.2）
            tool_calls.append("get_product_detail")
            events.append(("tool_call", {"tool": "get_product_detail", "status": "running"}))
            ids = PRODUCT_ID_PATTERN.findall(message)[:2]
            if len(ids) < 2:
                answer = "请提供两个要对比的产品，例如：对比 demo-p-001 和 demo-p-002。"
                return {"route": route, "answer": answer, "events": events, "tool_calls": tool_calls}
            details = [await _call_tool(tools["get_product_detail"], pid) for pid in ids]
            details = [d for d in details if d is not None]
            if len(details) < 2:
                answer = "有一个产品未找到，请确认产品编号后重试。"
                return {"route": route, "answer": answer, "events": events, "tool_calls": tool_calls}
            events.append(("tool_call", {"tool": "get_product_detail", "status": "done"}))
            for product in details:
                events.append(
                    (
                        "citation",
                        {"title": product.name, "url": product.url, "trust": "merchant"},
                    )
                )
                if product.price_display.mode == "shown":
                    whitelist.add(product.price_display.text.strip())
            events.append(("card", _compare_matrix_payload(details)))
            matrix = build_compare_matrix(details)
            answer = render_compare_answer(matrix)

        else:
            answer = (
                "请补充更多信息，例如目标真空度、抽速、应用场景，我来帮您缩小范围。"
                "也可以点输入框上方「选型」→「选型向导」填工况表单。"
            )

        answer, _ = filter_output(answer, frozenset(whitelist))
        return {
            "route": route,
            "answer": answer,
            "events": events,
            "tool_calls": tool_calls,
            "spec_context": spec_ctx,
        }

    return node


async def _vacuum_system_suggestion(
    rag: Any, criteria: Any, tool_calls: list[str], events: list[tuple[str, dict[str, Any]]]
) -> str:
    """机组组合建议（P1-3）：高真空/大抽速工况 → RAG 检索选型指南，**摘录不生成**。

    触发阈值（领域启发式，与 spec_matcher 方向表同源）：极限真空 ≤ 10 Pa（高真空，
    罗茨+前级机组典型区间）或抽速 ≥ 500 m³/h（大抽速，需前级搭配）。摘录带上限
    160 字并附引用事件；rag 无召回/端口异常返回空串静默跳过，不阻塞匹配主流程。
    """
    high_vacuum = criteria.ultimate_vacuum_max is not None and criteria.ultimate_vacuum_max <= 10
    large_speed = criteria.pumping_speed_min is not None and criteria.pumping_speed_min >= 500
    if not (high_vacuum or large_speed):
        return ""
    tool_calls.append("search_knowledge")
    events.append(("tool_call", {"tool": "search_knowledge", "status": "running"}))
    focus = "高真空" if high_vacuum else "大抽速"
    try:
        chunks = await rag.search(f"{focus} 机组 罗茨泵 前级泵 搭配 选型", top_k=2)
    except CopilotError as exc:
        logger.warning("suggestion.retrieve.failed", error=str(exc))
        chunks = []
    finally:
        events.append(("tool_call", {"tool": "search_knowledge", "status": "done"}))
    if not chunks:
        return ""
    top = chunks[0]
    events.append(("citation", {"title": top.title, "trust": top.trust_level, **({"url": top.url} if top.url else {})}))
    snippet = " ".join(top.content.split())[:160]
    return f"\n\n系统建议（{focus}工况）：{snippet}……\n（摘自站内资料「{top.title}」；具体机组配置以供应商方案为准。）"


def _inquiry_node(deps: GraphDeps) -> Any:
    async def node(state: AgentState) -> dict[str, Any]:
        events: list[tuple[str, dict[str, Any]]] = []
        sink = deps.inquiry_sink
        if sink is None or not deps.manifest.ports.inquiry_sink.enabled:
            events.append(("error", {"code": "PORT_DISABLED", "message": "询盘能力未启用"}))
            return {"route": "inquiry_flow", "answer": "当前环境未接入询盘通道。", "events": events}

        cfg = deps.manifest.ports.inquiry_sink
        contact_in = state.get("contact") or {}
        contact = Contact(
            name=contact_in.get("name") or "",
            company=contact_in.get("company"),
            phone=contact_in.get("phone") or "",
            email=contact_in.get("email"),
        )
        provided = {
            "contact_name": bool(contact.name),
            "contact_phone": bool(contact.phone),
        }
        missing = [f for f in cfg.required_fields if not provided.get(f, False)]
        if missing:
            names = "、".join({"contact_name": "联系人", "contact_phone": "手机号"}.get(f, f) for f in missing)
            answer = f"请您补充以下信息以便创建询盘：{names}（如：13800000000）。"
            return {"route": "inquiry_flow", "answer": answer, "events": events}

        if state.get("user_ref") is None and not cfg.guest_allowed:
            answer = "创建询盘需要先注册/登录，请您登录后再试。"
            return {"route": "inquiry_flow", "answer": answer, "events": events}

        u = state.get("understanding", {})
        # P1-4 询盘工况带入：历史轮 spec_context 为底、当前轮实体优先，先聊规格后询盘不丢工况
        merged_params: dict[str, Any] = {**(state.get("spec_context") or {}), **(u.get("entities") or {})}
        spec_bits = spec_summary(merged_params)
        extract = AiExtract(
            intent=u.get("intent", "inquiry_flow"),
            confidence=float(u.get("confidence", 0.5)),
            entities=u.get("entities", {}),
            lead_level="high" if (state.get("quantity") or 0) >= 5 else "medium",
            lead_market_candidate=(state.get("quantity") or 0) >= 5,
            missing_fields=[],
        )
        summary = json.dumps(
            {"product": state.get("product_id"), "quantity": state.get("quantity"), "contact": contact.model_dump()},
            ensure_ascii=False,
            sort_keys=True,
        )
        key = hashlib.sha256(f"{state['session_id']}|{summary}".encode()).hexdigest()
        draft = InquiryDraft(
            session_id=state["session_id"],
            user_ref=state.get("user_ref"),
            product_id=state.get("product_id"),
            quantity=state.get("quantity"),
            params=merged_params,
            message=state.get("message", "")[:1000],
            contact=contact,
            lead_score=min(100, 40 + (10 if extract.lead_market_candidate else 0)),
            ai_extract=extract,
            idempotency_key=key,
        )
        spec_note = f"工况：{spec_bits}。" if spec_bits else ""
        answer = (
            f"请您确认以下询盘信息：产品 {draft.product_id}，数量 {draft.quantity}，"
            f"联系人 {contact.name}（{_mask(contact.phone)}）。{spec_note}确认无误请回复“确认提交”。"
        )
        pending = {"confirm_id": key[:16], "draft_json": draft.model_dump_json()}
        # Human-in-the-loop: pause execution; checkpoint persists state (thread_id = session_id).
        # Resume via Command(resume={"action": "confirm_inquiry"|"cancel_inquiry"}) re-enters here.
        approval = interrupt(pending)
        action = (approval or {}).get("action")
        if action != "confirm_inquiry":
            answer = "已取消，本次不提交任何信息。"
            return {"route": "inquiry_flow", "answer": answer, "events": events}
        # 行内编辑回传：resume 可携带 draft_override（quantity/contact_name/contact_phone），白名单合并
        override = (approval or {}).get("draft_override") or {}
        if override:
            _q = override.get("quantity")
            if isinstance(_q, int) and 0 < _q <= 100000:
                draft.quantity = _q
            _name = override.get("contact_name")
            if isinstance(_name, str) and _name.strip():
                contact.name = _name.strip()[:50]
            _phone = override.get("contact_phone")
            if isinstance(_phone, str) and _phone.strip().isdigit() and 7 <= len(_phone.strip()) <= 20:
                contact.phone = _phone.strip()
            _ct = contact.model_dump()
            provided_keys = {
                "contact_name": bool(contact.name),
                "contact_phone": bool(contact.phone),
            }
            _missing = [f for f in cfg.required_fields if not provided_keys.get(f, False)]
            if _missing:
                names = "、".join({"contact_name": "联系人", "contact_phone": "手机号"}.get(f, f) for f in _missing)
                events.append(
                    (
                        "inquiry_confirm",
                        {
                            "confirm_id": key[:16],
                            "draft": {
                                "product_id": draft.product_id,
                                "quantity": draft.quantity,
                                "contact_name": contact.name,
                                "contact_phone_masked": _mask(contact.phone),
                                "specs": spec_summary(draft.params),
                            },
                        },
                    )
                )
                answer = f"修改后仍缺少必填信息：{names}，请补充后再提交。"
                return {"route": "inquiry_flow", "answer": answer, "events": events, "needs_more_info": True}
            draft = InquiryDraft(
                session_id=draft.session_id,
                user_ref=draft.user_ref,
                product_id=draft.product_id,
                quantity=draft.quantity,
                params=draft.params,
                message=draft.message,
                contact=contact,
                lead_score=draft.lead_score,
                ai_extract=draft.ai_extract,
                idempotency_key=draft.idempotency_key,
            )
            _ = _ct  # 旧值仅用于类型完整性，不落库
        sink = deps.inquiry_sink
        if sink is None:
            events.append(("error", {"code": "PORT_DISABLED", "message": "询盘能力未启用"}))
            return {"route": "inquiry_flow", "answer": "当前环境未接入询盘通道。", "events": events}
        result = await _call_tool(sink.create, draft)
        events.append(("inquiry_created", {"inquiry_id": result.inquiry_id, "state": result.state}))
        wechat = deps.manifest.chat.wechat
        wechat_payload: dict[str, Any] = {
            "guidance": "询盘已创建，您可以添加供应商微信获取更快响应。",
        }
        if wechat.qrcode_url:
            wechat_payload["qrcode_url"] = wechat.qrcode_url
            wechat_payload["contact_name"] = wechat.contact_name or "专属工程师"
            if wechat.guidance_text:
                wechat_payload["guidance"] = wechat.guidance_text
        events.append(("wechat_guidance", wechat_payload))
        answer = "询盘已创建成功，供应商会尽快与您联系。\n您也可以添加供应商微信获取更快响应（扫描二维码）。"
        return {"route": "inquiry_flow", "answer": answer, "events": events, "confirm_done": True}

    return node


def _mask(phone: str) -> str:
    return f"{phone[:3]}****{phone[-4:]}" if len(phone) >= 7 else phone


def _understand_node(deps: GraphDeps) -> Any:
    async def node(state: AgentState) -> dict[str, Any]:
        events: list[tuple[str, dict[str, Any]]] = []
        deps.store.append_message(state["session_id"], "user", state.get("message", ""))
        # 第一层：FAQ 关键词匹配（0 token，覆盖高频问题）
        faq_answer = deps.faq_matcher.match(state.get("message", "")) if deps.faq_matcher else None
        if faq_answer:
            return {
                "understanding": {"intent": "faq_match", "route": "faq_answer", "confidence": 1.0},
                "route": "faq_answer",
                "answer": faq_answer,
                "events": [],
            }
        u = _understanding_from_tools(state, deps)
        if u is None:
            history = deps.store.messages(state["session_id"])[-6:]
            history_text = "\n".join(f"{m.get('role', '')}: {str(m.get('content', ''))[:120]}" for m in history)
            system = deps.prompts.render(
                "base_constitution",
                display_name=deps.manifest.display_name,
                suggested_questions=deps.manifest.chat.suggested_questions,
            )
            system += "\n\n" + deps.prompts.render("security_constitution")
            user = (
                deps.prompts.render(
                    "intent_entity_extraction",
                    disabled_capabilities=deps.manifest.disabled_capabilities(),
                )
                + f"\n\n对话历史（最近轮次）：\n{history_text}\n\n用户输入：{state.get('message', '')}"
            )
            raw = await deps.llm.complete_json(system, user)
            u = parse_understanding(raw)
            # 多轮槽位合并：当前轮实体 + 历史累积（slot filling）
            if u.get("entities"):
                deps.store.merge_entities(state["session_id"], u["entities"])
                u["entities"] = deps.store.merged_entities(state["session_id"])
        else:
            events.append(("status", {"message": "正在整理回答"}))
        # 确定性护栏：修正分类器在产品问法/供应商问法之间的摇摆（见 routing_guards 模块）
        u = apply_routing_guards(state.get("message", ""), u)
        if u.get("route_guard"):
            events.append(("status", {"message": "正在整理回答"}))
        # ADR-0008 D1：类型级选型咨询误入产品搜索路由 → 改道 knowledge_flow（RAG 作答）
        u = apply_selection_guard(state.get("message", ""), u)
        if u.get("route_guard") == "selection_over_search":
            events.append(("status", {"message": "正在整理回答"}))
        # ADR-0009 D4：场景类追问（"它适合什么场景"）误入 selection_flow 补工况兜底 → knowledge_flow
        u = apply_scenario_followup_guard(state.get("message", ""), u, deps.store.messages(state["session_id"])[:-1])
        if u.get("route_guard") == "scenario_over_clarify":
            events.append(("status", {"message": "正在整理回答"}))
        return {"understanding": u, "route": str(u["route"]), "events": events}

    return node


def _understanding_from_tools(state: AgentState, deps: GraphDeps) -> dict[str, Any] | None:
    """Deterministic shortcuts that bypass the LLM for tool-level intents (cost engineering)."""
    message = state.get("message", "")
    # QA-0004：能力禁用拒绝走单一决策函数（与 app.main 游客门共用，杜绝镜像漂移）
    refusal_hit = detect_capability_refusal(message, deps.refusal_policies)
    if refusal_hit is not None:
        return {
            "intent": refusal_hit.intent,
            "confidence": 0.99,
            "entities": {},
            "missing_fields": [],
            "route": "refuse_fabrication",
            "needs_clarification": False,
            "needs_human": False,
            "human_reason": None,
            "refusal_reason": refusal_hit.reason,
        }
    # 询盘状态查询：必须先于询盘创建判定（"我的询盘有人跟吗"含"询盘"二字）
    if detect_inquiry_status_query(message) and deps.inquiry_status is not None:
        return {
            "intent": "status_inquiry",
            "confidence": 0.99,
            "entities": {},
            "missing_fields": [],
            "route": "status_flow",
            "needs_clarification": False,
            "needs_human": False,
            "human_reason": None,
            "refusal_reason": None,
        }
    # 案例意图确定性路由：案例问法（+可选行业词）→ case_flow（0 token）
    case_industry, case_matched = deps.cases.detect_query(message) if deps.cases else (None, False)
    if case_matched:
        return {
            "intent": "case_inquiry",
            "confidence": 0.99,
            "entities": {"industry": case_industry} if case_industry else {},
            "missing_fields": [],
            "route": "case_flow",
            "needs_clarification": False,
            "needs_human": False,
            "human_reason": None,
            "refusal_reason": None,
        }
    # 方案意图确定性路由：行业词 + 方案问法 → solution_flow（0 token）
    solution_industry = deps.solutions.detect_query(message) if deps.solutions else None
    if solution_industry:
        return {
            "intent": "solution_inquiry",
            "confidence": 0.99,
            "entities": {"industry": solution_industry},
            "missing_fields": [],
            "route": "solution_flow",
            "needs_clarification": False,
            "needs_human": False,
            "human_reason": None,
            "refusal_reason": None,
        }
    # 询盘意图确定性路由：0 LLM token 直达 inquiry_flow（确认卡 human-in-the-loop）
    if message.strip() and any(marker in message for marker in INQUIRY_CREATE_MARKERS):
        return {
            "intent": "inquiry_flow",
            "confidence": 0.99,
            # P1-4：0-token 直达原样丢 entities，"改成抽速 500 m3/h，帮我发起询盘"
            # 的同句规格会丢；确定性扫描兜住显式「关键词+数字+单位」表达
            "entities": scan_spec_entities(message),
            "missing_fields": [],
            "route": "inquiry_flow",
            "needs_clarification": False,
            "needs_human": False,
            "human_reason": None,
            "refusal_reason": None,
        }
    # 规格意图确定性路由（P1-5）：显式「关键词+数字（+单位）」规格 + 非问询/商务守卫词
    # → 0-token 直达 spec_match_flow。LLM 理解对 "抽速 300 m3/h 的泵" 有方差（偶落澄清），
    # 确定性路由既省 token 又稳定。守卫词防误路由：概念问句（是什么/怎么/区别…）与
    # 商务问句（价格/货期/售后/厂家…）交还 LLM——refusal/selection/compare 语义更准。
    # 仅数值型规格（抽速/极限真空）触发；仅无油（无数值）不触发，保持 LLM 对选型咨询的判别。
    if deps.rag is not None and message.strip():
        scanned = scan_spec_entities(message)
        numeric_spec = any(k in scanned for k in ("pumping_speed", "ultimate_vacuum"))
        guarded = any(g in message for g in SPEC_ROUTE_GUARDS)
        if numeric_spec and not guarded:
            return {
                "intent": "spec_inquiry",
                "confidence": 0.95,
                "entities": scanned,
                "missing_fields": [],
                "route": "spec_match_flow",
                "needs_clarification": False,
                "needs_human": False,
                "human_reason": None,
                "refusal_reason": None,
            }
    if message.strip() in {"", "嗯", "好的"} and state.get("action") is None:
        return {
            "intent": "unknown",
            "confidence": 0.3,
            "entities": {},
            "missing_fields": [],
            "route": "clarify",
            "needs_clarification": True,
            "needs_human": False,
            "human_reason": None,
            "refusal_reason": None,
        }
    return None


def _route_after_understand(state: AgentState) -> str:
    return state.get("route", "clarify")


def build_graph(deps: GraphDeps, checkpointer: Any | None = None) -> Any:
    """Compile the agent graph. A checkpointer is REQUIRED for interrupt()/resume flows."""
    if not deps.refusal_policies and deps.manifest.disabled_capabilities():
        raise ConfigError("refusal policies must be derived from manifest before building graph")

    builder: StateGraph[AgentState] = StateGraph(state_schema=AgentState)
    builder.add_node("understand", _understand_node(deps))
    builder.add_node("refuse", _refusal_node(deps))
    builder.add_node("handoff", _handoff_node(deps))
    builder.add_node("respond", _respond_node(deps))
    builder.add_node("inquiry", _inquiry_node(deps))
    builder.set_entry_point("understand")
    builder.add_conditional_edges(
        "understand",
        _route_after_understand,
        {
            "refuse_fabrication": "refuse",
            "handoff_flow": "handoff",
            "inquiry_flow": "inquiry",
            "product_flow": "respond",
            "selection_flow": "respond",
            "knowledge_flow": "respond",
            "supplier_flow": "respond",
            "compare_flow": "respond",
            "clarify": "respond",
            "faq_answer": "respond",
            "spec_match_flow": "respond",
            "solution_flow": "respond",
            "case_flow": "respond",
            "status_flow": "respond",
        },
    )
    for name in ("refuse", "handoff", "respond", "inquiry"):
        builder.add_edge(name, END)
    return builder.compile(checkpointer=checkpointer)
