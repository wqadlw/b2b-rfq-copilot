"""Integration: 适配器选择（ADAPTER 环境变量）与两条数据路径不混用。"""

from collections.abc import Iterator

import pytest

from rfq_copilot.adapters.vacuum_b2b_sample.adapter import VacuumSampleProductCatalog
from rfq_copilot.adapters.zhaozhenkong_offline.zzk_catalog import ZzkProductCatalog
from rfq_copilot.app.runtime import build_runtime
from rfq_copilot.config.settings import get_settings

SITE_ENV = {
    "INTERNAL_API_BASE_URL": "https://internal-api.example.com",
    "INTERNAL_API_TOKEN": "unit-test-token",
}


@pytest.fixture()
def clean_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _set(monkeypatch: pytest.MonkeyPatch, **env: str) -> None:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()


def test_default_adapter_is_demo(monkeypatch: pytest.MonkeyPatch, clean_settings: None) -> None:
    _set(monkeypatch, ADAPTER="", KNOWLEDGE_DATA_DIR="")
    runtime = build_runtime()
    assert runtime.manifest.adapter == "demo"


def test_adapter_env_selects_real_channel(monkeypatch: pytest.MonkeyPatch, clean_settings: None) -> None:
    """ADAPTER=vacuum_b2b_sample：端口来自站点内部 API。"""
    _set(monkeypatch, ADAPTER="vacuum_b2b_sample", **SITE_ENV)
    runtime = build_runtime()
    assert runtime.manifest.adapter == "vacuum_b2b_sample"
    assert isinstance(runtime.deps.catalog, VacuumSampleProductCatalog)


def test_offline_override_applies_to_demo_only(monkeypatch: pytest.MonkeyPatch, clean_settings: None, tmp_path) -> None:
    """两条数据路径不得混用：真通道模式不得被离线导出覆盖。"""
    data_dir = tmp_path / "zzk"
    data_dir.mkdir()

    _set(monkeypatch, ADAPTER="demo", KNOWLEDGE_DATA_DIR=str(data_dir))
    demo_runtime = build_runtime()
    assert isinstance(demo_runtime.deps.catalog, ZzkProductCatalog)

    _set(monkeypatch, ADAPTER="vacuum_b2b_sample", KNOWLEDGE_DATA_DIR=str(data_dir), **SITE_ENV)
    real_runtime = build_runtime()
    assert isinstance(real_runtime.deps.catalog, VacuumSampleProductCatalog)


def test_explicit_argument_wins_over_env(monkeypatch: pytest.MonkeyPatch, clean_settings: None) -> None:
    _set(monkeypatch, ADAPTER="vacuum_b2b_sample", **SITE_ENV)
    runtime = build_runtime(adapter="demo")
    assert runtime.manifest.adapter == "demo"
