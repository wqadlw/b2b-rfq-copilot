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
        FaqEntry(
            keywords=("发货时间", "多久发货", "什么时候发货"),
            answer="发货时间以供应商确认为准。您可在询盘中注明期望交期，供应商会评估后回复。",
            category="交易",
        ),
        FaqEntry(
            keywords=("发票", "开票", "增值税"),
            answer="发票由供应商开具，支持增值税专用/普通发票。请在询盘备注中说明开票需求。",
            category="交易",
        ),
        FaqEntry(
            keywords=("样品", "打样", "试样"),
            answer="部分供应商支持寄样。您可以提交询盘并在需求中注明『样品申请』，供应商会与您联系确认。",
            category="交易",
        ),
        FaqEntry(
            keywords=("定制", "非标", "特殊规格"),
            answer="支持非标定制。请提交询盘并描述工况参数（介质/温度/真空度等），供应商会评估可行性。",
            category="交易",
        ),
        FaqEntry(
            keywords=("最小起订", "起订量", "moq"),
            answer="起订量由各供应商设定，请在询盘中注明采购数量，供应商会给出最优方案。",
            category="交易",
        ),
        FaqEntry(
            keywords=("人工客服", "联系客服", "找人工"),
            answer="您可以扫码添加专属工程师微信一对一咨询；平台内提交询盘后供应商也会主动与您联系。",
            category="联系",
        ),
    ]


class FaqRegistry:
    """运行时可变的 FAQ 库（chatwoot canned-response 思想）：运营增删改，立即生效。

    默认条目来自 build_default_faq()；运营条目可覆盖/追加；未答问题可沉淀为候选条目。
    """

    def __init__(self, entries: list[FaqEntry] | None = None) -> None:
        self._entries: list[FaqEntry] = list(entries) if entries is not None else build_default_faq()
        self._matcher = FaqMatcher(self._entries)

    def match(self, query: str) -> tuple[str, FaqEntry] | None:
        """命中返回 (答案, 条目)；未命中 None。"""
        query_lower = query.lower().strip()
        if not query_lower:
            return None
        for entry in self._entries:
            for kw in entry.keywords:
                if kw in query_lower:
                    return entry.answer, entry
        return None

    def suggest(self, query: str, limit: int = 3) -> list[dict[str, str]]:
        """未命中时返回最相似的条目（供"你可能想问"推荐），学习 help-center 搜索联想。"""
        scored: list[tuple[float, FaqEntry]] = []
        query_lower = query.lower().strip()
        for entry in self._entries:
            score = 0.0
            for kw in entry.keywords:
                if kw in query_lower:
                    score += 1.0
                elif any(ch in query_lower for ch in kw if ch.isalnum()):
                    score = max(score, 0.3)
            if score > 0:
                scored.append((score, entry))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            {"question": "、".join(entry.keywords[:3]), "answer": entry.answer, "category": entry.category}
            for _, entry in scored[:limit]
        ]

    def add(self, keywords: list[str], answer: str, category: str = "通用") -> FaqEntry:
        entry = FaqEntry(keywords=tuple(keywords), answer=answer, category=category)
        self._entries.append(entry)
        self._matcher = FaqMatcher(self._entries)
        return entry

    def remove(self, index: int) -> bool:
        if 0 <= index < len(self._entries):
            self._entries.pop(index)
            self._matcher = FaqMatcher(self._entries)
            return True
        return False

    def list(self) -> list[dict[str, str]]:
        return [
            {"index": str(i), "keywords": "、".join(e.keywords), "answer": e.answer, "category": e.category}
            for i, e in enumerate(self._entries)
        ]
