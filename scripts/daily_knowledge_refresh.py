"""每日知识兜底刷新（08-knowledge-export-spec §6，阶段 3.3）：重导 → diff → 有变才换。

用法：
    uv run python scripts/daily_knowledge_refresh.py \
        --source-dir <站点>/database/seeders \
        [--live-dir .ai/private/rag_data]

实现为 app/knowledge_refresh.run_refresh 的薄壳（08-spec §6.5 单一实现）。
引擎内置调度（KNOWLEDGE_REFRESH_ENABLED）与本 CLI 共用同一核心；CLI 供人工立即触发。
替换后引擎**无需重启**——调度器/下次刷新会热加载；手工替换后如需立即可见，
调用方自行重启或等待引擎下一轮热加载（§6.3）。

注意：运行期间的实时增量由站点 webhook（POST /api/v1/knowledge）覆盖，本通道是防事件
丢失的兜底。cases/solutions/search_meta 走独立通道，不在本脚本范围。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "backend" / "src"))

from rfq_copilot.app.knowledge_refresh import run_refresh  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="知识库每日兜底：重导 + diff + 有变才换")
    parser.add_argument("--source-dir", required=True, help="站点 database/seeders 目录")
    parser.add_argument("--live-dir", default=".ai/private/rag_data", help="现网知识数据目录")
    args = parser.parse_args(argv)

    try:
        result = run_refresh(args.source_dir, args.live_dir)
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"刷新中止：{exc}", file=sys.stderr)
        return 2

    if not result.refreshed:
        print("unchanged：语料与现网一致，无需更新。")
        return 0
    print(
        f"refreshed：added={len(result.added)} removed={len(result.removed)} "
        f"changed={len(result.changed)} → {Path(args.live_dir).resolve()}"
    )
    for item in (result.added + result.removed + result.changed)[:15]:
        print(f"  - {item}")
    print("提示：引擎内置调度会在下一轮热加载；未启用调度时需重启引擎加载新快照。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
