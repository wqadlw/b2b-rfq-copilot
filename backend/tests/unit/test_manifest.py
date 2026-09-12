"""Manifest loader V1~V7 validation tests."""

from pathlib import Path

import pytest

from conftest import ADAPTER_DIR
from rfq_copilot.core.manifest import load_manifest
from rfq_copilot.ports.errors import ConfigError

VALID = (ADAPTER_DIR / "manifest.yaml").read_text(encoding="utf-8")


def _write(tmp_path: Path, text: str, adapter: str = "demo") -> Path:
    d = tmp_path / adapter
    d.mkdir()
    (d / "manifest.yaml").write_text(text, encoding="utf-8")
    return d


def test_load_demo_manifest_ok() -> None:
    manifest = load_manifest(ADAPTER_DIR)
    assert manifest.adapter == "demo"
    assert manifest.disabled_capabilities() == ["pricing", "lead_time", "stock"]
    assert manifest.ports.inquiry_sink.guest_allowed is True
    assert manifest.ports.inquiry_sink.required_fields == ["contact_name", "contact_phone"]


def test_v7_missing_capability_key(tmp_path: Path) -> None:
    bad = VALID.replace("  stock:     { enabled: false }\n", "")
    with pytest.raises(ConfigError, match="V7"):
        load_manifest(_write(tmp_path, bad))


def test_v1_adapter_dir_mismatch(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="V1"):
        load_manifest(_write(tmp_path, VALID, adapter="other"))


def test_v3_disjoint_fields(tmp_path: Path) -> None:
    bad = VALID.replace(
        "    optional_fields: [company, email, quantity, region]",
        "    optional_fields: [company, contact_name]",
    )
    with pytest.raises(ConfigError, match="V3"):
        load_manifest(_write(tmp_path, bad))


def test_v4_guest_action_conflict(tmp_path: Path) -> None:
    bad = VALID.replace(
        "    guest_allowed: true\n", "    guest_allowed: true\n    guest_action: require_registration\n"
    )
    with pytest.raises(ConfigError, match="V4"):
        load_manifest(_write(tmp_path, bad))


def test_v6_catalog_needs_search(tmp_path: Path) -> None:
    bad = VALID.replace("    features: [search, detail]", "    features: [detail]")
    with pytest.raises(ConfigError, match="V6"):
        load_manifest(_write(tmp_path, bad))
