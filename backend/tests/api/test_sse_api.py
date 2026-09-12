"""API tests: SSE event order, ui-config capabilities, health."""

import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

import rfq_copilot.app.main as main_module
from rfq_copilot.app.runtime import build_runtime
from rfq_copilot.core.agent.llm import FakeLLM


@pytest.fixture()
def client() -> Iterator[TestClient]:
    llm = FakeLLM([{"intent": "product_inquiry", "route": "product_flow", "confidence": 0.9, "entities": {}}])
    main_module._RUNTIME = build_runtime(llm=llm)  # inject fake LLM: no network in tests
    with TestClient(main_module.app) as c:
        yield c


def _events(body: str) -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    for frame in body.split("\n\n"):
        if not frame.strip():
            continue
        name = data = None
        for line in frame.splitlines():
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        assert name is not None and data is not None
        out.append((name, data))
    return out


def test_health(client: TestClient) -> None:
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["adapter"] == "demo"


def test_ui_config_capabilities(client: TestClient) -> None:
    caps = client.get("/api/v1/ui-config").json()["capabilities"]
    assert caps["pricing"] is False and caps["lead_time"] is False and caps["stock"] is False
    assert caps["product_catalog"] is True and caps["inquiry"] is True


def test_chat_stream_event_order(client: TestClient) -> None:
    r = client.post("/api/v1/chat/stream", json={"session_id": "sess-x", "message": "有哪些真空泵？"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    events = _events(r.text)
    names = [n for n, _ in events]
    assert names[0] == "status" and names[-1] == "done"
    assert "answer_delta" in names
    done = dict(events)["done"]
    assert done["finish_reason"] == "answered"
