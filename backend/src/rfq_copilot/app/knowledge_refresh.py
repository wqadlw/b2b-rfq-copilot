"""引擎内置每日兜底刷新（08-knowledge-export-spec §6，v1.1）：重导 → diff → 热加载。

设计要点：
- 数据停更是无声失败——webhook 覆盖运行期实时增量，本模块是防事件丢失的定时兜底。
- 单一实现两处复用：引擎内调度（refresh_loop）与 CLI 手工通道
  （scripts/daily_knowledge_refresh.py 薄壳）。
- 热加载免重启：RAG store 差量补丁走与 webhook 相同的 remove→ingest 路径
  （家族替换语义，QA-0002），离线端口构造时一次性装载故必须重建热换。
- 失败自愈：任何一轮异常结构化 WARN + 计入 last_refresh，循环继续。
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import shutil
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from rfq_copilot.app.freshness import load_corpus_freshness
from rfq_copilot.config.settings import get_settings
from rfq_copilot.core.rag.chunking import chunk_document
from rfq_copilot.ports.knowledge_source import KnowledgeDocument

logger = structlog.get_logger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[4]  # app → rfq_copilot → src → backend → repo root
_EXPORT_SCRIPT = _REPO_ROOT / "scripts" / "vacuum_b2b_export.py"
_REFRESH_FILES = ("knowledge.json", "export_manifest.json", "etl_filtered.log")
_FIRST_RUN_GRACE_SECONDS = 60


def _load_export_module() -> Any:
    """加载导出脚本为模块（单一事实源：导出/manifest/diff 全部复用脚本实现）。"""
    spec = importlib.util.spec_from_file_location("vacuum_b2b_export", _EXPORT_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["vacuum_b2b_export"] = module
    spec.loader.exec_module(module)
    return module


@dataclass
class RefreshResult:
    """一轮刷新的结果（doc_id 全量三类差异，08-spec §3）。"""

    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)

    @property
    def refreshed(self) -> bool:
        return bool(self.added or self.removed or self.changed)


def run_refresh(source_dir: str, live_dir: str) -> RefreshResult:
    """重导 → 全量 diff → 有变才原子替换 live 目录三件套。同步阻塞（调用方放线程池）。"""
    export_mod = _load_export_module()
    live = Path(live_dir).resolve()
    if not (live / "knowledge.json").is_file():
        raise FileNotFoundError(f"现网目录缺少 knowledge.json：{live}")
    refresh_dir = live.parent / f"{live.name}_refresh"
    if refresh_dir.exists():
        shutil.rmtree(refresh_dir)

    rc = export_mod.main(["--source-dir", source_dir, "--output-dir", str(refresh_dir), "--diff-from", str(live)])
    if rc != 0:
        # 导出失败：现网数据保持不变（宁可旧不可错）
        if refresh_dir.exists():
            shutil.rmtree(refresh_dir)
        raise RuntimeError(f"知识导出失败（exit {rc}），现网数据保持不变")

    old_manifest = json.loads((live / "export_manifest.json").read_text(encoding="utf-8"))
    new_manifest = json.loads((refresh_dir / "export_manifest.json").read_text(encoding="utf-8"))
    report = export_mod.diff_manifests(old_manifest, new_manifest, sample_limit=10**9)
    result = RefreshResult(
        added=list(report["added"]["samples"]),
        removed=list(report["removed"]["samples"]),
        changed=list(report["changed"]["samples"]),
    )
    if not result.refreshed:
        shutil.rmtree(refresh_dir)
        return result

    for name in _REFRESH_FILES:
        src = refresh_dir / name
        if src.is_file():
            shutil.copy2(src, live / name)
    shutil.rmtree(refresh_dir)
    return result


async def apply_refresh(runtime: Any, live_dir: str, result: RefreshResult) -> None:
    """热加载（08-spec §6.3）：RAG 差量补丁 + 离线端口重建 + freshness 重算。"""
    settings = get_settings()
    rag = runtime.deps.rag
    if rag is not None and result.refreshed:
        payload = json.loads((Path(live_dir) / "knowledge.json").read_text(encoding="utf-8"))
        docs = {d["doc_id"]: KnowledgeDocument(**d) for d in payload["documents"]}
        for doc_id in result.removed + result.changed:
            await rag.remove_doc(doc_id)  # 家族替换语义，与 webhook 同一路径
        new_docs = [docs[doc_id] for doc_id in result.added + result.changed if doc_id in docs]
        chunks = [chunk for doc in new_docs for chunk in chunk_document(doc)]
        if chunks:
            await rag.ingest(chunks)

    if settings.knowledge_data_dir:
        # 离线端口构造时一次性装载——刷新后必须重建热换（GraphDeps 节点每次调用读字段）
        from rfq_copilot.adapters.vacuum_b2b_offline.cases import OfflineCaseDirectory
        from rfq_copilot.adapters.vacuum_b2b_offline.catalog import OfflineProductCatalog
        from rfq_copilot.adapters.vacuum_b2b_offline.solutions import OfflineSolutionDirectory
        from rfq_copilot.adapters.vacuum_b2b_offline.suppliers import OfflineSupplierDirectory

        if runtime.deps.catalog is not None:
            runtime.deps.catalog = OfflineProductCatalog(settings.knowledge_data_dir)
        if runtime.deps.suppliers is not None:
            runtime.deps.suppliers = OfflineSupplierDirectory(settings.knowledge_data_dir)
        if runtime.deps.solutions is not None:
            runtime.deps.solutions = OfflineSolutionDirectory(settings.knowledge_data_dir)
        if runtime.deps.cases is not None:
            runtime.deps.cases = OfflineCaseDirectory(settings.knowledge_data_dir)
        runtime.corpus_freshness = load_corpus_freshness(settings.knowledge_data_dir, settings.rag_stale_days)

    if result.refreshed:
        logger.info(
            "knowledge.refresh.applied",
            added=len(result.added),
            removed=len(result.removed),
            changed=len(result.changed),
        )


async def run_once(runtime: Any) -> dict[str, Any]:
    """一轮完整刷新（导出 + 热加载），返回落 /health 的 last_refresh 记录。永不抛出。"""
    settings = get_settings()
    record: dict[str, Any] = {
        "enabled": True,
        "last_run_at": datetime.now(UTC).isoformat(),
        "refreshed": False,
        "added": 0,
        "removed": 0,
        "changed": 0,
        "error": None,
    }
    try:
        result = await asyncio.to_thread(run_refresh, settings.knowledge_source_dir, settings.knowledge_data_dir)
        record["added"], record["removed"], record["changed"] = (
            len(result.added),
            len(result.removed),
            len(result.changed),
        )
        if result.refreshed:
            await apply_refresh(runtime, settings.knowledge_data_dir, result)
            record["refreshed"] = True
        else:
            logger.info("knowledge.refresh.unchanged")
    except Exception as exc:  # noqa: BLE001 —— 兜底通道一轮失败不得拖垮引擎，下一轮自愈
        record["error"] = str(exc)
        logger.warning("knowledge.refresh.failed", error=str(exc))
    runtime.last_refresh = record
    return record


async def refresh_loop(runtime: Any) -> None:
    """调度循环：启动宽限 60s 首跑（兜住停机期间变化），此后按间隔循环。"""
    settings = get_settings()
    first = True
    while True:
        delay = _FIRST_RUN_GRACE_SECONDS if first else settings.knowledge_refresh_interval_hours * 3600
        first = False
        await asyncio.sleep(delay)
        await run_once(runtime)


def start_knowledge_refresh(runtime: Any) -> asyncio.Task[None] | None:
    """按 §6.1 门禁启动后台调度；不满足条件返回 None（不静默——原因落 WARN）。"""
    settings = get_settings()
    if not settings.knowledge_refresh_enabled:
        return None
    if not settings.knowledge_source_dir or not Path(settings.knowledge_source_dir).is_dir():
        logger.warning(
            "knowledge.refresh.disabled",
            reason="KNOWLEDGE_SOURCE_DIR 缺失或不是目录（半配置不静默）",
        )
        return None
    return asyncio.create_task(refresh_loop(runtime))
