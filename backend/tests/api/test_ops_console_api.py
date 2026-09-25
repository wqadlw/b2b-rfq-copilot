"""运营只读端点 API 测试（spec 02-engine-read-api-spec：feedback / no-match / knowledge 4 端点）。"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

import rfq_copilot.app.main as main_module
from rfq_copilot.app.runtime import build_runtime
from rfq_copilot.config.settings import get_settings
from rfq_copilot.core.agent.llm import FakeLLM

TOKEN = "test-internal-token-123"
HEADERS = {"X-Internal-Token": TOKEN}


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("INTERNAL_API_TOKEN", TOKEN)
    get_settings.cache_clear()
    main_module._RUNTIME = build_runtime(llm=FakeLLM([]))
    with TestClient(main_module.app) as c:
        yield c
    get_settings.cache_clear()


# ---- feedback（M1/N1：空壳→真存）----


def test_feedback_post_public_returns_id(client: TestClient) -> None:
    r = client.post(
        "/api/v1/feedback",
        json={"session_id": "s1", "message_id": "m1", "feedback": "not_helpful", "comment": "答非所问"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "recorded" and body["id"]


def test_feedback_list_requires_token(client: TestClient) -> None:
    assert client.get("/api/v1/feedback").status_code == 401


def test_feedback_post_then_list_and_stats(client: TestClient) -> None:
    client.post("/api/v1/feedback", json={"session_id": "s1", "message_id": "m1", "feedback": "helpful"})
    client.post("/api/v1/feedback", json={"session_id": "s2", "message_id": "m2", "feedback": "not_helpful"})
    r = client.get("/api/v1/feedback", headers=HEADERS)
    assert r.status_code == 200 and r.json()["total"] == 2
    r = client.get("/api/v1/feedback?feedback=not_helpful", headers=HEADERS)
    assert r.json()["total"] == 1 and r.json()["items"][0]["session_id"] == "s2"
    r = client.get("/api/v1/feedback/stats?period=week", headers=HEADERS)
    stats = r.json()
    assert stats["helpful"] == 1 and stats["not_helpful"] == 1
    assert len(stats["by_day"]) == 1


# ---- no-match（N2）----


def test_no_match_endpoints_require_token(client: TestClient) -> None:
    assert client.get("/api/v1/no-match-events").status_code == 401
    assert client.get("/api/v1/no-match/stats").status_code == 401


def test_no_match_empty_and_invalid_period(client: TestClient) -> None:
    r = client.get("/api/v1/no-match-events", headers=HEADERS)
    assert r.json() == {"items": [], "total": 0}
    r = client.get("/api/v1/no-match/stats?period=year", headers=HEADERS)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "INVALID_PERIOD"


# ---- knowledge 只读四端点（N3）----


def test_knowledge_stats_with_demo_corpus(client: TestClient) -> None:
    r = client.get("/api/v1/knowledge/stats", headers=HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["documents"] > 0 and body["chunks"] >= body["documents"]
    assert body["rag_store"] == "inmemory"
    assert sum(body["by_trust_level"].values()) == body["documents"]


def test_knowledge_docs_list_pagination_and_filter(client: TestClient) -> None:
    r = client.get("/api/v1/knowledge/docs?page=1&page_size=2", headers=HEADERS)
    body = r.json()
    assert body["total"] > 0 and len(body["items"]) == 2
    ids = [d["doc_id"] for d in body["items"]]
    assert ids == sorted(ids)  # 字典序确定性
    r = client.get("/api/v1/knowledge/docs?page=0", headers=HEADERS)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "INVALID_PAGINATION"
    r = client.get("/api/v1/knowledge/docs?trust=platform", headers=HEADERS)
    assert all(d["trust_level"] == "platform" for d in r.json()["items"])


def test_knowledge_docs_detail_and_404(client: TestClient) -> None:
    listed = client.get("/api/v1/knowledge/docs?page_size=1", headers=HEADERS).json()["items"][0]
    r = client.get(f"/api/v1/knowledge/docs/{listed['doc_id']}", headers=HEADERS)
    body = r.json()
    assert body["doc"]["doc_id"] == listed["doc_id"]
    assert len(body["chunks"]) == listed["chunk_count"]
    assert [c["chunk_index"] for c in body["chunks"]] == sorted(c["chunk_index"] for c in body["chunks"])
    r = client.get("/api/v1/knowledge/docs/definitely-not-exist", headers=HEADERS)
    assert r.status_code == 404 and r.json()["detail"]["code"] == "KNOWLEDGE_NOT_FOUND"


def test_knowledge_test_retrieval_shape_and_threshold(client: TestClient) -> None:
    r = client.post(
        "/api/v1/knowledge/test-retrieval",
        json={"query": "无油旋片泵适合什么场景", "top_k": 3},
        headers=HEADERS,
    )
    body = r.json()
    assert body["count"] <= 3 and body["rag_store"] == "inmemory"
    assert body["records"], "demo 语料对该查询应有召回"
    top = body["records"][0]
    assert top["score"] > 0 and "content" in top and "trust_level" in top
    assert set(top["score"] for top in body["records"]) is not None
    assert "predicted_route" in body["routing"]
    # threshold 过滤：阈值抬到比最高分还高 → 0 条
    max_score = max(rec["score"] for rec in body["records"])
    r = client.post(
        "/api/v1/knowledge/test-retrieval",
        json={"query": "无油旋片泵适合什么场景", "top_k": 3, "score_threshold": max_score + 1},
        headers=HEADERS,
    )
    assert r.json()["count"] == 0
    r = client.post("/api/v1/knowledge/test-retrieval", json={"query": "  "}, headers=HEADERS)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "MISSING_FIELDS"


def test_knowledge_hit_stats_empty_then_shape(client: TestClient) -> None:
    r = client.get("/api/v1/knowledge/hit-stats?days=7", headers=HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["days"] == 7 and body["series"] == [] and body["total_by_doc"] == []
    r = client.get("/api/v1/knowledge/hit-stats?days=0", headers=HEADERS)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "INVALID_DAYS"


def test_health_includes_refresh_history(client: TestClient) -> None:
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    # 未启用兜底刷新：refresh_history 为 None（或空）；启用时 last_refresh == 末条
    assert body.get("refresh_history") in (None, []) or body["refresh_history"][-1] == body["knowledge_refresh"]
