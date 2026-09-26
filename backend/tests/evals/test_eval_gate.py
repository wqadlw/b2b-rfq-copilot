"""CI gate: deterministic execution of the committed eval case store.

Runs every case marked ``"ci": true`` plus the derived B family (fabrication attacks).
Cases may pin the classifier output via ``scripted_understanding`` so post-LLM
deterministic behaviour (routing guards) is covered in CI too.
against the real graph with an empty-script FakeLLM. A ci case that needs the model
fails loudly ("FakeLLM exhausted") — that is the signal it does not belong in CI.

Live/interactive coverage stays with the manual runner:

    uv run python scripts/run_eval.py --live

Rationale (LangGraph/LangSmith practice, lightweight): catch routing/refusal
regressions on every commit without shipping API keys or network access into CI.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from conftest import ADAPTER_DIR, make_deps
from rfq_copilot.core.agent.graph import build_graph
from rfq_copilot.core.eval.assertions import (
    IMPLEMENTED_TYPES,
    EvalContext,
    check_assertion,
    render_failure,
)
from rfq_copilot.core.eval.deriver import derive_b_cases
from rfq_copilot.core.manifest import load_manifest

pytestmark = pytest.mark.eval

ROOT = Path(__file__).resolve().parents[3]
CASES_DIR = ROOT / "eval" / "cases"


def _load_ci_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for path in sorted(CASES_DIR.rglob("*.jsonl")):
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            case = json.loads(line)
            if case.get("ci") is True:
                case["_source"] = f"{path.parent.name}/{path.name}:{line_no}"
                cases.append(case)
    return cases


def _derived_b_cases() -> list[dict[str, Any]]:
    manifest = load_manifest(ADAPTER_DIR)
    return [{**case, "_source": "derived:B"} for case in derive_b_cases(manifest)]


CI_CASES = _load_ci_cases()
ALL_CASES = CI_CASES + _derived_b_cases()


def test_store_only_uses_implemented_assertions() -> None:
    """回归：未实现的断言类型曾静默通过（等于没断言）。"""
    unknown = {
        assertion.get("type")
        for path in CASES_DIR.rglob("*.jsonl")
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
        for assertion in json.loads(line).get("asserts", [])
        if assertion.get("type") not in IMPLEMENTED_TYPES
    }
    assert not unknown, f"case store uses unimplemented assertion types: {sorted(unknown)}"


def test_ci_coverage_is_not_empty() -> None:
    assert len(CI_CASES) >= 8 and len(ALL_CASES) >= len(CI_CASES) + 15
    # QA-0027：C 族（投毒红队）必须全量入 CI，红线「B/C/D 全绿」中 C 不允许零机器执行
    c_cases = [c for c in CI_CASES if c["family"] == "C"]
    assert len(c_cases) >= 12, f"C 族 CI 覆盖不足：{len(c_cases)}/12"


@pytest.mark.parametrize("case", ALL_CASES, ids=[c["id"] for c in ALL_CASES])
async def test_case_passes_on_deterministic_path(case: dict[str, Any]) -> None:
    turns = case["turns"]
    assert len(turns) == 1, (
        f"{case['id']}: ci cases must be single-turn; multi-turn or interactive flows "
        "belong to scripts/run_eval.py --live"
    )

    # 用例可携带 scripted_understanding：把"分类器输出"固定下来，
    # 从而让路由护栏这类"LLM 之后"的行为也能被 CI 确定性锁定。
    # scripted_followup：understanding 之后的补充脚本段（06-eval-spec §2.1），
    # 如 knowledge_flow 的答案草稿 {"text_chunks": [...]}。
    scripted = []
    if case.get("scripted_understanding"):
        scripted.append(case["scripted_understanding"])
    scripted.extend(case.get("scripted_followup") or [])
    # O4：运营信号捕获（no_match 缺口事件 / 命中统计 doc_id），断言类型 no_match_recorded/hit_recorded 消费
    no_match_events: list[dict[str, Any]] = []
    hit_events: list[list[str]] = []
    deps, ports = make_deps(scripted=scripted or None, no_match_events=no_match_events, hit_events=hit_events)
    if (case.get("preconditions") or {}).get("empty_rag"):
        # 空库前置：knowledge_flow 零召回路径（与集成测试 test_no_match_recorder 同构）
        from rfq_copilot.core.rag.embedding import HashingEmbedder
        from rfq_copilot.core.rag.pipeline import RAGPipeline
        from rfq_copilot.core.rag.reranker import NoopReranker
        from rfq_copilot.core.rag.store import InMemoryVectorStore

        deps.rag = RAGPipeline(
            embedder=HashingEmbedder(), store=InMemoryVectorStore(), reranker=NoopReranker(), hit_recorder=hit_events.append
        )
    graph = build_graph(deps)
    try:
        final = await graph.ainvoke(
            {
                "session_id": f"ci-{case['id']}",
                "message": str(turns[0]["content"])[:2000],
                "events": [],
                "tool_calls": [],
            }
        )
    except AssertionError as exc:  # FakeLLM exhausted: case is not deterministic
        pytest.fail(f"{case['id']} ({case['_source']}): marked ci but needs the LLM path ({exc})")

    ctx = EvalContext(
        answer=str(final.get("answer", "")),
        events=[kind for kind, _ in final.get("events", [])],
        final=final,
        created_inquiries=list(ports.store.inquiries),
        no_match_events=no_match_events,
        hit_doc_ids=[doc_id for call in hit_events for doc_id in call],
    )
    failures = []
    for assertion in case["asserts"]:
        try:
            if not check_assertion(assertion, ctx):
                failures.append(f"{assertion['type']} — {render_failure(assertion, ctx)}")
        except ValueError as exc:
            failures.append(f"{assertion['type']} — INVALID_ASSERTION {exc}")
    assert not failures, f"{case['id']} ({case['_source']}): " + "; ".join(failures)
