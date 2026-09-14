"""SSE Event Mapper: translates the LangGraph stream into the frozen 10-event contract.

Authority: docs/specs/03-api-spec.md §2. Raw graph events never reach the frontend.
Also the single metrics observation point: sees routes, events, finish reasons,
and per-turn LLM consumption (before/after snapshots of the client's counters).
"""

import time
from collections.abc import AsyncIterator
from typing import Any

import structlog

from rfq_copilot.app.runtime import Runtime
from rfq_copilot.schemas.events import sse_text

logger = structlog.get_logger(__name__)

_CHUNK_SIZE = 24


def _mask(phone: str) -> str:
    return f"{phone[:3]}****{phone[-4:]}" if len(phone) >= 7 else phone


def _chunk_answer(answer: str) -> list[str]:
    return [answer[i : i + _CHUNK_SIZE] for i in range(0, len(answer), _CHUNK_SIZE)]


def _llm_counters(llm: Any) -> tuple[int, int, int, int]:
    calls = getattr(llm, "call_count", None)
    if calls is None:
        calls = len(getattr(llm, "calls", []))
    return (
        calls,
        getattr(llm, "prompt_tokens_total", 0),
        getattr(llm, "completion_tokens_total", 0),
        getattr(llm, "stream_chars_total", 0),
    )


def _record_turn(
    rt: Runtime,
    session_id: str,
    question: str,
    route: str,
    faq_hit: bool,
    inquiry_created: bool,
    before: tuple[int, int, int, int],
    t0: float,
    *,
    errored: bool = False,
) -> None:
    after = _llm_counters(rt.deps.llm)
    rt.metrics.record_turn(
        session_id=session_id,
        question=question,
        route=route,
        faq_hit=faq_hit,
        llm_calls=max(0, after[0] - before[0]),
        prompt_tokens=max(0, after[1] - before[1]),
        completion_tokens=max(0, after[2] - before[2]),
        stream_chars=max(0, after[3] - before[3]),
        latency_ms=int((time.perf_counter() - t0) * 1000),
        inquiry_created=inquiry_created,
        errored=errored,
    )


async def map_graph_stream(rt: Runtime, graph_input: Any, config: dict[str, Any]) -> AsyncIterator[str]:
    """Consume graph.astream(updates) → emit spec-compliant SSE frames.

    Interrupted runs surface as an ``__interrupt__`` update; the interrupt payload
    becomes the ``inquiry_confirm`` event (confirmation card data).
    图级异常（LLM 断连/配置缺失）→ 优雅降级 error+done，绝不裸断流。
    """
    t0 = time.perf_counter()
    before = _llm_counters(rt.deps.llm)
    session_id = str(config["configurable"]["thread_id"])
    question = graph_input.get("message", "") if isinstance(graph_input, dict) else ""
    final_answer: str | None = None
    finish_reason = "answered"
    route = ""
    faq_hit = False
    tool_calls: list[str] = []
    citations: list[dict[str, Any]] = []
    event_trail: list[tuple[str, dict[str, Any]]] = []
    try:
        if isinstance(graph_input, dict):
            yield sse_text([("status", {"message": "正在理解您的需求"})])
        async for mode, chunk in rt.graph.astream(graph_input, config=config, stream_mode=["updates", "custom"]):
            if mode == "custom":
                if isinstance(chunk, dict) and "answer_delta" in chunk:
                    final_answer = (final_answer or "") + str(chunk["answer_delta"])
                    yield sse_text([("answer_delta", {"delta": str(chunk["answer_delta"])})])
                continue
            for node, output in chunk.items():
                if node == "__interrupt__":
                    for intr in output:
                        payload = getattr(intr, "value", None) or {}
                        confirm_id = payload.get("confirm_id", "")
                        draft = payload.get("draft_json", "")
                        event_trail.append(("inquiry_confirm", {"confirm_id": confirm_id}))
                        yield sse_text([("inquiry_confirm", {"confirm_id": confirm_id, "draft_json": draft})])
                        finish_reason = "awaiting_confirmation"
                    continue
                if not isinstance(output, dict):
                    continue
                if output.get("route"):
                    route = str(output["route"])
                if node == "understand" and "answer" in output:
                    faq_hit = True
                for event in output.get("events", []):
                    if event[0] == "citation":
                        citations.append(event[1])
                    event_trail.append(event)
                    yield sse_text([event])
                for tc in output.get("tool_calls", []):
                    tool_calls.append(tc)
                answer = output.get("answer")
                if answer:
                    final_answer = answer
    except Exception as exc:
        logger.error("chat.stream.failed", error=str(exc))
        _record_turn(rt, session_id, question, route, faq_hit, False, before, t0, errored=True)
        yield sse_text([("error", {"code": "INTERNAL_ERROR", "message": "系统正在繁忙，请稍后再试"})])
        yield sse_text([("answer_delta", {"delta": "系统正在繁忙，请稍后再试。"})])
        yield sse_text([("done", {"finish_reason": "error"})])
        return
    if final_answer:
        meta: dict[str, Any] = {}
        if tool_calls:
            meta["tool_calls"] = tool_calls
        if citations:
            meta["citations"] = citations
        if event_trail:
            meta["events"] = event_trail
        rt.store.append_message(session_id, "assistant", final_answer, **meta)
        for piece in _chunk_answer(final_answer):
            yield sse_text([("answer_delta", {"delta": piece})])
    _record_turn(rt, session_id, question, route, faq_hit, "inquiry_created" in [e[0] for e in event_trail], before, t0)
    yield sse_text([("done", {"finish_reason": finish_reason})])
