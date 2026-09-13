"""SSE Event Mapper: translates the LangGraph stream into the frozen 10-event contract.

Authority: docs/specs/03-api-spec.md §2. Raw graph events never reach the frontend.
"""

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


async def map_graph_stream(rt: Runtime, graph_input: Any, config: dict[str, Any]) -> AsyncIterator[str]:
    """Consume graph.astream(updates) → emit spec-compliant SSE frames.

    Interrupted runs surface as an ``__interrupt__`` update; the interrupt payload
    becomes the ``inquiry_confirm`` event (confirmation card data).
    图级异常（LLM 断连/配置缺失）→ 优雅降级 error+done，绝不裸断流。
    """
    final_answer: str | None = None
    finish_reason = "answered"
    try:
        async for chunk in rt.graph.astream(graph_input, config=config, stream_mode="updates"):
            for node, output in chunk.items():
                if node == "__interrupt__":
                    for intr in output:
                        payload = getattr(intr, "value", None) or {}
                        confirm_id = payload.get("confirm_id", "")
                        draft = payload.get("draft_json", "")
                        yield sse_text([("inquiry_confirm", {"confirm_id": confirm_id, "draft_json": draft})])
                        finish_reason = "awaiting_confirmation"
                    continue
                if not isinstance(output, dict):
                    continue
                for event in output.get("events", []):
                    yield sse_text([event])
                answer = output.get("answer")
                if answer:
                    final_answer = answer
    except Exception as exc:
        logger.error("chat.stream.failed", error=str(exc))
        yield sse_text([("error", {"code": "INTERNAL_ERROR", "message": "系统正在繁忙，请稍后再试"})])
        yield sse_text([("answer_delta", {"delta": "系统正在繁忙，请稍后再试。"})])
        yield sse_text([("done", {"finish_reason": "error"})])
        return
    if final_answer:
        rt.store.append_message(str(config["configurable"]["thread_id"]), "assistant", final_answer)
        for piece in _chunk_answer(final_answer):
            yield sse_text([("answer_delta", {"delta": piece})])
    yield sse_text([("done", {"finish_reason": finish_reason})])
