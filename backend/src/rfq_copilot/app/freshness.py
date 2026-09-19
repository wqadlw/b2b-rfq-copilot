"""知识语料新鲜度（08-knowledge-export-spec §4）。

数据停更是无声失败：本模块把"语料多老"变成可观测的确定性字段——
manifest 时间戳优先，knowledge.json mtime 回退，全部缺失则标记 missing。
只计算与判定，不做任何阻断（旧知识仍可用，禁答不是运行时的职责）。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MANIFEST_NAME = "export_manifest.json"
KNOWLEDGE_NAME = "knowledge.json"


@dataclass(frozen=True)
class CorpusFreshness:
    doc_count: int
    generated_at: str | None
    age_days: float | None
    stale: bool
    source: str  # "manifest" | "mtime" | "missing"


def _parse_ts(raw: str) -> float | None:
    """ISO 8601 → epoch 秒；容忍 Z 后缀与本地无时区时间戳。解析失败返回 None。"""
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.timestamp()


def load_corpus_freshness(
    knowledge_dir: str | Path | None, stale_days: int, *, now: float | None = None
) -> CorpusFreshness | None:
    """按 08-spec §4 计算语料新鲜度；目录为空/不存在返回 None，坏数据逐级降级。"""
    if not knowledge_dir:
        return None
    base = Path(knowledge_dir)
    if not base.is_dir():
        return None
    current = now if now is not None else datetime.now(UTC).timestamp()

    doc_count = 0
    generated_at: str | None = None
    age_days: float | None = None
    source = "missing"

    manifest_path = base / MANIFEST_NAME
    knowledge_path = base / KNOWLEDGE_NAME
    payload: dict[str, Any] | None = None
    if knowledge_path.is_file():
        try:
            loaded = json.loads(knowledge_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                payload = loaded
        except (OSError, json.JSONDecodeError):
            payload = None
    if isinstance(payload, dict) and isinstance(payload.get("documents"), list):
        doc_count = len(payload["documents"])

    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            manifest = None
        if isinstance(manifest, dict):
            source = "manifest"
            generated_at = manifest.get("generated_at") if isinstance(manifest.get("generated_at"), str) else None
            manifest_count = manifest.get("document_count")
            if isinstance(manifest_count, int):
                doc_count = manifest_count
            ts = _parse_ts(generated_at) if generated_at else None
            if ts is not None:
                age_days = max(0.0, (current - ts) / 86400)
            else:
                source = "missing"
                generated_at = None

    if age_days is None and knowledge_path.is_file():
        # mtime 回退：manifest 缺失/损坏时，文件系统时间仍是可用的保守下界
        try:
            mtime = knowledge_path.stat().st_mtime
            age_days = max(0.0, (current - mtime) / 86400)
            source = "mtime"
            generated_at = datetime.fromtimestamp(mtime, tz=UTC).isoformat()
        except OSError:
            return None

    stale = age_days is not None and age_days > stale_days
    return CorpusFreshness(
        doc_count=doc_count, generated_at=generated_at, age_days=age_days, stale=stale, source=source
    )
