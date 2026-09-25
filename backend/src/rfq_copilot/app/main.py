"""FastAPI composition root: sessions / chat stream (SSE) / ui-config / health / feedback."""

import hmac
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langgraph.types import Command

from rfq_copilot.app import knowledge_admin
from rfq_copilot.app.guest_paths import (
    detect_case_query,
    detect_guest_inquiry_intent,
    detect_guest_query,
    detect_inquiry_status_query,
    detect_solution_query,
    detect_supplier_query,
    guest_knowledge_answer,
    guest_search_answer,
    guest_supplier_answer,
    looks_like_knowledge_query,
)
from rfq_copilot.app.knowledge_refresh import start_knowledge_refresh
from rfq_copilot.app.limiter import DailyTokenBudget, SlidingWindowLimiter
from rfq_copilot.app.metrics import VALID_PERIODS
from rfq_copilot.app.runtime import (
    Runtime,
    build_runtime,
    close_checkpointer,
    init_checkpointer,
    seed_demo,
    ui_config,
)
from rfq_copilot.app.sse_mapper import map_graph_stream
from rfq_copilot.config.settings import get_settings
from rfq_copilot.core.auth.ticket import verify_ticket
from rfq_copilot.core.policies.refusal import RefusalPolicy, detect_capability_refusal
from rfq_copilot.core.rag.spec_matcher import extract_spec_criteria
from rfq_copilot.schemas.chat import (
    ChatRequest,
    FeedbackRequest,
    HealthResponse,
    SessionCreateRequest,
    SessionCreateResponse,
    TestRetrievalRequest,
    UiConfigResponse,
)
from rfq_copilot.schemas.events import EventName, sse_text

_RUNTIME: Runtime | None = None
_LIMITER: SlidingWindowLimiter | None = None
_BUDGET: DailyTokenBudget | None = None


def _get_limiter() -> SlidingWindowLimiter:
    """惰性构造限流器（QA-0008：import 期固化使日额度不可热更）。"""
    global _LIMITER
    if _LIMITER is None:
        _LIMITER = SlidingWindowLimiter()
    return _LIMITER


def _get_budget() -> DailyTokenBudget:
    """惰性构造预算，跟随 get_settings() 当前值；配置刷新后调 reset_rate_limit_state()。"""
    global _BUDGET
    if _BUDGET is None:
        _BUDGET = DailyTokenBudget(get_settings().llm_daily_token_budget)
    return _BUDGET


def reset_rate_limit_state() -> None:
    """配置热更后由运维/测试显式调用：下一次请求按新 Settings 重建预算。"""
    global _LIMITER, _BUDGET
    _LIMITER = None
    _BUDGET = None


def _resolve_user_ref(
    raw_user_ref: str | None,
    ai_ticket: str | None,
    *,
    secret: str,
) -> tuple[str | None, str | None]:
    """E1 鉴权桥：ai_ticket 验签通过才信任 user_ref；否则视为游客。

    返回 (user_ref, reason)。secret 未配置（本地开发）时保留旧行为——
    裸 user_ref 仍生效（向后兼容，生产必须配置 AI_TICKET_SECRET）。
    """
    if raw_user_ref and ai_ticket:
        if not secret:
            return raw_user_ref, None  # 未启用鉴权桥：向后兼容
        result = verify_ticket(ai_ticket, secret)
        if result.ok and result.user_id == raw_user_ref:
            return raw_user_ref, None
        return None, result.reason
    if raw_user_ref and secret:
        return None, "ticket_required"  # 启用鉴权桥后，裸 user_ref 一律降级
    return raw_user_ref, None


def get_runtime() -> Runtime:
    global _RUNTIME
    if _RUNTIME is None:
        _RUNTIME = build_runtime()
    return _RUNTIME


def _check_internal_token(request: Request) -> None:
    """X-Internal-Token 校验；配置缺失即拒绝（防裸奔），不匹配直接 401。

    Token 只从 Settings（.env / 环境变量）读取——os.environ 看不到 .env 文件。
    hmac.compare_digest 常量时间比较，防时序侧信道。
    """
    expected = get_settings().internal_api_token
    provided = request.headers.get("X-Internal-Token", "")
    if not expected or not provided or not hmac.compare_digest(expected.encode("utf-8"), provided.encode("utf-8")):
        raise HTTPException(
            status_code=401,
            detail={"code": "UPSTREAM_AUTH", "message": "invalid internal token"},
        )


