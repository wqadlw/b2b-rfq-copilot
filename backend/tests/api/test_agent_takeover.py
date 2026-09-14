"""Agent takeover endpoints + human_serving graph bypass (CS-1)."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

import rfq_copilot.app.main as main_module
from rfq_copilot.app.runtime import build_runtime
from rfq_copilot.config.settings import get_settings
from rfq_copilot.core.agent.llm import FakeLLM

TOKEN = "test-internal-cs1"


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    get_settings.cache_clear()
    monkeypatch.setenv("INTERNAL_API_TOKEN", TOKEN)
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


def _auth() -> dict[str, str]:
    return {"X-Internal-Token": TOKEN}


def test_agent_sessions_requires_token(client: TestClient) -> None:
    assert client.get("/api/v1/agent/sessions").status_code == 401


def test_agent_sessions_invalid_status_400(client: TestClient) -> None:
    r = client.get("/api/v1/agent/sessions", params={"status": "bogus"}, headers=_auth())
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "INVALID_STATUS"


def test_takeover_flow_full(client: TestClient) -> None:
    # 1) user chats -> bot_serving
    assert (
        client.post(
            "/api/v1/chat/stream",
            json={"session_id": "cs1-a", "message": "demo-p-001"},
        ).status_code
        == 200
    )
    # 2) simulate handoff_pending (graph sets it via handoff route; direct set here)
    state = main_module._RUNTIME.store.find("cs1-a")
    assert state is not None
    state.status = "handoff_pending"
    # 3) agent lists pending sessions
    r2 = client.get("/api/v1/agent/sessions", headers=_auth())
    assert r2.status_code == 200
    ids = [item["session_id"] for item in r2.json()["items"]]
    assert "cs1-a" in ids
    # 4) takeover
    r3 = client.post("/api/v1/agent/sessions/cs1-a/takeover", headers=_auth())
    assert r3.status_code == 200
    assert r3.json()["status"] == "human_serving"
    # 5) agent reply
    r4 = client.post(
        "/api/v1/agent/sessions/cs1-a/reply",
        json={"content": "您好，我是人工坐席，有什么可以帮您？"},
        headers=_auth(),
    )
    assert r4.status_code == 200
    # 6) user message during human_serving: bypasses LLM, echoes last agent reply
    r5 = client.post(
        "/api/v1/chat/stream",
        json={"session_id": "cs1-a", "message": "价格怎么算"},
    )
    body = r5.read().decode("utf-8")
    assert "人工服务中" in body
    assert "您好，我是人工坐席" in body
    # 7) close
    r6 = client.post("/api/v1/agent/sessions/cs1-a/close", headers=_auth())
    assert r6.status_code == 200
    assert r6.json()["status"] == "closed"
    # 8) takeover after closed -> 404
    r7 = client.post("/api/v1/agent/sessions/cs1-a/takeover", headers=_auth())
    assert r7.status_code == 404


def test_takeover_unknown_session_404(client: TestClient) -> None:
    r = client.post("/api/v1/agent/sessions/no-such/takeover", headers=_auth())
    assert r.status_code == 404


def test_reply_requires_human_serving(client: TestClient) -> None:
    r = client.post(
        "/api/v1/agent/sessions/some-random/reply",
        json={"content": "hi"},
        headers=_auth(),
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "NOT_HUMAN_SERVING"


def test_reply_invalid_json_400(client: TestClient) -> None:
    client.post(
        "/api/v1/chat/stream",
        json={"session_id": "cs1-b", "message": "demo-p-001"},
    )
    state = main_module._RUNTIME.store.find("cs1-b")
    assert state is not None
    state.status = "human_serving"
    r = client.post(
        "/api/v1/agent/sessions/cs1-b/reply",
        content="not-json{",
        headers={**_auth(), "Content-Type": "application/json"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "INVALID_JSON"
