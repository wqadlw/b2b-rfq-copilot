"""08-knowledge-export-spec 回归：导出清单/内容哈希/差异报告 + 语料新鲜度。

- export_manifest.json：幂等哈希（重跑未变数据哈希不变）、document_count 一致性、
  --diff-from 差异报告（added/removed/changed）与基线缺失明确失败。
- CorpusFreshness：manifest 优先 / mtime 回退 / missing 三条路径 + stale 边界
  （==阈值不告警，>阈值告警）。
"""

import datetime as _dt
import importlib.util
import json
import os
import sys
from pathlib import Path as _Path

_SCRIPT = _Path(__file__).resolve().parents[3] / "scripts" / "vacuum_b2b_export.py"
_spec = importlib.util.spec_from_file_location("vacuum_b2b_export", _SCRIPT)
assert _spec is not None and _spec.loader is not None
vacuum_b2b_export = importlib.util.module_from_spec(_spec)
sys.modules["vacuum_b2b_export"] = vacuum_b2b_export
_spec.loader.exec_module(vacuum_b2b_export)
from pathlib import Path  # noqa: E402

from rfq_copilot.app.freshness import load_corpus_freshness  # noqa: E402
from rfq_copilot.ports.knowledge_source import KnowledgeDocument  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "site"

NOW = 1_800_000_000.0
DAY = 86400.0
UTC = _dt.UTC


def _doc(doc_id: str = "d1", content: str = "内容", **overrides: str) -> KnowledgeDocument:
    fields: dict = {
        "doc_id": doc_id,
        "title": f"标题-{doc_id}",
        "doc_type": "platform_faq",
        "trust_level": "platform",
        "content": content,
    }
    fields.update(overrides)
    return KnowledgeDocument(**fields)


# ---------------------------------------------------------------------------
# export script: hash / manifest / diff
# ---------------------------------------------------------------------------


def test_content_hash_is_idempotent_and_sensitive() -> None:
    assert vacuum_b2b_export.content_hash(_doc()) == vacuum_b2b_export.content_hash(_doc())
    assert vacuum_b2b_export.content_hash(_doc()) != vacuum_b2b_export.content_hash(_doc(content="变了"))


def test_build_manifest_shape_and_count() -> None:
    docs = [_doc("a"), _doc("b")]
    manifest = vacuum_b2b_export.build_manifest(docs, Path("/tmp/site"), generated_at="2026-09-19T00:00:00+00:00")
    assert manifest["manifest_version"] == 1
    assert manifest["document_count"] == 2 == len(manifest["documents"])
    assert set(manifest["documents"]) == {"a", "b"}
    assert all("content_hash" in v for v in manifest["documents"].values())


def test_diff_manifests_added_removed_changed() -> None:
    old = vacuum_b2b_export.build_manifest([_doc("keep"), _doc("gone"), _doc("mut")], Path("/x"))
    new = vacuum_b2b_export.build_manifest([_doc("keep"), _doc("mut", content="已修改"), _doc("fresh")], Path("/x"))
    report = vacuum_b2b_export.diff_manifests(old, new)
    assert report["added"]["samples"] == ["fresh"]
    assert report["removed"]["samples"] == ["gone"]
    assert report["changed"]["samples"] == ["mut"]
    assert report["unchanged_count"] == 1


def test_main_writes_manifest_and_diff_report(tmp_path: Path) -> None:
    out1, out2 = tmp_path / "rag_data_run1", tmp_path / "rag_data_run2"
    assert vacuum_b2b_export.main(["--source-dir", str(FIXTURES), "--output-dir", str(out1)]) == 0
    manifest1 = json.loads((out1 / "export_manifest.json").read_text(encoding="utf-8"))
    knowledge = json.loads((out1 / "knowledge.json").read_text(encoding="utf-8"))
    assert manifest1["document_count"] == len(knowledge["documents"]) > 0

    args2 = ["--source-dir", str(FIXTURES), "--output-dir", str(out2), "--diff-from", str(out1)]
    assert vacuum_b2b_export.main(args2) == 0
    report = json.loads((out2 / "diff_report.json").read_text(encoding="utf-8"))
    assert report["added"]["count"] == 0
    assert report["removed"]["count"] == 0
    assert report["changed"]["count"] == 0


def test_main_diff_missing_baseline_fails_loudly(tmp_path: Path) -> None:
    out = tmp_path / "rag_data_run"
    try:
        vacuum_b2b_export.main(
            ["--source-dir", str(FIXTURES), "--output-dir", str(out), "--diff-from", str(tmp_path / "nope")]
        )
    except SystemExit as exc:
        assert "基线清单不存在" in str(exc)
        return
    raise AssertionError("缺基线必须 SystemExit（spec §3 明确失败优于静默误报）")


# ---------------------------------------------------------------------------
# freshness: manifest / mtime / missing + stale boundary
# ---------------------------------------------------------------------------


def _seed_dir(tmp_path: Path, manifest: dict | None, mtime: float | None = None) -> Path:
    base = tmp_path / "rag_data"
    base.mkdir(parents=True, exist_ok=True)
    payload = {"stats": {}, "documents": [{"doc_id": "a"}, {"doc_id": "b"}]}
    (base / "knowledge.json").write_text(json.dumps(payload), encoding="utf-8")
    if manifest is not None:
        (base / "export_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    if mtime is not None:
        os.utime(base / "knowledge.json", (mtime, mtime))
    return base


def test_freshness_none_when_dir_empty_or_missing() -> None:
    assert load_corpus_freshness(None, 14, now=NOW) is None
    assert load_corpus_freshness("", 14, now=NOW) is None
    assert load_corpus_freshness(Path("/definitely/not/here"), 14, now=NOW) is None


def test_freshness_manifest_path_and_stale_boundary(tmp_path: Path) -> None:
    base = _seed_dir(tmp_path, {"manifest_version": 1, "generated_at": "not-a-time", "document_count": 7})
    boundary = _dt.datetime.fromtimestamp(NOW - 14 * DAY, tz=UTC)  # 恰好等于阈值
    (base / "export_manifest.json").write_text(
        json.dumps({"manifest_version": 1, "generated_at": boundary.isoformat(), "document_count": 7}),
        encoding="utf-8",
    )
    edge = load_corpus_freshness(base, 14, now=NOW)
    assert edge is not None and edge.source == "manifest" and edge.doc_count == 7
    assert edge.age_days == 14.0 and edge.stale is False  # ==阈值不告警
    older = load_corpus_freshness(base, 14, now=NOW + 3600)
    assert older is not None and older.age_days == 14.0 + 3600 / DAY and older.stale is True


def test_freshness_bad_timestamp_falls_to_missing_then_mtime(tmp_path: Path) -> None:
    # manifest 存在但时间戳不可解析 → generated_at 弃用（spec：source 降级），mtime 回扶年龄
    base = _seed_dir(tmp_path, manifest={"generated_at": "不是时间", "document_count": 3}, mtime=NOW - 2 * DAY)
    info = load_corpus_freshness(base, 14, now=NOW)
    assert info is not None and info.source == "mtime"
    assert info.age_days == 2.0 and info.stale is False and info.doc_count == 3
    base2 = _seed_dir(tmp_path / "c2", manifest=None, mtime=NOW - 20 * DAY)
    info2 = load_corpus_freshness(base2, 14, now=NOW)
    assert info2 is not None and info2.stale is True and info2.source == "mtime"
