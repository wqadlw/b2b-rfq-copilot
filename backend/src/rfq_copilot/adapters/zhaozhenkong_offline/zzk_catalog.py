"""ZZK 真实产品目录（adapters/zhaozhenkong_offline）——从导出 JSON 构建ProductCatalogPort。

数据源：scripts/zhaozhenkong_export.py 的 --output-dir 产物 zzk_knowledge.json
（857 documents 中 doc_type=product 的 359 款真实产品，params/detail 已 ETL 清洗）。

防腐层注意：本类不 import core（import-linter 契约），复用 demo 的 _zh_terms 匹配器
思路以结构化实现；组合根（runtime）按 ProductCatalogPort 协议注入。
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from rfq_copilot.adapters.zhaozhenkong_offline.search_meta import SearchMeta
from rfq_copilot.ports.product_catalog import (
    PriceDisplay,
    ProductCatalogPort,
    ProductDetail,
    ProductSearchQuery,
    ProductSearchResult,
    ProductSummary,
)

DEFAULT_DATA_DIR = ".ai/private/zzk_rag_data"


def _zh_terms(query: str) -> set[str]:
    ascii_tokens = set(re.findall(r"[A-Za-z0-9-]{2,}", query))
    han = re.sub(r"[^\u4e00-\u9fff]", "", query)
    bigrams = {han[i : i + 2] for i in range(len(han) - 1)}
    return bigrams | ascii_tokens


def _strip_html(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html or "")
    return re.sub(r"\s+", " ", text).strip()


class ZzkProductCatalog(ProductCatalogPort):
    """真实找真空产品目录（内存态，进程启动时从导出 JSON 装载一次）。"""

    def __init__(self, data_dir: str | None = None) -> None:
        self._data_dir = Path(data_dir or DEFAULT_DATA_DIR)
        self._products: list[ProductDetail] = []
        self._meta = SearchMeta.load(self._data_dir)  # 同义词/屏蔽词（缺失即退化为空）
        self._load()

    @property
    def search_meta(self) -> SearchMeta:
        return self._meta

    def _load(self) -> None:
        payload_path = self._data_dir / "zzk_knowledge.json"
        if not payload_path.is_file():
            return
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        docs = payload.get("documents", [])
        by_product: dict[str, list[dict[str, Any]]] = {}
        for doc in docs:
            doc_id = str(doc.get("doc_id", ""))
            base = doc_id.split(" (")[0]
            by_product.setdefault(base, []).append(doc)

        for base_id, group in by_product.items():
            content_full = "\n".join(d["content"] for d in group)
            first = group[0]
            product_id = base_id.replace("zzk-product-", "")
            name = first.get("title", "")
            # 从正文提取字段（导出时已结构化写入）
            fields: dict[str, str] = {}
            for line in content_full.split("\n"):
                if "：" in line and len(line) < 120:
                    key, _, val = line.partition("：")
                    fields.setdefault(key.strip(), val.strip())
            supplier_name = fields.get("供应商", "找真空供应商")
            price_line = fields.get("价格", "请联系供应商询价")
            price_mode = "shown" if price_line.startswith("￥") or price_line.startswith("¥") else "contact"
            params = {k: v for k, v in fields.items() if k not in {"产品名称", "价格", "详情"} and v}
            self._products.append(
                ProductDetail(
                    id=product_id,
                    name=name,
                    category_name="真空设备",
                    brand_name=params.get("品牌"),
                    supplier_id="zzk-supplier",
                    supplier_name=supplier_name,
                    specs=dict(list(params.items())[:6]),
                    price_display=PriceDisplay(
                        mode="shown" if price_mode == "shown" else "contact",
                        text=price_line if price_mode == "shown" else "",
                    ),
                    url=f"/products/{product_id}",
                    description=_strip_html(fields.get("详情", ""))[:400],
                    params=params,
                )
            )
        self._products.sort(key=lambda p: p.id)

    @property
    def count(self) -> int:
        return len(self._products)

    async def search(self, query: ProductSearchQuery) -> ProductSearchResult:
        kw = query.keyword.strip()
        if kw and self._meta.is_blocked(kw):
            # 站点语义：屏蔽词命中直接空结果（SearchService::isBlocked）
            return ProductSearchResult(items=[], total=0)
        if kw:
            kw = self._meta.apply_query_synonym(kw)  # 站点语义：整串同义词替换
            terms = _zh_terms(kw) | self._meta.expand_terms(kw)  # 增强：分词级 OR 扩召回
            hits = [
                p
                for p in self._products
                if any(term in p.name or term in p.category_name or term in p.description for term in terms)
            ]
        else:
            hits = list(self._products)
        start = (query.page - 1) * query.page_size
        page = hits[start : start + query.page_size]
        items = [
            ProductSummary(
                id=p.id,
                name=p.name,
                category_name=p.category_name,
                brand_name=p.brand_name,
                supplier_id=p.supplier_id,
                supplier_name=p.supplier_name,
                specs=p.specs,
                price_display=p.price_display,
                url=p.url,
            )
            for p in page
        ]
        return ProductSearchResult(items=items, total=len(hits))

    async def get_detail(self, product_id: str) -> ProductDetail | None:
        return next((p for p in self._products if p.id == product_id), None)


@lru_cache
def load_zzk_catalog(data_dir: str | None = None) -> ZzkProductCatalog:
    return ZzkProductCatalog(data_dir)
