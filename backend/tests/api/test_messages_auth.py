"""Messages endpoint: internal-token gate (data level equals /replay)."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

import rfq_copilot.app.main as main_module
from rfq_copilot.app.runtime import build_runtime
from rfq_copilot.config.settings import get_settings
from rfq_copilot.core.agent.llm import FakeLLM

TOKEN = "test-internal-123"


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("INTERNAL_API_TOKEN", TOKEN)
    get_settings.cache_clear()
    llm = FakeLLM([{"intent": "product_inquiry", "route": "product_flow", "confidence": 0.9, "entities": {}}])
    main_module._RUNTIME = build_runtime(llm=llm)
    with TestClient(main_module.app) as c:
        yield c
    get_settings.cache_clear()


def test_messages_requires_token(client: TestClient) -> None:
    r = client.get("/api/v1/sessions/sess-m1/messages")
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "UPSTREAM_AUTH"


def test_messages_wrong_token_401(client: TestClient) -> None:
    r = client.get("/api/v1/sessions/sess-m1/messages", headers={"X-Internal-Token": "wrong"})
    assert r.status_code == 401


def test_messages_with_token_returns_history(client: TestClient) -> None:
    r = client.post(
        "/api/v1/chat/stream",
        json={"session_id": "sess-m2", "message": "有哪些真空泵？"},
    )
    assert r.status_code == 200
    r2 = client.get("/api/v1/sessions/sess-m2/messages", headers={"X-Internal-Token": TOKEN})
    assert r2.status_code == 200
    body = r2.json()
    assert body["has_more"] is False
    roles = [m["role"] for m in body["messages"]]
    assert "user" in roles and "assistant" in roles
