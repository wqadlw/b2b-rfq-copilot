"""Guest zero-LLM turn handlers: tool-data answers for visitors (G1/G2 free tier).

安全边界：全部回答只由工具数据（端口结果/检索原文）拼装，不经过 LLM 生成——
没有编造风险；价格只逐字引用 price_display（shown 模式），contact 模式固定话术。
设计参考：电商 faceted search 的直搜 + chatwoot help-center 的文章引用。
"""

from __future__ import annotations

import inspect
import re
from typing import Any

from rfq_copilot.core.manifest import Manifest
from rfq_copilot.core.rag.pipeline import RAGPipeline
from rfq_copilot.ports.product_catalog import ProductCatalogPort

# demo 词表（G1 触发词）——真实站点接入时由 manifest chat.free_search_keywords 配置
DEFAULT_PRODUCT_WORDS: tuple[str, ...] = ("真空泵", "真空阀门", "真空管件", "真空计", "旋片泵", "涡旋泵", "分子泵")
DEMO_ID_RE = re.compile(r"demo-p-\d+")


def detect_guest_query(message: str) -> str:
    """G1 命中判定：明确产品词或产品编号。返回搜索词；不命中返回空串。"""
    text = message.strip()
    if DEMO_ID_RE.search(text):
        return DEMO_ID_RE.search(text).group(0)  # type: ignore[union-attr]
    for word in DEFAULT_PRODUCT_WORDS:
        if word in text:
            return word
    return ""


def looks_like_knowledge_query(message: str) -> bool:
    """G2 命中判定：知识/政策/流程类问题（启发式：问句词 + 不含产品词的短问句）。"""
    knowledge_markers = (
        "怎么选",
        "如何选",
        "有什么区别",
        "区别",
        "流程",
        "政策",
        "规则",
        "怎么用",
        "如何使用",
        "什么是",
        "什么是",
        "原理",
        "适用",
        "适合",
    )
    return any(marker in message for marker in knowledge_markers)


async def guest_search_answer(query: str, catalog: ProductCatalogPort | None, manifest: Manifest) -> dict[str, Any]:
    """G1: 直搜产品/编号查询（0 token）。返回 SSE 事件载荷。"""
    events: list[tuple[str, dict[str, Any]]] = []
    if catalog is None:
        return {"answer": "当前环境未接入产品库。", "events": events, "finish": "answered"}

    # 编号查询走 get_detail
    if DEMO_ID_RE.fullmatch(query):
        detail_out = catalog.get_detail(query)
        detail: Any = await detail_out if inspect.isawaitable(detail_out) else detail_out
        if detail is None:
            return {
                "answer": f"未找到产品 {query}。请确认编号，或登录后让我帮您匹配。",
                "events": events,
                "finish": "answered",
            }
        price = detail.price_display.text if detail.price_display.mode == "shown" else "请联系供应商询价"
        specs = "；".join(f"{k}:{v}" for k, v in list(detail.specs.items())[:4]) or "参数详见详情页"
        events.append(("citation", {"title": detail.name, "url": detail.url, "trust": "merchant"}))
        answer = (
            f"{detail.name}（{detail.supplier_name}）\n主要参数：{specs}\n价格：{price}\n"
            "登录后可对比同类产品、匹配供应商并创建询盘。"
        )
        return {"answer": answer, "events": events, "finish": "answered"}

    from rfq_copilot.ports.product_catalog import ProductSearchQuery

    search_out = catalog.search(ProductSearchQuery(keyword=query[:40], page_size=10))
    result: Any = await search_out if inspect.isawaitable(search_out) else search_out
    if not result.items:
        return {
            "answer": f"暂未找到与「{query}」相关的产品。您可以登录后描述需求，我来帮您匹配；或直接提交询盘。",
            "events": events,
            "finish": "answered",
        }
    lines = [f"为您找到 {len(result.items)} 件相关产品（游客可浏览，登录后可深度咨询与创建询盘）："]
    for i, item in enumerate(result.items[:3], start=1):
        price = item.price_display.text if item.price_display.mode == "shown" else "请联系供应商询价"
        lines.append(f"{i}. {item.name}（{item.supplier_name}）｜{price}")
        events.append(("citation", {"title": item.name, "url": item.url, "trust": "merchant"}))
    lines.append("登录后可查看参数对比、规格匹配与供应商推荐。")
    return {"answer": "\n".join(lines), "events": events, "finish": "answered"}


async def guest_knowledge_answer(message: str, rag: RAGPipeline | None, manifest: Manifest) -> dict[str, Any] | None:
    """G2: 知识检索引用（0 token）——列文档标题+原文片段；RAG 未启用返回 None 落回登录引导。"""
    if rag is None:
        return None
    chunks = await rag.search(message)
    if not chunks:
        return None
    lines = ["找到以下相关资料（游客可读原文，登录后可获得 AI 提炼的完整答案）："]
    for i, chunk in enumerate(chunks[:3], start=1):
        snippet = chunk.content[:80].replace("\n", " ")
        lines.append(f"{i}. 《{chunk.title}》（{chunk.trust_level}）：{snippet}…")
    lines.append("以上为原文摘录；登录后我将基于资料给出完整分析与建议。")
    events: list[tuple[str, dict[str, Any]]] = [
        ("retrieval", {"count": len(chunks[:3]), "trust": [c.trust_level for c in chunks[:3]]}),
        *(("citation", {"title": c.title, "trust": c.trust_level}) for c in chunks[:3]),
    ]
    return {"answer": "\n".join(lines), "events": events, "finish": "answered"}
