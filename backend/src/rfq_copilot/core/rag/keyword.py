"""混合检索的关键词通道（01-port-spec §6.4）。

extract_keywords 是两实现共用的唯一分词事实源：
ASCII 连续段（型号/货号精确匹配）+ CJK 二元组（中文无分词器的次优近似）。
rrf_fuse 是唯一融合事实源：score = Σ 1/(60+rank)，doc_id 去重取首现。
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from rfq_copilot.core.rag.chunking import Chunk

_RRF_K = 60
_MAX_TOKENS = 12
_ASCII_RUN = re.compile(r"[a-z0-9][a-z0-9\-_]{1,}")
_CJK = re.compile(r"[\u4e00-\u9fff]")


def extract_keywords(query: str, max_tokens: int = _MAX_TOKENS) -> list[str]:
    """查询 → 关键词 token 序列：ASCII 词（≥2 字符，连字符拆子词）+ CJK 二元组，去重保序。"""
    lowered = query.lower()
    tokens: list[str] = []

    def _push(tok: str) -> None:
        if tok and tok not in tokens and len(tokens) < max_tokens:
            tokens.append(tok)

    for match in _ASCII_RUN.finditer(lowered):
        run = match.group(0)
        _push(run)
        for part in re.split(r"[-_]+", run):
            if len(part) >= 2:
                _push(part)

    cjk_runs = [run for run in re.findall(r"[\u4e00-\u9fff]+", lowered)]
    for run in cjk_runs:
        if len(run) == 1:
            _push(run)
            continue
        for i in range(len(run) - 1):
            _push(run[i : i + 2])
    return tokens


def rrf_fuse_scored(*ranked_lists: Sequence[Chunk], top_k: int = 20) -> list[tuple[Chunk, float]]:
    """多路召回 RRF 融合（带分数版，spec 02-engine-read-api-spec §2.0）。

    score = Σ 1/(60+rank)，同 doc_id 累加、保留首现 chunk；返回按融合分降序的
    (chunk, rrf_score)。rrf_fuse 是本函数丢弃分数的薄委托——两者永远同序同分。
    """
    scores: dict[str, list[float]] = {}
    chunks: dict[str, Chunk] = {}
    for ranked in ranked_lists:
        for rank, chunk in enumerate(ranked, start=1):
            contribution = 1.0 / (_RRF_K + rank)
            scores.setdefault(chunk.doc_id, []).append(contribution)
            chunks.setdefault(chunk.doc_id, chunk)
    ordered = sorted(scores.items(), key=lambda pair: -sum(pair[1]))
    return [(chunks[doc_id], sum(pair)) for doc_id, pair in ordered[:top_k]]


def rrf_fuse(*ranked_lists: Sequence[Chunk], top_k: int = 20) -> list[Chunk]:
    """多路召回 RRF 融合：score = Σ 1/(60+rank)，同 doc_id 累加、保留首现 chunk。"""
    return [chunk for chunk, _ in rrf_fuse_scored(*ranked_lists, top_k=top_k)]


def is_cjk(char: str) -> bool:
    return bool(_CJK.match(char))
