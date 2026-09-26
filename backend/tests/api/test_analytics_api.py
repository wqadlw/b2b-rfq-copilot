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


# ---- 逐日用量序列（用量屏数据源）----


def test_usage_requires_token(client: TestClient) -> None:
    r = client.get("/api/v1/analytics/usage")
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "UPSTREAM_AUTH"


def test_usage_invalid_days_is_400(client: TestClient) -> None:
    for bad in (0, 31, -5):
        r = client.get("/api/v1/analytics/usage", params={"days": bad}, headers={"X-Internal-Token": TOKEN})
        assert r.status_code == 400
        assert r.json()["detail"]["code"] == "INVALID_DAYS"


def test_usage_series_after_chat(client: TestClient) -> None:
    r = client.post("/api/v1/chat/stream", json={"session_id": "sess-u1", "message": "有哪些真空泵？"})
    assert r.status_code == 200

    r = client.get("/api/v1/analytics/usage", params={"days": 7}, headers={"X-Internal-Token": TOKEN})
    assert r.status_code == 200
    body = r.json()
    assert body["days"] == 7
    assert len(body["series"]) == 7  # 窗口逐日连续，零流量日出 0

    today = body["series"][-1]
    assert today["turns"] == 1
    assert today["sessions"] == 1
    assert today["llm_calls"] >= 1  # FakeLLM counter delta
    assert today["errors"] == 0
    assert body["oldest_record_age_days"] is not None

    # 除今天外窗口内应为空桶（测试时钟内只发生一轮对话）
    earlier = [d for d in body["series"][:-1]]
    assert all(d["turns"] == 0 for d in earlier)


def test_usage_series_default_days(client: TestClient) -> None:
    r = client.get("/api/v1/analytics/usage", headers={"X-Internal-Token": TOKEN})
    assert r.status_code == 200
    assert r.json()["days"] == 14


def test_metrics_registry_usage_series_buckets() -> None:
    import datetime as dt
    import time

    reg = MetricsRegistry()
    now = time.time()
    # 今天 2 轮（含 1 错误）+ 昨日 1 轮；边界用当日 00:05 前后构造跨日
    reg.record_turn(session_id="s1", question="问1", route="a", llm_calls=2, prompt_tokens=100, completion_tokens=50, errored=True, ts=now - 60)
    reg.record_turn(session_id="s2", question="问2", route="b", llm_calls=1, prompt_tokens=30, completion_tokens=20, ts=now - 120)
    reg.record_turn(session_id="s3", question="问3", route="a", llm_calls=1, prompt_tokens=10, completion_tokens=5, ts=now - 1.5 * 86400)

    out = reg.usage_series(3)
    assert out["days"] == 3 and len(out["series"]) == 3
    today = out["series"][-1]
    assert today["turns"] == 2 and today["sessions"] == 2
    assert today["llm_calls"] == 3 and today["errors"] == 1
    assert today["prompt_tokens"] == 130 and today["completion_tokens"] == 70
    # 窗口三日 tokens 总量与写入一致（分桶不丢）
    assert sum(d["prompt_tokens"] for d in out["series"]) == 140

    # 日期字符串可被 date 解析且严格升序
    dates = [dt.date.fromisoformat(d["date"]) for d in out["series"]]
    assert dates == sorted(dates) and (dates[-1] - dates[0]).days == 2
