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

from rfq_copilot.app.guest_paths import (
    detect_guest_inquiry_intent,
    detect_guest_query,
    detect_solution_query,
    detect_supplier_query,
    guest_knowledge_answer,
    guest_search_answer,
    guest_supplier_answer,
    looks_like_knowledge_query,
)
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
from rfq_copilot.schemas.chat import (
    ChatRequest,
    FeedbackRequest,
    HealthResponse,
    SessionCreateRequest,
    SessionCreateResponse,
    UiConfigResponse,
)
from rfq_copilot.schemas.events import sse_text

_RUNTIME: Runtime | None = None
_LIMITER = SlidingWindowLimiter()
_BUDGET = DailyTokenBudget(get_settings().llm_daily_token_budget)


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


def _is_zero_token_intent(message: str) -> bool:
    """Guest-allowed deterministic paths: price/lead-time/stock refusals are template-only.

    Mirrors graph._understanding_from_tools markers — kept in sync intentionally (guest tier
    must not call the LLM, so we approximate the same trigger set cheaply).
    """
    markers = ("多少钱", "价格", "报价", "区间", "货期", "交期", "交货", "有货", "库存", "现货")
    return any(m in message for m in markers)


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        runtime = get_runtime()
        await init_checkpointer(runtime)
        await seed_demo(runtime)
        try:
            yield
        finally:
            await close_checkpointer(runtime)

    app = FastAPI(title="b2b-rfq-copilot", version="0.1.0", lifespan=lifespan)

    # CORS：宿主站点跨域嵌入（M4-c）；凭据头部走显式白名单方式，不使用通配 *
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"https?://.*",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
    )

    @app.post("/api/v1/sessions", response_model=SessionCreateResponse)
    async def create_session(body: SessionCreateRequest) -> SessionCreateResponse:
        rt = get_runtime()
        session_id = f"sess_{uuid.uuid4().hex[:12]}"
        rt.store.get_or_create(session_id, user_ref=body.user_ref)
        return SessionCreateResponse(session_id=session_id, token=f"tok_{uuid.uuid4().hex[:8]}")

    @app.post("/api/v1/chat/stream")
    async def chat_stream(body: ChatRequest, request: Request) -> StreamingResponse:
        rt = get_runtime()
        if not _LIMITER.allow(session_id=body.session_id, ip=request.client.host if request.client else None):

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

            async def _guest_stream(answer_text: str, events: list[tuple[str, dict[str, Any]]]) -> StreamingResponse:
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
                    sol_events: list[tuple[str, dict[str, Any]]] = [
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

            if faq is None and not _is_zero_token_intent(body.message):
                rtg.store.append_message(body.session_id, "user", body.message)
                guidance = (
                    "深度咨询需要登录后使用（免费注册）。登录后我可以为您：查产品参数、做选型对比、"
                    "匹配供应商，并协助创建询盘。当前未登录状态仍可浏览常见问题与平台说明。"
                )
                wechat = rtg.manifest.chat.wechat
                suggestions = rtg.faq_registry.suggest(body.message, limit=3) if rtg.faq_registry else []
                events: list[tuple[str, dict[str, Any]]] = [
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
            if _BUDGET.remaining(body.user_ref) <= 0:
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
            graph_input: Any = Command(resume={"action": body.action})
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
        return HealthResponse(status="ok", adapter=rt.manifest.adapter, profile="demo")

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

        doc = KnowledgeDocument(
            doc_id=doc_id,
            title=title,
            doc_type=body.get("doc_type", "platform_faq"),
            trust_level=trust,
            content=content,
        )
        chunks = chunk_document(doc)
        await rt.deps.rag.ingest(chunks)
        return {"doc_id": doc_id, "chunks": len(chunks), "status": "ingested"}

    @app.delete("/api/v1/knowledge/{doc_id}")
    async def delete_knowledge(doc_id: str, request: Request) -> dict[str, Any]:
        _check_internal_token(request)
        rt = get_runtime()
        if rt.deps.rag is None:
            raise HTTPException(status_code=503, detail={"code": "PORT_DISABLED", "message": "知识库未启用"})
        removed = rt.deps.rag.remove_doc(doc_id)
        return {"doc_id": doc_id, "chunks_removed": removed}

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
        return {"status": "recorded"}

    return app


app = create_app()
