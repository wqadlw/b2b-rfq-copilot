r"""从找真空站点导出检索元数据（同义词 + 屏蔽词）→ KNOWLEDGE_DATA_DIR。

数据只在站点数据库里（无 seeder），因此走站点自己的 artisan/tinker 连接（只读 SELECT）。
站点 DB 未启动时脚本会明确报错退出——绝不用空数据覆盖已有文件。

用法：
    uv run python scripts/export_search_meta.py \
        --site-dir D:\AAAAA\zhaozhenkong \
        --output-dir .ai/private/zzk_rag_data
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

BEGIN = "ZZKMETA_BEGIN"
END = "ZZKMETA_END"

PHP_SNIPPET = (
    f"echo '{BEGIN}'; "
    "echo json_encode(["
    "'synonyms' => App\\Models\\SearchSynonym::where('status', true)->pluck('synonym', 'word')->toArray(), "
    "'block_words' => App\\Models\\SearchBlockWord::pluck('word')->toArray(), "
    "], JSON_UNESCAPED_UNICODE); "
    f"echo '{END}';"
)


def extract_payload(stdout: str) -> dict:
    """从 tinker 输出里截取 BEGIN/END 之间的 JSON（tinker 会混入横幅与 BOM）。"""
    start = stdout.find(BEGIN)
    end = stdout.find(END, start + 1)
    if start == -1 or end == -1:
        raise ValueError("artisan 输出中未找到元数据标记（站点 DB 是否可用？）")
    raw = stdout[start + len(BEGIN) : end].strip()
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("元数据载荷不是对象")
    payload["synonyms"] = {str(k): str(v) for k, v in (payload.get("synonyms") or {}).items()}
    payload["block_words"] = [str(w) for w in (payload.get("block_words") or [])]
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="导出站点同义词/屏蔽词（只读）")
    parser.add_argument("--site-dir", required=True, help="找真空仓库路径")
    parser.add_argument("--output-dir", required=True, help="KNOWLEDGE_DATA_DIR")
    parser.add_argument("--php", default="php", help="php 可执行文件")
    args = parser.parse_args()

    proc = subprocess.run(
        [args.php, "artisan", "tinker", f"--execute={PHP_SNIPPET}"],
        cwd=args.site_dir,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        payload = extract_payload(proc.stdout or "")
    except ValueError as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        tail = (proc.stdout or proc.stderr or "")[-400:]
        print(f"stdout/stderr tail: {tail}", file=sys.stderr)
        return 2

    payload["version"] = 1
    payload["exported_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "zzk_search_meta.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"written {out_path} synonyms={len(payload['synonyms'])} block_words={len(payload['block_words'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
