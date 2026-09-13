"""Langfuse trace 可视化接入（--live/生产启用，CI 跳过）。

每次 LLM 调用 / 工具调用 / 检索 记录 span，
会话结束 flush 到 Langfuse，支持按 session_id 查看完整链路。
"""

from __future__ import annotations

import os
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class LangfuseTracer:
    """轻量 Langfuse 封装：仅在 LANGFUSE_ENABLED=true 且 Key 存在时启用。"""

    def __init__(self) -> None:
        self._enabled = (
            os.environ.get("LANGFUSE_ENABLED", "false").lower() == "true"
            and bool(os.environ.get("LANGFUSE_PUBLIC_KEY"))
            and bool(os.environ.get("LANGFUSE_SECRET_KEY"))
        )
        self._client: Any = None
        if self._enabled:
            try:
                from langfuse import Langfuse

                self._client = Langfuse(
                    public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
                    secret_key=os.environ["LANGFUSE_SECRET_KEY"],
                    host=os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com"),
                )
            except Exception:
                logger.warning("langfuse.init.failed — 降级为纯 structlog")
                self._client = None

    @property
    def enabled(self) -> bool:
        return self._enabled and self._client is not None

    def trace_llm_call(
        self,
        session_id: str,
        operation: str,
        model: str,
        input_text: str,
        output_text: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        latency_ms: int = 0,
    ) -> None:
        """记录一次 LLM 调用（token 用量 + 延迟）。"""
        if not self.enabled:
            return
        self._client.trace(
            id=f"llm-{session_id}-{operation}",
            session_id=session_id,
            name=operation,
            input={"text": input_text[:500]},
            output={"text": output_text[:500]},
            metadata={
                "model": model,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "latency_ms": latency_ms,
            },
        )

    def trace_tool_call(self, session_id: str, tool_name: str, result_summary: str) -> None:
        """记录一次工具调用。"""
        if not self.enabled:
            return
        self._client.trace(
            id=f"tool-{session_id}-{tool_name}",
            session_id=session_id,
            name=f"tool:{tool_name}",
            output={"summary": result_summary[:300]},
        )

    def trace_retrieval(self, session_id: str, query: str, chunk_ids: list[str], trust: list[str]) -> None:
        """记录一次 RAG 检索。"""
        if not self.enabled:
            return
        self._client.trace(
            id=f"rag-{session_id}",
            session_id=session_id,
            name="rag.retrieve",
            input={"query": query[:200]},
            output={"chunk_ids": chunk_ids, "trust_levels": trust},
        )

    def flush(self) -> None:
        if self.enabled:
            self._client.flush()
