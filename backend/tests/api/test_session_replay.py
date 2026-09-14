"""Session replay API: internal-token gate + rich message trail (citations/tool_calls/events/ts)."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

import rfq_copilot.app.main as main_module
from rfq_copilot.app.runtime import build_runtime
from rfq_copilot.config.settings import get_settings
from rfq_copilot.core.agent.llm import FakeLLM

TOKEN = "test-internal-token-123"


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("INTERNAL_API_TOKEN", TOKEN)
    get_settings.cache_clear()
    llm = FakeLLM([{"intent": "product_inquiry", "route": "product_flow", "confidence": 0.9, "entities": {}}])
    main_module._RUNTIME = build_runtime(llm=llm)
    with TestClient(main_module.app) as c:
        yield c
    get_settings.cache_clear()


def _chat(client: TestClient, session_id: str, message: str) -> None:
    r = client.post("/api/v1/chat/stream", json={"session_id": session_id, "message": message})
    assert r.status_code == 200


def test_replay_requires_token(client: TestClient) -> None:
    r = client.get("/api/v1/sessions/sess-r1/replay")
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "UPSTREAM_AUTH"


def test_replay_unknown_session_is_404(client: TestClient) -> None:
    r = client.get("/api/v1/sessions/no-such-session/replay", headers={"X-Internal-Token": TOKEN})
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "SESSION_NOT_FOUND"


def test_replay_rich_trail(client: TestClient) -> None:
    _chat(client, "sess-r2", "有哪些真空泵？")
    r = client.get("/api/v1/sessions/sess-r2/replay", headers={"X-Internal-Token": TOKEN})
    assert r.status_code == 200
    body = r.json()
    assert body["session_id"] == "sess-r2"
    assert body["message_count"] == 2

    user_msg, ai_msg = body["messages"]
    assert user_msg["role"] == "user" and "真空泵" in user_msg["content"]
    assert user_msg["ts"]  # auto timestamp

    assert ai_msg["role"] == "assistant"
    assert ai_msg["ts"]
    assert ai_msg["tool_calls"] == ["search_products"]
    # citation events captured into metadata (was silently empty before)
    assert ai_msg["citations"] and all("title" in c for c in ai_msg["citations"])
    # full event trail preserved for admin panels
    trail_names = [name for name, _ in ai_msg["events"]]
    assert "tool_call" in trail_names and "citation" in trail_names
