"""ZZK 行业解决方案目录（离线导出 zzk_solutions.json，只读内存态）。

数据源：站点 Solution 表（status=1，含 pain_points/topology/关联供应商与深链）。
导出：站点侧 `php artisan tinker` 查询 → KNOWLEDGE_DATA_DIR/zzk_solutions.json
（与 SearchSynonym 导出同模式；站点 DB 离线时沿用既有导出文件）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

SOLUTIONS_FILENAME = "zzk_solutions.json"

# 行业同义词：用户口语 → industry_slug（如"锂电"→ lidian）
_INDUSTRY_ALIASES: dict[str, str] = {
    "半导体": "bandaoti",
    "电子": "bandaoti",
    "光伏": "guangfu",
    "新能源": "guangfu",
    "锂电": "lidian",
    "锂电池": "lidian",
    "食品": "shipin",
    "食品加工": "shipin",
    "医药": "yiyao",
    "生物": "yiyao",
    "医药生物": "yiyao",
    "化工": "huagong",
}


@dataclass(frozen=True)
class Solution:
    """一张方案卡的全部展示数据。"""

    name: str
    slug: str
    industry_slug: str
    industry_name: str
    subtitle: str | None = None
    pain_points: list[dict[str, str]] = field(default_factory=list)
    topology: str | None = None
    budget_min: float | None = None
    budget_max: float | None = None
    suppliers: list[str] = field(default_factory=list)
    url: str = ""

    @property
    def budget_text(self) -> str | None:
        if self.budget_min and self.budget_max:
            return f"{self.budget_min:g}–{self.budget_max:g} 万"
        if self.budget_min:
            return f"{self.budget_min:g} 万起"
        return None


class ZzkSolutionDirectory:
    """按行业检索方案；数据文件缺失/损坏时保持空目录（不抛错、不瘫痪）。"""

    def __init__(self, data_dir: str | None = None) -> None:
        self._data_dir = Path(data_dir) if data_dir else None
        self._solutions: list[Solution] = []
        self._load()

    def _load(self) -> None:
        if self._data_dir is None:
            return
        path = Path(self._data_dir) / SOLUTIONS_FILENAME
        if not path.is_file():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        for raw in payload.get("solutions", []):
            self._solutions.append(
                Solution(
                    name=str(raw.get("name", "")),
                    slug=str(raw.get("slug", "")),
                    industry_slug=str(raw.get("industry_slug", "")),
                    industry_name=str(raw.get("industry_name", "")),
                    subtitle=raw.get("subtitle"),
                    pain_points=[
                        {"title": str(p.get("title", "")), "desc": str(p.get("desc", ""))}
                        for p in (raw.get("pain_points") or [])
                        if isinstance(p, dict)
                    ],
                    topology=raw.get("topology"),
                    budget_min=raw.get("budget_min"),
                    budget_max=raw.get("budget_max"),
                    suppliers=[str(s) for s in (raw.get("suppliers") or [])],
                    url=str(raw.get("url", "")),
                )
            )

    def __len__(self) -> int:
        return len(self._solutions)

    def all(self) -> list[Solution]:
        return list(self._solutions)

    @staticmethod
    def resolve_industry(message: str) -> str | None:
        """从消息解析行业 slug（含口语同义词）；无行业词返回 None。"""
        text = message.strip()
        if not text:
            return None
        # 长词优先，避免"锂电池"命中"电子"
        for alias in sorted(_INDUSTRY_ALIASES, key=len, reverse=True):
            if alias in text:
                return _INDUSTRY_ALIASES[alias]
        for slug, name in _INDUSTRY_NAMES_CACHE.items():
            if name and name in text:
                return slug
        return None

    def by_industry(self, industry_slug: str) -> Solution | None:
        for solution in self._solutions:
            if solution.industry_slug == industry_slug:
                return solution
        return None


# 行业中文名缓存（resolve_industry 兜底用）：site 导出里 industries 已随文件提供；
# 这里静态维护核心映射，避免加载顺序依赖。
_INDUSTRY_NAMES_CACHE: dict[str, str] = {
    "shipin": "食品加工",
    "bandaoti": "半导体/电子",
    "huagong": "化工",
    "yiyao": "医药/生物",
    "guangfu": "光伏/新能源",
}


def detect_solution_query(message: str) -> str | None:
    """确定性方案意图：消息含行业词 + 方案问法 → 返回 industry_slug；否则 None。

    方案问法（任一命中）：方案 / 解决方案 / 配套 / 整套 / 成套 / 产线 / 系统怎么配
    """
    text = message.strip()
    if not text:
        return None
    if not any(marker in text for marker in ("方案", "配套", "整套", "成套", "产线", "系统怎么配", "系统配置")):
        return None
    return ZzkSolutionDirectory.resolve_industry(text)
