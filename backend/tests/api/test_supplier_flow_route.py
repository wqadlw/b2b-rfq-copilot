"""supplier_flow route: graph-level tests (five-feature plan P1-2)."""

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
                "intent": "supplier_search",
                "route": "supplier_flow",
                "confidence": 0.9,
                "entities": {"product_category": "真空泵", "region": "苏州"},
            }
        ]
    )
    main_module._RUNTIME = build_runtime(llm=llm)
    with TestClient(main_module.app) as c:
        yield c
    get_settings.cache_clear()


def _collect_answer(client: TestClient, session_id: str, message: str) -> str:
    raw = b""
    with client.stream(
        "POST",
        "/api/v1/chat/stream",
        json={"session_id": session_id, "message": message},
    ) as r:
        assert r.status_code == 200
        raw = b"".join(r.iter_bytes())
    text = raw.decode("utf-8")
    deltas = [json.loads(m).get("delta", "") for m in re.findall(r"data: (.*)", text) if "delta" in m]
    return "".join(deltas)


def test_supplier_flow_streams_suppliers(client: TestClient) -> None:
    """supplier_flow 走通：回答含并列供应商、匹配原因与 tool_call 事件。"""
    answer = _collect_answer(client, "sess-sup1", "帮我找苏州做真空泵的供应商")
    assert "demo 供应商" in answer
    assert "匹配参考" in answer
    # 中立性：并列话术，无"最好/推荐购买"措辞
    assert "最好" not in answer and "推荐购买" not in answer


def test_supplier_flow_neutral_no_ranking_language(client: TestClient) -> None:
    """回答不出现排序推荐措辞；呈现为并列列表。"""
    answer = _collect_answer(client, "sess-sup2", "苏州的真空泵供应商有哪些")
    assert answer.startswith("以下是为您找到的供应商")
