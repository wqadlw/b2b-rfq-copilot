"""每日知识兜底刷新（08-knowledge-export-spec §6，阶段 3.3）：重导 → diff → 有变才换。

用法：
    uv run python scripts/daily_knowledge_refresh.py \
        --source-dir <站点>/database/seeders \
        [--live-dir .ai/private/rag_data]

流程：
1. 全量导出到临时目录 `.ai/private/rag_data_refresh`（带 --diff-from 对比现网目录）；
2. diff（added/removed/changed）全零 → 丢弃临时目录，报 "unchanged"；
3. 有变化 → 用新 knowledge.json / export_manifest.json / etl_filtered.log 原子替换现网目录，
   打印差异摘要与保鲜提示。

注意：替换后引擎需重启才加载新快照；运行期间的实时增量由站点 webhook（POST /api/v1/knowledge）
覆盖，本脚本是防事件丢失的兜底通道。cases/solutions/search_meta 走独立通道，不在本脚本范围。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO_ROOT / "scripts" / "vacuum_b2b_export.py"
_spec = importlib.util.spec_from_file_location("vacuum_b2b_export", _SCRIPT)
assert _spec is not None and _spec.loader is not None
export_mod = importlib.util.module_from_spec(_spec)
sys.modules["vacuum_b2b_export"] = export_mod
_spec.loader.exec_module(export_mod)

_REFRESH_FILES = ("knowledge.json", "export_manifest.json", "etl_filtered.log")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="知识库每日兜底：重导 + diff + 有变才换")
    parser.add_argument("--source-dir", required=True, help="站点 database/seeders 目录")
    parser.add_argument("--live-dir", default=".ai/private/rag_data", help="现网知识数据目录")
    args = parser.parse_args(argv)

    live_dir = Path(args.live_dir).resolve()
    if not (live_dir / "knowledge.json").is_file():
        print(f"拒绝：现网目录缺少 knowledge.json：{live_dir}", file=sys.stderr)
        return 2
    refresh_dir = live_dir.parent / f"{live_dir.name}_refresh"
    if refresh_dir.exists():
        shutil.rmtree(refresh_dir)

    rc = export_mod.main(
        [
            "--source-dir",
            args.source_dir,
            "--output-dir",
            str(refresh_dir),
            "--diff-from",
            str(live_dir),
        ]
    )
    if rc != 0:
        print("导出失败，现网数据保持不变。", file=sys.stderr)
        return rc

    report_path = refresh_dir / "diff_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else {}
    added = report.get("added", {"count": 0, "samples": []})
    removed = report.get("removed", {"count": 0, "samples": []})
    changed = report.get("changed", {"count": 0, "samples": []})
    if not (added["count"] or removed["count"] or changed["count"]):
        shutil.rmtree(refresh_dir)
        print("unchanged：语料与现网一致，无需更新。")
        return 0

    for name in _REFRESH_FILES:
        src = refresh_dir / name
        if src.is_file():
            shutil.copy2(src, live_dir / name)
    shutil.rmtree(refresh_dir)
    print(f"refreshed：added={added['count']} removed={removed['count']} changed={changed['count']} → {live_dir}")
    for item in added["samples"][:5] + removed["samples"][:5] + changed["samples"][:5]:
        print(f"  - {item}")
    print("提示：引擎重启后加载新快照；运行期实时增量由 webhook 覆盖。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
