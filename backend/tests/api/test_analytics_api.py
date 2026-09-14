"""Analytics summary API: internal-token gate + per-turn metrics recorded by the SSE mapper."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

import rfq_copilot.app.main as main_module
from rfq_copilot.app.metrics import MetricsRegistry
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


def test_summary_requires_token(client: TestClient) -> None:
    r = client.get("/api/v1/analytics/summary")
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "UPSTREAM_AUTH"


def test_summary_invalid_period_is_400(client: TestClient) -> None:
    r = client.get("/api/v1/analytics/summary", params={"period": "forever"}, headers={"X-Internal-Token": TOKEN})
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "INVALID_PERIOD"


def test_summary_after_chat(client: TestClient) -> None:
    r = client.post("/api/v1/chat/stream", json={"session_id": "sess-a1", "message": "有哪些真空泵？"})
    assert r.status_code == 200

    r = client.get("/api/v1/analytics/summary", params={"period": "today"}, headers={"X-Internal-Token": TOKEN})
    assert r.status_code == 200
    body = r.json()
    assert body["period"] == "today"
    assert body["sessions"] == 1
    assert body["turns"] == 1
    assert body["errors"] == 0
    assert body["llm_calls"] >= 1  # FakeLLM counter delta
    assert body["avg_latency_ms"] >= 0
    assert body["top_questions"] and body["top_questions"][0]["question"] == "有哪些真空泵？"
    assert body["top_questions"][0]["count"] == 1


def test_metrics_registry_period_filter() -> None:
    reg = MetricsRegistry()
    import time

    now = time.time()
    reg.record_turn(session_id="s1", question="问", route="knowledge_flow", ts=now - 100)
    reg.record_turn(session_id="s2", question="问", route="product_flow", ts=now - 20 * 86400)
    out = reg.summary("today")
    assert out["turns"] == 1 and out["sessions"] == 1
    out = reg.summary("month")
    assert out["turns"] == 2 and out["sessions"] == 2
    assert out["faq_hit_rate"] == 0.0
