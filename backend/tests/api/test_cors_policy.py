"""QA-0001 回归：CORS 永不通配+凭证——恶意源拒绝、本机开发源放行、白名单源放行。

修复缺陷：allow_origin_regex=r"https?://.*" + allow_credentials=True，
任意互联网页面可携凭证跨域调用引擎（叠加 E1 票据的盗用面）。
策略见 docs/adr/0005-cors-allowlist.md。
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

import rfq_copilot.app.main as main_module
from rfq_copilot.app.runtime import build_runtime
from rfq_copilot.config.settings import get_settings


@pytest.fixture()
def api_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    get_settings.cache_clear()
    monkeypatch.setenv("INTERNAL_API_TOKEN", "test-cors")
    main_module._RUNTIME = build_runtime()
    with TestClient(main_module.app) as c:
        yield c
    get_settings.cache_clear()


@pytest.mark.parametrize(
    ("origin", "allowed"),
    [
        ("https://evil.example.com", False),  # 任意互联网源：拒绝（修复前放行）
        ("http://evil.example.com", False),
        ("https://your-domain.com", False),  # 未配置白名单时生产域也拒绝（默认拒绝）
        ("http://localhost:5173", True),  # 本机开发源恒放行
        ("http://127.0.0.1:8001", True),
    ],
)
def test_cors_default_deny(api_client: TestClient, origin: str, allowed: bool) -> None:
    r = api_client.get("/api/v1/ui-config", headers={"Origin": origin})
    aco = r.headers.get("access-control-allow-origin")
    if allowed:
        assert aco == origin
    else:
        assert aco is None


def test_cors_allowlist_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """配置 CORS_ALLOW_ORIGINS 后，白名单源放行、其余生产域仍拒绝。

    注意：middleware 在 create_app() 时读取配置，故需新建 app 实例验证。
    """
    get_settings.cache_clear()
    monkeypatch.setenv("INTERNAL_API_TOKEN", "test-cors")
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "https://your-domain.com,https://www.your-domain.com")
    main_module._RUNTIME = build_runtime()
    fresh_app = main_module.create_app()
    with TestClient(fresh_app) as client:
        ok = client.get("/api/v1/ui-config", headers={"Origin": "https://www.your-domain.com"})
        bad = client.get("/api/v1/ui-config", headers={"Origin": "https://evil.example.com"})
    assert ok.headers.get("access-control-allow-origin") == "https://www.your-domain.com"
    assert bad.headers.get("access-control-allow-origin") is None
    get_settings.cache_clear()
