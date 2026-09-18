"""站点知识导出 CLI 测试：dry-run 统计 + 输出目录安全拒绝。"""

import importlib.util
import json
import sys
from pathlib import Path as _Path

import pytest

_SCRIPT = _Path(__file__).resolve().parents[3] / "scripts" / "vacuum_b2b_export.py"
_spec = importlib.util.spec_from_file_location("vacuum_b2b_export", _SCRIPT)
assert _spec is not None and _spec.loader is not None
vacuum_b2b_export = importlib.util.module_from_spec(_spec)
sys.modules["vacuum_b2b_export"] = vacuum_b2b_export
_spec.loader.exec_module(vacuum_b2b_export)
from pathlib import Path  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "site"


def test_dry_run_reports_stats(capsys: pytest.CaptureFixture[str]) -> None:
    code = vacuum_b2b_export.main(["--source-dir", str(FIXTURES), "--dry-run"])
    assert code == 0
    out = capsys.readouterr().out
    assert "documents:" in out
    assert "by_trust_level" in out
    assert "filtered_by_reason" in out
    assert "merchant 样本" in out
    assert "工艺库路径样本" in out


def test_json_export(tmp_path: Path) -> None:
    json_path = tmp_path / "out.json"
    code = vacuum_b2b_export.main(["--source-dir", str(FIXTURES), "--dry-run", "--json", str(json_path)])
    assert code == 0
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["stats"]["documents"] == len(payload["documents"])
    assert all("trust_level" in doc for doc in payload["documents"])


def test_output_dir_rejects_backend_knowledge() -> None:
    with pytest.raises(SystemExit, match="backend/knowledge"):
        vacuum_b2b_export.main(
            [
                "--source-dir",
                str(FIXTURES),
                "--dry-run",
                "--output-dir",
                str(Path(__file__).resolve().parents[3] / "backend" / "knowledge" / "out"),
            ]
        )


def test_output_dir_rejects_arbitrary_repo_path(tmp_path: Path) -> None:
    bad = Path(__file__).resolve().parents[3] / "docs" / "out"
    with pytest.raises(SystemExit, match="拒绝"):
        vacuum_b2b_export.main(["--source-dir", str(FIXTURES), "--dry-run", "--output-dir", str(bad)])


def test_output_dir_allows_private_and_writes_filtered_log(tmp_path: Path) -> None:
    target = tmp_path / "rag_data"
    code = vacuum_b2b_export.main(["--source-dir", str(FIXTURES), "--output-dir", str(target)])
    assert code == 0
    payload = json.loads((target / "knowledge.json").read_text(encoding="utf-8"))
    assert payload["stats"]["documents"] > 0
    log_text = (target / "etl_filtered.log").read_text(encoding="utf-8")
    assert "STATUS_NOT_ON" in log_text
    assert "PRICE_ANOMALY" in log_text
