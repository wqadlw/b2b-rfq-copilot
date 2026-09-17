"""ZZK 客户案例目录（离线导出 zzk_cases.json，只读内存态）。

数据源：站点 CaseStudy 表（status=STATUS_PUB=2，含脱敏客户/量化指标/白皮书）。
导出：站点侧 artisan 查询 → KNOWLEDGE_DATA_DIR/zzk_cases.json。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from rfq_copilot.adapters.zhaozhenkong_offline.zzk_solutions import _INDUSTRY_ALIASES

CASES_FILENAME = "zzk_cases.json"


@dataclass(frozen=True)
class Case:
    """一张案例卡的展示数据（客户已脱敏、指标已量化）。"""

    case_id: int
    title: str
    industry_slug: str | None
    industry_name: str
    customer_name: str | None
    challenge: str | None
    result: str | None
    metrics: list[dict[str, str]] = field(default_factory=list)
    has_whitepaper: bool = False
    supplier: str | None = None
    url: str = ""


class ZzkCaseDirectory:
    """案例检索；数据文件缺失/损坏时保持空目录（不抛错、不瘫痪）。"""

    def __init__(self, data_dir: str | None = None) -> None:
        self._data_dir = Path(data_dir) if data_dir else None
        self._cases: list[Case] = []
        self._load()

    def _load(self) -> None:
        if self._data_dir is None:
            return
        path = Path(self._data_dir) / CASES_FILENAME
        if not path.is_file():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        for raw in payload.get("cases", []):
            self._cases.append(
                Case(
                    case_id=int(raw.get("id", 0)),
                    title=str(raw.get("title", "")),
                    industry_slug=raw.get("industry_slug"),
                    industry_name=str(raw.get("industry_name", "")),
                    customer_name=raw.get("customer_name"),
                    challenge=raw.get("challenge"),
                    result=raw.get("result"),
                    metrics=[
                        {
                            "label": str(m.get("label", "")),
                            "actual": str(m.get("actual", "")),
                            "unit": str(m.get("unit", "")),
                        }
                        for m in (raw.get("metrics") or [])
                        if isinstance(m, dict)
                    ],
                    has_whitepaper=bool(raw.get("has_whitepaper")),
                    supplier=raw.get("supplier"),
                    url=str(raw.get("url", "")),
                )
            )

    def __len__(self) -> int:
        return len(self._cases)

    def by_industry_slug(self, industry_slug: str | None) -> list[Case]:
        """按行业取案例；无行业词或该行业无案例时返回全部（案例是稀缺背书资产）。"""
        if industry_slug:
            hits = [c for c in self._cases if c.industry_slug == industry_slug]
            if hits:
                return hits
        return list(self._cases)


# 案例问法（与产品问法区分："用过/做过/案例/交付/效果"）
_CASE_MARKERS: tuple[str, ...] = (
    "案例",
    "用过",
    "做过",
    "交付",
    "成功案",
    "客户在用",
    "有没有人用",
    "效果怎么",
    "什么效果",
    "实绩",
)

# 明确不命中：方案问法归 solution_flow
_SOLUTION_MARKERS = ("方案", "配套", "整套", "成套", "产线")


def detect_case_query(message: str) -> tuple[str | None, bool]:
    """确定性案例意图检测。

    Returns:
        (industry_slug | None, matched)：matched=False 表示不是案例问法。
        industry_slug 可为 None（无行业词 → 返回全部案例）。
    """
    text = (message or "").strip()
    if not text:
        return None, False
    if any(marker in text for marker in _SOLUTION_MARKERS):
        return None, False  # 方案问法让路给 solution_flow
    if not any(marker in text for marker in _CASE_MARKERS):
        return None, False
    for alias in sorted(_INDUSTRY_ALIASES, key=len, reverse=True):
        if alias in text:
            return _INDUSTRY_ALIASES[alias], True
    return None, True
