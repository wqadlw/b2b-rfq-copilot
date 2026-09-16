"""Guest zero-LLM turn handlers: tool-data answers for visitors (G1/G2 free tier).

安全边界：全部回答只由工具数据（端口结果/检索原文）拼装，不经过 LLM 生成——
没有编造风险；价格只逐字引用 price_display（shown 模式），contact 模式固定话术。
设计参考：电商 faceted search 的直搜 + chatwoot help-center 的文章引用。
"""

from __future__ import annotations

import inspect
import re
from typing import Any

from rfq_copilot.adapters.zhaozhenkong_offline.zzk_solutions import (
    detect_solution_query as detect_solution_query,
)
from rfq_copilot.core.agent.graph import _humanize_spec_value
from rfq_copilot.core.manifest import Manifest
from rfq_copilot.core.rag.pipeline import RAGPipeline
from rfq_copilot.ports.product_catalog import ProductCatalogPort

# demo 词表（G1 触发词）——真实站点接入时由 manifest chat.free_search_keywords 配置
# G1 触发词表：站点官方分类核心词 ∪ 同义词表用户词（2026-09-16 导入 49 条）∪ 常见简称。
# 词表越长覆盖越广；均为"产品词"，不会误伤供应商/厂家类提问（那些走 SUPPLIER_LIST_RE）。
DEFAULT_PRODUCT_WORDS: tuple[str, ...] = (
    # 官方分类核心词
    "真空泵",
    "真空机组",
    "真空系统",
    "真空阀门",
    "真空管件",
    "真空法兰",
    "密封圈",
    "波纹管",
    "观察窗",
    "真空计",
    "规管",
    "检漏仪",
    "残余气体分析仪",
    "真空泵油",
    "扩散泵油",
    "真空硅脂",
    "冷水机",
    "干燥过滤器",
    "真空泵维修",
    "保养服务",
    "真空配件",
    # 泵型（官方分类 + 口语简称 + 写法变体）
    "旋片泵",
    "旋片真空泵",
    "旋片式真空泵",
    "螺杆泵",
    "螺杆真空泵",
    "螺杆式真空泵",
    "罗茨泵",
    "罗茨真空泵",
    "罗茨式真空泵",
    "水环泵",
    "水环真空泵",
    "水环式真空泵",
    "液环泵",
    "液环真空泵",
    "分子泵",
    "涡轮分子泵",
    "涡轮泵",
    "涡旋泵",
    "涡旋真空泵",
    "涡旋式真空泵",
    "扩散泵",
    "油扩散泵",
    "干泵",
    "干式泵",
    "干式螺杆泵",
    "干式涡旋泵",
    "油泵",
    # 机组
    "泵组",
    "真空泵组",
    "罗茨旋片机组",
    "罗茨螺杆机组",
    "罗茨水环机组",
    # 其他高频词
    "无油真空泵",
    "无油泵",
    "真空泵油雾过滤器",
    "胶圈",
    "O型圈",
    "硅脂",
    "法兰盘",
    "维修服务",
    "真空规",
)
DEMO_ID_RE = re.compile(r"demo-p-\d+")


def detect_guest_query(message: str) -> str:
    """G1 命中判定：明确产品词或产品编号。返回搜索词；不命中返回空串。"""
    text = message.strip()
    if DEMO_ID_RE.search(text):
        return DEMO_ID_RE.search(text).group(0)  # type: ignore[union-attr]
    hits = [word for word in DEFAULT_PRODUCT_WORDS if word in text]
    if hits:
        return max(hits, key=len)  # 最长命中优先：'螺杆真空泵' 不被 '真空泵' 短词截胡
    return ""


SUPPLIER_LIST_RE = re.compile(r"供应商|厂家|厂商|服务商")


def detect_guest_inquiry_intent(message: str) -> bool:
    """游客询盘意图白名单：明确要求发起询盘（创建流程走 0-token 工具链+确认卡）。"""
    text = message.strip()
    return bool(text) and ("询盘" in text or "询价" in text or "要买" in text or "求购" in text)


def detect_supplier_query(message: str, suppliers: Any) -> str:
    """G3 命中判定：点名公司（前6字）→ 详情；供应商类词 → 列表。返回 supplier_id | "list" | ""。

    供应商档案是站点公开内容（0 token、工具拼装），游客可浏览。
    """
    text = message.strip()
    items: list[Any] = list(getattr(suppliers, "_suppliers", []) or [])
    for s in items:
        name = str(getattr(s, "name", ""))
        if name[:6] and name[:6] in text:
            return str(getattr(s, "id", ""))
    if SUPPLIER_LIST_RE.search(text):
        return "list"
    return ""


