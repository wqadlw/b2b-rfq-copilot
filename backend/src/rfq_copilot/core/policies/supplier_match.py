"""Supplier matching score (pure function, unit-testable; neutral presentation upstream).

Scoring rule (five-feature plan P1-2): category 0-40 + region 0-25 + certification 0-25 + activity 0-10.
Port-spec section 3.2 neutrality: scores drive filtering/reasons only. The respond layer must
present suppliers side by side with match reasons, never ranked "best" claims.
参考：chatwoot auto_assignment 的多维加权思想（只借鉴，未复制代码）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rfq_copilot.ports.supplier_directory import SupplierSummary

# 认证加分映射（0-25 档）：实名 10 + 企业认证 10 + ISO 5
_CERT_SCORES: dict[str, int] = {
    "实名认证": 10,
    "企业认证": 10,
    "ISO9001": 5,
}


@dataclass
class SupplierMatch:
    """单个供应商的匹配结果（并列陈述用，分数不用于排序推荐）。"""

    supplier: SupplierSummary
    score: int
    reasons: list[str] = field(default_factory=list)


def _region_hit(supplier_region: str | None, target: str) -> bool:
    """双向子串命中：'苏州' 命中 '江苏 苏州'，'江苏 苏州' 命中 '江苏 苏州'。"""
    if not supplier_region or not target:
        return False
    return target in supplier_region or supplier_region in target


def match_suppliers(
    suppliers: list[SupplierSummary],
    *,
    category: str | None = None,
    region: str | None = None,
) -> list[SupplierMatch]:
    """按评分规则为供应商打分并返回带匹配原因的结果列表。

    评分构成：
    - 品类 0-40：main_products 含目标品类（子串命中，大小写不敏感）→ +40
    - 地区 0-25：region 与目标双向子串命中 → +25
    - 认证 0-25：实名 10 + 企业认证 10 + ISO 5（按 certifications 列表命中计分）
    - 基础分 0：活跃度暂无数据源，一期恒 0（端口无该字段，不编造）
    """
    results: list[SupplierMatch] = []
    for supplier in suppliers:
        score = 0
        reasons: list[str] = []

        if category:
            hit = any(category.lower() in product.lower() for product in supplier.main_products)
            if hit:
                score += 40
                reasons.append("品类匹配")

        if region and _region_hit(supplier.region, region):
            score += 25
            reasons.append("地区匹配")

        cert_score = sum(
            cert_points for cert in supplier.certifications if (cert_points := _CERT_SCORES.get(cert)) is not None
        )
        if cert_score:
            score += cert_score
            reasons.append("资质认证")

        results.append(SupplierMatch(supplier=supplier, score=score, reasons=reasons))
    return results
