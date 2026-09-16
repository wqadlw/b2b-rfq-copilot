"""Guest free-tier v2: G1 direct search + G2 knowledge citations (0 LLM token)."""

import json
import re
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

import rfq_copilot.app.main as main_module
from rfq_copilot.app.guest_paths import detect_guest_query, looks_like_knowledge_query
from rfq_copilot.app.runtime import build_runtime
from rfq_copilot.config.settings import get_settings
from rfq_copilot.core.agent.llm import FakeLLM


@pytest.fixture()
def guest_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    get_settings.cache_clear()
    monkeypatch.setenv("INTERNAL_API_TOKEN", "test-tier")
    monkeypatch.setenv("GUEST_TIER_ENABLED", "true")
    llm = FakeLLM(
        [
            {
                "intent": "product_inquiry",
                "route": "product_flow",
                "confidence": 0.9,
                "entities": {},
            }
        ]
    )
    main_module._RUNTIME = build_runtime(llm=llm)
    with TestClient(main_module.app) as c:
        yield c
    get_settings.cache_clear()


def _turn(client: TestClient, session: str, message: str) -> tuple[str, list[str]]:
    raw = b""
    with client.stream("POST", "/api/v1/chat/stream", json={"session_id": session, "message": message}) as r:
        assert r.status_code == 200
        raw = b"".join(r.iter_bytes())
    text = raw.decode("utf-8")
    events = re.findall(r"event: (\w+)", text)
    answer = ""
    for m in re.finditer(r"event: (\w+)\ndata: (.*)", text):
        if m.group(1) == "answer_delta":
            answer += str(json.loads(m.group(2)).get("delta", ""))
    return answer, events


def test_detect_guest_query() -> None:
    assert detect_guest_query("有哪些真空泵") == "真空泵"
    assert detect_guest_query("看看 demo-p-003") == "demo-p-003"
    assert detect_guest_query("帮我选型") == ""


def test_looks_like_knowledge() -> None:
    assert looks_like_knowledge_query("无油泵和旋片泵有什么区别")
    assert looks_like_knowledge_query("询盘流程是怎样的")
    assert not looks_like_knowledge_query("推荐几款真空泵")


def test_guest_direct_product_search(guest_client: TestClient) -> None:
    answer, events = _turn(guest_client, "g1-1", "有哪些真空泵")
    assert "login_required" not in events
    # 回答形式契约：卡片承载数据，文本简短引导（不复读产品名/URL）
    assert "为您找到" in answer
    assert "登录后" in answer  # 引导但不阻断
    assert "citation" in events
    assert events.count("card") >= 1
    assert "/products/" not in answer


def test_guest_demo_id_lookup(guest_client: TestClient) -> None:
    answer, events = _turn(guest_client, "g1-2", "demo-p-005")
    assert "login_required" not in events
    assert "demo 设备" in answer


def test_guest_knowledge_citations(guest_client: TestClient) -> None:
    answer, events = _turn(guest_client, "g2-1", "无油泵和旋片泵有什么区别")
    assert "login_required" not in events
    assert "相关资料" in answer
    assert "retrieval" in events
    assert "原文" in answer  # 游客看摘录，登录看 AI 提炼


def test_guest_open_selection_still_walled(guest_client: TestClient) -> None:
    answer, events = _turn(guest_client, "wall-1", "帮我做一个完整的选型方案")
    assert "login_required" in events
    assert "登录" in answer
