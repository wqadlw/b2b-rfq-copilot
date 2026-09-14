"""Tiered access: guest gate + daily token budget (CS-tier tests)."""

import json
import re
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

import rfq_copilot.app.main as main_module
from rfq_copilot.app.limiter import DailyTokenBudget
from rfq_copilot.app.runtime import build_runtime
from rfq_copilot.config.settings import get_settings
from rfq_copilot.core.agent.llm import FakeLLM


@pytest.fixture()
def guest_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """Guest tier ON: guests limited to 0-token paths."""
    get_settings.cache_clear()
    monkeypatch.setenv("INTERNAL_API_TOKEN", "test-tier")
    monkeypatch.setenv("GUEST_TIER_ENABLED", "true")
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
    main_module._BUDGET = DailyTokenBudget(20000)
    with TestClient(main_module.app) as c:
        yield c
    get_settings.cache_clear()


@pytest.fixture()
def open_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """Guest tier OFF (legacy open chat, existing tests' baseline)."""
    get_settings.cache_clear()
    monkeypatch.setenv("INTERNAL_API_TOKEN", "test-tier")
    monkeypatch.delenv("GUEST_TIER_ENABLED", raising=False)
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
    main_module._BUDGET = DailyTokenBudget(20000)
    with TestClient(main_module.app) as c:
        yield c
    get_settings.cache_clear()


def _events(text: str) -> list[str]:
    return re.findall(r"event: (\w+)", text)


def _answer(text: str) -> str:
    answer = ""
    for m in re.finditer(r"event: (\w+)\ndata: (.*)", text):
        if m.group(1) == "answer_delta":
            answer += str(json.loads(m.group(2)).get("delta", ""))
    return answer


def test_guest_llm_turn_blocked_with_login_required(guest_client: TestClient) -> None:
    raw = b""
    with guest_client.stream(
        "POST", "/api/v1/chat/stream", json={"session_id": "tier-1", "message": "推荐几款真空泵"}
    ) as r:
        assert r.status_code == 200
        raw = b"".join(r.iter_bytes())
    text = raw.decode("utf-8")
    assert "login_required" in _events(text)
    assert "登录" in _answer(text)
    assert json.loads(re.search(r"event: done\ndata: (.*)", text).group(1))["finish_reason"] == "login_required"  # type: ignore[union-attr]


def test_guest_zero_token_paths_pass(guest_client: TestClient) -> None:
    # FAQ hit (keyword): 0 token, no login needed
    raw = b""
    with guest_client.stream(
        "POST", "/api/v1/chat/stream", json={"session_id": "tier-2", "message": "怎么注册账号"}
    ) as r:
        raw = b"".join(r.iter_bytes())
    text = raw.decode("utf-8")
    assert "login_required" not in _events(text)
    # deterministic refusal (price): template-only, 0 token
    raw2 = b""
    with guest_client.stream(
        "POST", "/api/v1/chat/stream", json={"session_id": "tier-3", "message": "这个多少钱"}
    ) as r:
        raw2 = b"".join(r.iter_bytes())
    assert "login_required" not in _events(raw2.decode("utf-8"))


def test_logged_in_user_bypasses_guest_gate(guest_client: TestClient) -> None:
    raw = b""
    with guest_client.stream(
        "POST",
        "/api/v1/chat/stream",
        json={"session_id": "tier-4", "message": "推荐几款真空泵", "user_ref": "user-9"},
    ) as r:
        assert r.status_code == 200
        raw = b"".join(r.iter_bytes())
    assert "login_required" not in _events(raw.decode("utf-8"))


def test_open_client_keeps_legacy_behavior(open_client: TestClient) -> None:
    raw = b""
    with open_client.stream("POST", "/api/v1/chat/stream", json={"session_id": "tier-5", "message": "demo-p-001"}) as r:
        raw = b"".join(r.iter_bytes())
    assert "login_required" not in _events(raw.decode("utf-8"))


def test_token_budget_exhausted_guides_wechat(monkeypatch: pytest.MonkeyPatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("INTERNAL_API_TOKEN", "test-tier")
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
    main_module._BUDGET = DailyTokenBudget(10)
    main_module._BUDGET.consume("user-broke", 10)  # exhaust
    with TestClient(main_module.app) as client:
        raw = b""
        with client.stream(
            "POST",
            "/api/v1/chat/stream",
            json={"session_id": "tier-6", "message": "再问一个", "user_ref": "user-broke"},
        ) as r:
            assert r.status_code == 200
            raw = b"".join(r.iter_bytes())
    text = raw.decode("utf-8")
    assert "token_budget_exceeded" in _events(text)
    assert "额度已用完" in _answer(text)
    assert "wechat_guidance" in _events(text)  # 引导加微信
    assert json.loads(re.search(r"event: done\ndata: (.*)", text).group(1))["finish_reason"] == "token_budget"  # type: ignore[union-attr]
    get_settings.cache_clear()
