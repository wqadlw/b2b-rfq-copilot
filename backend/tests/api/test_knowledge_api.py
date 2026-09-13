"""Knowledge CRUD API: X-Internal-Token gate semantics (401) + ingest/remove roundtrip."""

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
    main_module._RUNTIME = build_runtime(llm=FakeLLM([]))
    with TestClient(main_module.app) as c:
        yield c
    get_settings.cache_clear()


def test_post_without_token_is_401(client: TestClient) -> None:
    r = client.post("/api/v1/knowledge", json={"doc_id": "t", "title": "t", "content": "c"})
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "UPSTREAM_AUTH"


def test_post_with_wrong_token_is_401(client: TestClient) -> None:
    r = client.post(
        "/api/v1/knowledge",
        json={"doc_id": "t", "title": "t", "content": "c"},
        headers={"X-Internal-Token": "nope"},
    )
    assert r.status_code == 401


def test_delete_without_token_is_401(client: TestClient) -> None:
    r = client.delete("/api/v1/knowledge/some-doc")
    assert r.status_code == 401


def test_post_missing_fields_is_400(client: TestClient) -> None:
    r = client.post("/api/v1/knowledge", json={"doc_id": "t"}, headers={"X-Internal-Token": TOKEN})
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "MISSING_FIELDS"


def test_add_and_remove_roundtrip(client: TestClient) -> None:
    headers = {"X-Internal-Token": TOKEN}
    r = client.post(
        "/api/v1/knowledge",
        json={
            "doc_id": "test-kb-001",
            "title": "测试文档",
            "content": "无油真空泵适合实验室场景，极限真空度可达 0.1 Pa。",
            "trust_level": "platform",
        },
        headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ingested" and body["chunks"] >= 1

    r = client.delete("/api/v1/knowledge/test-kb-001", headers=headers)
    assert r.status_code == 200
    assert r.json()["chunks_removed"] >= 1
