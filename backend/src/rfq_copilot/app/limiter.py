"""In-memory sliding-window rate limiter (03-api-spec §5).

Enterprise note: for single-instance demo this is authoritative; multi-instance
deployment swaps the backend for Redis (same interface). Per-session and per-IP
windows are tracked independently; a hit on either blocks the request.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass, field


@dataclass
class WindowRule:
    limit: int
    window_seconds: int


@dataclass
class SlidingWindowLimiter:
    session_rule: WindowRule = field(default_factory=lambda: WindowRule(20, 3600))
    ip_rule: WindowRule = field(default_factory=lambda: WindowRule(60, 3600))
    _hits: dict[str, deque[float]] = field(default_factory=lambda: defaultdict(deque))

    def _prune(self, key: str, now: float, window: int) -> None:
        q = self._hits[key]
        while q and now - q[0] > window:
            q.popleft()

    def allow(self, *, session_id: str | None = None, ip: str | None = None) -> bool:
        """Check both dimensions; record the hit only when allowed."""
        now = time.monotonic()
        checks: list[tuple[str, WindowRule]] = []
        if session_id:
            checks.append((f"sess:{session_id}", self.session_rule))
        if ip:
            checks.append((f"ip:{ip}", self.ip_rule))
        for key, rule in checks:
            self._prune(key, now, rule.window_seconds)
            if len(self._hits[key]) >= rule.limit:
                return False
        for key, rule in checks:
            self._hits[key].append(now)
            self._prune(key, now, rule.window_seconds)
        return True
