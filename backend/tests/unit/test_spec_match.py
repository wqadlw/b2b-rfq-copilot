"""Unit: spec_matcher 纯函数——规格条件提取 + 硬条件评分（spec_match_flow 下游引擎）。

覆盖 05-structured-output-spec v1.1：抽速别名/数值提取、极限真空方向、无油布尔、
未知键入 extra；match_products 降序排名、硬条件排除、ProductSummary（无 params）防御。
"""

from rfq_copilot.core.rag.spec_matcher import extract_spec_criteria, match_products
from rfq_copilot.ports.product_catalog import PriceDisplay, ProductDetail, ProductSummary


def _detail(
    speed: str,
    vacuum: str | None = None,
    oil_free: str = "是",
    pid: str = "demo-p-001",
    specs: dict[str, str] | None = None,
) -> ProductDetail:
    if specs is None:
        specs = {"抽速": speed}
        if vacuum is not None:
            specs["极限真空"] = vacuum
    return ProductDetail(
        id=pid,
        name=f"demo 泵 {pid} 型",
        category_name="真空泵",
        brand_name="demo 品牌",
        supplier_id="demo-s-001",
        supplier_name="demo 供应商 1",
        specs=specs,
        price_display=PriceDisplay(mode="contact", text="请联系供应商询价"),
        url=f"/products/{pid}",
        description="demo",
        params={"无油": oil_free},
    )


def _summary(detail: ProductDetail) -> ProductSummary:
    return ProductSummary(**detail.model_dump(include=set(ProductSummary.model_fields)))


def test_extract_speed_alias_to_float() -> None:
    criteria = extract_spec_criteria({"抽速": "100 m3/h"})
    assert criteria.pumping_speed_min == 100.0
    assert criteria.ultimate_vacuum_max is None
    assert criteria.oil_free is None
    assert criteria.extra == {}


def test_extract_ultimate_vacuum_upper_bound_semantics() -> None:
    # 极限真空方向：数值越低越好，提取值语义为"不可超过的上限"
    criteria = extract_spec_criteria({"极限真空": "0.05 Pa"})
    assert criteria.ultimate_vacuum_max == 0.05


def test_extract_canonical_key_oil_free_and_unknown_to_extra() -> None:
    criteria = extract_spec_criteria({"pumping_speed": "80", "无油": "true", "接口": "KF25"})
    assert criteria.pumping_speed_min == 80.0
    assert criteria.oil_free is True
    assert criteria.extra == {"接口": "KF25"}


def test_extract_oil_free_false_when_negative() -> None:
    criteria = extract_spec_criteria({"无油": "否"})
    assert criteria.oil_free is False
    assert not criteria.is_empty


def test_extract_empty_entities_is_empty() -> None:
    assert extract_spec_criteria({}).is_empty


def test_match_ranks_by_score_desc() -> None:
    slower = _detail("10 m³/h", pid="demo-p-001")
    faster = _detail("20 m³/h", pid="demo-p-002")
    matched = match_products([slower, faster], extract_spec_criteria({"抽速": "5 m3/h"}))
    assert [p.id for p, _s, _e in matched] == ["demo-p-002", "demo-p-001"]  # 分数降序
    assert [score for _, score, _e in matched] == [70.0, 60.0]  # 50 基础 + 超出需求加分


def test_match_excludes_speed_below_min() -> None:
    products = [_detail("20 m³/h")]
    assert match_products(products, extract_spec_criteria({"抽速": "100 m3/h"})) == []


def test_match_excludes_missing_speed_spec() -> None:
    no_speed = _detail("20 m³/h", specs={"极限真空": "0.01 Pa"})  # 缺少关键参数无法判定
    assert match_products([no_speed], extract_spec_criteria({"抽速": "5 m3/h"})) == []


def test_match_excludes_vacuum_above_max() -> None:
    worse = _detail("20 m³/h", vacuum="0.1 Pa", pid="demo-p-001")
    better = _detail("20 m³/h", vacuum="0.01 Pa", pid="demo-p-002")
    matched = match_products([worse, better], extract_spec_criteria({"极限真空": "0.05 Pa"}))
    assert [p.id for p, _s, _e in matched] == ["demo-p-002"]
    assert matched[0][1] == 60.0  # 基础 50 + 极限真空达标 10


def test_match_oil_free_filters_product_detail() -> None:
    oilless = _detail("20 m³/h", oil_free="是", pid="demo-p-002")
    oiled = _detail("20 m³/h", oil_free="否", pid="demo-p-001")
    matched = match_products([oilless, oiled], extract_spec_criteria({"无油": "是"}))
    assert [p.id for p, _s, _e in matched] == ["demo-p-002"]


def test_match_summary_without_params_skips_oil_free() -> None:
    summary = _summary(_detail("120 m³/h"))
    assert not hasattr(summary, "params")  # ProductSummary 无 params 字段
    matched = match_products([summary], extract_spec_criteria({"抽速": "100 m3/h", "无油": "是"}))
    assert len(matched) == 1
    assert matched[0][0] is summary  # oil_free 不可判定 → 跳过该条件继续评分，不抛异常


# ---------------------------------------------------------------------------
# product_compare（03-api-spec v1.1）：matched_on grounded 匹配依据
# ---------------------------------------------------------------------------


def test_match_entries_ground_in_product_spec_text() -> None:
    product = _detail("100-1000 m³/h", pid="demo-p-001")
    matched = match_products([product], extract_spec_criteria({"抽速": "300 m3/h"}))
    entries = matched[0][2]
    assert entries == ["抽速 100-1000 m³/h（需求 ≥ 300 m³/h）"]  # 实际值=参数原文，需求=归一化口径


def test_match_entries_vacuum_and_oil_free() -> None:
    product = _detail("20 m³/h", vacuum="0.01 Pa", oil_free="是", pid="demo-p-001")
    matched = match_products(
        [product],
        extract_spec_criteria({"极限真空": "0.05 Pa", "无油": "是"}),
    )
    entries = matched[0][2]
    assert "极限真空 0.01 Pa（需求 ≤ 0.05 Pa）" in entries
    assert "无油 ✓" in entries
