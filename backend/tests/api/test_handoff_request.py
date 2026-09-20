"""用户侧转人工端点（CS-1 配套）：公开、session_id 即凭证、幂等。03-api-spec §4.5。"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

import rfq_copilot.app.main as main_module
from rfq_copilot.app.runtime import build_runtime
from rfq_copilot.config.settings import get_settings

TOKEN = "test-internal-handoff"


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    get_settings.cache_clear()
    monkeypatch.setenv("INTERNAL_API_TOKEN", TOKEN)
    main_module._RUNTIME = build_runtime()
    with TestClient(main_module.app) as c:
        yield c
    get_settings.cache_clear()


def _make_session(_client: TestClient, sid: str) -> None:
    """直接经 store 建会话（sessions 端点自行生成 id，不适合固定 sid 断言）。"""
    main_module._RUNTIME.store.get_or_create(sid)


def test_handoff_request_unknown_session_404(client: TestClient) -> None:
    r = client.post("/api/v1/sessions/no-such/handoff-request")
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "SESSION_NOT_FOUND"


def test_handoff_request_bot_serving_transitions_and_system_message(client: TestClient) -> None:
    _make_session(client, "hf-a")
    r = client.post("/api/v1/sessions/hf-a/handoff-request")
    assert r.status_code == 200
    assert r.json() == {"session_id": "hf-a", "status": "handoff_pending"}
    # 系统消息落库（坐席工作台可见上下文）
    msgs = client.get(
        "/api/v1/sessions/hf-a/messages", headers={"X-Internal-Token": TOKEN}
    ).json()["messages"]
    assert any(m["role"] == "system" and "人工服务请求" in m["content"] for m in msgs)


def test_handoff_request_idempotent_no_duplicate_message(client: TestClient) -> None:
    _make_session(client, "hf-b")
    assert client.post("/api/v1/sessions/hf-b/handoff-request").status_code == 200
    assert client.post("/api/v1/sessions/hf-b/handoff-request").status_code == 200
    msgs = client.get(
        "/api/v1/sessions/hf-b/messages", headers={"X-Internal-Token": TOKEN}
    ).json()["messages"]
    assert sum(1 for m in msgs if m["role"] == "system" and "人工服务请求" in m["content"]) == 1


def test_handoff_request_idempotent_when_human_serving(client: TestClient) -> None:
    _make_session(client, "hf-c")
    state = main_module._RUNTIME.store.find("hf-c")
    assert state is not None
    state.status = "human_serving"
    r = client.post("/api/v1/sessions/hf-c/handoff-request")
    assert r.status_code == 200
    assert r.json()["status"] == "human_serving"


def test_handoff_request_closed_session_409(client: TestClient) -> None:
    _make_session(client, "hf-d")
    state = main_module._RUNTIME.store.find("hf-d")
    assert state is not None
    state.status = "closed"
    r = client.post("/api/v1/sessions/hf-d/handoff-request")
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "SESSION_CLOSED"
