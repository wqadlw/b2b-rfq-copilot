"""Hardened HTTP client for the vacuum sample adapter.

Production-grade behaviors (architect guide M3 §1): strict timeouts, retry on
5xx/network faults (tenacity), and exhaustive mapping of transport/status errors
into the CopilotError taxonomy so the agent degrades gracefully.
"""

from __future__ import annotations

from typing import Any

import httpx
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_fixed

from rfq_copilot.ports.errors import (
    PortTimeoutError,
    UpstreamAuthError,
    UpstreamUnavailableError,
)

HARD_TIMEOUT = httpx.Timeout(connect=2.0, read=5.0, write=5.0, pool=2.0)
RETRYABLE = (httpx.TimeoutException, httpx.TransportError)


def _retryable(exc: BaseException) -> bool:
    """Network faults and 5xx responses retry; 4xx never does."""
    if isinstance(exc, RETRYABLE):
        return True
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code >= 500


class VacuumInternalClient:
    """Calls the site's /internal-api/v1/* endpoints (base_url + token from env only)."""

    def __init__(self, base_url: str, token: str, retry_attempts: int = 2) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = {"X-Internal-Token": token}
        self._retry = AsyncRetrying(
            stop=stop_after_attempt(retry_attempts),
            wait=wait_fixed(0.2),
            retry=retry_if_exception(_retryable),
            reraise=True,
        )

    async def _request(self, method: str, path: str, json_body: dict[str, Any] | None = None) -> Any:
        url = f"{self._base_url}{path}"
        resp: httpx.Response | None = None
        try:
            async for attempt in self._retry:
                with attempt:
                    async with httpx.AsyncClient(timeout=HARD_TIMEOUT) as client:
                        resp = await client.request(method, url, json=json_body, headers=self._headers)
                        if resp.status_code >= 500:
                            resp.raise_for_status()  # 5xx joins the retryable family
        except httpx.HTTPStatusError as exc:
            resp = exc.response  # retries exhausted on 5xx: fall through to status mapping
        except RETRYABLE as exc:
            raise PortTimeoutError(f"upstream timeout after retries: {path}") from exc
        assert resp is not None
        if resp.status_code in (401, 403):
            raise UpstreamAuthError(f"upstream auth rejected: {path}")
        if resp.status_code >= 500:
            raise UpstreamUnavailableError(f"upstream {resp.status_code}: {path}")
        return resp

    async def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        resp = await self._request("GET", path)
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise UpstreamUnavailableError(f"unexpected status {resp.status_code}: {path}")
        return resp.json()

    async def get_json_or_error(self, path: str, params: dict[str, Any] | None = None) -> Any:
        resp = await self._request("GET", path)
        if resp.status_code == 404:
            raise UpstreamUnavailableError(f"missing resource: {path}")
        if resp.status_code != 200:
            raise UpstreamUnavailableError(f"unexpected status {resp.status_code}: {path}")
        return resp.json()

    async def post_json(self, path: str, body: dict[str, Any]) -> Any:
        resp = await self._request("POST", path, json_body=body)
        if resp.status_code != 201:
            raise UpstreamUnavailableError(f"unexpected status {resp.status_code}: {path}")
        return resp.json()
