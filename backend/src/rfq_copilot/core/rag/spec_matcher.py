"""规格匹配引擎——从自然语言实体到结构化参数过滤。

深层理解：
- 真空领域"越好"的方向因参数而异——抽速越高越好，极限真空越低越好
- 匹配不是精确等于，而是"满足或超过用户需求"
- 每个参数有明确的比较方向和数据类型
"""

# 图内传入 ProductSummary（无 params）：oil_free 条件在 Summary 上视为不可判定，
# 激活完整匹配需 get_detail 补全——一期可接受。

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rfq_copilot.ports.product_catalog import ProductDetail, ProductSummary

# 已知参数的比较方向和标签
SPEC_DIRECTIONS: dict[str, str] = {
    "抽速": "higher",  # 抽速越高越好
    "pumping_speed": "higher",
    "极限真空": "lower",  # 极限真空数值越低越好（更接近理想真空）
    "spec_vacuum": "lower",
    "功率": "lower",  # 功率越低越节能
    "power": "lower",
}

# 参数别名映射（用户可能说"抽速100"或"pumping speed 100"）
SPEC_ALIASES: dict[str, str] = {
    "抽速": "pumping_speed",
    "pumping_speed": "pumping_speed",
    "极限真空": "ultimate_vacuum",
    "ultimate_vacuum": "ultimate_vacuum",
    "功率": "power",
    "power": "power",
    "无油": "oil_free",
    "oil_free": "oil_free",
}


@dataclass
class SpecCriteria:
    """从用户实体中提取的结构化规格条件。"""

    pumping_speed_min: float | None = None
    ultimate_vacuum_max: float | None = None
    oil_free: bool | None = None
    extra: dict[str, str] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return (
            self.pumping_speed_min is None
            and self.ultimate_vacuum_max is None
            and self.oil_free is None
            and not self.extra
        )


def extract_spec_criteria(entities: dict[str, str]) -> SpecCriteria:
    """从理解节点的实体中提取规格条件。

    实体键可能是 "pumping_speed"、"抽速" 等别名——统一映射后提取数值。
    """
    criteria = SpecCriteria()
    for key, value in entities.items():
        canonical = SPEC_ALIASES.get(key.lower(), key.lower())
        if canonical == "pumping_speed":
            criteria.pumping_speed_min = _to_float(value)
        elif canonical == "ultimate_vacuum":
            criteria.ultimate_vacuum_max = _to_float(value)
        elif canonical == "oil_free":
            criteria.oil_free = str(value).lower() in ("是", "true", "yes", "1")
        else:
            criteria.extra[key] = str(value)
    return criteria


def _to_float(value: Any) -> float | None:
    """从可能包含单位的字符串中提取数值。"""
    import re

    if value is None:
        return None
    match = re.search(r"[\d.]+", str(value))
    return float(match.group()) if match else None


def match_products(
    products: list[ProductDetail] | list[ProductSummary],
    criteria: SpecCriteria,
) -> list[tuple[ProductDetail | ProductSummary, float]]:
    """按规格条件匹配产品，返回 (产品, 匹配分) 按分数降序。

    评分规则：
    - 满足所有硬条件 → 基础分 50
    - 每项规格优于用户要求 → +10（超出需求）
    - 恰好等于用户要求 → +5
    - 不满足硬条件 → 排除
    """
    scored: list[tuple[ProductDetail | ProductSummary, float]] = []
    for product in products:
        score = _score_product(product, criteria)
        if score is not None:
            scored.append((product, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def _score_product(product: ProductDetail | ProductSummary, criteria: SpecCriteria) -> float | None:
    """对单个产品打分；不满足硬条件返回 None（排除）。"""
    score = 50.0
    specs = product.specs

    if criteria.pumping_speed_min is not None:
        speed = _extract_number(specs.get("抽速") or specs.get("pumping_speed"))
        if speed is None:
            return None  # 缺少关键参数，无法判断
        if speed < criteria.pumping_speed_min:
            return None  # 不满足最低要求
        score += min(20, (speed - criteria.pumping_speed_min) / max(criteria.pumping_speed_min, 1) * 10)

    if criteria.ultimate_vacuum_max is not None:
        vacuum = _extract_number(specs.get("极限真空") or specs.get("ultimate_vacuum"))
        if vacuum is None:
            return None
        if vacuum > criteria.ultimate_vacuum_max:
            return None  # 不满足极限真空要求
        score += 10

    if criteria.oil_free is not None:
        params = getattr(product, "params", None)  # ProductSummary 无 params 字段
        if isinstance(params, dict) and criteria.oil_free and params.get("无油", "") != "是":
            return None
        # 无 params 属性（Summary）：oil_free 视为不可判定，跳过该条件继续评分

    return score


def _extract_number(text: str | None) -> float | None:
    if text is None:
        return None
    import re

    match = re.search(r"[\d.]+", str(text))
    return float(match.group()) if match else None
