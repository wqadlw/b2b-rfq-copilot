"""运营观测数据存储（spec 02-engine-read-api-spec §1.0/§2.5）。

三个 registry 共用一套机制：
- FeedbackStore  ：用户 👍👎 反馈（feedback.jsonl）——此前空壳丢数据，运营质量信号唯一来源。
- NoMatchStore   ：产品零命中/知识零召回事件（no_match_events.jsonl）——知识缺口发现的唯一数据源。
- HitStatsRegistry：知识文档命中计数（hit_stats.json，按日聚合）——V2 效果象限的燃料。

持久化模式：RUNTIME_DATA_DIR 非空时 append 即落盘 JSONL，启动回放（重启不丢）；
置空 = 纯内存（CI/测试）。线程安全模式对齐 MetricsRegistry（Lock + deque）。
"""

import json
import threading
import time
from collections import deque
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

_MEM_CLUSTER = {"today": 1, "week": 7, "month": 30}  # 与 metrics.VALID_PERIODS 同口径


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


def _local_date(iso_ts: str) -> str:
    """ISO 时间戳 → 本地日期 YYYY-MM-DD（统计归日口径：按服务器本地时区）。"""
    try:
        dt = datetime.fromisoformat(iso_ts)
    except ValueError:
        return ""
    return dt.astimezone().strftime("%Y-%m-%d")


