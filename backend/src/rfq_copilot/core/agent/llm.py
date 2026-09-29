"""LLM client: OpenAI-compatible JSON completion + SSE streaming; fakeable for tests."""

from collections.abc import AsyncIterator
from typing import Any, Protocol

import httpx

from rfq_copilot.ports.errors import PortTimeoutError, UpstreamUnavailableError


class LLMClient(Protocol):
    async def complete_json(self, system: str, user: str) -> dict[str, Any]: ...

    def stream_text(self, system: str, user: str) -> AsyncIterator[str]:
        """Yield text deltas incrementally (SSE). Any async iterator of str works."""
        ...


def _loads(content: str) -> dict[str, Any]:
    import json

    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise UpstreamUnavailableError("llm returned non-json content") from exc
    if not isinstance(data, dict):
        raise UpstreamUnavailableError("llm json must be an object")
    return data


class OpenAICompatLLM:
    """Thin OpenAI-compatible client: json_object completions + SSE text streaming.

    Usage counters (call_count / prompt_tokens_total / completion_tokens_total /
    stream_chars_total) let the SSE mapper attribute per-turn consumption via
    before/after snapshots — no changes needed at call sites.

    v1.3 (spec 02 §2.6): prompt_cache_hit_total / prompt_cache_miss_total accumulate
    DeepSeek's prefix-cache usage fields (absent on other providers → stay 0).
    stream_text sends stream_options.include_usage and books the usage-only final
    chunk (empty choices list — guarded); providers without support simply never
    carry a usage key and accounting falls back to the old behavior.
    """

    def __init__(self, base_url: str, api_key: str, model: str, timeout_seconds: float = 30.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout_seconds
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self.call_count = 0
        self.prompt_tokens_total = 0
        self.completion_tokens_total = 0
        self.stream_chars_total = 0
        self.prompt_cache_hit_total = 0
        self.prompt_cache_miss_total = 0

    def _book_usage(self, usage: dict[str, Any]) -> None:
        self.prompt_tokens_total += int(usage.get("prompt_tokens") or 0)
        self.completion_tokens_total += int(usage.get("completion_tokens") or 0)
        self.prompt_cache_hit_total += int(usage.get("prompt_cache_hit_tokens") or 0)
        self.prompt_cache_miss_total += int(usage.get("prompt_cache_miss_tokens") or 0)

    async def complete_json(self, system: str, user: str) -> dict[str, Any]:
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(f"{self._base_url}/chat/completions", json=payload, headers=self._headers)
        except httpx.TimeoutException as exc:
            raise PortTimeoutError("llm timeout") from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailableError(f"llm unreachable: {exc}") from exc
        resp.raise_for_status()
        data = resp.json()
        self.call_count += 1
        self._book_usage(data.get("usage") or {})
        content = data["choices"][0]["message"]["content"]
        return _loads(content)

    async def stream_text(self, system: str, user: str) -> AsyncIterator[str]:
        """True token streaming: chat/completions with stream=true, SSE lines parsed."""
        import json

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": True,
            "stream_options": {"include_usage": True},
            "temperature": 0.3,
        }
        try:
            async with (
                httpx.AsyncClient(timeout=self._timeout) as client,
                client.stream(
                    "POST", f"{self._base_url}/chat/completions", json=payload, headers=self._headers
                ) as resp,
            ):
                resp.raise_for_status()
                self.call_count += 1
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        return
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    # usage-only 末块（include_usage 约定）：choices 为空数组，先记账再取 delta
                    if chunk.get("usage"):
                        self._book_usage(chunk["usage"])
                    choices = chunk.get("choices") or []
                    delta = choices[0].get("delta", {}).get("content") if choices else None
                    if delta:
                        self.stream_chars_total += len(delta)
                        yield delta
        except httpx.TimeoutException as exc:
            raise PortTimeoutError("llm stream timeout") from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailableError(f"llm stream unreachable: {exc}") from exc


class FakeLLM:
    """Scripted responses for tests/evals; pops one dict per call.

    complete_json pops a dict; stream_text pops a dict with optional
    ``text_chunks`` (list[str]) and yields them as token deltas.
    """

    def __init__(self, scripted: list[dict[str, Any]]) -> None:
        self._scripted = list(scripted)
        self.calls: list[tuple[str, str]] = []
        self.call_count = 0
        self.prompt_tokens_total = 0
        self.completion_tokens_total = 0
        self.stream_chars_total = 0
        self.prompt_cache_hit_total = 0
        self.prompt_cache_miss_total = 0

    async def complete_json(self, system: str, user: str) -> dict[str, Any]:
        self.calls.append((system, user))
        self.call_count += 1
        if not self._scripted:
            raise AssertionError("FakeLLM exhausted")
        return self._scripted.pop(0)

    async def stream_text(self, system: str, user: str) -> AsyncIterator[str]:
        self.calls.append((system, user))
        self.call_count += 1
        if not self._scripted:
            raise AssertionError("FakeLLM exhausted")
        item = self._scripted.pop(0)
        for piece in item.get("text_chunks", []):
            self.stream_chars_total += len(piece)
            yield piece
