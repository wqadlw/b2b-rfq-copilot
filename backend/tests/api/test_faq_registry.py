"""CS-faq: FaqRegistry CRUD + guest suggestions tests."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

import rfq_copilot.app.main as main_module
from rfq_copilot.app.runtime import build_runtime
from rfq_copilot.config.settings import get_settings
from rfq_copilot.core.agent.llm import FakeLLM

TOKEN = "***"


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


def test_list_faq_requires_token(client: TestClient) -> None:
    assert client.get("/api/v1/faq").status_code == 401


def test_list_faq_returns_default_entries(client: TestClient) -> None:
    r = client.get("/api/v1/faq", headers=_auth())
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 12  # 扩容后默认库
    assert all("keywords" in item and "answer" in item for item in body["items"])


def test_add_and_runtime_effective(client: TestClient) -> None:
    r = client.post(
        "/api/v1/faq",
        json={"keywords": ["真空泵怎么选型"], "answer": "请参考选型指南：先定真空度，再定抽速。", "category": "选型"},
        headers=_auth(),
    )
    assert r.status_code == 200
    # 立即生效：匹配新条目（registry 与 matcher 同库）
    assert client.get("/api/v1/faq", headers=_auth()).json()["total"] >= 13


def test_add_missing_fields_400(client: TestClient) -> None:
    r = client.post("/api/v1/faq", json={"keywords": ["x"]}, headers=_auth())
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "MISSING_FIELDS"


def test_delete_faq(client: TestClient) -> None:
    before = client.get("/api/v1/faq", headers=_auth()).json()["total"]
    r = client.delete("/api/v1/faq/0", headers=_auth())
    assert r.status_code == 200
    after = client.get("/api/v1/faq", headers=_auth()).json()["total"]
    assert after == before - 1
    assert client.delete("/api/v1/faq/99999", headers=_auth()).status_code == 404


def test_suggest_public_endpoint(client: TestClient) -> None:
    r = client.get("/api/v1/faq/suggest", params={"q": "真空泵选型"})
    assert r.status_code == 200
    items = r.json()["items"]
    assert isinstance(items, list) and len(items) <= 3
    assert all("question" in item for item in items)
