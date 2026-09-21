"""compare_flow route: graph-level SSE tests (five-feature plan P1-3)."""

import json
import re
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

import rfq_copilot.app.main as main_module
from rfq_copilot.app.runtime import build_runtime
from rfq_copilot.config.settings import get_settings
from rfq_copilot.core.agent.llm import FakeLLM


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    get_settings.cache_clear()
    llm = FakeLLM(
        [
            {
                "intent": "product_inquiry",
                "route": "compare_flow",
                "confidence": 0.9,
                "entities": {},
            }
        ]
    )
    main_module._RUNTIME = build_runtime(llm=llm)
    with TestClient(main_module.app) as c:
        yield c
    get_settings.cache_clear()


def _collect(client: TestClient, session_id: str, message: str) -> tuple[str, list[str]]:
    raw = b""
    with client.stream(
        "POST",
        "/api/v1/chat/stream",
        json={"session_id": session_id, "message": message},
    ) as r:
        assert r.status_code == 200
        raw = b"".join(r.iter_bytes())
    text = raw.decode("utf-8")
    answer = "".join(json.loads(m).get("delta", "") for m in re.findall(r"data: (.*)", text) if "delta" in m)
    tools = re.findall(r'"tool": "([a-z_]+)"', text)
    return answer, tools


def test_compare_flow_renders_matrix(client: TestClient) -> None:
    answer, tools = _collect(client, "sess-cmp1", "对比一下 demo-p-001 和 demo-p-002")
    assert "get_product_detail" in tools
    assert "demo 设备" in answer
    assert "对比" in answer or "参数" in answer
    for banned in ("更好", "更优", "推荐购买", "首选"):
        assert banned not in answer


def test_compare_flow_missing_ids_prompts(client: TestClient) -> None:
    answer, _ = _collect(client, "sess-cmp2", "帮我对比一下产品")
    assert "两个" in answer


def test_compare_flow_one_unknown_id_prompts(client: TestClient) -> None:
    answer, _ = _collect(client, "sess-cmp3", "对比 demo-p-001 和 demo-p-999")
    assert "未找到" in answer


def test_compare_flow_emits_product_compare_card(client: TestClient) -> None:
    raw = b""
    with client.stream(
        "POST",
        "/api/v1/chat/stream",
        json={"session_id": "sess-cmp4", "message": "对比一下 demo-p-001 和 demo-p-002"},
    ) as r:
        assert r.status_code == 200
        raw = b"".join(r.iter_bytes())
    payloads = []
    for m in re.findall(r"data: (.*)", raw.decode("utf-8")):
        try:
            payloads.append(json.loads(m))
        except json.JSONDecodeError:
            continue
    cards = [p for p in payloads if isinstance(p, dict) and p.get("kind") == "product_compare"]
    assert len(cards) == 1
    card = cards[0]
    assert card["title"] == "产品参数对比"
    assert len(card["products"]) == 2
    assert any(row["label"] == "产品名称" for row in card["rows"])  # 复用 build_compare_matrix 行集
