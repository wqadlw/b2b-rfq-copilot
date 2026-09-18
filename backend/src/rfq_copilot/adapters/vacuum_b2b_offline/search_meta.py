"""站点检索元数据（同义词 / 屏蔽词）的离线复刻。

权威语义（站点 SearchService 同义词/屏蔽词实现，2026-09-16 实测）：
- `applySynonym()`：**整串精确替换**——`isset($synonyms[trim($q)])`，只替换与整条查询完全
  相同的词；不是分词替换。
- `isBlocked()`：屏蔽词**子串命中**即拦截，站点返回空结果集。

本模块在此基础上做一处**刻意的增强**（可关）：分词级同义词扩展（SIGIR eCom 2019
「token 级同义词字典 → OR 召回」模式）。离线目录的匹配本就是"任一词命中即召回"，
因此把命中词的同义词也加入词集，等价于 OR 扩召回。增强仅在数据存在时生效。

数据文件：`<KNOWLEDGE_DATA_DIR>/search_meta.json`
  {"version": 1, "exported_at": "...", "synonyms": {"词": "同义词"}, "block_words": ["..."]}
数据由 `scripts/export_search_meta.py` 从站点库导出（需站点 DB 在线）；
文件缺失或损坏时不扩词、不拦截——绝不因元数据问题让检索瘫痪。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

META_FILENAME = "search_meta.json"


def _zh_terms(text: str) -> set[str]:
    """与目录匹配器同构的词集：中文二元组 + ASCII 词（长度 ≥2）。"""
    ascii_tokens = set(re.findall(r"[A-Za-z0-9-]{2,}", text))
    han = re.sub(r"[^\u4e00-\u9fff]", "", text)
    bigrams = {han[i : i + 2] for i in range(len(han) - 1)}
    return bigrams | ascii_tokens


@dataclass(frozen=True)
class SearchMeta:
    """站点检索元数据；``empty()`` 表示"无元数据"（行为与扩展前完全一致）。"""

    synonyms: dict[str, str] = field(default_factory=dict)
    block_words: tuple[str, ...] = ()
    exported_at: str | None = None

    @classmethod
    def empty(cls) -> SearchMeta:
        return cls()

    @classmethod
    def load(cls, data_dir: str | Path) -> SearchMeta:
        """读取元数据；缺失/损坏一律退化为 empty（记在返回值里，不抛错）。"""
        path = Path(data_dir) / META_FILENAME
        if not path.is_file():
            return cls.empty()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls.empty()
        if not isinstance(payload, dict):
            return cls.empty()
        raw_synonyms = payload.get("synonyms")
        raw_blocks = payload.get("block_words")
        synonyms = (
            {str(k): str(v) for k, v in raw_synonyms.items() if str(k).strip() and str(v).strip()}
            if isinstance(raw_synonyms, dict)
            else {}
        )
        block_words = tuple(str(w) for w in raw_blocks if str(w).strip()) if isinstance(raw_blocks, list) else ()
        exported_at = payload.get("exported_at")
        return cls(
            synonyms=synonyms,
            block_words=block_words,
            exported_at=str(exported_at) if exported_at else None,
        )

    @property
    def enabled(self) -> bool:
        return bool(self.synonyms or self.block_words)

    def is_blocked(self, query: str) -> bool:
        """站点语义：屏蔽词子串命中即拦截。"""
        trimmed = query.strip()
        return any(word and word in trimmed for word in self.block_words)

    def apply_query_synonym(self, query: str) -> str:
        """站点语义：整串精确替换（仅当整条查询恰好是词典中的词）。"""
        trimmed = query.strip()
        return self.synonyms.get(trimmed, query)

    def expand_terms(self, query: str) -> set[str]:
        """分词级扩展：命中词的同义词词集并入 recall 词集（OR 扩召回）。

        按词长降序匹配，长词优先，避免短词把长词的同义词也一并展开。
        """
        extra: set[str] = set()
        for word in sorted(self.synonyms, key=len, reverse=True):
            if word and word in query:
                extra |= _zh_terms(self.synonyms[word])
        return extra
