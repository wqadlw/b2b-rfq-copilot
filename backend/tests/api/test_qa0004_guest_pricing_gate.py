"""QA-0004 回归：游客价格问句的成本红线。

修复缺陷：main 游客门与 graph 各持一份手抄 marker 镜像——pricing 能力开启时，
游客含价格词的消息穿透到 LLM understanding（烧 token + 可能编造报价）。
修复后两者共用 core.policies.refusal.detect_capability_refusal 单一确定性决策：
- pricing 关：graph 确定性模板拒绝（0 token）
- pricing 开：游客门外即 login_required（0 token，绝不触达 LLM）
"""

import json
import re
from collections.abc import AsyncIterator, Iterator

import pytest
from fastapi.testclient import TestClient

import rfq_copilot.app.main as main_module
from rfq_copilot.app.runtime import Runtime, build_runtime
from rfq_copilot.config.settings import get_settings
from rfq_copilot.core.policies.refusal import derive_refusal_policies, detect_capability_refusal

MSG = "这个多少钱？"  # 含价格词（多少钱），无产品词 → 旧镜像下 B 场景穿透


class RecordingLLM:
    """实现 LLMClient 协议；只记录是否被调用（被调用=烧了 token）。"""

    def __init__(self) -> None:
        self.call_count = 0

    async def complete_json(self, system: str, user: str) -> dict[str, object]:
        self.call_count += 1
        return {"intent": "price_inquiry", "route": "answer_flow", "confidence": 0.7, "needs_clarification": True}

    async def stream_text(self, system: str, user: str) -> AsyncIterator[str]:
        self.call_count += 1
        yield "这款型号 报价大约 ￥8,000 元。"


@pytest.fixture()
def guest_runtime(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Runtime, RecordingLLM]]:
    get_settings.cache_clear()
    monkeypatch.setenv("INTERNAL_API_TOKEN", "test-qa0004")
    monkeypatch.setenv("GUEST_TIER_ENABLED", "true")
    llm = RecordingLLM()
    rt = build_runtime(llm=llm)
    main_module._RUNTIME = rt
    yield rt, llm
    get_settings.cache_clear()


def _turn(client: TestClient, session: str, message: str) -> tuple[str, list[str]]:
    raw = b""
    with client.stream("POST", "/api/v1/chat/stream", json={"session_id": session, "message": message}) as r:
        assert r.status_code == 200
        raw = b"".join(r.iter_bytes())
    text = raw.decode("utf-8")
    events = re.findall(r"event: (\w+)", text)
    answer = ""
    for m in re.finditer(r"event: (\w+)\ndata: (.*)", text):
        if m.group(1) == "answer_delta":
            answer += str(json.loads(m.group(2)).get("delta", ""))
    return answer, events


@pytest.mark.parametrize(
    ("message", "expected_intent"),
    [
        ("这个多少钱？", "price_inquiry"),
        ("能打个折扣吗", "discount_inquiry"),
        ("货期多久", "lead_time_inquiry"),
        ("有现货吗", "stock_inquiry"),
        ("帮我推荐无油真空泵", None),  # 无能力触发词 → 不命中拒绝
    ],
)
def test_detect_capability_refusal_single_decision(message: str, expected_intent: str | None) -> None:
    """单一决策函数：策略派生自 manifest（demo 默认 pricing/lead_time/stock 关）。"""
    from pathlib import Path

    from rfq_copilot.core.manifest import load_manifest

    adapter_dir = Path(__file__).resolve().parents[2] / "src" / "rfq_copilot" / "adapters" / "demo"
    policies = derive_refusal_policies(load_manifest(adapter_dir))
    hit = detect_capability_refusal(message, policies)
    if expected_intent is None:
        assert hit is None
    else:
        assert hit is not None and hit.intent == expected_intent
        assert hit.reason.endswith("_disabled")
        # 空策略（全部能力开启）→ 永不命中：这正是游客门必须拦在 LLM 之前的场景
        assert detect_capability_refusal(message, {}) is None


def test_guest_pricing_disabled_zero_token(guest_runtime: tuple[Runtime, RecordingLLM]) -> None:
    """A：pricing 关（demo 默认）——游客价格问句走确定性拒绝，0 LLM 调用。"""
    rt, llm = guest_runtime
    with TestClient(main_module.app) as client:
        _, events = _turn(client, "qa0004-a", MSG)
    assert llm.call_count == 0
    short = detect_capability_refusal(MSG, rt.deps.refusal_policies)
    assert short is not None and short.reason == "pricing_disabled"


def test_guest_pricing_enabled_login_required(guest_runtime: tuple[Runtime, RecordingLLM]) -> None:
    """B：pricing 开（修复前 llm_calls>=1 穿透）——游客门外 login_required，0 LLM 调用。"""
    rt, llm = guest_runtime
    manifest = rt.manifest
    try:
        manifest.capabilities.pricing.enabled = True
    except Exception:  # noqa: BLE001 — pydantic frozen 兜底
        object.__setattr__(manifest.capabilities.pricing, "enabled", True)
    rt.deps.refusal_policies = derive_refusal_policies(manifest)
    assert detect_capability_refusal(MSG, rt.deps.refusal_policies) is None  # 能力开→无拒绝策略

    with TestClient(main_module.app) as client:
        answer, events = _turn(client, "qa0004-b", MSG)
    assert llm.call_count == 0  # 修复核心断言：绝不触达 LLM
    assert "login_required" in events
    assert "￥" not in answer  # 无编造报价
