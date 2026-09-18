"""QA-0008 回归：预算/限流不再 import 期固化——随 Settings 惰性构造、可显式刷新。

修复前：`_BUDGET = DailyTokenBudget(get_settings().llm_daily_token_budget)` 在模块导入时
求值，改 env 后永不生效（进程级"配置化石"）。修复后 _get_budget() 惰性跟随当前 Settings，
reset_rate_limit_state() 提供显式刷新点。
"""

import pytest

import rfq_copilot.app.main as main_module
from rfq_copilot.config.settings import get_settings


@pytest.fixture(autouse=True)
def _restore_state() -> None:
    """测试后复位模块态，避免污染其它用例。"""
    main_module.reset_rate_limit_state()


def test_budget_follows_settings_after_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    main_module.reset_rate_limit_state()
    first = main_module._get_budget()
    baseline = first.remaining("qa-budget-user")

    monkeypatch.setenv("LLM_DAILY_TOKEN_BUDGET", "123456")
    get_settings.cache_clear()
    main_module.reset_rate_limit_state()

    refreshed = main_module._get_budget()
    assert refreshed is not first  # 惰性重建，非复用旧单例
    assert refreshed.remaining("qa-budget-user") == 123456
    assert baseline != 123456  # 前值确与环境默认不同，断言才有效力


def test_limiter_lazy_singleton_reuses_instance() -> None:
    main_module.reset_rate_limit_state()
    limiter1 = main_module._get_limiter()
    limiter2 = main_module._get_limiter()
    assert limiter1 is limiter2  # 同一配置窗口内复用，不逐请求重建

    main_module.reset_rate_limit_state()
    assert main_module._get_limiter() is not limiter1
