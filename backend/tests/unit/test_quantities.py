"""QA-0030 回归：物理量解析（quantities.parse_quantity）对真实站点参数格式的正确性。

用例值全部取自站点 database/seeders/product_data.php 的真实形态：
科学计数上标（≤1×10⁻⁸ Pa，87 条）、区间（100-1000 m³/h）、跨单位（hPa/mbar/Torr）、
'大气压 ~ X' 区间、括号注记（(50Hz) / （配合前级泵） / (N₂)）。
基准单位契约：真空 → Pa，抽速 → m³/h。
"""

import pytest

from rfq_copilot.core.rag.quantities import parse_quantity


@pytest.mark.parametrize(
    ("raw", "expected_low", "expected_high"),
    [
        # —— 真空：科学计数（seeder 87 条同形态）——
        ("≤1×10⁻⁸ Pa", 1e-8, 1e-8),
        ("≤5×10⁻⁴ Pa", 5e-4, 5e-4),
        ("≤5×10⁻² Pa", 5e-2, 5e-2),
        ("≤1×10⁻³ Pa（配合前级泵）", 1e-3, 1e-3),
        # —— 真空：跨单位换算 ——
        ("≤0.08 hPa", 8.0, 8.0),
        ("≤0.05 hPa", 5.0, 5.0),
        ("≤120 mbar", 12000.0, 12000.0),
        ("≤0.5 mbar", 50.0, 50.0),
        ("≤5 Torr", 5 * 133.322, 5 * 133.322),
        ("≤3300 Pa", 3300.0, 3300.0),
        # —— 真空：大气压 ~ X 区间（可达最好值在右端）——
        ("大气压 ~ 1×10⁻⁸ Pa", 1e-8, 1e-8),
        ("大气压 ~ 1×10⁻⁹ Pa", 1e-9, 1e-9),
        # —— 抽速：区间（区间语义由 spec_matcher 负责取哪端，此处只验证解析）——
        ("100-1000 m³/h", 100.0, 1000.0),
        ("1.5-30 m³/min", 90.0, 1800.0),
        ("100-10000 L/s", 360.0, 36000.0),
        ("500-5000 m³/h", 500.0, 5000.0),
        # —— 抽速：单值 + 括号注记 ——
        ("400 m³/h", 400.0, 400.0),
        ("40 m³/h (50Hz)", 40.0, 40.0),
        ("65 m³/h (50Hz)", 65.0, 65.0),
        ("300 L/s (N₂)", 1080.0, 1080.0),
        ("36 L/min", 2.16, 2.16),
        ("600 L/s", 2160.0, 2160.0),
        # —— ASCII 科学计数 / 幂符号变体 ——
        ("5e-4 Pa", 5e-4, 5e-4),
        ("5E-4 Pa", 5e-4, 5e-4),
        ("5×10^-4 Pa", 5e-4, 5e-4),
        ("1.2 m3/h", 1.2, 1.2),
    ],
)
def test_parse_real_site_formats(raw: str, expected_low: float, expected_high: float) -> None:
    parsed = parse_quantity(raw)
    assert parsed is not None, raw
    assert parsed.low == pytest.approx(expected_low, rel=1e-6), raw
    assert parsed.high == pytest.approx(expected_high, rel=1e-6), raw


@pytest.mark.parametrize(
    "raw",
    [
        "大气压",  # 纯文字无数值
        "内置干式泵",  # 无数值
        None,
        "",
        "水冷",  # 无数值无单位
        "1.5kW",  # 功率单位不在本解析器领域 → 不可判定
        "5",  # 有数字无单位：宁可不可判定也不猜（QA-0030 教训）
    ],
)
def test_parse_undecidable_returns_none(raw: str | None) -> None:
    assert parse_quantity(raw) is None
