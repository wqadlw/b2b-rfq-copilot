"""Minimal LangGraph agent (M0/M1): understand → deterministic route → respond.

M2 will expand: real answer generation, checkpointer, full tool loop. Policy layer
(refusal/output-filter/confirmation-gate) and the M1 RAG pipeline are wired here.
"""

import hashlib
import inspect
import json
from dataclasses import dataclass, field
from typing import Annotated, Any, TypedDict

import structlog
from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from rfq_copilot.core.agent.llm import LLMClient
from rfq_copilot.core.manifest import Manifest
from rfq_copilot.core.memory import SessionStore
from rfq_copilot.core.policies.output_filter import filter_output
from rfq_copilot.core.policies.refusal import RefusalPolicy, refusal_answer
from rfq_copilot.core.prompts import PromptRegistry
from rfq_copilot.core.rag.citation import validate_citations
from rfq_copilot.core.rag.pipeline import RAGPipeline
from rfq_copilot.ports.errors import ConfigError
from rfq_copilot.ports.inquiry_sink import AiExtract, Contact, InquiryDraft, InquirySinkPort
from rfq_copilot.ports.lead_distribution import LeadDistributionPort
from rfq_copilot.ports.product_catalog import ProductCatalogPort, ProductSearchQuery
from rfq_copilot.ports.supplier_directory import SupplierDirectoryPort

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
        "knowledge_flow",
        "inquiry_flow",
        "handoff_flow",
        "clarify",
        "refuse_fabrication",
    }
)
LEAD_SCORE_THRESHOLD = 70


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


@dataclass
class GraphDeps:
    manifest: Manifest
    llm: LLMClient
    prompts: PromptRegistry
    refusal_policies: dict[str, RefusalPolicy]
    store: SessionStore
    catalog: ProductCatalogPort | None = None
    suppliers: SupplierDirectoryPort | None = None
    rag: RAGPipeline | None = None
    inquiry_sink: InquirySinkPort | None = None
    lead_distribution: LeadDistributionPort | None = None
    poisoned_ids: frozenset[str] = field(default_factory=frozenset)

    def tool_guard(self, name: str) -> None:
        """Explicit interception: a hallucinated/disabled tool call is denied at code level."""
        if name not in self.tool_registry():
            from rfq_copilot.ports.errors import CapabilityDisabledError

            raise CapabilityDisabledError(name)

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
        return {
            "route": "handoff_flow",
            "answer": answer,
            "events": [("handoff", {"reason": reason, "priority": priority})],
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

        if route in {"product_flow", "selection_flow"} and "search_products" in tools:
            events.append(("tool_call", {"tool": "search_products", "status": "running"}))
            tool_calls.append("search_products")
            result = await _call_tool(tools["search_products"], ProductSearchQuery(keyword=message[:40]))
            events.append(("tool_call", {"tool": "search_products", "status": "done"}))
            lines = ["为您找到以下产品（并列供参考）："]
            for item in result.items[:3]:
                specs = "；".join(f"{k}:{v}" for k, v in list(item.specs.items())[:2])
                price = item.price_display.text
                if item.price_display.mode == "shown":
                    whitelist.add(price.strip())
                lines.append(f"1. {item.name}（{item.supplier_name}）{specs}；价格：{price}。详情：{item.url}")
                events.append(("citation", {"title": item.name, "url": item.url, "trust": "merchant"}))
            answer = "\n".join(lines) if result.items else "暂未找到匹配产品，您可以补充关键词或提交询盘。"
        elif route == "knowledge_flow" and deps.rag is not None:
            tool_calls.append("search_knowledge")
            events.append(("tool_call", {"tool": "search_knowledge", "status": "running"}))
            context, chunks = await deps.rag.context_for(message)
            events.append(("retrieval", {"count": len(chunks), "trust": [c.trust_level for c in chunks]}))
            lines = [f"[{i + 1}] {c.title}（{c.trust_level}）" for i, c in enumerate(chunks)]
            answer = "根据站内资料：" + context + "\n" + "\n".join(lines)
            answer, invalid = validate_citations(answer, len(chunks))
            if invalid:
                logger.warning("citation.invalid", invalid=invalid)  # programmatic citations never trigger
            answer += "\n如需进一步确认，欢迎提交询盘。"
        else:
            answer = "请补充更多信息，例如目标真空度、抽速、应用场景，我来帮您缩小范围。"

        answer, _ = filter_output(answer, frozenset(whitelist))
        return {"route": route, "answer": answer, "events": events, "tool_calls": tool_calls}

    return node


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
            params=u.get("entities", {}),
            message=state.get("message", "")[:1000],
            contact=contact,
            lead_score=min(100, 40 + (10 if extract.lead_market_candidate else 0)),
            ai_extract=extract,
            idempotency_key=key,
        )
        pending = {"confirm_id": key[:16], "draft_json": draft.model_dump_json()}
        answer = (
            f"请您确认以下询盘信息：产品 {draft.product_id}，数量 {draft.quantity}，"
            f"联系人 {contact.name}（{_mask(contact.phone)}）。确认无误请回复“确认提交”。"
        )
        # Human-in-the-loop: pause execution; checkpoint persists state (thread_id = session_id).
        # Resume via Command(resume={"action": "confirm_inquiry"|"cancel_inquiry"}) re-enters here.
        approval = interrupt(pending)
        action = (approval or {}).get("action")
        if action != "confirm_inquiry":
            answer = "已取消，本次不提交任何信息。"
            return {"route": "inquiry_flow", "answer": answer, "events": events}
        sink = deps.inquiry_sink
        if sink is None:
            events.append(("error", {"code": "PORT_DISABLED", "message": "询盘能力未启用"}))
            return {"route": "inquiry_flow", "answer": "当前环境未接入询盘通道。", "events": events}
        result = await _call_tool(sink.create, draft)
        events.append(("inquiry_created", {"inquiry_id": result.inquiry_id, "state": result.state}))
        answer = "询盘已创建成功，供应商会尽快与您联系。"
        return {"route": "inquiry_flow", "answer": answer, "events": events, "confirm_done": True}

    return node


