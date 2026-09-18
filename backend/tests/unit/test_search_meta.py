"""Unit: 站点检索元数据离线复刻（同义词替换/扩展 + 屏蔽词 + 退化）。"""

import json
from pathlib import Path

from rfq_copilot.adapters.vacuum_b2b_offline.search_meta import SearchMeta


def _write(dir_path: Path, payload: object) -> None:
    (dir_path / "search_meta.json").write_text(
        payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )


def test_missing_file_degrades_to_empty(tmp_path: Path) -> None:
    meta = SearchMeta.load(tmp_path)
    assert meta.enabled is False
    assert meta.apply_query_synonym("螺杆泵") == "螺杆泵"
    assert meta.expand_terms("螺杆泵") == set()
    assert meta.is_blocked("赌博") is False


def test_malformed_file_degrades_to_empty(tmp_path: Path) -> None:
    _write(tmp_path, "{not json")
    assert SearchMeta.load(tmp_path).enabled is False
    _write(tmp_path, '"just a string"')
    assert SearchMeta.load(tmp_path).enabled is False


def test_query_synonym_is_whole_query_exact(tmp_path: Path) -> None:
    """站点语义：仅整串相等才替换（不是分词替换）。"""
    _write(tmp_path, {"synonyms": {"螺杆泵": "螺杆式真空泵"}})
    meta = SearchMeta.load(tmp_path)
    assert meta.apply_query_synonym(" 螺杆泵 ") == "螺杆式真空泵"
    assert meta.apply_query_synonym("螺杆泵 价格") == "螺杆泵 价格"


def test_expand_terms_adds_synonym_tokens(tmp_path: Path) -> None:
    """增强：命中词的同义词词集并入召回词集。"""
    _write(tmp_path, {"synonyms": {"螺杆泵": "螺杆式真空泵"}})
    meta = SearchMeta.load(tmp_path)
    extra = meta.expand_terms("求购螺杆泵")
    assert "螺杆" in extra and "真空" in extra  # 同义词的中文二元组
    assert meta.expand_terms("求购旋片泵") == set()  # 未命中不扩词


def test_longest_word_wins(tmp_path: Path) -> None:
    _write(tmp_path, {"synonyms": {"无油泵": "无油真空泵", "泵": "真空泵"}})
    meta = SearchMeta.load(tmp_path)
    extra = meta.expand_terms("无油泵")
    assert "真空" in extra  # 来自"无油真空泵"
    assert "真空泵" not in extra  # 短词"泵"不应额外展开


def test_block_words_substring_match(tmp_path: Path) -> None:
    _write(tmp_path, {"block_words": ["赌博"]})
    meta = SearchMeta.load(tmp_path)
    assert meta.is_blocked("在线赌博平台")
    assert meta.is_blocked("赌博") is True
    assert meta.is_blocked("真空泵") is False


def test_exported_at_preserved(tmp_path: Path) -> None:
    _write(tmp_path, {"exported_at": "2026-09-16T08:00:00+00:00", "synonyms": {"a": "b"}})
    assert SearchMeta.load(tmp_path).exported_at == "2026-09-16T08:00:00+00:00"
