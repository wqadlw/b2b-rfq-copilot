"""Tool result truncation + finish_reason monitoring — API 成本防线（深水区指南 §1/§3）."""

from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)

MAX_TOOL_RESPONSE_CHARS = 4000
MAX_SEARCH_ITEMS = 3


def truncate_tool_result(result_text: str, tool_name: str, max_chars: int = MAX_TOOL_RESPONSE_CHARS) -> str:
    """Truncate oversized tool results before they enter the LLM context.

    防止"双向吸血"：工具结果全部算 Prompt Tokens，不限长度则一次 Tool Call 烧掉数万 Tokens。
    """
    if len(result_text) <= max_chars:
        return result_text
    truncated = result_text[:max_chars]
    logger.warning(
        "tool.result.truncated",
        tool=tool_name,
        original_len=len(result_text),
        truncated_to=max_chars,
    )
    return truncated + "\n…(结果已截断)"


def check_finish_reason(finish_reason: str | None, session_id: str) -> bool:
    """Monitor finish_reason: 'length' means truncated garbage that was still billed.

    Returns True if this was a BadCase (should trigger retry with shorter output).
    """
    if finish_reason == "length":
        logger.warning(
            "llm.finish_reason.length",
            session_id=session_id,
            detail="回答被 max_tokens 截断——计费但产出无意义，应触发精简重试",
        )
        return True
    return False