async def guest_supplier_answer(mode: str, suppliers: Any) -> dict[str, Any]:
    """G3: 供应商列表/档案（0 token）。返回 SSE 事件载荷（含 card 结构化事件）。"""
    import inspect as _inspect

    events: list[tuple[str, dict[str, Any]]] = []
    if suppliers is None:
        return {"answer": "当前环境未接入供应商目录。", "events": events, "finish": "answered"}
    if mode == "list":
        items = list(getattr(suppliers, "_suppliers", []) or [])[:5]
        lines = ["以下是为您找到的供应商（并列供参考，可按需联系）："]
        for s in items:
            cert_text = "、".join(s.certifications) if s.certifications else "无认证信息"
            region_text = s.region or "地区未标注"
            lines.append(f"- {s.name}（{region_text}｜{cert_text}）")
            events.append(("citation", {"title": s.name, "url": s.url, "trust": "platform"}))
            events.append(
                (
                    "card",
                    {
                        "kind": "supplier",
                        "name": s.name,
                        "region": s.region,
                        "certs": list(s.certifications),
                        "main_products": list(s.main_products),
                        "description": "平台认证供应商",
                        "url": s.url,
                    },
                )
            )
        lines.append("提交询盘后供应商会主动与您联系；登录后可获得 AI 匹配推荐。")
        return {"answer": "\n".join(lines), "events": events, "finish": "answered"}
    detail_out = suppliers.get_detail(mode)
    detail: Any = await detail_out if _inspect.isawaitable(detail_out) else detail_out
    if detail is None:
        return {
            "answer": "未找到该公司档案，可告诉我您需要的设备类型，我来帮您匹配供应商。",
            "events": events,
            "finish": "answered",
        }
    events.append(("citation", {"title": detail.name, "url": detail.url, "trust": "merchant"}))
    events.append(
        (
            "card",
            {
                "kind": "supplier",
                "name": detail.name,
                "region": detail.region,
                "certs": list(detail.certifications),
                "main_products": list(detail.main_products),
                "description": detail.description or "",
                "url": detail.url,
            },
        )
    )
    intro = detail.description or "该公司档案完善中。"
    certs = "、".join(detail.certifications) if detail.certifications else "认证信息完善中"
    region = detail.region or "地区未标注"
    cats = "、".join(detail.main_products[:4]) if detail.main_products else "真空设备"
    answer = (
        f"{detail.name}（{region}｜{certs}）\n\n"
        f"公司简介：{intro}\n\n"
        f"主营：{cats}\n\n"
        "如需询价或了解更多，可提交询盘，供应商会主动与您联系。"
    )
    return {"answer": answer, "events": events, "finish": "answered"}


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
        events.append(
            (
                "card",
                {
                    "kind": "product",
                    "name": detail.name,
                    "supplier": detail.supplier_name,
                    "brand": detail.brand_name,
                    "category": detail.category_name,
                    "price": price,
                    "url": detail.url,
                    "specs": {k: _humanize_spec_value(v) for k, v in list(detail.specs.items())[:3]},
                },
            )
        )
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
    # 回答形式与 graph 产品流对齐：数据交给卡片（最多 10 张，前端分页），文本只做简短引导
    seen_names: set[str] = set()
    deduped: list[Any] = []
    for item in result.items:
        if item.name in seen_names:
            continue
        seen_names.add(item.name)
        deduped.append(item)
    shown = deduped[:10]
    for item in shown:
        price = item.price_display.text if item.price_display.mode == "shown" else "请联系供应商询价"
        events.append(("citation", {"title": item.name, "url": item.url, "trust": "merchant"}))
        events.append(
            (
                "card",
                {
                    "kind": "product",
                    "name": item.name,
                    "supplier": item.supplier_name,
                    "brand": item.brand_name,
                    "category": item.category_name,
                    "price": price,
                    "url": item.url,
                    "specs": {k: _humanize_spec_value(v) for k, v in list(item.specs.items())[:3]},
                },
            )
        )
    answer = (
        f"为您找到 {len(result.items)} 款相关产品，点击卡片可查看参数与详情。"
        "登录后可对比参数、匹配供应商并创建询盘；也可以直接发起询盘。"
    )
    return {"answer": answer, "events": events, "finish": "answered"}


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