def _mask(phone: str) -> str:
    return f"{phone[:3]}****{phone[-4:]}" if len(phone) >= 7 else phone


def _understand_node(deps: GraphDeps) -> Any:
    async def node(state: AgentState) -> dict[str, Any]:
        events: list[tuple[str, dict[str, Any]]] = [("status", {"message": "正在理解您的需求"})]
        deps.store.append_message(state["session_id"], "user", state.get("message", ""))
        u = _understanding_from_tools(state, deps)
        if u is None:
            history = deps.store.messages(state["session_id"])[-6:]
            history_text = "\n".join(f"{m['role']}: {m['content'][:80]}" for m in history)
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
        else:
            events.append(("status", {"message": "正在整理回答"}))
        return {"understanding": u, "route": str(u["route"]), "events": events}

    return node


def _understanding_from_tools(state: AgentState, deps: GraphDeps) -> dict[str, Any] | None:
    """Deterministic shortcuts that bypass the LLM for tool-level intents (cost engineering)."""
    message = state.get("message", "")
    policy_by_intent = {
        intent: cap for cap, policy in deps.refusal_policies.items() for intent in policy.trigger_intents
    }
    for intent, capability in policy_by_intent.items():
        markers = {
            "price_inquiry": ("多少钱", "价格", "报价", "区间"),
            "discount_inquiry": ("折扣", "优惠"),
            "lead_time_inquiry": ("货期", "交期", "交货", "多久"),
            "stock_inquiry": ("有货", "库存"),
        }.get(intent, ())
        if any(m in message for m in markers):
            reason = {
                "pricing": "pricing_disabled",
                "lead_time": "lead_time_disabled",
                "stock": "stock_disabled",
            }[capability]
            return {
                "intent": intent,
                "confidence": 0.99,
                "entities": {},
                "missing_fields": [],
                "route": "refuse_fabrication",
                "needs_clarification": False,
                "needs_human": False,
                "human_reason": None,
                "refusal_reason": reason,
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
            "clarify": "respond",
        },
    )
    for name in ("refuse", "handoff", "respond", "inquiry"):
        builder.add_edge(name, END)
    return builder.compile(checkpointer=checkpointer)
