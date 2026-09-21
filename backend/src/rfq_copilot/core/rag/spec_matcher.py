"""规格匹配引擎——从自然语言实体到结构化参数过滤。

深层理解：
- 真空领域"越好"的方向因参数而异——抽速越高越好，极限真空越低越好
- 匹配不是精确等于，而是"满足或超过用户需求"
- 每个参数有明确的比较方向和数据类型
- **单位契约（QA-0030）**：抽速基准单位 m³/h、真空基准单位 Pa；用户条件与产品参数
  两侧都经 `quantities.parse_quantity` 归一化后比较，不做单位盲比

缺参语义（QA-0033，两条路径**有意不同**，见 01-port-spec §6.4.1）：
- `match_products`（产品硬列表，spec_flow）：关键参数取不到 → 排除——面向用户的
  匹配清单宁缺勿滥，无法验证的硬条件不得默认满足；
- `chunk_matches_spec`（知识块过滤，检索召回路径）：参数取不到 → 不可判定、放行——
  缺参数的知识块（非产品块）绝不因过滤被团灭，回落保护由 pipeline 层兜底。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from rfq_copilot.core.rag.chunking import Chunk
from rfq_copilot.core.rag.quantities import QuantityRange, parse_quantity
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

# 抽速别名匹配时必须排除的键——前级/维持泵是另一台泵的抽速，绝不能当主抽速（QA-0030 ⑥）
_SPEED_KEY_EXCLUDE = ("前级", "维持泵", "Backing", "backing")
# 无油判定词面：'无油' 后不接 '润滑'（"无油润滑轴承"是部件描述，不是无油泵），干式/干泵等同无油
_OIL_FREE_PATTERN = re.compile(r"无油(?!润滑)|干式|干泵")


@dataclass
class SpecCriteria:
    """从用户实体中提取的结构化规格条件。

    数值一律为基准单位：pumping_speed_min → m³/h，ultimate_vacuum_max → Pa。
    """

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

    实体键可能是 "pumping_speed"、"抽速" 等别名——统一映射后经 parse_quantity 解析；
    数值缺省单位时按基准单位（m³/h / Pa）解释，带单位则换算（"10 m³/min" → 600）。
    """
    criteria = SpecCriteria()
    for key, value in entities.items():
        canonical = SPEC_ALIASES.get(key.lower(), key.lower())
        if canonical == "pumping_speed":
            criteria.pumping_speed_min = _requirement_value(value)
        elif canonical == "ultimate_vacuum":
            criteria.ultimate_vacuum_max = _requirement_value(value)
        elif canonical == "oil_free":
            criteria.oil_free = str(value).lower() in ("是", "true", "yes", "1")
        else:
            criteria.extra[key] = str(value)
    return criteria


def _requirement_value(value: str | None) -> float | None:
    """用户要求数值：带单位换算（"10 m³/min" → 600）；裸数字按基准单位解释（实体键已
    标识量纲，无歧义）；取区间右端（"≥300" / "100-1000" 需求按上界计）。产品参数侧
    的"无单位不猜"规则**不适用**于用户实体——键名即量纲（QA-0030 修复配套约定）。
    """
    parsed = parse_quantity(value)
    if parsed is not None:
        return parsed.high
    if value is None:
        return None
    match = re.search(r"\d+(?:\.\d+)?", str(value))
    return float(match.group()) if match else None


def fmt_num(value: float) -> str:
    """数值 → 展示串（去尾零：300.0 → "300"），与 graph._humanize_spec_value 同口径。"""
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text or "0"


def match_products(
    products: list[ProductDetail] | list[ProductSummary],
    criteria: SpecCriteria,
) -> list[tuple[ProductDetail | ProductSummary, float, list[str]]]:
    """按规格条件匹配产品，返回 (产品, 匹配分, 匹配依据) 按分数降序。

    评分规则：
    - 满足所有硬条件 → 基础分 50
    - 每项规格优于用户要求 → +10（超出需求）
    - 恰好等于用户要求 → +5
    - 不满足硬条件 → 排除；关键参数**取不到也排除**（产品硬列表语义，QA-0033）

    匹配依据（matched_on）为 grounded 文本：参数名 + 产品参数原文 + 需求口径，
    全部由确定性判定生成（03-api-spec v1.1：禁止 LLM 生成推荐理由）。
    """
    scored: list[tuple[ProductDetail | ProductSummary, float, list[str]]] = []
    for product in products:
        outcome = _score_product(product, criteria)
        if outcome is not None:
            score, entries = outcome
            scored.append((product, score, entries))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def _speed_ok(quantity: QuantityRange | None, minimum: float) -> bool | None:
    """抽速条件判定：区间看上界（泵能覆盖即满足）；None=不可判定。"""
    if quantity is None:
        return None
    return quantity.high >= minimum


def _vacuum_ok(quantity: QuantityRange | None, maximum: float) -> bool | None:
    """真空条件判定：取可达最好值（区间下界；'≤X' 单值即 X）；None=不可判定。"""
    if quantity is None:
        return None
    return quantity.low <= maximum


