"""Rerank stage: cross-encoder over retrieved candidates (top 20 → top 5)."""

from typing import Any, Protocol

import httpx

from rfq_copilot.core.rag.chunking import Chunk
from rfq_copilot.ports.errors import PortTimeoutError, UpstreamUnavailableError


class Reranker(Protocol):
    def rerank(self, query: str, chunks: list[Chunk]) -> list[Chunk]: ...


class NoopReranker:
    """Keeps retrieval order (demo/CI profile; semantic order comes from the embedder)."""

    def rerank(self, query: str, chunks: list[Chunk]) -> list[Chunk]:
        return chunks


class ApiReranker:
    """bge-reranker-v2-m3 via SiliconFlow-style /rerank endpoint."""

    def __init__(self, base_url: str, api_key: str, model: str, timeout_seconds: float = 30.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout_seconds
        self._headers = {"Authorization": f"Bearer {api_key}"}

    def rerank(self, query: str, chunks: list[Chunk]) -> list[Chunk]:
        payload: dict[str, Any] = {
            "model": self._model,
            "query": query,
            "documents": [chunk.content for chunk in chunks],
        }
        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.post(f"{self._base_url}/rerank", json=payload, headers=self._headers)
        except httpx.TimeoutException as exc:
            raise PortTimeoutError("rerank timeout") from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailableError(f"rerank unreachable: {exc}") from exc
        resp.raise_for_status()
        order = [item["index"] for item in sorted(resp.json()["results"], key=lambda r: -r["relevance_score"])]
        return [chunks[i] for i in order if 0 <= i < len(chunks)]
