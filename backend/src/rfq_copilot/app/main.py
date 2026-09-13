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

from rfq_copilot.app.limiter import SlidingWindowLimiter
from rfq_copilot.app.runtime import Runtime, build_runtime, seed_demo, ui_config
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


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await seed_demo(get_runtime())
        yield

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
    async def messages(session_id: str) -> dict[str, Any]:
        return {"messages": get_runtime().store.messages(session_id), "has_more": False}

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

    @app.post("/api/v1/feedback")
    async def feedback(body: FeedbackRequest) -> dict[str, str]:
        return {"status": "recorded"}

    return app


app = create_app()