def _score_product(product: ProductDetail | ProductSummary, criteria: SpecCriteria) -> tuple[float, list[str]] | None:
    """对单个产品打分并产出匹配依据；不满足硬条件返回 None（排除）。

    依据文本中的"实际值"取产品参数**原文**（grounded，不做二次加工），
    "需求"口径由 criteria 数值格式化而来（基准单位已在 extract 阶段归一）。
    """
    score = 50.0
    entries: list[str] = []
    specs = product.specs

    if criteria.pumping_speed_min is not None:
        raw = specs.get("抽速") or specs.get("pumping_speed")
        speed = parse_quantity(raw)
        verdict = _speed_ok(speed, criteria.pumping_speed_min)
        if verdict is None or not verdict:
            return None  # 缺参数或换算后不满足 → 产品路径一律排除
        best = speed.high if speed else 0.0
        score += min(20, (best - criteria.pumping_speed_min) / max(criteria.pumping_speed_min, 1) * 10)
        entries.append(f"抽速 {str(raw).strip()}（需求 ≥ {fmt_num(criteria.pumping_speed_min)} m³/h）")

    if criteria.ultimate_vacuum_max is not None:
        raw = specs.get("极限真空") or specs.get("ultimate_vacuum")
        vacuum = parse_quantity(raw)
        verdict = _vacuum_ok(vacuum, criteria.ultimate_vacuum_max)
        if verdict is None or not verdict:
            return None
        score += 10
        entries.append(f"极限真空 {str(raw).strip()}（需求 ≤ {fmt_num(criteria.ultimate_vacuum_max)} Pa）")

    if criteria.oil_free is not None:
        params = getattr(product, "params", None)  # ProductSummary 无 params 字段
        if isinstance(params, dict) and criteria.oil_free and params.get("无油", "") != "是":
            return None
        if criteria.oil_free:
            entries.append("无油 ✓")
        # 无 params 属性（Summary）：oil_free 视为不可判定，跳过该条件继续评分

    return score, entries


# ---------------------------------------------------------------------------
# 知识块规格过滤（01-port-spec §6.4.1）
# ---------------------------------------------------------------------------


def chunk_matches_spec(chunk: Chunk, criteria: SpecCriteria) -> bool:
    """按 SpecCriteria 判定知识块是否满足规格；不可判定的项一律放行。

    与 match_products 的语义**有意不同**（QA-0033）：本函数服务于检索召回路径，
    缺参数的知识块（非产品块）不得因过滤被团灭；回落保护由 pipeline 层负责。
    数值经 parse_quantity 归一化（抽速 → m³/h，真空 → Pa）后按方向比较：
    - 抽速 ≥ min：区间看上界（`100-1000 m³/h` 对 ≥300 成立——泵能覆盖）；
    - 极限真空 ≤ max：取可达最好值（区间下界 / `≤X` 取 X）。
    参数键别名查找（真实 seeder 键名如"抽气速率(50Hz)"）：精确名优先，含子串次之；
    含"前级/维持泵"的键**永不**充当主抽速。
    """
    mapping = chunk.params if isinstance(chunk.params, dict) else {}

    if criteria.pumping_speed_min is not None:
        speed = parse_quantity(_find_speed_param(mapping))
        verdict = _speed_ok(speed, criteria.pumping_speed_min)
        if verdict is False:
            return False  # 只有"确证不满足"才排除；取不到数 = 不可判定 = 放行

    if criteria.ultimate_vacuum_max is not None:
        vacuum = parse_quantity(_find_param(mapping, "极限真空", "ultimate_vacuum"))
        verdict = _vacuum_ok(vacuum, criteria.ultimate_vacuum_max)
        if verdict is False:
            return False

    if criteria.oil_free:
        return _looks_oil_free(mapping, chunk)
    return True


def _looks_oil_free(mapping: dict[str, str], chunk: Chunk) -> bool:
    """无油判定：params `无油=是`，或产品类型/标题/正文命中无油词面（'无油润滑'不算）。"""
    if mapping.get("无油") == "是":
        return True
    product_type = mapping.get("产品类型", "")
    return bool(
        _OIL_FREE_PATTERN.search(product_type)
        or _OIL_FREE_PATTERN.search(chunk.title)
        or _OIL_FREE_PATTERN.search(chunk.content)
    )


def _find_speed_param(mapping: dict[str, str]) -> str | None:
    """主抽速参数查找：别名匹配 + 前级/维持泵键排除。"""
    for alias in ("抽速", "抽气速率", "pumping_speed"):
        if alias in mapping:
            return mapping[alias]
    for alias in ("抽速", "抽气速率", "pumping_speed"):
        for key, value in mapping.items():
            if alias in key and not any(bad in key for bad in _SPEED_KEY_EXCLUDE):
                return value
    return None


def _find_param(mapping: dict[str, str], *aliases: str) -> str | None:
    """参数键别名查找：精确名优先，含子串次之（键序保持插入序，确定性）。"""
    for alias in aliases:
        if alias in mapping:
            return mapping[alias]
    for alias in aliases:
        for key, value in mapping.items():
            if alias in key:
                return value
    return None
