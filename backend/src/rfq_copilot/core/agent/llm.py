"""LLM client: OpenAI-compatible JSON completion; fakeable for tests."""

from typing import Any, Protocol

import httpx

from rfq_copilot.ports.errors import PortTimeoutError, UpstreamUnavailableError


class LLMClient(Protocol):
    async def complete_json(self, system: str, user: str) -> dict[str, Any]: ...


class OpenAICompatLLM:
    """Thin OpenAI-compatible chat-completions client (json_object mode)."""

    def __init__(self, base_url: str, api_key: str, model: str, timeout_seconds: float = 30.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout_seconds
        self._headers = {"Authorization": f"Bearer {api_key}"}

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
        content = resp.json()["choices"][0]["message"]["content"]
        return _loads(content)


def _loads(content: str) -> dict[str, Any]:
    import json

    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise UpstreamUnavailableError("llm returned non-json content") from exc
    if not isinstance(data, dict):
        raise UpstreamUnavailableError("llm json must be an object")
    return data


class FakeLLM:
    """Scripted responses for tests/evals; pops one dict per call."""

    def __init__(self, scripted: list[dict[str, Any]]) -> None:
        self._scripted = list(scripted)
        self.calls: list[tuple[str, str]] = []

    async def complete_json(self, system: str, user: str) -> dict[str, Any]:
        self.calls.append((system, user))
        if not self._scripted:
            raise AssertionError("FakeLLM exhausted")
        return self._scripted.pop(0)
