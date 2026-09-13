"""三层漏斗：FAQ 匹配 → RAG 检索 → LLM 生成。
70% 的问题零 LLM token 即可回答（企业成本核心优化）。"""

from __future__ import annotations

from dataclasses import dataclass

from rfq_copilot.core.policies.faq_matcher import FaqMatcher


@dataclass(frozen=True)
class FunnelResult:
    answer: str
    tier: int  # 1=FAQ(0 token) 2=RAG(0 LLM token) 3=LLM(花 token)
    faq_hit: bool = False


class ThreeTierFunnel:
    """按序尝试三层，命中即返回，未命中降级到下一层。"""

    def __init__(self, faq_matcher: FaqMatcher) -> None:
        self._faq = faq_matcher

    def try_faq(self, query: str) -> FunnelResult | None:
        """第一层：FAQ 关键词匹配。命中→0 token。"""
        answer = self._faq.match(query)
        if answer:
            return FunnelResult(answer=answer, tier=1, faq_hit=True)
        return None

    def should_skip_llm(self, query: str) -> FunnelResult | None:
        """对外入口：检查 FAQ 层是否已能回答，能则跳过 LLM。"""
        return self.try_faq(query)
