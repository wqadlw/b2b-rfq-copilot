"""Golden-set regression gate: deterministic router/refusal assertions in CI.

Data lives in backend/evals/golden/router_cases.json (see backend/evals/README.md).
These cases are 0-LLM-token by construction, so they are safe and fast in CI.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from conftest import make_deps
from rfq_copilot.core.agent.graph import _understanding_from_tools, build_graph

GOLDEN = json.loads(
    (Path(__file__).resolve().parents[2] / "evals" / "golden" / "router_cases.json").read_text(encoding="utf-8")
)
CASES: list[dict[str, Any]] = GOLDEN["cases"]
INVARIANTS: list[dict[str, Any]] = GOLDEN["answer_invariants"]

pytestmark = pytest.mark.eval


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_understanding_shortcut_route(case: dict[str, Any]) -> None:
    deps, _ = make_deps()
    state = {"session_id": f"eval-{case['id']}", "message": case["message"]}
    u = _understanding_from_tools(state, deps)
    assert u is not None, f"{case['id']}: expected a deterministic shortcut, got LLM fallback"
    for key, expected in case["expect"].items():
        assert u.get(key) == expected, f"{case['id']}: {key}={u.get(key)!r} != {expected!r}"


@pytest.mark.parametrize("case", INVARIANTS, ids=[c["id"] for c in INVARIANTS])
async def test_refusal_answer_invariants(case: dict[str, Any]) -> None:
    deps, _ = make_deps()
    graph = build_graph(deps)
    final = await graph.ainvoke({"session_id": f"eval-{case['id']}", "message": case["message"]})
    answer = final["answer"]
    for needle in case["contains"]:
        assert needle in answer, f"{case['id']}: missing {needle!r} in {answer!r}"
    for needle in case["absent"]:
        assert needle not in answer, f"{case['id']}: forbidden {needle!r} in {answer!r}"
    assert final["tool_calls"] == [], f"{case['id']}: refusal must not call tools"
