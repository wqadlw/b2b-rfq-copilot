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


def test_post_invalid_utf8_is_400(client: TestClient) -> None:
    r = client.post(
        "/api/v1/knowledge",
        content=b'{"doc_id": "t", "title": "\xb2\xb2", "content": "c"}',
        headers={"X-Internal-Token": TOKEN, "Content-Type": "application/json"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "INVALID_JSON"


def test_post_bad_json_syntax_is_400(client: TestClient) -> None:
    r = client.post(
        "/api/v1/knowledge",
        content=b'{"doc_id": "bad \escape"}',
        headers={"X-Internal-Token": TOKEN, "Content-Type": "application/json"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "INVALID_JSON"


def test_post_non_object_body_is_400(client: TestClient) -> None:
    r = client.post("/api/v1/knowledge", json=["not", "an", "object"], headers={"X-Internal-Token": TOKEN})
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "INVALID_JSON"


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


def test_post_accepts_optional_metadata_fields(client: TestClient) -> None:
    """03-api-spec：可选 supplier_id/product_id/params 透传（阶段 3 站点 webhook 依赖）。"""
    headers = {"X-Internal-Token": TOKEN}
    r = client.post(
        "/api/v1/knowledge",
        json={
            "doc_id": "offline-product-webhook-test",
            "title": "Webhook 测试泵",
            "doc_type": "product",
            "trust_level": "merchant",
            "content": "产品名称：Webhook 测试泵\n主要参数：\n抽气速率：250",
            "supplier_id": "sup-1",
            "product_id": "p-1",
            "params": {"抽气速率": "250", "无油": "是"},
        },
        headers=headers,
    )
    assert r.status_code == 200 and r.json()["status"] == "ingested"
    client.delete("/api/v1/knowledge/offline-product-webhook-test", headers=headers)


def test_post_rejects_non_string_params(client: TestClient) -> None:
    r = client.post(
        "/api/v1/knowledge",
        json={"doc_id": "t2", "title": "t", "content": "c", "params": {"抽速": 250}},
        headers={"X-Internal-Token": TOKEN},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "INVALID_PARAMS"