def _guest_refusal_hit(message: str, refusal_policies: dict[str, RefusalPolicy]) -> bool:
    """QA-0004：游客 0-token 放行判定——与 graph 共用单一确定性决策。

    仅当消息命中「已禁用能力」的拒绝触发词时才放行进 graph（graph 必然以模板拒绝、
    0 token）；能力开启（无策略）时返回 False，游客在门外即 login_required，
    绝不触达 LLM。旧手抄 marker 镜像（_is_zero_token_intent）已废弃。
    """
    return detect_capability_refusal(message, refusal_policies) is not None


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        runtime = get_runtime()
        await init_checkpointer(runtime)
        await seed_demo(runtime)
        refresh_task = start_knowledge_refresh(runtime)  # 08-spec §6：门禁不满足返回 None
        try:
            yield
        finally:
            if refresh_task is not None:
                refresh_task.cancel()
            await close_checkpointer(runtime)

    app = FastAPI(title="b2b-rfq-copilot", version="0.1.0", lifespan=lifespan)

    # CORS（QA-0001 / ADR-0005）：永不通配源+凭证。生产由 CORS_ALLOW_ORIGINS 显式
    # 白名单；未配置时仅放行本机开发源（localhost/127.0.0.1），默认拒绝其余跨域。
    # 方法/头按最小权限枚举（ADR-0005 收紧补充）：widget 只用 GET/POST + Content-Type，
    # 内部端点走 X-Internal-Token 服务器间调用不经浏览器，预检层直接拒绝 X-Internal-Token。
    cors_origins = [o.strip() for o in get_settings().cors_allow_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
        allow_credentials=False,  # 鉴权走请求体 ai_ticket（E1），不依赖 cookies
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
        max_age=600,
    )

    @app.post("/api/v1/sessions", response_model=SessionCreateResponse)
    async def create_session(body: SessionCreateRequest) -> SessionCreateResponse:
        rt = get_runtime()
        user_ref, _reason = _resolve_user_ref(body.user_ref, body.ai_ticket, secret=get_settings().ai_ticket_secret)
        session_id = f"sess_{uuid.uuid4().hex[:12]}"
        rt.store.get_or_create(session_id, user_ref=user_ref)
        return SessionCreateResponse(session_id=session_id, token=f"tok_{uuid.uuid4().hex[:8]}")

    @app.post("/api/v1/chat/stream")
    async def chat_stream(body: ChatRequest, request: Request) -> StreamingResponse:
        rt = get_runtime()
        body.user_ref, _ticket_reason = _resolve_user_ref(
            body.user_ref, body.ai_ticket, secret=get_settings().ai_ticket_secret
        )
        if not _get_limiter().allow(session_id=body.session_id, ip=request.client.host if request.client else None):

            async def _limited() -> AsyncIterator[str]:
                yield sse_text([("error", {"code": "RATE_LIMITED", "message": "请求过于频繁，请稍后再试"})])
                yield sse_text([("answer_delta", {"delta": "请求过于频繁，请稍后再试。"})])
                yield sse_text([("done", {"finish_reason": "rate_limited"})])

            return StreamingResponse(_limited(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
        # ---- Tiered access (guest gate): guests get 0-token paths only (FAQ/deterministic
        # shortcuts); LLM-requiring turns require login (user_ref). Inquiry creation is the
        # conversion goal — guided, not blocked: guests are told to log in first.
        if (
            get_settings().guest_tier_enabled
            and not body.user_ref
            and body.message.strip()
            and not body.action
            and not detect_guest_inquiry_intent(body.message)
        ):
            rtg = get_runtime()
            faq = rtg.deps.faq_matcher.match(body.message) if rtg.deps.faq_matcher else None

            async def _guest_stream(
                answer_text: str, events: list[tuple[EventName, dict[str, Any]]]
            ) -> StreamingResponse:
                async def _gen() -> AsyncIterator[str]:
                    yield sse_text([("status", {"message": "正在查询"})])
                    yield sse_text([("answer_delta", {"delta": answer_text})])
                    for ev in events:
                        yield sse_text([ev])
                    yield sse_text([("done", {"finish_reason": "answered"})])

                return StreamingResponse(
                    _gen(),
                    media_type="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
                )

            # G0: FAQ hit -> free answer
            if faq is not None:
                rtg.store.append_message(body.session_id, "user", body.message)
                rtg.store.append_message(body.session_id, "assistant", faq)
                return await _guest_stream(faq, [])

            # G4: 行业方案捷径（0 token 公开知识：痛点/拓扑/关联供应商，含 solution 卡）
            solution_industry = detect_solution_query(body.message)
            if solution_industry and rtg.deps.solutions is not None:
                rtg.store.append_message(body.session_id, "user", body.message)
                solution = rtg.deps.solutions.by_industry(solution_industry)
                if solution is not None:
                    sol_events: list[tuple[EventName, dict[str, Any]]] = [
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
                    ]
                    sol_answer = (
                        f"「{solution.industry_name}」行业已有一套成熟方案：{solution.name}。"
                        "卡片内含痛点分析与设备拓扑，点击可查看完整方案；登录后可让 AI 按您的产量匹配机型。"
                    )
                    rtg.store.append_message(body.session_id, "assistant", sol_answer)
                    return await _guest_stream(sol_answer, sol_events)

            # G4.5: 客户案例捷径（0 token 公开背书：量化指标/客户成效，含 case 卡）
            case_industry, case_matched = detect_case_query(body.message)
            if case_matched and rtg.deps.cases is not None:
                rtg.store.append_message(body.session_id, "user", body.message)
                case_hits = rtg.deps.cases.by_industry_slug(case_industry)[:3]
                if case_hits:
                    case_events: list[tuple[EventName, dict[str, Any]]] = []
                    for case in case_hits:
                        case_events.append(("citation", {"title": case.title, "url": case.url, "trust": "platform"}))
                        case_events.append(
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
                    case_answer = (
                        f"找到 {len(case_hits)} 个{case_scope}交付案例"
                        "（卡片含量化指标与客户成效）。白皮书可在案例页留资下载。"
                    )
                    rtg.store.append_message(body.session_id, "assistant", case_answer)
                    return await _guest_stream(case_answer, case_events)

            # G4.6: 询盘状态捷径（session_id 即凭证；0 token 只读摘要）
            if detect_inquiry_status_query(body.message) and rtg.deps.inquiry_status is not None:
                rtg.store.append_message(body.session_id, "user", body.message)
                status_payload = await rtg.deps.inquiry_status.by_session(body.session_id)
                status_items = status_payload.get("items") or []
                if not status_items:
                    no_answer = "本会话还没有创建过询盘。您可以直接发起询盘，创建后在这里随时查询进展。"
                    rtg.store.append_message(body.session_id, "assistant", no_answer)
                    return await _guest_stream(no_answer, [])
                status_lines = []
                status_events: list[tuple[EventName, dict[str, Any]]] = []
                for item in status_items[:5]:
                    quote_note = f"收到 {item['quote_count']} 份报价" if item.get("quote_count") else "待供应商报价"
                    status_lines.append(
                        f"  · [{item['inquiry_id']}] {item['title']}｜状态：{item['status_text']}｜{quote_note}"
                    )
                    status_events.append(
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
                status_answer = (
                    f"本会话共 {len(status_items)} 条询盘，进展如下：\n"
                    + "\n".join(status_lines)
                    + "\n如需修改或补充，直接告诉我，或扫码联系专属工程师。"
                )
                rtg.store.append_message(body.session_id, "assistant", status_answer)
                return await _guest_stream(status_answer, status_events)

            # G3: 供应商白名单（0 token 公开档案：列表/详情，含 card 结构化事件）
            supplier_mode = detect_supplier_query(body.message, rtg.deps.suppliers)
            if supplier_mode and rtg.deps.suppliers is not None:
                rtg.store.append_message(body.session_id, "user", body.message)
                sup_result = await guest_supplier_answer(supplier_mode, rtg.deps.suppliers)
                rtg.store.append_message(body.session_id, "assistant", sup_result["answer"])
                return await _guest_stream(sup_result["answer"], sup_result["events"])

            # G2 优先：知识/对比类问题先走引用（"X和Y有什么区别"即使含产品词也是知识问答）
            # 询盘意图消息跳过 G1/G2 捷径——直达 graph inquiry_flow（确认卡 human-in-the-loop）
            if (
                looks_like_knowledge_query(body.message)
                and rtg.deps.rag is not None
                and not detect_guest_inquiry_intent(body.message)
            ):
                rtg.store.append_message(body.session_id, "user", body.message)
                knowledge_result = await guest_knowledge_answer(body.message, rtg.deps.rag, rtg.manifest)
                if knowledge_result is not None:
                    rtg.store.append_message(body.session_id, "assistant", knowledge_result["answer"])
                    return await _guest_stream(knowledge_result["answer"], knowledge_result["events"])

            # G1: explicit product word / demo id -> direct catalog search (0 token)
            guest_query = "" if detect_guest_inquiry_intent(body.message) else detect_guest_query(body.message)
            if guest_query:
                rtg.store.append_message(body.session_id, "user", body.message)
                result = await guest_search_answer(guest_query, rtg.deps.catalog, rtg.manifest)
                rtg.store.append_message(body.session_id, "assistant", result["answer"])
                return await _guest_stream(result["answer"], result["events"])

            if faq is None and not _guest_refusal_hit(body.message, rtg.deps.refusal_policies):
                rtg.store.append_message(body.session_id, "user", body.message)
                guidance = (
                    "深度咨询需要登录后使用（免费注册）。登录后我可以为您：查产品参数、做选型对比、"
                    "匹配供应商，并协助创建询盘。当前未登录状态仍可浏览常见问题与平台说明。"
                )
                wechat = rtg.manifest.chat.wechat
                suggestions = rtg.faq_registry.suggest(body.message, limit=3) if rtg.faq_registry else []
                events: list[tuple[EventName, dict[str, Any]]] = [
                    ("login_required", {"reason": "llm_turn", "suggestions": suggestions})
                ]
                if wechat.qrcode_url:
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

                async def _guest_gate() -> AsyncIterator[str]:
                    yield sse_text([("status", {"message": "需要登录"})])
                    yield sse_text([("login_required", {"reason": "llm_turn"})])
                    yield sse_text([("answer_delta", {"delta": guidance})])
                    for ev in events[1:]:
                        yield sse_text([ev])
                    yield sse_text([("done", {"finish_reason": "login_required"})])

                return StreamingResponse(
                    _guest_gate(),
                    media_type="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
                )

        # ---- Tiered access (token budget): logged-in users have a daily completion-token
        # budget; over budget -> wechat guidance, no LLM call this turn.
        if body.user_ref and not body.action:
            rtb = get_runtime()
            if _get_budget().remaining(body.user_ref) <= 0:
                rtb.store.append_message(body.session_id, "user", body.message)
                wechat = rtb.manifest.chat.wechat
                budget_answer = "您今天的 AI 使用额度已用完，明天恢复。如需立即咨询，可扫码添加专属工程师一对一响应。"

                async def _budget_gate() -> AsyncIterator[str]:
                    yield sse_text([("status", {"message": "今日额度已用完"})])
                    yield sse_text([("token_budget_exceeded", {"user_ref": body.user_ref})])
                    yield sse_text([("answer_delta", {"delta": budget_answer})])
                    if wechat.qrcode_url:
                        yield sse_text(
                            [
                                (
                                    "wechat_guidance",
                                    {
                                        "guidance": wechat.guidance_text or "扫码添加专属工程师一对一快速响应",
                                        "qrcode_url": wechat.qrcode_url,
                                        "contact_name": wechat.contact_name or "专属工程师",
                                    },
                                )
                            ]
                        )
                    yield sse_text([("done", {"finish_reason": "token_budget"})])

                return StreamingResponse(
                    _budget_gate(),
                    media_type="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
                )

        # CS-1: human_serving sessions bypass the LLM graph (0 token) — agent replies land
        # in the message store; the user's message is recorded and echoed with a status note.
        if get_runtime().store.status(body.session_id) == "human_serving" and not body.action:
            rt2 = get_runtime()
            rt2.store.append_message(body.session_id, "user", body.message)

            async def _human_serving() -> AsyncIterator[str]:
                last_agent = next(
                    (m["content"] for m in reversed(rt2.store.messages(body.session_id)) if m["role"] == "agent"),
                    None,
                )
                yield sse_text([("status", {"message": "人工服务中，坐席正在回复"})])
                if last_agent:
                    yield sse_text([("answer_delta", {"delta": last_agent})])
                yield sse_text([("done", {"finish_reason": "human_serving"})])

            return StreamingResponse(
                _human_serving(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )
        config: dict[str, Any] = {"configurable": {"thread_id": body.session_id}}
        if body.action:
            # resume an interrupted confirmation (interrupt()/Command pattern)
            # QA-0003：draft_override 随 resume 透传进 graph（白名单合并由确认门执行）
            graph_input: Any = Command(resume={"action": body.action, "draft_override": body.draft_override})
        else:
            graph_input = {
                "session_id": body.session_id,
                "user_ref": body.user_ref,
                "message": body.message,
                "contact": body.contact.model_dump() if body.contact else None,
                "quantity": body.quantity,
                "product_id": body.product_id,
                "events": [],
                "tool_calls": [],
            }
        return StreamingResponse(
            map_graph_stream(rt, graph_input, config),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",  # 关键：Nginx/反代禁缓冲，SSE 实时到达
            },
        )

    @app.get("/api/v1/ui-config", response_model=UiConfigResponse)
    async def ui_config_route() -> UiConfigResponse:
        return UiConfigResponse.model_validate(ui_config(get_runtime()))

    @app.get("/api/v1/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        rt = get_runtime()
        freshness = rt.corpus_freshness
        return HealthResponse(
            status="ok",
            adapter=rt.manifest.adapter,
            profile="demo",
            corpus_age_days=freshness.age_days if freshness is not None else None,
            corpus_stale=freshness.stale if freshness is not None else False,
            knowledge_refresh=rt.last_refresh,
            refresh_history=rt.refresh_history or None,  # spec 02 §3（N4）
        )

    @app.get("/api/v1/sessions/{session_id}/messages")
    async def messages(session_id: str, request: Request) -> dict[str, Any]:
        """Session history. Data level equals /replay: requires X-Internal-Token."""
        _check_internal_token(request)
        return {"messages": get_runtime().store.messages(session_id), "has_more": False}

    @app.get("/api/v1/sessions/{session_id}/replay")
    async def session_replay(session_id: str, request: Request) -> dict[str, Any]:
        """运营会话回放：完整消息流 + 累计槽位 + 引用/工具调用/事件轨迹。需 X-Internal-Token。"""
        _check_internal_token(request)
        state = get_runtime().store.find(session_id)
        if state is None:
            raise HTTPException(status_code=404, detail={"code": "SESSION_NOT_FOUND", "message": "会话不存在"})
        return {
            "session_id": session_id,
            "user_ref": state.user_ref,
            "merged_entities": state.merged_entities,
            "message_count": len(state.messages),
            "messages": state.messages,
        }

    @app.post("/api/v1/knowledge")
    async def add_knowledge(request: Request) -> dict[str, Any]:
        """运营自助添加知识文档（运行时生效，无需重启）。需 X-Internal-Token。"""
        _check_internal_token(request)
        rt = get_runtime()
        if rt.deps.rag is None:
            raise HTTPException(status_code=503, detail={"code": "PORT_DISABLED", "message": "知识库未启用"})
        try:
            body = await request.json()
        except ValueError:
            # JSONDecodeError 与 UnicodeDecodeError 均为 ValueError 子类：
            # 覆盖坏语法与非法 UTF-8 两种坏请求体
            raise HTTPException(
                status_code=400,
                detail={"code": "INVALID_JSON", "message": "请求体必须是合法的 UTF-8 JSON"},
            ) from None
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail={"code": "INVALID_JSON", "message": "请求体必须是 JSON 对象"})
        doc_id = body.get("doc_id", "")
        title = body.get("title", "")
        content = body.get("content", "")
        trust = body.get("trust_level", "platform")
        if not doc_id or not title or not content:
            raise HTTPException(
                status_code=400,
                detail={"code": "MISSING_FIELDS", "message": "doc_id/title/content 必填"},
            )
        from rfq_copilot.core.rag.chunking import chunk_document
        from rfq_copilot.ports.knowledge_source import KnowledgeDocument

        params = body.get("params")
        if params is not None and not (
            isinstance(params, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in params.items())
        ):
            raise HTTPException(
                status_code=400,
                detail={"code": "INVALID_PARAMS", "message": "params 必须是字符串到字符串的映射"},
            )
        doc = KnowledgeDocument(
            doc_id=doc_id,
            title=title,
            doc_type=body.get("doc_type", "platform_faq"),
            trust_level=trust,
            content=content,
            supplier_id=body.get("supplier_id") or None,
            product_id=body.get("product_id") or None,
            params=params or None,
        )
        # 替换语义：先移除旧文档家族（含 (i/n) 分块后缀），再灌新块——更新后旧块不残留
        removed = await rt.deps.rag.remove_doc(doc_id)
        chunks = chunk_document(doc)
        await rt.deps.rag.ingest(chunks)
        return {"doc_id": doc_id, "chunks": len(chunks), "replaced_chunks": removed, "status": "ingested"}

    @app.delete("/api/v1/knowledge/{doc_id}")
    async def delete_knowledge(doc_id: str, request: Request) -> dict[str, Any]:
        _check_internal_token(request)
        rt = get_runtime()
        if rt.deps.rag is None:
            raise HTTPException(status_code=503, detail={"code": "PORT_DISABLED", "message": "知识库未启用"})
        removed = await rt.deps.rag.remove_doc(doc_id)
        return {"doc_id": doc_id, "chunks_removed": removed}

    # ---- 运营只读端点（spec 02-engine-read-api-spec §2；X-Internal-Token）----

    def _admin_rag() -> Any:
        """只读端点公共前置：RAG 启用 + inmemory 后端（v1 已知降级，spec 02 §0.3）。返回窄化后的 pipeline。"""
        rt = get_runtime()
        rag = rt.deps.rag
        if rag is None:
            raise HTTPException(status_code=503, detail={"code": "PORT_DISABLED", "message": "知识库未启用"})
        if get_settings().rag_store != "inmemory":
            raise HTTPException(
                status_code=503,
                detail={"code": "ADMIN_UNSUPPORTED", "message": "运营只读端点 v1 仅支持 inmemory 存储"},
            )
        return rag

    @app.get("/api/v1/knowledge/stats")
    async def knowledge_stats(request: Request) -> dict[str, Any]:
        """知识库存总览（N3）：文档/chunk 计数 + doc_type/trust 分布 + 语料新鲜度。"""
        rag = _admin_rag()
        corpus = await rag.corpus()
        families = knowledge_admin.family_map(corpus)
        by_doc_type: dict[str, int] = {}
        by_trust: dict[str, int] = {}
        for chunks in families.values():
            first = chunks[0]
            dtype = str(first.doc_type or "unknown")
            by_doc_type[dtype] = by_doc_type.get(dtype, 0) + 1
            by_trust[first.trust_level] = by_trust.get(first.trust_level, 0) + 1
        freshness = get_runtime().corpus_freshness
        corpus_payload = (
            {
                "age_days": freshness.age_days,
                "stale": freshness.stale,
                "doc_count": freshness.doc_count,
                "source": freshness.source,
            }
            if freshness is not None
            else None
        )
        return {
            "documents": len(families),
            "chunks": len(corpus),
            "by_doc_type": by_doc_type,
            "by_trust_level": by_trust,
            "rag_store": get_settings().rag_store,
            "corpus": corpus_payload,
        }

    @app.get("/api/v1/knowledge/docs")
    async def knowledge_docs(
        request: Request,
        q: str = "",
        trust: str = "",
        doc_type: str = "",
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        """知识文档列表（N3）：家族归并 + 过滤 + 翻页；doc_id 字典序确定性排序。"""
        rag = _admin_rag()
        if page < 1 or page_size < 1 or page_size > 100:
            raise HTTPException(
                status_code=400,
                detail={"code": "INVALID_PAGINATION", "message": "page ≥ 1 且 1 ≤ page_size ≤ 100"},
            )
        corpus = await rag.corpus()
        families = knowledge_admin.family_map(corpus)
        manifest_hashes = knowledge_admin.load_manifest_hashes(get_settings().knowledge_data_dir)
        items = [
            knowledge_admin.doc_summary(base_id, chunks, manifest_hashes)
            for base_id, chunks in families.items()
        ]
        q_lower = q.strip().lower()
        if q_lower:
            items = [d for d in items if q_lower in d["doc_id"].lower() or q_lower in d["title"].lower()]
        if trust:
            items = [d for d in items if d["trust_level"] == trust]
        if doc_type:
            items = [d for d in items if d["doc_type"] == doc_type]
        total = len(items)
        start = (page - 1) * page_size
        return {"items": items[start : start + page_size], "page": page, "page_size": page_size, "total": total}

    @app.get("/api/v1/knowledge/docs/{doc_id}")
    async def knowledge_doc_detail(doc_id: str, request: Request) -> dict[str, Any]:
        """知识文档详情（N3）：家族条目 + 分块内容（chunk_index 升序）。"""
        rag = _admin_rag()
        corpus = await rag.corpus()
        families = knowledge_admin.family_map(corpus)
        base_id = knowledge_admin.base_doc_id(doc_id)
        chunks = families.get(base_id)
        if chunks is None:
            raise HTTPException(status_code=404, detail={"code": "KNOWLEDGE_NOT_FOUND", "message": "文档不存在"})
        manifest_hashes = knowledge_admin.load_manifest_hashes(get_settings().knowledge_data_dir)
        return {
            "doc": knowledge_admin.doc_summary(base_id, chunks, manifest_hashes),
            "chunks": [knowledge_admin.chunk_payload(c) for c in chunks],
        }

    @app.post("/api/v1/knowledge/test-retrieval")
    async def knowledge_test_retrieval(body: TestRetrievalRequest, request: Request) -> dict[str, Any]:
        """召回测试（N3，Dify hit_testing 形态）：带 RRF 分数，免 LLM，不触发命中统计。"""
        rag = _admin_rag()
        query = body.query.strip()
        if not query:
            raise HTTPException(status_code=400, detail={"code": "MISSING_FIELDS", "message": "query 必填"})
        if body.top_k < 1 or body.top_k > 50:
            raise HTTPException(
                status_code=400, detail={"code": "INVALID_TOP_K", "message": "top_k 取值 1~50"}
            )
        spec = extract_spec_criteria(body.entities) if body.entities else None
        scored = await rag.search_scored(query, top_k=body.top_k, spec=spec)
        records = [
            {
                "doc_id": knowledge_admin.base_doc_id(s.chunk.doc_id),
                "chunk_doc_id": s.chunk.doc_id,
                "chunk_index": s.chunk.chunk_index,
                "title": s.chunk.title,
                "content": s.chunk.content,
                "trust_level": s.chunk.trust_level,
                "score": round(s.score, 6),
            }
            for s in scored
            if s.score >= body.score_threshold
        ]
        return {
            "query": query,
            "rag_store": get_settings().rag_store,
            "count": len(records),
            "records": records,
            "routing": knowledge_admin.predict_route(query),
        }

    @app.get("/api/v1/knowledge/hit-stats")
    async def knowledge_hit_stats(request: Request, days: int = 30) -> dict[str, Any]:
        """知识命中统计（N3）：RAG search() final top-k 按日聚合；效果象限的燃料。"""
        _admin_rag()
        if days < 1 or days > 90:
            raise HTTPException(status_code=400, detail={"code": "INVALID_DAYS", "message": "days 取值 1~90"})
        return get_runtime().hit_stats.summary(days)

    # ---- 缺口事件（spec 02 §1.2，N2）----

    @app.get("/api/v1/no-match-events")
    async def no_match_events(
        request: Request, route: str = "", limit: int = 50, offset: int = 0
    ) -> dict[str, Any]:
        """缺口事件列表：产品零命中 / 知识零召回。缺口工单自动化的唯一数据源。"""
        _check_internal_token(request)
        filters = {"route": route} if route else None
        items, total = get_runtime().no_match_store.items(filters=filters, limit=limit, offset=offset)
        return {"items": items, "total": total}

    @app.get("/api/v1/no-match/stats")
    async def no_match_stats(request: Request, period: str = "today") -> dict[str, Any]:
        """缺口事件统计：按路由/按日聚合 + top 问题（候选知识池的入口视图）。"""
        _check_internal_token(request)
        if period not in VALID_PERIODS:
            raise HTTPException(
                status_code=400, detail={"code": "INVALID_PERIOD", "message": "period 仅支持 today/week/month"}
            )
        return get_runtime().no_match_store.stats(period)

    @app.get("/api/v1/analytics/summary")
    async def analytics_summary(request: Request, period: str = "today") -> dict[str, Any]:
        """运营统计看板：会话/轮次/FAQ 命中率/询盘/LLM 用量/延迟/热门问题。需 X-Internal-Token。"""
        _check_internal_token(request)
        if period not in VALID_PERIODS:
            raise HTTPException(
                status_code=400,
                detail={"code": "INVALID_PERIOD", "message": "period 仅支持 today/week/month"},
            )
        return get_runtime().metrics.summary(period)

    # ---- CS-1 agent takeover (all internal-token gated; authority: 03-api-spec §6) ----

    @app.get("/api/v1/agent/sessions")
    async def agent_sessions(request: Request, status: str = "handoff_pending") -> dict[str, Any]:
        """坐席工作台会话列表（按状态过滤）。需 X-Internal-Token。"""
        _check_internal_token(request)
        valid_statuses: tuple[str, ...] = ("bot_serving", "handoff_pending", "human_serving", "closed")
        if status not in valid_statuses:
            raise HTTPException(status_code=400, detail={"code": "INVALID_STATUS", "message": "未知会话状态"})
        rt = get_runtime()
        items = [
            {
                "session_id": state.session_id,
                "status": str(state.status),
                "user_ref": state.user_ref,
                "message_count": len(state.messages),
                "last_message": str(state.messages[-1].get("content", ""))[:80] if state.messages else "",
                "last_ts": state.messages[-1].get("ts") if state.messages else None,
            }
            for state in rt.store.list_by_status(status)  # type: ignore[arg-type]
        ]
        return {"items": items, "total": len(items)}

    @app.post("/api/v1/agent/sessions/{session_id}/takeover")
    async def agent_takeover(session_id: str, request: Request) -> dict[str, Any]:
        """坐席接管：handoff_pending/bot_serving → human_serving。需 X-Internal-Token。"""
        _check_internal_token(request)
        rt = get_runtime()
        state = rt.store.find(session_id)
        if state is None or state.status == "closed":
            raise HTTPException(status_code=404, detail={"code": "SESSION_NOT_FOUND", "message": "会话不存在或已结束"})
        rt.store.set_status(session_id, "human_serving")
        rt.store.append_message(session_id, "system", "坐席已接入，正在为您人工服务。")
        return {"session_id": session_id, "status": "human_serving"}

    @app.post("/api/v1/agent/sessions/{session_id}/reply")
    async def agent_reply(session_id: str, request: Request) -> dict[str, Any]:
        """坐席回复：直接落会话消息流（用户侧轮询/replay 可见），不进 LLM。需 X-Internal-Token。"""
        _check_internal_token(request)
        rt = get_runtime()
        state = rt.store.find(session_id)
        if state is None or state.status != "human_serving":
            msg = "会话不在人工服务状态"
            raise HTTPException(status_code=409, detail={"code": "NOT_HUMAN_SERVING", "message": msg})
        try:
            body = await request.json()
        except ValueError:
            msg = "请求体不是合法 JSON"
            raise HTTPException(status_code=400, detail={"code": "INVALID_JSON", "message": msg}) from None
        if not isinstance(body, dict) or not str(body.get("content", "")).strip():
            raise HTTPException(status_code=400, detail={"code": "MISSING_CONTENT", "message": "缺少回复内容"})
        rt.store.append_message(session_id, "agent", str(body["content"])[:2000])
        return {"session_id": session_id, "role": "agent", "delivered": True}

    @app.post("/api/v1/agent/sessions/{session_id}/close")
    async def agent_close(session_id: str, request: Request) -> dict[str, Any]:
        """结束会话（human_serving/bot_serving → closed）。需 X-Internal-Token。"""
        _check_internal_token(request)
        rt = get_runtime()
        if rt.store.find(session_id) is None:
            raise HTTPException(status_code=404, detail={"code": "SESSION_NOT_FOUND", "message": "会话不存在"})
        rt.store.set_status(session_id, "closed")
        rt.store.append_message(session_id, "system", "本次服务已结束，感谢您的咨询。")
        return {"session_id": session_id, "status": "closed"}

    @app.post("/api/v1/sessions/{session_id}/handoff-request")
    async def handoff_request(session_id: str) -> dict[str, Any]:
        """用户侧转人工（CS-1 配套，03-api-spec §4.5）：session_id 即凭证，幂等。

        bot_serving → handoff_pending + 系统消息；已在人工流程 → 幂等 200；
        closed → 409。无 LLM 成本，幂等即防滥用，不设额外限流。
        """
        rt = get_runtime()
        state = rt.store.find(session_id)
        if state is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "SESSION_NOT_FOUND", "message": "会话不存在"},
            )
        if state.status == "closed":
            raise HTTPException(
                status_code=409,
                detail={"code": "SESSION_CLOSED", "message": "会话已结束"},
            )
        if state.status == "bot_serving":
            rt.store.set_status(session_id, "handoff_pending")
            rt.store.append_message(session_id, "system", "已收到人工服务请求，工程师会尽快接入。")
        return {"session_id": session_id, "status": rt.store.status(session_id)}

    # ---- CS-faq：运营自助 FAQ 管理（chatwoot canned-response 思想，全部内部 token 门） ----

    @app.get("/api/v1/faq")
    async def list_faq(request: Request) -> dict[str, Any]:
        """运营 FAQ 库列表。需 X-Internal-Token。"""
        _check_internal_token(request)
        rt = get_runtime()
        if rt.faq_registry is None:
            raise HTTPException(status_code=503, detail={"code": "PORT_DISABLED", "message": "FAQ 未启用"})
        return {"items": rt.faq_registry.list(), "total": len(rt.faq_registry.list())}

    @app.post("/api/v1/faq")
    async def add_faq(request: Request) -> dict[str, Any]:
        """运营新增 FAQ 条目（运行时生效，立即参与游客免费答）。需 X-Internal-Token。"""
        _check_internal_token(request)
        rt = get_runtime()
        if rt.faq_registry is None:
            raise HTTPException(status_code=503, detail={"code": "PORT_DISABLED", "message": "FAQ 未启用"})
        try:
            body = await request.json()
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail={"code": "INVALID_JSON", "message": "请求体不是合法的 UTF-8 JSON"}
            ) from exc
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail={"code": "INVALID_JSON", "message": "请求体必须是 JSON 对象"})
        keywords = body.get("keywords")
        answer = body.get("answer")
        category = str(body.get("category", "通用"))
        if not isinstance(keywords, list) or not keywords or not answer or not str(answer).strip():
            raise HTTPException(
                status_code=400, detail={"code": "MISSING_FIELDS", "message": "keywords（数组）与 answer 必填"}
            )
        entry = rt.faq_registry.add(
            keywords=[str(k) for k in keywords],
            answer=str(answer)[:500],
            category=category[:20],
        )
        return {"entry": {"keywords": "、".join(entry.keywords), "answer": entry.answer, "category": entry.category}}

    @app.delete("/api/v1/faq/{index}")
    async def delete_faq(index: int, request: Request) -> dict[str, Any]:
        """运营删除 FAQ 条目（按索引）。需 X-Internal-Token。"""
        _check_internal_token(request)
        rt = get_runtime()
        if rt.faq_registry is None:
            raise HTTPException(status_code=503, detail={"code": "PORT_DISABLED", "message": "FAQ 未启用"})
        if not rt.faq_registry.remove(index):
            raise HTTPException(status_code=404, detail={"code": "FAQ_NOT_FOUND", "message": "条目不存在"})
        return {"deleted": index}

    @app.get("/api/v1/faq/suggest")
    async def suggest_faq(request: Request, q: str = "") -> dict[str, Any]:
        """ "你可能想问"推荐（公开端点：游客未命中时前端引导用，只暴露问题不暴露运营答案库全量）。"""
        rt = get_runtime()
        if rt.faq_registry is None:
            return {"items": []}
        return {"items": rt.faq_registry.suggest(q)}

    @app.post("/api/v1/feedback")
    async def feedback(body: FeedbackRequest) -> dict[str, str]:
        """用户反馈真存（spec 02 §1.1，M1/N1）：此前空壳丢数据——运营质量信号唯一来源。

        请求契约不变（网站端零改动）；响应新增 id 字段（向后兼容）。
        """
        feedback_id = uuid.uuid4().hex[:12]
        get_runtime().feedback_store.append(
            {
                "id": feedback_id,
                "session_id": body.session_id,
                "message_id": body.message_id,
                "feedback": body.feedback,
                "comment": body.comment,
            }
        )
        return {"status": "recorded", "id": feedback_id}

    @app.get("/api/v1/feedback")
    async def feedback_list(
        request: Request, feedback: str = "", session_id: str = "", limit: int = 50, offset: int = 0
    ) -> dict[str, Any]:
        """反馈列表（运营只读）：按 ts 倒序 + 可选过滤。"""
        _check_internal_token(request)
        filters: dict[str, str] = {}
        if feedback:
            filters["feedback"] = feedback
        if session_id:
            filters["session_id"] = session_id
        items, total = get_runtime().feedback_store.items(filters=filters or None, limit=limit, offset=offset)
        return {"items": items, "total": total}

    @app.get("/api/v1/feedback/stats")
    async def feedback_stats(request: Request, period: str = "today") -> dict[str, Any]:
        """反馈统计：👍👎 总量 + 按日聚合（差评列表屏/反馈分析屏数据源）。"""
        _check_internal_token(request)
        if period not in VALID_PERIODS:
            raise HTTPException(
                status_code=400, detail={"code": "INVALID_PERIOD", "message": "period 仅支持 today/week/month"}
            )
        return get_runtime().feedback_store.stats(period)

    return app


app = create_app()
