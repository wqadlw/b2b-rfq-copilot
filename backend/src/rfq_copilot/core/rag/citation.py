"""Trust-isolated context rendering + citation post-validation (port-spec §6.3, architect guide §4)."""

import html
import re

from rfq_copilot.core.rag.chunking import Chunk

CITATION_PATTERN = re.compile(r"\[(\d+)\]")

# QA-0002 单一事实源：外层信封是 system prompt 引用的锚点（spec §01 6.3）；
# 内层按信任级分块。prompt 侧引用的 <*_context> 标签必须 ⊆ context_anchor_tags()。
RETRIEVED_CONTEXT_TAG = "retrieved_context"
PLATFORM_CONTEXT_TAG = "platform_context"
MERCHANT_CONTEXT_TAG = "merchant_context"


def context_anchor_tags() -> frozenset[str]:
    """渲染器可能产出的全部具名标签（信封 + 信任分块），供一致性测试对照。"""
    return frozenset({RETRIEVED_CONTEXT_TAG, PLATFORM_CONTEXT_TAG, MERCHANT_CONTEXT_TAG})


def _escape(text: str) -> str:
    """Escape angle brackets/& so merchant content cannot forge context tags."""
    return html.escape(text, quote=False)


def render_context(chunks: list[Chunk]) -> str:
    """Group retrieved chunks by trust level into isolated XML blocks with [n] ids."""
    blocks: list[str] = []
    platform = [(i + 1, c) for i, c in enumerate(chunks) if c.trust_level == "platform"]
    merchant = [(i + 1, c) for i, c in enumerate(chunks) if c.trust_level != "platform"]
    if platform:
        lines = "\n".join(f"[{i}] {_escape(c.content)}" for i, c in platform)
        blocks.append(f'<platform_context trusted="true">\n{lines}\n</platform_context>')
    by_supplier: dict[str, list[tuple[int, Chunk]]] = {}
    for i, c in merchant:
        by_supplier.setdefault(c.supplier_id or "unknown", []).append((i, c))
    for supplier_id, pairs in by_supplier.items():
        lines = "\n".join(f"[{i}] {_escape(c.content)}" for i, c in pairs)
        blocks.append(
            f'<merchant_context trusted="false" supplier_id="{_escape(supplier_id)}">\n{lines}\n</merchant_context>'
        )
    body = "\n\n".join(blocks)
    return f"<{RETRIEVED_CONTEXT_TAG}>\n{body}\n</{RETRIEVED_CONTEXT_TAG}>" if body else ""


def validate_citations(answer: str, chunk_count: int) -> tuple[str, list[str]]:
    """Strip hallucinated [n] citations; returns (clean_answer, invalid_ids)."""
    invalid: list[str] = []

    def _sub(match: re.Match[str]) -> str:
        n = int(match.group(1))
        if 1 <= n <= chunk_count:
            return match.group(0)
        invalid.append(match.group(1))
        return ""

    cleaned = CITATION_PATTERN.sub(_sub, answer)
    return cleaned, invalid
