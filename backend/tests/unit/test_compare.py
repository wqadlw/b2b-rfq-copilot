"""Product comparison: matrix builder pure-function tests (five-feature plan P1-3)."""

from rfq_copilot.core.rag.compare import build_compare_matrix, render_compare_answer
from rfq_copilot.ports.product_catalog import PriceDisplay, ProductDetail


def _product(pid: str, name: str, speed: str, vacuum: str, oil: str, price: str, shown: bool) -> ProductDetail:
    return ProductDetail(
        id=pid,
        name=name,
        category_name="真空泵",
        brand_name="demo 品牌",
        supplier_id="demo-s-001",
        supplier_name="demo 供应商 1",
        specs={"抽速": speed, "极限真空": vacuum},
        price_display=PriceDisplay(mode="shown" if shown else "contact", text=price if shown else ""),
        url=f"/products/{pid}",
        description="demo",
        params={"无油": oil, "接口": "KF25"},
    )


A = _product("demo-p-001", "产品A", "8 m3/h", "0.01 Pa", "是", "￥3,000", True)
B = _product("demo-p-002", "产品B", "12 m3/h", "0.005 Pa", "否", "", False)


def test_matrix_rows_and_differs() -> None:
    matrix = build_compare_matrix([A, B])
    labels = [row.label for row in matrix.rows]
    assert "产品名称" in labels and "抽速" in labels and "极限真空" in labels and "价格" in labels
    speed_row = next(r for r in matrix.rows if r.label == "抽速")
    assert speed_row.values == ["8 m3/h", "12 m3/h"]
    assert speed_row.differs is True


def test_identical_row_marked_not_differs() -> None:
    matrix = build_compare_matrix([A, A])
    name_row = next(r for r in matrix.rows if r.label == "产品名称")
    assert name_row.differs is False


def test_direction_hint_only_for_lower_better_keys() -> None:
    matrix = build_compare_matrix([A, B])
    vacuum_row = next(r for r in matrix.rows if r.label == "极限真空")
    assert vacuum_row.direction_hint in {"更低", "更高"}
    speed_row = next(r for r in matrix.rows if r.label == "抽速")
    assert speed_row.direction_hint is None  # 抽速越高越好：不在 _LOWER_IS_BETTER_KEYS


def test_price_neutral_contact_mode() -> None:
    matrix = build_compare_matrix([A, B])
    price_row = next(r for r in matrix.rows if r.label == "价格")
    assert price_row.values == ["￥3,000", "请联系供应商询价"]


def test_fewer_than_two_products_returns_empty_matrix() -> None:
    matrix = build_compare_matrix([A])
    assert matrix.rows == []


def test_answer_neutral_no_superiority_claims() -> None:
    matrix = build_compare_matrix([A, B])
    answer = render_compare_answer(matrix)
    assert "产品A" in answer and "产品B" in answer
    for banned in ("更好", "更优", "推荐购买", "首选", "最好"):
        assert banned not in answer


def test_answer_includes_direction_hint_and_disclaimer() -> None:
    matrix = build_compare_matrix([A, B])
    answer = render_compare_answer(matrix)
    assert "（更低）" in answer or "（更高）" in answer
    assert "以供应商确认为准" in answer


def test_answer_identical_products_guides_inquiry() -> None:
    matrix = build_compare_matrix([A, A])
    answer = render_compare_answer(matrix)
    assert "完全一致" in answer


def test_answer_fewer_than_two_prompts() -> None:
    matrix = build_compare_matrix([A])
    assert "两个" in render_compare_answer(matrix)
