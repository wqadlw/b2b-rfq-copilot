"""Evaluation baseline runner (M0): parse/validate seed cases + report skeleton.

M1 wires the real runner (graph execution + programmatic asserts); this script
already enforces case-format discipline and produces a Markdown+JSON report stub.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CASES_DIR = ROOT / "eval" / "cases"
REPORTS_DIR = ROOT / "eval" / "reports"
REQUIRED_FIELDS = {"id", "family", "turns", "asserts"}
FAMILIES = {"A", "B", "C", "D"}


def load_cases() -> list[dict]:
    cases: list[dict] = []
    errors: list[str] = []
    for path in sorted(CASES_DIR.rglob("*.jsonl")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                case = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"{path.name}:{lineno}: invalid JSON ({exc})")
                continue
            missing = REQUIRED_FIELDS - set(case)
            if missing:
                errors.append(f"{path.name}:{lineno}: missing fields {sorted(missing)}")
                continue
            if case["family"] not in FAMILIES:
                errors.append(f"{path.name}:{lineno}: unknown family {case['family']}")
                continue
            cases.append(case)
    for error in errors:
        print(f"ERROR {error}")
    if errors:
        sys.exit(2)
    return cases


def derive_b_placeholders(cases: list[dict]) -> list[str]:
    """B-family is derived, never hand-written; M0 lists what the deriver will produce."""
    disabled = ["pricing", "lead_time", "stock"]  # demo + vacuum manifests freeze these
    templates = ["direct_ask", "range_request", "fake_context_table", "poisoned_instruction", "persistence_loop"]
    return [f"B__{capability}__{template}" for capability in disabled for template in templates]


def main() -> int:
    cases = load_cases()
    by_family = Counter(case["family"] for case in cases)
    b_pending = derive_b_placeholders(cases)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    report_path = REPORTS_DIR / f"{stamp}_baseline.md"
    report_path.write_text(
        "\n".join(
            [
                f"# 评测基线报告 {stamp}（M0 stub）",
                "",
                "| 族 | 用例数 |",
                "|---|---|",
                *(f"| {family} | {count} |" for family, count in sorted(by_family.items())),
                f"| B(派生占位) | {len(b_pending)} |",
                "",
                "> M0 阶段仅校验用例格式与派生计划；真实执行（graph + 程序化断言）随 M1 runner 接入。",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (REPORTS_DIR / f"{stamp}_baseline.json").write_text(
        json.dumps({"by_family": dict(by_family), "b_derived_pending": b_pending}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"eval baseline: {dict(by_family)} + {len(b_pending)} B placeholders")
    print(f"report: {report_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
