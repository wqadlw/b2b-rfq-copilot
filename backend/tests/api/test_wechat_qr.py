"""CS-1.5: WeChat QR passthrough tests (manifest -> ui-config / wechat_guidance / handoff)."""

import json
import re
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

import rfq_copilot.app.main as main_module
from rfq_copilot.app.runtime import build_runtime
from rfq_copilot.config.settings import get_settings
from rfq_copilot.core.agent.llm import FakeLLM


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    get_settings.cache_clear()
    llm = FakeLLM(
        [
            {
                "intent": "human_request",
                "route": "handoff_flow",
                "confidence": 0.95,
                "entities": {},
                "needs_human": True,
                "human_reason": "user_request",
            }
        ]
    )
    main_module._RUNTIME = build_runtime(llm=llm)
    with TestClient(main_module.app) as c:
        yield c
    get_settings.cache_clear()


def _collect(client: TestClient, session_id: str, message: str) -> tuple[str, list[str], list[dict]]:
    raw = b""
    with client.stream(
        "POST",
        "/api/v1/chat/stream",
        json={"session_id": session_id, "message": message},
    ) as r:
        assert r.status_code == 200
        raw = b"".join(r.iter_bytes())
    text = raw.decode("utf-8")
    answer = ""
    for event_match in re.finditer(r"event: (\w+)\ndata: (.*)", text):
        if event_match.group(1) == "answer_delta":
            answer += str(json.loads(event_match.group(2)).get("delta", ""))
    events = re.findall(r"event: (\w+)", text)
    qr_payloads = [json.loads(m) for m in re.findall(r"data: (.*)", text) if "qrcode_url" in m]
    return answer, events, qr_payloads


def test_ui_config_exposes_wechat_config(client: TestClient) -> None:
    r = client.get("/api/v1/ui-config")
    assert r.status_code == 200
    wechat = r.json()["chat"]["wechat"]
    assert wechat["qrcode_url"] == "/demo-assets/demo-wechat-qr.svg"
    assert wechat["contact_name"] == "demo 工程师"
    assert wechat["guidance_text"]


def test_handoff_emits_wechat_guidance_with_qrcode(client: TestClient) -> None:
    answer, events, qr_payloads = _collect(client, "cs15-1", "我要投诉")
    assert "handoff" in events
    assert "wechat_guidance" in events
    assert qr_payloads, "wechat_guidance must carry qrcode_url"
    payload = qr_payloads[0]
    assert payload["qrcode_url"] == "/demo-assets/demo-wechat-qr.svg"
    assert payload["contact_name"] == "demo 工程师"
    # 中立兜底：坐席链路同时保留（有坐席走平台，无坐席走微信）


def test_handoff_answer_mentions_qr(client: TestClient) -> None:
    answer, _, _ = _collect(client, "cs15-2", "转人工")
    assert "二维码" in answer
    assert "demo 工程师" in answer
