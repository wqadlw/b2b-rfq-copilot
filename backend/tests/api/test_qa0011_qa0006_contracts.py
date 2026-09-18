"""QA-0011 + QA-0006 回归：FAQ 落点直返 + SSE 事件三方合同（后端==实发==前端）。

- QA-0011：faq_answer 路由此前在 _respond_node 无分支，落 else 被澄清模板覆盖；
  修复后直返 understand 节点生成的 FAQ 答案（0 token）。
- QA-0006：EventName 冻结集此前 10 名与实发集漂移（card/login_required/
  wechat_guidance/token_budget_exceeded 越集零校验）；修复后补齐 14 名并窄化
  sse_text 签名（mypy strict 在 CI 拦截未登记事件）。
"""

import re
from collections.abc import Iterator
from typing import get_args

import pytest
from fastapi.testclient import TestClient

import rfq_copilot.app.main as main_module
from conftest import make_deps, understanding
from rfq_copilot.app.runtime import build_runtime
from rfq_copilot.config.settings import get_settings
from rfq_copilot.core.policies.faq_matcher import FaqEntry, FaqMatcher
from rfq_copilot.schemas.events import EVENT_NAMES, EventName

# 与 frontend/src/lib/types.ts ChatEventName 一一对应（QA-0006 三方合同）
EXPECTED_EVENT_NAMES = frozenset(
    {
        "status",
        "tool_call",
        "retrieval",
        "answer_delta",
        "citation",
        "card",
        "inquiry_confirm",
        "inquiry_created",
        "handoff",
        "error",
        "wechat_guidance",
        "login_required",
        "token_budget_exceeded",
        "done",
    }
)


def test_event_literal_matches_frontend_contract() -> None:
    """后端 Literal == 实发集合常量 == 前端 ChatEventName（14 名，三方一致）。"""
    assert frozenset(get_args(EventName)) == EXPECTED_EVENT_NAMES
    assert EVENT_NAMES == EXPECTED_EVENT_NAMES


# ===== QA-0011：FAQ 落点 =====


async def test_faq_answer_not_swallowed_by_clarify() -> None:
    """faq_answer 路由直返 FAQ 答案（0 token），不得落 else 澄清模板。"""
    deps, _ = make_deps()
    deps.faq_matcher = FaqMatcher([FaqEntry(keywords=("发票",), answer="电子发票在订单页自助开具。", category="售后")])
    from rfq_copilot.core.agent.graph import build_graph

    graph = build_graph(deps)
    final = await graph.ainvoke({"session_id": "qa0011", "message": "怎么开发票"})
    assert final["route"] == "faq_answer"
    assert final["answer"] == "电子发票在订单页自助开具。"
    assert "请补充更多信息" not in final["answer"]
    assert deps.llm.calls == []  # 0 token：FAQ 层拦截，LLM 未被调用


async def test_faq_miss_still_clarifies() -> None:
    """FAQ 未命中时澄清路径不受影响（防修复过宽）。"""
    deps, _ = make_deps(scripted=[understanding("product_inquiry", "clarify")])
    deps.faq_matcher = FaqMatcher([FaqEntry(keywords=("发票",), answer="电子发票在订单页自助开具。")])
    from rfq_copilot.core.agent.graph import build_graph

    graph = build_graph(deps)
    final = await graph.ainvoke({"session_id": "qa0011-miss", "message": "帮我做一套方案"})
    assert "请补充更多信息" in final["answer"]


# ===== QA-0006：实发事件名 ⊆ 冻结集（端到端） =====


@pytest.fixture()
def guest_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    get_settings.cache_clear()
    monkeypatch.setenv("INTERNAL_API_TOKEN", "test-qa0006")
    monkeypatch.setenv("GUEST_TIER_ENABLED", "true")
    main_module._RUNTIME = build_runtime()
    with TestClient(main_module.app) as c:
        yield c
    get_settings.cache_clear()


def _collect_events(client: TestClient, session: str, message: str) -> list[str]:
    with client.stream("POST", "/api/v1/chat/stream", json={"session_id": session, "message": message}) as r:
        assert r.status_code == 200
        text = b"".join(r.iter_bytes()).decode("utf-8")
    return re.findall(r"event: (\w+)", text)


def test_guest_flow_events_within_frozen_set(guest_client: TestClient) -> None:
    """游客两条流（G1 直搜发 card / 登录墙发 login_required）实发名全部 ⊆ 冻结集。"""
    seen: set[str] = set()
    seen.update(_collect_events(guest_client, "qa0006-a", "有哪些真空泵"))
    seen.update(_collect_events(guest_client, "qa0006-b", "帮我深度选型"))
    assert seen, "expected at least one SSE event"
    assert seen <= set(get_args(EventName)), f"越集事件: {seen - set(get_args(EventName))}"
    # 关键标志位：此前越集的 card / login_required 现已登记在冻结集内
    assert {"card", "login_required"} & seen, "探针标志位：实发流应含 card 或 login_required"