class JsonlStore:
    """JSONL 追加存储：内存 deque 镜像 + 可选落盘 + 启动回放。"""

    def __init__(self, name: str, data_dir: str = "", maxlen: int = 10000) -> None:
        self._lock = threading.Lock()
        self._items: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self._seq = 0  # 单调序号：时钟同刻度时保证排序确定性
        self._path: Path | None = None
        if data_dir:
            self._path = Path(data_dir) / f"{name}.jsonl"
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._replay()

    def _replay(self) -> None:
        assert self._path is not None
        if not self._path.is_file():
            return
        for line in self._path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                self._items.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # 半行/坏行跳过：观测数据宁可少不可炸启动

    def _persist(self, record: dict[str, Any]) -> None:
        if self._path is None:
            return
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def append(self, record: dict[str, Any]) -> None:
        """追加一条记录（ts/seq 缺省补齐；落盘失败不阻断内存写入）。"""
        self._seq += 1
        record = {"ts": _iso_now(), "seq": self._seq, **record}
        with self._lock:
            self._items.append(record)
        if self._path is not None:
            with suppress(OSError):
                self._persist(record)  # 磁盘故障降级为内存态；问答主路径不受影响

    def items(
        self,
        *,
        filters: dict[str, str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """过滤 + (ts, seq) 倒序分页。返回 (items, 过滤后 total)。"""
        with self._lock:
            rows = list(self._items)
        for key, value in (filters or {}).items():
            rows = [r for r in rows if str(r.get(key, "")) == value]
        rows.sort(key=lambda r: (str(r.get("ts", "")), int(r.get("seq", 0))), reverse=True)
        return rows[offset : offset + limit], len(rows)


class FeedbackStore(JsonlStore):
    """用户反馈（M1/N1）：👍👎 + 备注。POST /feedback 写入，运营端列表/统计。"""

    def __init__(self, data_dir: str = "") -> None:
        super().__init__("feedback", data_dir)

    def stats(self, period: str) -> dict[str, Any]:
        days = _MEM_CLUSTER[period]
        cutoff = time.time() - days * 86400
        with self._lock:
            rows = list(self._items)
        recent = [r for r in rows if _parse_ts(r.get("ts")) >= cutoff]
        by_day: dict[str, dict[str, int]] = {}
        helpful = not_helpful = 0
        for r in recent:
            day = _local_date(str(r.get("ts", "")))
            bucket = by_day.setdefault(day, {"helpful": 0, "not_helpful": 0})
            if r.get("feedback") == "helpful":
                helpful += 1
                bucket["helpful"] += 1
            elif r.get("feedback") == "not_helpful":
                not_helpful += 1
                bucket["not_helpful"] += 1
        return {
            "period": period,
            "helpful": helpful,
            "not_helpful": not_helpful,
            "total": len(recent),
            "by_day": [{"date": d, **v} for d, v in sorted(by_day.items())],
        }


class NoMatchStore(JsonlStore):
    """缺口事件（N2）：产品零命中 + 知识零召回。缺口工单自动化的唯一数据源。"""

    def __init__(self, data_dir: str = "") -> None:
        super().__init__("no_match_events", data_dir)

    def stats(self, period: str) -> dict[str, Any]:
        days = _MEM_CLUSTER[period]
        cutoff = time.time() - days * 86400
        with self._lock:
            rows = list(self._items)
        recent = [r for r in rows if _parse_ts(r.get("ts")) >= cutoff]
        by_route: dict[str, int] = {}
        by_day: dict[str, int] = {}
        questions: dict[str, int] = {}
        for r in recent:
            route = str(r.get("route", "unknown"))
            by_route[route] = by_route.get(route, 0) + 1
            day = _local_date(str(r.get("ts", "")))
            by_day[day] = by_day.get(day, 0) + 1
            q = " ".join(str(r.get("question", "")).split())
            if q:
                questions[q] = questions.get(q, 0) + 1
        top = sorted(questions.items(), key=lambda kv: (-kv[1], kv[0]))[:10]
        return {
            "period": period,
            "total": len(recent),
            "by_route": by_route,
            "by_day": [{"date": d, "total": n} for d, n in sorted(by_day.items())],
            "top_questions": [{"question": q, "count": n} for q, n in top],
        }


class HitStatsRegistry:
    """知识命中计数（N3）：date → doc_id → hits，内存聚合 + 整文件落盘。

    记录点 = RAGPipeline.search() final top-k（test-retrieval 不触发）；
    每次变更后写整文件（≤数千行）换重启不丢。
    """

    def __init__(self, data_dir: str = "") -> None:
        self._lock = threading.Lock()
        self._counts: dict[str, dict[str, int]] = {}
        self._path: Path | None = None
        if data_dir:
            self._path = Path(data_dir) / "hit_stats.json"
            self._path.parent.mkdir(parents=True, exist_ok=True)
            if self._path.is_file():
                try:
                    self._counts = json.loads(self._path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    self._counts = {}

    def _flush(self) -> None:
        if self._path is None:
            return
        with suppress(OSError):
            # 落盘失败降级内存态；下一次命中再试
            self._path.write_text(json.dumps(self._counts, ensure_ascii=False), encoding="utf-8")

    def record(self, doc_ids: list[str], *, day: str | None = None) -> None:
        """一轮检索 final top-k 计数（契约=去重后列表；此处防御性再去重，保序）。"""
        date = day or datetime.now().astimezone().strftime("%Y-%m-%d")
        with self._lock:
            bucket = self._counts.setdefault(date, {})
            for doc_id in dict.fromkeys(doc_ids):
                bucket[doc_id] = bucket.get(doc_id, 0) + 1
            self._flush()

    def summary(self, days: int = 30) -> dict[str, Any]:
        cutoff = (datetime.now() - timedelta(days=days - 1)).strftime("%Y-%m-%d")
        with self._lock:
            snapshot = {d: dict(docs) for d, docs in self._counts.items() if d >= cutoff}
        series: list[dict[str, Any]] = []
        total_by_doc: dict[str, int] = {}
        for date in sorted(snapshot):
            for doc_id, hits in sorted(snapshot[date].items()):
                series.append({"date": date, "doc_id": doc_id, "hits": hits})
                total_by_doc[doc_id] = total_by_doc.get(doc_id, 0) + hits
        ranked = sorted(total_by_doc.items(), key=lambda kv: (-kv[1], kv[0]))
        return {
            "days": days,
            "series": series,
            "total_by_doc": [{"doc_id": d, "hits": n} for d, n in ranked],
        }


def _parse_ts(iso_ts: Any) -> float:
    try:
        return datetime.fromisoformat(str(iso_ts)).timestamp()
    except (ValueError, TypeError):
        return 0.0
