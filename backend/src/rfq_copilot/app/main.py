"""FastAPI composition root: sessions / chat stream (SSE) / ui-config / health / feedback."""

import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI
from fastapi.responses import StreamingResponse

from rfq_copilot.app.runtime import Runtime, build_runtime, ui_config
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


def get_runtime() -> Runtime:
    global _RUNTIME
    if _RUNTIME is None:
        _RUNTIME = build_runtime()
    return _RUNTIME


def create_app() -> FastAPI:
    app = FastAPI(title="b2b-rfq-copilot", version="0.1.0")

    @app.post("/api/v1/sessions", response_model=SessionCreateResponse)
    async def create_session(body: SessionCreateRequest) -> SessionCreateResponse:
        rt = get_runtime()
        session_id = f"sess_{uuid.uuid4().hex[:12]}"
        rt.store.get_or_create(session_id, user_ref=body.user_ref)
        return SessionCreateResponse(session_id=session_id, token=f"tok_{uuid.uuid4().hex[:8]}")

    @app.post("/api/v1/chat/stream")
    async def chat_stream(body: ChatRequest) -> StreamingResponse:
        rt = get_runtime()
        rt.store.append_message(body.session_id, "user", body.message)
        state: dict[str, Any] = {
            "session_id": body.session_id,
            "user_ref": body.user_ref,
            "message": body.message,
            "action": body.action,
            "contact": body.contact.model_dump() if body.contact else None,
            "quantity": body.quantity,
            "product_id": body.product_id,
            "events": [],
            "tool_calls": [],
        }
        final: dict[str, Any] = await rt.graph.ainvoke(state)
        events: list[tuple[str, dict[str, Any]]] = list(final.get("events", []))
        answer = final.get("answer", "")
        if answer:
            events.append(("answer_delta", {"delta": answer}))
            rt.store.append_message(body.session_id, "assistant", answer)
        events.append(("done", {"finish_reason": "answered"}))
        return StreamingResponse(_stream(events), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    async def _stream(events: list[tuple[str, dict[str, Any]]]) -> AsyncIterator[str]:
        for name, data in events:
            yield sse_text([(name, data)])

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
