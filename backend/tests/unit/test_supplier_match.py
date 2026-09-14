"""Supplier matching score: pure function tests (five-feature plan P1-2)."""

from rfq_copilot.core.policies.supplier_match import match_suppliers
from rfq_copilot.ports.supplier_directory import SupplierSummary


def _supplier(
    sid: str,
    region: str | None = None,
    products: list[str] | None = None,
    certs: list[str] | None = None,
) -> SupplierSummary:
    return SupplierSummary(
        id=sid,
        name=f"供应商 {sid}",
        region=region,
        main_products=products or [],
        certifications=certs or [],
        url=f"/suppliers/{sid}",
    )


def test_category_hit_scores_40() -> None:
    m = match_suppliers([_supplier("s1", products=["真空泵", "真空阀门"])], category="真空泵")
    assert m[0].score == 40
    assert m[0].reasons == ["品类匹配"]


def test_category_miss_scores_0() -> None:
    m = match_suppliers([_supplier("s1", products=["真空阀门"])], category="真空泵")
    assert m[0].score == 0
    assert m[0].reasons == []


def test_region_bidirectional_substring_scores_25() -> None:
    full = _supplier("s1", region="江苏 苏州")
    m1 = match_suppliers([full], region="苏州")
    assert m1[0].score == 25
    m2 = match_suppliers([full], region="江苏 苏州")
    assert m2[0].score == 25


def test_region_no_hit() -> None:
    m = match_suppliers([_supplier("s1", region="上海")], region="苏州")
    assert m[0].score == 0


def test_certification_scores_capped_at_25() -> None:
    triple = _supplier("s1", certs=["实名认证", "企业认证", "ISO9001"])
    m = match_suppliers([triple])
    assert m[0].score == 25
    assert m[0].reasons == ["资质认证"]


def test_certification_partial() -> None:
    m = match_suppliers([_supplier("s1", certs=["企业认证"])])
    assert m[0].score == 10


def test_unknown_cert_ignored() -> None:
    m = match_suppliers([_supplier("s1", certs=["星级金牌"])])
    assert m[0].score == 0


def test_combined_category_region_cert() -> None:
    s = _supplier("s1", region="江苏 苏州", products=["真空泵"], certs=["实名认证", "ISO9001"])
    m = match_suppliers([s], category="真空泵", region="苏州")
    assert m[0].score == 40 + 25 + 10 + 5
    assert m[0].reasons == ["品类匹配", "地区匹配", "资质认证"]


def test_demo_five_suppliers_three_tier_certs() -> None:
    """Demo 数据契约：i<2 三证、i==2 一证、其余无证；5 家地区互异。"""
    regions = ["江苏 苏州", "山东 潍坊", "广东 深圳", "浙江 宁波", "上海"]
    cert_tiers = [
        ["实名认证", "企业认证", "ISO9001"],
        ["实名认证", "企业认证", "ISO9001"],
        ["企业认证"],
        [],
        [],
    ]
    suppliers = [_supplier(f"demo-s-{i + 1:03d}", region=regions[i], certs=cert_tiers[i]) for i in range(5)]
    results = match_suppliers(suppliers, category="真空泵", region="苏州")
    scores = {r.supplier.id: r.score for r in results}
    # s1: 苏州 + 三证(+40 品类由 main_products 决定——此处未给 products，0)
    assert scores["demo-s-001"] == 25 + 25  # 地区 + 三证
    assert scores["demo-s-002"] == 25  # 仅三证
    assert scores["demo-s-003"] == 10  # 仅企业认证
    assert scores["demo-s-004"] == 0
    assert scores["demo-s-005"] == 0


def test_never_orders_or_labels_best() -> None:
    """中立性护栏（port-spec §3.2）：结果列表保持输入顺序，分数仅作参考属性。"""
    s_low = _supplier("low", region="上海")
    s_high = _supplier("high", region="江苏 苏州", certs=["实名认证", "企业认证", "ISO9001"])
    results = match_suppliers([s_low, s_high], region="苏州")
    assert [r.supplier.id for r in results] == ["low", "high"]
