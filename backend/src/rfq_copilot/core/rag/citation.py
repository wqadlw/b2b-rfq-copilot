"""Trust-isolated context rendering + citation post-validation (port-spec §6.3, architect guide §4)."""

import html
import re

from rfq_copilot.core.rag.chunking import Chunk

CITATION_PATTERN = re.compile(r"\[(\d+)\]")


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
    return "\n\n".join(blocks)


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
