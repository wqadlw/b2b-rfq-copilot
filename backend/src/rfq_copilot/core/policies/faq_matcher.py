"""第一层：FAQ 关键词匹配（0 LLM token）。

高频问题通过关键词/模糊匹配直接返回预置答案，
只在 FAQ 库无法覆盖时才进入 RAG 检索或 LLM 生成。
企业部署中此层覆盖 40-60% 的用户提问。
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher


@dataclass(frozen=True)
class FaqEntry:
    keywords: tuple[str, ...]  # 触发关键词
    answer: str
    category: str = "通用"


class FaqMatcher:
    """关键词 + 模糊匹配 FAQ 库；零 LLM token，响应 <1ms。"""

    def __init__(self, entries: list[FaqEntry]) -> None:
        self._entries = entries

    def match(self, query: str, threshold: float = 0.6) -> str | None:
        query_lower = query.lower().strip()
        if not query_lower:
            return None

        best_score = 0.0
        best_answer: str | None = None

        for entry in self._entries:
            # 关键词命中即返回
            for kw in entry.keywords:
                if kw in query_lower:
                    return entry.answer

            # 模糊匹配
            score = SequenceMatcher(None, query_lower, entry.answer[:30]).ratio()
            if score > best_score:
                best_score = score
                best_answer = entry.answer

        if best_score >= threshold and best_answer:
            return best_answer
        return None


def build_default_faq() -> list[FaqEntry]:
    """默认 FAQ 库——B2B 通用高频问题。站点侧可通过 manifest 配置覆盖。"""
    return [
        FaqEntry(
            keywords=("怎么注册", "注册账号", "如何注册"),
            answer="点击右上角『注册』按钮，填写企业信息并验证手机号即可完成注册。注册后可发布产品和查看询盘。",
            category="账户",
        ),
        FaqEntry(
            keywords=("怎么联系", "联系方式", "联系电话"),
            answer="您可以在产品详情页查看供应商联系方式，或直接提交询盘，供应商会尽快与您联系。",
            category="联系",
        ),
        FaqEntry(
            keywords=("物流", "运费", "发货"),
            answer="大件设备走专线物流，具体运费和发货时间以供应商确认为准。您可以提交询盘后与供应商沟通物流细节。",
            category="物流",
        ),
        FaqEntry(
            keywords=("支付", "付款", "怎么买"),
            answer="支持对公转账和平台担保交易。确定采购意向后可提交询盘，供应商会提供具体付款方式。",
            category="交易",
        ),
        FaqEntry(
            keywords=("售后", "维修", "质保"),
            answer="设备类商品享受供应商质保服务，平台协助协调售后问题。具体质保期限以供应商报价为准。",
            category="售后",
        ),
        FaqEntry(
            keywords=("会员", "vip", "有什么好处"),
            answer="平台会员可查看更多供应商联系方式、获取优先报价、享受专属客服服务。详情请查看会员中心。",
            category="会员",
        ),
    ]
