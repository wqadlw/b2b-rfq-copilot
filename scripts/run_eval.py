"""Evaluation runner: M0 format discipline + M2 live execution (graph + programmatic asserts).

--live requires EMBEDDING_PROVIDER=openai_compatible and LLM_API_KEY in .env;
executes seed cases against the real graph and writes Markdown+JSON reports
to eval/reports/ (gitignored — copy numbers into private notes/README by hand).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CASES_DIR = ROOT / "eval" / "cases"
REPORTS_DIR = ROOT / "eval" / "reports"
REQUIRED_FIELDS = {"id", "family", "turns", "asserts"}
FAMILIES = {"A", "B", "C", "D"}
ALLOWED_RESUME_ACTIONS = frozenset({"confirm_inquiry", "cancel_inquiry"})


def load_cases() -> tuple[list[dict], list[str]]:
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
    return cases, errors


def derive_b_cases() -> list[dict[str, Any]]:
    """实装派生器：从 demo manifest 生成可执行 B 族用例（port-spec §5/§7）。"""
    sys.path.insert(0, str(ROOT / "backend" / "src"))
    from rfq_copilot.core.eval.deriver import derive_b_cases as derive
    from rfq_copilot.core.manifest import load_manifest

    manifest = load_manifest(Path(ROOT) / "backend" / "src" / "rfq_copilot" / "adapters" / "demo")
    return derive(manifest)


def _run_b(b_cases: list[dict[str, Any]]) -> int:
    """Execute derived B cases via the deterministic refusal path (no LLM)."""
    sys.path.insert(0, str(ROOT / "backend" / "src"))
    from rfq_copilot.core.agent.graph import GraphDeps, build_graph
    from rfq_copilot.core.manifest import load_manifest
    from rfq_copilot.core.memory import SessionStore
    from rfq_copilot.core.policies.refusal import derive_refusal_policies
    from rfq_copilot.core.prompts import PromptRegistry

    adapter_dir = Path(ROOT) / "backend" / "src" / "rfq_copilot" / "adapters" / "demo"
    manifest = load_manifest(adapter_dir)
    deps = GraphDeps(
        manifest=manifest,
        llm=_NullLLM(),
        prompts=PromptRegistry(),
        refusal_policies=derive_refusal_policies(manifest),
        store=SessionStore(),
    )
    graph = build_graph(deps)
    from rfq_copilot.core.eval.assertions import EvalContext, check_assertion

    passed = 0
    for i, case in enumerate(b_cases):
        import asyncio

        final = asyncio.run(
            graph.ainvoke(
                {"session_id": f"b-{i}", "message": case["turns"][0]["content"]},
                {"configurable": {"thread_id": f"b-{i}"}},
            )
        )
        ctx = EvalContext(
            answer=str(final.get("answer", "")),
            events=[e for e, _ in final.get("events", [])],
            final=final,
        )
        ok = all(check_assertion(a, ctx) for a in case["asserts"])
        passed += int(ok)
    return passed


class _NullLLM:
    async def complete_json(self, system: str, user: str) -> dict[str, Any]:
        raise AssertionError("B-family refusals must be deterministic (no LLM)")


def _created_inquiries(rt: Any) -> list[dict[str, Any]] | None:
    """Records created through the demo inquiry sink (``db_state`` assertions need them)."""
    store = getattr(getattr(rt.deps, "inquiry_sink", None), "_store", None)
    records = getattr(store, "inquiries", None)
    return list(records) if records is not None else None


def _run_live(cases: list[dict]) -> tuple[Counter, list[str]]:
    sys.path.insert(0, str(ROOT / "backend" / "src"))
    from langgraph.types import Command

    from rfq_copilot.app.runtime import build_runtime, seed_demo
    from rfq_copilot.config.settings import get_settings

    settings = get_settings()
    if not settings.llm_api_key:
        print("live run requires LLM_API_KEY in .env")
        sys.exit(3)
    retrieval_mode = "semantic(bge-m3)" if settings.embedding_provider == "openai_compatible" else "hashing(fallback)"
    rt = build_runtime()
    from rfq_copilot.core.eval.faithfulness import judge as faithfulness_judge

    print(f"live: llm={settings.llm_model} retrieval={retrieval_mode}")

    async def drive() -> tuple[Counter, list[str]]:
        await seed_demo(rt)
        tally: Counter = Counter()
        failures: list[str] = []
        for case in cases:
            session_id = "evalcase-" + str(abs(hash(case["id"])) % 10_000_000_00)
            config = {"configurable": {"thread_id": session_id}}
            expects_created = any("inquiry_created" in a.get("must_include", []) for a in case.get("asserts", []))
            supply_contact = expects_created
            answer, events = "", []
            for turn_index, turn in enumerate(case["turns"]):
                state: dict[str, Any] = {
                    "session_id": session_id,
                    "message": str(turn["content"])[:2000],
                    "contact": {"name": "评测", "phone": "13800000000"} if supply_contact else None,
                    "quantity": 10 if supply_contact else None,
                    "events": [],
                    "tool_calls": [],
                }
                final = await rt.graph.ainvoke(state, config)
                interrupted = final.get("__interrupt__") or []
                if interrupted and turn_index == len(case["turns"]) - 1:
                    events.append("inquiry_confirm")  # 中断→确认卡（03-api-spec 事件源）
                    resume = case.get("resume_action")
                    if resume in ALLOWED_RESUME_ACTIONS:
                        final = await rt.graph.ainvoke(Command(resume={"action": resume}), config)
                        events.append("inquiry_created") if any(
                            e[0] == "inquiry_created" for e in final.get("events", [])
                        ) else None
                    else:
                        answer = "请您确认以上询盘信息（等待您的确认）。"
                answer = str(final.get("answer", ""))[:2000]
                events += [e for e, _ in final.get("events", [])]
            if interrupted and not answer:
                answer = "请您确认以上询盘信息（等待您的确认）。"
            from rfq_copilot.core.eval.assertions import EvalContext, check_assertion, render_failure

            ctx = EvalContext(
                answer=answer,
                events=events,
                final=final,
                created_inquiries=_created_inquiries(rt),
            )
            ok = True
            for assertion in case.get("asserts", []):
                try:
                    passed_assertion = check_assertion(assertion, ctx)
                except ValueError as exc:  # 未实现/不可验证的断言必须中断评测，不得静默通过
                    failures.append(f"{case['id']}: INVALID_ASSERTION {exc}")
                    ok = False
                    continue
                if not passed_assertion:
                    ok = False
                    failures.append(f"{case['id']}: {assertion['type']} — {render_failure(assertion, ctx)}")
            if case["family"] == "A" and answer and rt.deps.rag is not None:
                ctx, _ = await rt.deps.rag.context_for(state["message"], top_k=5)
                verdict = await faithfulness_judge(rt.deps.llm, state["message"], answer, ctx)
                tally["A_faithful"] += int(verdict["faithful"])
            tally[case["family"]] += 1
            tally[f"{case['family']}_pass"] += int(ok)
        return tally, failures

    return asyncio.run(drive())


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed-case format checks and live graph execution.")
    parser.add_argument("--live", action="store_true", help="execute cases against the real graph")
    args = parser.parse_args()

    cases, errors = load_cases()
    for error in errors:
        print(f"ERROR {error}")
    if errors:
        return 2

    if args.live:
        tally, failures = _run_live(cases)
    else:
        tally = Counter(case["family"] for case in cases)
        failures = []
        b_cases = derive_b_cases()
        tally["B"] = len(b_cases)
        tally["B_pass"] = _run_b(b_cases)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    mode = "live" if args.live else "baseline"
    report_path = REPORTS_DIR / f"{stamp}_{mode}.md"
    lines = [f"# 测评报告 {stamp}（{mode}）", "", "| 族 | 用例 | 通过 | 通过率 |", "|---|---|---|---|"]
    for family in sorted(FAMILIES):
        total = tally.get(family, 0)
        passed = tally.get(f"{family}_pass", total if not args.live else 0)
        rate = f"{passed / total:.0%}" if total else "—"
        lines.append(f"| {family} | {total} | {passed} | {rate} |")
    if not args.live:
        lines += ["", f"> B 族派生用例 {len(derive_b_cases())} 条（已实机执行，见上方 B 行）。"]
    if failures:
        lines += ["", "## 失败明细", *(f"- {f}" for f in failures)]
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (REPORTS_DIR / f"{stamp}_{mode}.json").write_text(
        json.dumps(
            {"mode": mode, "tally": {k: v for k, v in tally.items()}, "failures": failures},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"mode={mode} tally={dict(tally)} failures={len(failures)}")
    print(f"report: {report_path.relative_to(ROOT)}")
    return 1 if args.live and failures else 0


if __name__ == "__main__":
    sys.exit(main())
