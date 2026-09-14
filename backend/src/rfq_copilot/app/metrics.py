"""In-memory ops metrics (v1). Production swaps for Langfuse / log aggregation (M5+).

One TurnRecord per chat turn, recorded by the SSE mapper — the single observation
point that sees routes, events, finish reasons, and timing. Thread-safe: the ASGI
loop is single-threaded, but the registry is also read by sync contexts (tests).
"""

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any

_PERIOD_DAYS = {"today": 1, "week": 7, "month": 30}
VALID_PERIODS = tuple(_PERIOD_DAYS)


@dataclass
class TurnRecord:
    ts: float
    session_id: str
    question: str
    route: str
    faq_hit: bool
    llm_calls: int
    prompt_tokens: int
    completion_tokens: int
    stream_chars: int
    latency_ms: int
    inquiry_created: bool
    errored: bool


class MetricsRegistry:
    def __init__(self, max_turns: int = 10000) -> None:
        self._lock = threading.Lock()
        self._turns: deque[TurnRecord] = deque(maxlen=max_turns)

    def record_turn(
        self,
        session_id: str,
        question: str,
        route: str,
        faq_hit: bool = False,
        llm_calls: int = 0,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        stream_chars: int = 0,
        latency_ms: int = 0,
        inquiry_created: bool = False,
        errored: bool = False,
        ts: float | None = None,
    ) -> None:
        rec = TurnRecord(
            ts=time.time() if ts is None else ts,
            session_id=session_id,
            question=" ".join(question.split()),
            route=route,
            faq_hit=faq_hit,
            llm_calls=llm_calls,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            stream_chars=stream_chars,
            latency_ms=latency_ms,
            inquiry_created=inquiry_created,
            errored=errored,
        )
        with self._lock:
            self._turns.append(rec)

    def summary(self, period: str) -> dict[str, Any]:
        days = _PERIOD_DAYS[period]
        cutoff = time.time() - days * 86400
        with self._lock:
            rows = [t for t in self._turns if t.ts >= cutoff]

        turns = len(rows)
        sessions = len({t.session_id for t in rows})
        faq_hits = sum(1 for t in rows if t.faq_hit)
        inquiries = sum(1 for t in rows if t.inquiry_created)
        errors = sum(1 for t in rows if t.errored)
        llm_calls = sum(t.llm_calls for t in rows)
        prompt_tokens = sum(t.prompt_tokens for t in rows)
        completion_tokens = sum(t.completion_tokens for t in rows)
        stream_chars = sum(t.stream_chars for t in rows)
        avg_latency = round(sum(t.latency_ms for t in rows) / turns) if turns else 0

        counter: dict[str, int] = {}
        for t in rows:
            if t.question:
                counter[t.question] = counter.get(t.question, 0) + 1
        top = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:10]

        return {
            "period": period,
            "sessions": sessions,
            "turns": turns,
            "faq_hit_rate": round(faq_hits / turns, 3) if turns else 0.0,
            "inquiries_created": inquiries,
            "errors": errors,
            "llm_calls": llm_calls,
            "llm_tokens": {"prompt": prompt_tokens, "completion": completion_tokens},
            "stream_chars": stream_chars,
            "avg_latency_ms": avg_latency,
            "top_questions": [{"question": q, "count": n} for q, n in top],
        }
