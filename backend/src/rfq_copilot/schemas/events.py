"""SSE event contracts (authority: docs/specs/03-api-spec.md §2, port-spec §8)."""

import json
from typing import Any, Literal

EventName = Literal[
    "status",
    "tool_call",
    "retrieval",
    "answer_delta",
    "citation",
    "card",
    "inquiry_confirm",
    "inquiry_created",
    "handoff",
    "error",
    "wechat_guidance",
    "login_required",
    "token_budget_exceeded",
    "done",
]
"""QA-0006：后端事件冻结集 == 实发集 == 前端 ChatEventName（14 名，03-api-spec §2）。
此前 10 名与实发集漂移（card/login_required/wechat_guidance/token_budget_exceeded 越集零校验）。
"""

EVENT_NAMES: frozenset[str] = frozenset(
    (
        "status",
        "tool_call",
        "retrieval",
        "answer_delta",
        "citation",
        "card",
        "inquiry_confirm",
        "inquiry_created",
        "handoff",
        "error",
        "wechat_guidance",
        "login_required",
        "token_budget_exceeded",
        "done",
    )
)


def sse_text(events: list[tuple[EventName, dict[str, Any]]]) -> str:
    """Render (event, data) pairs as an SSE response body.

    事件名收窄为 EventName：mypy strict 在 CI 拦截任何未登记事件（QA-0006）。
    """
    chunks: list[str] = []
    for name, data in events:
        chunks.append(f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n")
    return "".join(chunks)
