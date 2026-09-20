"""物理量解析——真实站点参数文本 → 基准单位数值区间（01-port-spec §6.4.1）。

契约（QA-0030 修复）：
- 抽速类基准单位 m³/h；真空类基准单位 Pa。两侧（用户条件 / 产品参数）统一归一化后比较。
- 支持：科学计数（``5×10⁻⁴`` / ``5e-4`` / ``5×10^-4``）、区间（``100-1000`` / ``1.5~30`` /
  ``大气压 ~ 1×10⁻⁸ Pa``）、单位换算（hPa/mbar/Torr/mmHg/kPa/MPa；m³/min、L/s、L/min 等）、
  括号注记剥离（``(50Hz)`` / ``（配合前级泵）`` / ``(N₂)``）。
- 解析不了（无数值 / 无单位 / 纯文字如"大气压"）返回 None——由调用方按"不可判定"处理。

设计取舍：不引入 pint——站点值是含中文注记的展示串（"≤1×10⁻³ Pa（配合前级泵）"），
grammatically 不适配 pint 的解析器；领域单位面窄（压力/抽速两类），自建 ~百行解析器
配全量真实格式测试矩阵更可控（零新依赖）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 上标 → ASCII（站点 seeder 用 ⁻ⁿ 表示指数）
_SUPERSCRIPT = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺", "0123456789-+")

# 压力 → Pa（长键在前，避免 "Pa" 吃掉 "hPa"）
_PRESSURE_TO_PA: list[tuple[str, float]] = [
    ("MPa", 1e6),
    ("kPa", 1e3),
    ("hPa", 1e2),
    ("mTorr", 0.133322),
    ("mbar", 1e2),
    ("bar", 1e5),
    ("Torr", 133.322),
    ("mmHg", 133.322),
    ("atm", 101325.0),
    ("Pa", 1.0),
    ("帕", 1.0),
]

# 抽速 → m³/h（长键在前）
_SPEED_TO_M3H: list[tuple[str, float]] = [
    ("m³/h", 1.0),
    ("m3/h", 1.0),
    ("m³/min", 60.0),
    ("m3/min", 60.0),
    ("m³/s", 3600.0),
    ("m3/s", 3600.0),
    ("L/s", 3.6),
    ("l/s", 3.6),
    ("L/min", 0.06),
    ("l/min", 0.06),
    ("cfm", 1.69901108),
]

_RANGE_SEPS = "-~～"


@dataclass(frozen=True)
class QuantityRange:
    """归一化到基准单位的数值区间；单值时 low == high。"""

    low: float
    high: float


def _strip_annotations(text: str) -> str:
    """剥离括号注记与空白：'(50Hz)'、'（配合前级泵）'、'(N₂)' 等。"""
    return re.sub(r"（[^）]*）|\([^)]*\)", "", text).strip()


def _unit_factor(text: str, table: list[tuple[str, float]]) -> float | None:
    for unit, factor in table:
        idx = text.find(unit)
        # 单位必须出现在数字之后（避免把 "Pa" 前缀类的词尾误判）；站点数据单位总在尾部
        if idx > 0:
            return factor
    return None


def parse_quantity(text: str | None) -> QuantityRange | None:
    """把参数文本解析为基准单位区间；解析不了返回 None。

    归一化步骤：上标转 ASCII → 剥括号注记 → 科学计数优先取 token → 剩余数字两两成区间
    （其间有 -/~/～ 分隔符）→ 按单位表换算。
    """
    if text is None:
        return None
    normalized = _strip_annotations(str(text).translate(_SUPERSCRIPT))

    tokens: list[tuple[float, int, int]] = []
    consumed: list[tuple[int, int]] = []
    # ① ×10 形式科学计数（站点主流：5×10⁻⁴）
    for match in re.finditer(r"(\d+(?:\.\d+)?)\s*[×x*]\s*10\^?\s*(-?\d+)", normalized):
        tokens.append((float(match.group(1)) * 10.0 ** int(match.group(2)), match.start(1), match.end(2)))
        consumed.append((match.start(), match.end()))
    # ② e/E 形式科学计数（5e-4）
    for match in re.finditer(r"(\d+(?:\.\d+)?)[eE](-?\d+)", normalized):
        if any(start <= match.start() < end for start, end in consumed):
            continue
        tokens.append((float(match.group(1)) * 10.0 ** int(match.group(2)), match.start(1), match.end(2)))
        consumed.append((match.start(), match.end()))

    # 未被科学计数吞掉的普通数字（区间 / 单值）
    for match in re.finditer(r"\d+(?:\.\d+)?", normalized):
        if any(start <= match.start() < end for start, end in consumed):
            continue
        tokens.append((float(match.group()), match.start(), match.end()))
    if not tokens:
        return None
    tokens.sort(key=lambda t: t[1])

    # 区间：相邻两 token 之间只隔分隔符（'100-1000' / '1.5~30' / '大气压 ~ 1×10⁻⁸'）
    def _gap_is_range_sep(left_end: int, right_start: int) -> bool:
        gap = normalized[left_end:right_start]
        return bool(gap) and all(ch in _RANGE_SEPS or ch.isspace() for ch in gap)

    low = tokens[0][0]
    high = tokens[0][0]
    for prev, nxt in zip(tokens, tokens[1:], strict=False):
        if _gap_is_range_sep(prev[2], nxt[1]):
            high = nxt[0]
            break

    factor = _unit_factor(normalized, _PRESSURE_TO_PA) or _unit_factor(normalized, _SPEED_TO_M3H)
    if factor is None:
        return None  # 有数字无单位：单位不明，宁可不可判定也不猜
    return QuantityRange(low=low * factor, high=high * factor)
