"""Embedding clients. bge-m3 = 1024 dense dims (ADR-0001); hashing fallback for CI/demo."""

import hashlib
import math
import re
from typing import Any, Protocol

import httpx

from rfq_copilot.ports.errors import PortTimeoutError, UpstreamUnavailableError

EMBEDDING_DIM = 1024


class EmbeddingClient(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashingEmbedder:
    """Deterministic bag-of-bigrams hashing embedding.

    Not semantic — exists so CI/demo run with zero keys and stable vectors.
    Production uses OpenAICompatEmbedder against bge-m3.
    """

    def __init__(self, dim: int = EMBEDDING_DIM) -> None:
        self._dim = dim

    def _one(self, text: str) -> list[float]:
        vec = [0.0] * self._dim
        han = re.sub(r"[^\u4e00-\u9fff a-zA-Z0-9]", "", text.lower())
        for token in han.split():
            self._bump(vec, token)
        for i in range(len(han) - 1):
            self._bump(vec, han[i : i + 2])
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def _bump(self, vec: list[float], gram: str) -> None:
        # sha256 as a feature hash (not security): uniform bucket distribution
        digest = hashlib.sha256(gram.encode("utf-8")).hexdigest()
        index = int(digest[:8], 16) % self._dim
        vec[index] += 1.0

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]

    def embed_sync(self, texts: list[str]) -> list[list[float]]:
        """Sync seeding path (tests / bootstrap); production ingests via async embed()."""
        return [self._one(t) for t in texts]


class OpenAICompatEmbedder:
    """POST {base_url}/embeddings with the OpenAI-compatible payload (bge-m3 via provider API)."""

    def __init__(self, base_url: str, api_key: str, model: str, timeout_seconds: float = 30.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout_seconds
        self._headers = {"Authorization": f"Bearer {api_key}"}

    async def embed(self, texts: list[str]) -> list[list[float]]:
        payload: dict[str, Any] = {"model": self._model, "input": texts}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(f"{self._base_url}/embeddings", json=payload, headers=self._headers)
        except httpx.TimeoutException as exc:
            raise PortTimeoutError("embedding timeout") from exc
        except httpx.HTTPError as exc:
            raise UpstreamUnavailableError(f"embedding unreachable: {exc}") from exc
        resp.raise_for_status()
        data = resp.json()["data"]
        vectors = [item["embedding"] for item in sorted(data, key=lambda item: item["index"])]
        if any(len(v) != EMBEDDING_DIM for v in vectors):
            raise UpstreamUnavailableError(f"embedding dim mismatch, expected {EMBEDDING_DIM}")
        return vectors


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))
