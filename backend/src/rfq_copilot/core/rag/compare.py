"""Product comparison matrix builder (pure function, unit-testable).

五大功能规划 P1-3：两个产品 → 行=参数名、列=产品 A/B 的对比矩阵。
中立性（port-spec §3.2）：只客观列差异，不输出"更好/更优"判词；价格只逐字引用
price_display.text（mode=shown），contact 模式固定"请联系供应商询价"。
参数方向（SPEC_DIRECTIONS 复用 spec_matcher 的领域知识）：仅用于标注差异方向
（"更高/更低"），不构成推荐结论。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rfq_copilot.ports.product_catalog import ProductDetail, ProductSummary

AnyProduct = ProductDetail | ProductSummary


@dataclass
class CompareRow:
    """对比矩阵一行：参数名 + 各产品的值 + 差异标记。"""

    label: str
    values: list[str]
    differs: bool = False
    # 客观方向提示（仅当两值均可解析为数值且方向表可判时填写；不构成推荐）
    direction_hint: str | None = None


@dataclass
class CompareMatrix:
    """两个产品的对比矩阵（中立呈现：只列差异，不判优劣）。"""

    products: list[AnyProduct] = field(default_factory=list)
    rows: list[CompareRow] = field(default_factory=list)


# 客观参数方向（值越低越好的参数；用于"更低/更高"方向提示，非推荐）
_LOWER_IS_BETTER_KEYS = {"极限真空", "ultimate_vacuum", "功率", "power"}


def _price_text(product: AnyProduct) -> str:
    price = product.price_display
    if price.mode == "shown":
        return price.text
    return "请联系供应商询价"


def _numeric(text: str) -> float | None:
    import re

    match = re.search(r"[\d.]+", str(text))
    return float(match.group()) if match else None


def build_compare_matrix(products: list[AnyProduct]) -> CompareMatrix:
    """从 2~3 个产品构建行=参数、列=产品的对比矩阵。

    行收集顺序：名称/品牌/供应商/品类（基础行）→ specs 并集（数值/文本混合时原样并列）
    → 价格行。differs=该行各产品值不完全相同。
    """
    matrix = CompareMatrix(products=list(products))
    if len(products) < 2:
        return matrix

    from collections.abc import Callable

    def _add_row(label: str, getter: Callable[[AnyProduct], str]) -> None:
        values = [getter(p) for p in products]
        matrix.rows.append(CompareRow(label=label, values=values, differs=len(set(values)) > 1))

    _add_row("产品名称", lambda p: p.name)
    _add_row("供应商", lambda p: p.supplier_name)
    _add_row("品类", lambda p: getattr(p, "category_name", "") or "—")

    spec_keys: list[str] = []
    for product in products:
        for key in getattr(product, "specs", {}):
            if key not in spec_keys:
                spec_keys.append(key)
    for key in spec_keys:

        def getter(p: AnyProduct, k: str = key) -> str:
            return str(getattr(p, "specs", {}).get(k, "—"))

        values = [getter(p) for p in products]
        differs = len(set(values)) > 1
        direction: str | None = None
        if differs:
            nums = [_numeric(v) for v in values]
            if all(n is not None for n in nums) and len(nums) == 2 and key in _LOWER_IS_BETTER_KEYS:
                direction = "更低" if nums[1] < nums[0] else "更高"  # type: ignore[operator]
        matrix.rows.append(CompareRow(label=key, values=values, differs=differs, direction_hint=direction))

    _add_row("价格", _price_text)
    return matrix


def render_compare_answer(matrix: CompareMatrix) -> str:
    """矩阵 → 中立并列话术（文本表格；前端 ComparisonTable 消费事件载荷，此为降级文本）。"""
    if len(matrix.products) < 2:
        return "请提供两个要对比的产品，例如：对比 demo-p-001 和 demo-p-002。"
    names = [p.name for p in matrix.products]
    lines = [f"以下是 {' 与 '.join(names)} 的参数对比（并列陈述，供参考）："]
    for row in matrix.rows:
        if not row.differs:
            continue
        suffix = f"（{row.direction_hint}）" if row.direction_hint else ""
        lines.append(f"- {row.label}{suffix}：" + "　vs　".join(row.values))
    diff_count = sum(1 for row in matrix.rows if row.differs)
    if diff_count == 0:
        lines.append("两个产品的展示参数完全一致，建议提交询盘向供应商确认详细规格。")
    lines.append("参数仅展示页面口径，具体以供应商确认为准。")
    return "\n".join(lines)
