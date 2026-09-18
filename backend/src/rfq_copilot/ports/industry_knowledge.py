"""行业知识资产端口（案例目录 / 行业方案目录）。

DTO（Case/Solution）定义在 ports 侧，core 只依赖本包；
zhaozhenkong_offline 适配器提供离线 JSON 实现（import-linter 强制 core 不触 adapters）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


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


class CasesPort(Protocol):
    """客户案例目录：检索 + 确定性案例意图检测（行业同义词归适配器所有）。"""

    def by_industry_slug(self, industry_slug: str | None) -> list[Case]: ...

    def detect_query(self, message: str) -> tuple[str | None, bool]:
        """返回 (industry_slug | None, matched)；matched=False 表示不是案例问法。"""
        ...


class SolutionsPort(Protocol):
    """行业方案目录：检索 + 确定性方案意图检测。"""

    def by_industry(self, industry_slug: str) -> Solution | None: ...

    def detect_query(self, message: str) -> str | None:
        """消息含行业词 + 方案问法 → industry_slug；否则 None。"""
        ...
