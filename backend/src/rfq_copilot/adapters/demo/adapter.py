"""Demo adapter: in-memory implementations of the five ports (clone-and-run profile)."""

import logging
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from rfq_copilot.adapters.demo import data
from rfq_copilot.ports.inquiry_sink import InquiryDraft, InquiryResult, InquirySinkPort
from rfq_copilot.ports.knowledge_source import IngestScope, KnowledgeDocument, KnowledgeSourcePort
from rfq_copilot.ports.lead_distribution import (
    DistributionResult,
    LeadCandidate,
    LeadDistributionPort,
)
from rfq_copilot.ports.product_catalog import (
    ProductCatalogPort,
    ProductDetail,
    ProductSearchQuery,
    ProductSearchResult,
    ProductSummary,
)
from rfq_copilot.ports.supplier_directory import (
    SupplierDetail,
    SupplierDirectoryPort,
    SupplierSearchQuery,
    SupplierSearchResult,
    SupplierSummary,
)

logger = logging.getLogger(__name__)


def _zh_terms(query: str) -> set[str]:
    """Naive zh matcher: 2-gram sliding window + ascii tokens (M0; M1 uses proper tokenization)."""
    import re

    ascii_tokens = set(re.findall(r"[A-Za-z0-9-]{2,}", query))
    han = re.sub(r"[^\u4e00-\u9fff]", "", query)
    bigrams = {han[i : i + 2] for i in range(len(han) - 1)}
    return bigrams | ascii_tokens


class DemoProductCatalog(ProductCatalogPort):
    async def search(self, query: ProductSearchQuery) -> ProductSearchResult:
        kw = query.keyword.strip()
        if not kw:
            hits = list(data.PRODUCTS)
        else:
            terms = _zh_terms(kw)
            hits = [
                p
                for p in data.PRODUCTS
                if any(term in p.name or term in p.category_name or term in p.description for term in terms)
            ]
        start = (query.page - 1) * query.page_size
        page = hits[start : start + query.page_size]
        items = [ProductSummary.model_validate(p.model_dump()) for p in page]
        return ProductSearchResult(items=items, total=len(hits))

    async def get_detail(self, product_id: str) -> ProductDetail | None:
        return next((p for p in data.PRODUCTS if p.id == product_id), None)


class DemoSupplierDirectory(SupplierDirectoryPort):
    async def search(self, query: SupplierSearchQuery) -> SupplierSearchResult:
        if query.product_id:
            supplier_id = next((p.supplier_id for p in data.PRODUCTS if p.id == query.product_id), None)
            hits = [s for s in data.SUPPLIERS if s.id == supplier_id] if supplier_id else []
        else:
            kw = (query.keyword or "").strip()
            hits = [s for s in data.SUPPLIERS if not kw or kw in s.name or any(kw in m for m in s.main_products)]
        items = [SupplierSummary.model_validate(s.model_dump()) for s in hits[: query.page_size]]
        return SupplierSearchResult(items=items, total=len(hits))

    async def get_detail(self, supplier_id: str) -> SupplierDetail | None:
        return next((s for s in data.SUPPLIERS if s.id == supplier_id), None)


class DemoKnowledgeSource(KnowledgeSourcePort):
    def __init__(self, docs: list[KnowledgeDocument]) -> None:
        self._docs = docs

    def iter_documents(self, scope: IngestScope | None = None) -> Iterator[KnowledgeDocument]:
        docs = self._docs
        if scope and scope.doc_types:
            docs = [d for d in docs if d.doc_type in scope.doc_types]
        return iter(docs)

    def fingerprint(self) -> str:
        return f"demo-{len(self._docs)}"


@dataclass
class DemoInquiryStore:
    inquiries: list[dict[str, Any]] = field(default_factory=list)
    keys: set[str] = field(default_factory=set)


class DemoInquirySink(InquirySinkPort):
    def __init__(self, store: DemoInquiryStore) -> None:
        self._store = store

    async def create(self, draft: InquiryDraft) -> InquiryResult:
        if draft.idempotency_key in self._store.keys:
            existing = next(i for i in self._store.inquiries if i["idempotency_key"] == draft.idempotency_key)
            return InquiryResult(inquiry_id=existing["inquiry_id"], state="created")
        inquiry_id = f"demo-inq-{len(self._store.inquiries) + 1:04d}"
        self._store.keys.add(draft.idempotency_key)
        self._store.inquiries.append(
            {
                "inquiry_id": inquiry_id,
                "idempotency_key": draft.idempotency_key,
                "user_ref": draft.user_ref,
                "lead_score": draft.lead_score,
            }
        )
        logger.info("demo inquiry created: %s", inquiry_id)
        return InquiryResult(inquiry_id=inquiry_id, state="created")


class DemoInquiryStatus:
    """会话内询盘状态摘要（demo store 直查；status_flow 用）。"""

    def __init__(self, store: DemoInquiryStore) -> None:
        self._store = store

    async def by_session(self, session_id: str) -> dict[str, Any]:
        """demo 语义：store 无 session 维度，返回空集——状态查询在 demo 模式下诚实报告"无记录"。"""
        return {"items": [], "total": 0}


class DemoLeadDistribution(LeadDistributionPort):
    async def submit(self, lead: LeadCandidate) -> DistributionResult:
        logger.info("demo lead candidate logged: %s score=%s", lead.inquiry_id, lead.lead_score)
        return DistributionResult(distributed=False, channel="log", reference_id=lead.inquiry_id)


@dataclass
class DemoPorts:
    catalog: DemoProductCatalog
    suppliers: DemoSupplierDirectory
    knowledge: DemoKnowledgeSource
    inquiry_sink: DemoInquirySink
    lead_distribution: DemoLeadDistribution
    inquiry_status: DemoInquiryStatus = field(default=None)  # type: ignore[assignment]
    store: DemoInquiryStore = field(default_factory=DemoInquiryStore)


def build_demo_ports() -> DemoPorts:
    store = DemoInquiryStore()
    return DemoPorts(
        catalog=DemoProductCatalog(),
        suppliers=DemoSupplierDirectory(),
        knowledge=DemoKnowledgeSource(data.DOCS + data.POISON_DOCS),
        inquiry_sink=DemoInquirySink(store),
        lead_distribution=DemoLeadDistribution(),
        inquiry_status=DemoInquiryStatus(store),
        store=store,
    )
