"""FastAPI composition root: sessions / chat stream (SSE) / ui-config / health / feedback."""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langgraph.types import Command

from rfq_copilot.app.limiter import SlidingWindowLimiter
from rfq_copilot.app.runtime import Runtime, build_runtime, seed_demo, ui_config
from rfq_copilot.app.sse_mapper import map_graph_stream
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

    @app.post("/api/v1/feedback")
    async def feedback(body: FeedbackRequest) -> dict[str, str]:
        return {"status": "recorded"}

    return app


app = create_app()
