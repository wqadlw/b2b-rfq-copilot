"""vacuum_b2b_sample: five ports over the internal HTTP API (sanitized example).

Real deployment reads VACUUM_API_BASE_URL / VACUUM_API_TOKEN from the environment;
nothing here contains real domains, tokens or private field mappings (repo-policy).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ValidationError

from rfq_copilot.adapters.vacuum_b2b_sample.client import VacuumInternalClient
from rfq_copilot.ports.errors import ConfigError, UpstreamInvalidResponseError
from rfq_copilot.ports.inquiry_sink import InquiryDraft, InquiryResult, InquirySinkPort
from rfq_copilot.ports.lead_distribution import DistributionResult, LeadCandidate, LeadDistributionPort
from rfq_copilot.ports.product_catalog import (
    ProductCatalogPort,
    ProductDetail,
    ProductSearchQuery,
    ProductSearchResult,
)
from rfq_copilot.ports.supplier_directory import (
    SupplierDirectoryPort,
    SupplierSearchQuery,
    SupplierSearchResult,
)


def _stringify_ids(value: Any) -> Any:
    """Site PKs are ints; port schemas are str — coerce id-ish keys recursively."""
    if isinstance(value, list):
        return [_stringify_ids(v) for v in value]
    if isinstance(value, dict):
        return {
            k: (str(v) if (k.endswith("_id") or k == "id") and isinstance(v, int) else _stringify_ids(v))
            for k, v in value.items()
        }
    return value


def _model[T: BaseModel](model_cls: type[T], payload: Any) -> T:
    try:
        try:
            return model_cls.model_validate(payload)
        except ValidationError:
            return model_cls.model_validate(_stringify_ids(payload))
    except ValidationError as exc:
        raise UpstreamInvalidResponseError(f"upstream payload violates {model_cls.__name__}") from exc


class VacuumSampleProductCatalog(ProductCatalogPort):
    def __init__(self, client: VacuumInternalClient) -> None:
        self._client = client

    async def search(self, query: ProductSearchQuery) -> ProductSearchResult:
        payload = await self._client.get_json(
            "/internal-api/v1/products/search",
            params={"keyword": query.keyword, "page": query.page, "page_size": query.page_size},
        )
        return _model(ProductSearchResult, payload)

    async def get_detail(self, product_id: str) -> ProductDetail | None:
        payload = await self._client.get_json(f"/internal-api/v1/products/{product_id}")
        return _model(ProductDetail, payload) if payload else None


class VacuumSampleSupplierDirectory(SupplierDirectoryPort):
    def __init__(self, client: VacuumInternalClient) -> None:
        self._client = client

    async def search(self, query: SupplierSearchQuery) -> SupplierSearchResult:
        payload = await self._client.get_json(
            "/internal-api/v1/suppliers",
            params={"keyword": query.keyword or "", "product_id": query.product_id or ""},
        )
        return _model(SupplierSearchResult, payload)

    async def get_detail(self, supplier_id: str) -> None:
        raise NotImplementedError("sample adapter: supplier detail not exposed in phase 1")


class VacuumSampleInquirySink(InquirySinkPort):
    def __init__(self, client: VacuumInternalClient) -> None:
        self._client = client

    async def create(self, draft: InquiryDraft) -> InquiryResult:
        payload = await self._client.post_json(
            "/internal-api/v1/inquiries",
            {
                "source": "ai_chat",
                "session_id": draft.session_id,
                "idempotency_key": draft.idempotency_key,
                "product_id": draft.product_id,
                "title": f"AI 询盘 {draft.session_id}",
                "quantity": draft.quantity,
                "params_text": "；".join(f"{k}:{v}" for k, v in draft.params.items()),
                "contact_name": draft.contact.name,
                "contact_phone": draft.contact.phone,
                "message": draft.message,
                "lead_score": draft.lead_score,
                "ai_extract": draft.ai_extract.model_dump(),
            },
        )
        return _model(InquiryResult, payload)


class VacuumSampleLeadDistribution(LeadDistributionPort):
    async def submit(self, lead: LeadCandidate) -> DistributionResult:
        # marketplace promotion is site-side (scheduled scan); adapter never triggers it
        return DistributionResult(distributed=False, channel="site_scan", reference_id=lead.inquiry_id)


def build_vacuum_sample_ports(base_url: str, token: str) -> dict[str, Any]:
    if not base_url or not token:
        raise ConfigError("vacuum_b2b_sample requires VACUUM_API_BASE_URL and VACUUM_API_TOKEN")
    client = VacuumInternalClient(base_url=base_url, token=token)
    return {
        "catalog": VacuumSampleProductCatalog(client),
        "suppliers": VacuumSampleSupplierDirectory(client),
        "inquiry_sink": VacuumSampleInquirySink(client),
        "lead_distribution": VacuumSampleLeadDistribution(),
    }
