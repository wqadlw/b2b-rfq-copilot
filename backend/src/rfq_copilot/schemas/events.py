"""SSE event contracts (authority: docs/specs/03-api-spec.md §2, port-spec §8)."""

import json
from typing import Any, Literal

EventName = Literal[
    "status",
    "tool_call",
    "retrieval",
    "answer_delta",
    "citation",
    "inquiry_confirm",
    "inquiry_created",
    "handoff",
    "error",
    "done",
]


def sse_text(events: list[tuple[str, dict[str, Any]]]) -> str:
    """Render (event, data) pairs as an SSE response body."""
    chunks: list[str] = []
    for name, data in events:
        chunks.append(f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n")
    return "".join(chunks)
