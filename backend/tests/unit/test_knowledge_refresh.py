"""08-knowledge-export-spec §6 回归：引擎内置每日兜底刷新（重导→diff→热加载）。

- §7.5 幂等：无变化轮不触碰现网目录；
- §7.6 热加载：刷新后免重启——检索立即可见变更、离线端口同步重建；
- §7.7 门禁：开关关闭/源目录缺失不启动；一轮异常不影响后续。
"""

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from rfq_copilot.app.knowledge_refresh import (
    RefreshResult,
    apply_refresh,
    run_once,
    run_refresh,
    start_knowledge_refresh,
)
from rfq_copilot.app.runtime import build_runtime
from rfq_copilot.config.settings import get_settings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "site"


def _export_to(target: Path) -> None:
    """用站点 fixtures 跑一次真实导出（与生产同一实现）。"""
    from rfq_copilot.app.knowledge_refresh import _load_export_module

    rc = _load_export_module().main(["--source-dir", str(FIXTURES), "--output-dir", str(target)])
    assert rc == 0


def _product_doc_id(live: Path) -> str:
    payload = json.loads((live / "knowledge.json").read_text(encoding="utf-8"))
    product = next(d for d in payload["documents"] if d["doc_type"] == "product")
    return product["doc_id"]


def test_run_refresh_unchanged_is_idempotent(tmp_path: Path) -> None:
    live = tmp_path / "rag_data"
    _export_to(live)
    before = (live / "knowledge.json").read_text(encoding="utf-8")

    result = run_refresh(str(FIXTURES), str(live))

    assert result.refreshed is False
    assert (live / "knowledge.json").read_text(encoding="utf-8") == before  # 现网目录零触碰
    assert not (live.parent / "rag_data_refresh").exists()  # 临时目录已清理


def test_run_refresh_detects_change_and_swaps(tmp_path: Path) -> None:
    live = tmp_path / "rag_data"
    _export_to(live)
    doc_id = _product_doc_id(live)

    # 变更源数据：改产品 detail 正文（拷贝 seeders 到 tmp，避免碰仓库 fixtures）
    seeders = tmp_path / "seeders"
    shutil.copytree(FIXTURES, seeders)
    marker = "热加载标记QA0030"
    php = (seeders / "product_data.php").read_text(encoding="utf-8")
    assert "无油设计" in php
    (seeders / "product_data.php").write_text(php.replace("无油设计", "无油设计" + marker, 1), encoding="utf-8")

    result = run_refresh(str(seeders), str(live))

    assert result.refreshed is True
    assert doc_id in (result.added + result.removed + result.changed)
    live_text = (live / "knowledge.json").read_text(encoding="utf-8")
    assert marker in live_text, "有变化轮必须把新语料原子替换进现网目录"


async def test_apply_refresh_hot_swaps_without_restart(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """§7.6：apply 后检索立即可见新内容、旧内容消失——全程不重启 runtime。"""
    live = tmp_path / "rag_data"
    _export_to(live)
    doc_id = _product_doc_id(live)
    settings = get_settings()
    monkeypatch.setattr(settings, "knowledge_data_dir", str(live))

    runtime: Any = build_runtime()
    from rfq_copilot.app.runtime import seed_demo

    await seed_demo(runtime)
    assert runtime.deps.rag is not None
    old_hit = await runtime.deps.rag.search("真空泵")
    assert old_hit, "初始语料应有命中"

    # 模拟一轮有变化的刷新：直接改 knowledge.json 中该产品的正文
    payload = json.loads((live / "knowledge.json").read_text(encoding="utf-8"))
    marker = f"热加载标记词{doc_id}"
    for doc in payload["documents"]:
        if doc["doc_id"] == doc_id:
            doc["content"] = (doc["content"] or "") + marker
    (live / "knowledge.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    await apply_refresh(runtime, str(live), RefreshResult(changed=[doc_id]))

    hits = await runtime.deps.rag.search(marker)
    assert any(c.doc_id.startswith(doc_id) for c in hits), "热加载后新内容必须立即可见"


async def test_start_knowledge_refresh_gating(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "knowledge_refresh_enabled", False)
    assert start_knowledge_refresh(object()) is None  # 开关关闭

    monkeypatch.setattr(settings, "knowledge_refresh_enabled", True)
    monkeypatch.setattr(settings, "knowledge_source_dir", "")
    assert start_knowledge_refresh(object()) is None  # 源目录缺失：不静默（warn 落日志）

    monkeypatch.setattr(settings, "knowledge_source_dir", str(FIXTURES))
    monkeypatch.setattr(settings, "knowledge_data_dir", str(FIXTURES))
    task = start_knowledge_refresh(object())
    assert task is not None
    task.cancel()


async def test_run_once_records_error_and_survives(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """§7.7：一轮失败（如源目录无效）→ error 落 last_refresh，不抛出拖垮引擎。"""
    settings = get_settings()
    monkeypatch.setattr(settings, "knowledge_refresh_enabled", True)
    monkeypatch.setattr(settings, "knowledge_source_dir", str(tmp_path / "nonexistent"))
    monkeypatch.setattr(settings, "knowledge_data_dir", str(tmp_path / "live"))
    runtime: Any = build_runtime()

    record = await run_once(runtime)

    assert record["error"] is not None
    assert runtime.last_refresh is record
