"""批次 H 用量记账单测：OpenAICompatLLM 缓存字段采集 + 流式 include_usage 补采 + MetricsRegistry 增量口径。

spec 02 §2.6 v1.3：流式末块 usage-only（choices 空数组）须防护；供应商不支持时无 usage 键退回旧口径。
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from rfq_copilot.app.metrics import MetricsRegistry
from rfq_copilot.core.agent.llm import OpenAICompatLLM


def _sse(chunks: list[dict[str, Any]]) -> bytes:
    lines = [b"data: " + json.dumps(c).encode() for c in chunks] + [b"data: [DONE]"]
    return b"\n\n".join(lines) + b"\n\n"


def _client_factory(handler: Any) -> Any:
    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    return factory


def _llm(monkeypatch: pytest.MonkeyPatch, handler: Any) -> OpenAICompatLLM:
    import rfq_copilot.core.agent.llm as llm_module

    monkeypatch.setattr(llm_module.httpx, "AsyncClient", _client_factory(handler))
    return OpenAICompatLLM(base_url="http://llm.test", api_key="k", model="deepseek-chat")


async def test_complete_json_books_cache_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    """非流式：usage 含 prompt_cache_hit_tokens/miss → 逐项入账。"""

    def handler(request: httpx.Request) -> httpx.Response:
        assert b"stream_options" not in request.content
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps({"intent": "x"})}}],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "prompt_cache_hit_tokens": 64,
                    "prompt_cache_miss_tokens": 36,
                },
            },
        )

    llm = _llm(monkeypatch, handler)
    await llm.complete_json("sys", "usr")
    assert (llm.prompt_tokens_total, llm.completion_tokens_total) == (100, 20)
    assert (llm.prompt_cache_hit_total, llm.prompt_cache_miss_total) == (64, 36)


async def test_stream_books_usage_only_final_chunk(monkeypatch: pytest.MonkeyPatch) -> None:
    """流式补采：include_usage 发出；usage-only 末块（choices 空数组）防护不炸且入账。"""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["stream_options"] == {"include_usage": True}
        chunks = [
            {"choices": [{"delta": {"content": "无油泵"}}]},
            {"choices": [{"delta": {"content": "适合实验室"}}]},
            {"choices": [], "usage": {  # usage-only 末块（OpenAI/DeepSeek 约定）
                "prompt_tokens": 500,
                "completion_tokens": 8,
                "prompt_cache_hit_tokens": 400,
                "prompt_cache_miss_tokens": 100,
            }},
        ]
        return httpx.Response(200, content=_sse(chunks), headers={"content-type": "text/event-stream"})

    llm = _llm(monkeypatch, handler)
    parts = [p async for p in llm.stream_text("sys", "usr")]
    assert "".join(parts) == "无油泵适合实验室"
    assert (llm.prompt_tokens_total, llm.completion_tokens_total) == (500, 8)
    assert (llm.prompt_cache_hit_total, llm.prompt_cache_miss_total) == (400, 100)


async def test_stream_without_usage_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    """供应商不支持 stream_options：无 usage 键 → 计数退回旧口径（0），不报错。"""

    def handler(request: httpx.Request) -> httpx.Response:
        chunks = [{"choices": [{"delta": {"content": "ok"}}]}]
        return httpx.Response(200, content=_sse(chunks), headers={"content-type": "text/event-stream"})

    llm = _llm(monkeypatch, handler)
    parts = [p async for p in llm.stream_text("sys", "usr")]
    assert parts == ["ok"]
    assert llm.prompt_tokens_total == 0 and llm.prompt_cache_hit_total == 0


def test_metrics_registry_cache_fields_in_series_and_summary() -> None:
    reg = MetricsRegistry()
    reg.record_turn("s1", "问题一", "knowledge_flow", prompt_tokens=100, completion_tokens=10, prompt_cache_hit=60, prompt_cache_miss=40)
    reg.record_turn("s2", "问题二", "product_flow", prompt_tokens=50, completion_tokens=5)
    day = reg.usage_series(days=1)["series"][0]
    assert day["prompt_cache_hit_tokens"] == 60 and day["prompt_cache_miss_tokens"] == 40
    summary = reg.summary("today")
    assert summary["llm_cache"] == {"prompt_cache_hit_tokens": 60, "prompt_cache_miss_tokens": 40}


def test_metrics_series_backward_shape() -> None:
    """旧调用（不传缓存字段）不炸，缓存键出 0。"""
    reg = MetricsRegistry()
    reg.record_turn("s1", "q", "faq_flow", prompt_tokens=1, completion_tokens=1)
    day = reg.usage_series(days=1)["series"][0]
    assert day["prompt_cache_hit_tokens"] == 0 and day["prompt_cache_miss_tokens"] == 0
