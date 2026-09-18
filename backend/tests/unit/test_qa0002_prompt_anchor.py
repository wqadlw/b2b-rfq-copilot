"""QA-0002 回归：prompt 引用的上下文锚点标签 ⊆ 渲染器实际产出集（契约一致性）。

修复前：base.md/security.md 引用 `<retrieved_context>`，而渲染器只产出
platform_context/merchant_context 具名块——锚点失效，注入防护条款悬空。
修复后：渲染器输出 `<retrieved_context>` 信封（内嵌信任分块），本测试钉死三方合同。
"""

import re
from pathlib import Path

from rfq_copilot.core.rag.citation import (
    RETRIEVED_CONTEXT_TAG,
    Chunk,
    context_anchor_tags,
    render_context,
)

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "src" / "rfq_copilot" / "prompts" / "system"


def test_render_wraps_output_in_envelope() -> None:
    chunks = [
        Chunk("doc-1", 0, "平台", "平台内容", "platform"),
        Chunk("doc-2", 0, "商户", "商户内容", "merchant", supplier_id="s-001"),
    ]
    context = render_context(chunks)
    assert context.startswith(f"<{RETRIEVED_CONTEXT_TAG}>")
    assert context.rstrip().endswith(f"</{RETRIEVED_CONTEXT_TAG}>")
    # 信任分块仍嵌套在信封内
    assert '<platform_context trusted="true">' in context
    assert '<merchant_context trusted="false" supplier_id="s-001">' in context


def test_render_empty_chunks_returns_empty_string() -> None:
    assert render_context([]) == ""


def test_prompts_reference_only_produced_context_tags() -> None:
    """一致性合同：system prompt 里引用的 <*_context> 标签必须是渲染器能产出的。"""
    referenced: set[str] = set()
    for md in sorted(PROMPTS_DIR.glob("*.md")):
        for match in re.finditer(r"<([a-z_]*context)[^>]*>", md.read_text(encoding="utf-8")):
            referenced.add(match.group(1))
    assert referenced, "system prompt 中未找到任何 context 锚点（测试失效，请检查 prompts 目录）"
    produced = context_anchor_tags()
    stray = referenced - produced
    assert not stray, f"prompt 引用了渲染器不产出的锚点标签：{sorted(stray)}（QA-0002 回归）"
