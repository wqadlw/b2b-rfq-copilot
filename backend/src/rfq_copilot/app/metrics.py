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
MAX_SERIES_DAYS = 30


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

    def usage_series(self, days: int) -> dict[str, Any]:
        """逐日用量序列（用量屏核心：Dify/FastGPT 用量页公共子集——日桶 + in/out tokens）。

        本地时区按日分桶，请求窗口内零流量日照常出 0（计数语义，非编造）。
        诚实边界：registry 是 maxlen 截断队列（默认 1 万轮），若窗口起点早于队列
        最老记录，更早的日桶会少计——响应携带 `oldest_record_age_days` 供前端标注。
        """
        import datetime as _dt

        n = max(1, min(int(days), MAX_SERIES_DAYS))
        today = _dt.date.today()
        dates = [today - _dt.timedelta(days=i) for i in range(n - 1, -1, -1)]
        buckets: dict[str, list[TurnRecord]] = {d.isoformat(): [] for d in dates}

        with self._lock:
            rows = list(self._turns)
        oldest_ts = rows[0].ts if rows else None
        for t in rows:
            key = _dt.datetime.fromtimestamp(t.ts).date().isoformat()
            if key in buckets:
                buckets[key].append(t)

        series = []
        for d in dates:
            recs = buckets[d.isoformat()]
            count = len(recs)
            series.append(
                {
                    "date": d.isoformat(),
                    "turns": count,
                    "sessions": len({r.session_id for r in recs}),
                    "llm_calls": sum(r.llm_calls for r in recs),
                    "prompt_tokens": sum(r.prompt_tokens for r in recs),
                    "completion_tokens": sum(r.completion_tokens for r in recs),
                    "errors": sum(1 for r in recs if r.errored),
                    "avg_latency_ms": round(sum(r.latency_ms for r in recs) / count) if count else 0,
                }
            )

        return {
            "days": n,
            "oldest_record_age_days": round((time.time() - oldest_ts) / 86400, 1) if oldest_ts else None,
            "series": series,
        }
