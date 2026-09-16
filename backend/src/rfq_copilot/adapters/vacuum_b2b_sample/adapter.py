"""vacuum_b2b_sample: five ports over the internal HTTP API (sanitized example).

Real deployment reads VACUUM_API_BASE_URL / VACUUM_API_TOKEN from the environment;
nothing here contains real domains, tokens or private field mappings (repo-policy).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ValidationError

from rfq_copilot.adapters.vacuum_b2b_sample.client import VacuumInternalClient
from rfq_copilot.config.settings import get_settings
from rfq_copilot.ports.bundle import AdapterPorts
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


def _as_int(value: str | None) -> int | None:
    """Site PKs are integers (validated `integer|exists`); port ids are str — coerce when numeric."""
    return int(value) if value is not None and value.isdigit() else None


class VacuumSampleInquirySink(InquirySinkPort):
    r"""POST /internal-api/v1/inquiries — payload mirrors the site's validation contract.

    Contract (site InternalApiController::storeInquiry):
    - `contact` is nested and `contact.name` / `contact.phone` are required
      (phone must match ^1[3-9]\d{9}$); flat contact_* keys are rejected.
    - `user_ref` / `product_id` / `category_id` are nullable integers with exists rules,
      so a non-numeric port id is omitted rather than sent to fail validation.
    - 201 = created, 200 = idempotent replay of the same idempotency_key.
    """

    def __init__(self, client: VacuumInternalClient) -> None:
        self._client = client

    async def create(self, draft: InquiryDraft) -> InquiryResult:
        contact: dict[str, Any] = {"name": draft.contact.name, "phone": draft.contact.phone}
        if draft.contact.company:
            contact["company"] = draft.contact.company
        if draft.contact.email:
            contact["email"] = draft.contact.email
        body: dict[str, Any] = {
            "session_id": draft.session_id,
            "idempotency_key": draft.idempotency_key,
            "title": f"AI询盘-{draft.session_id}",
            "message": draft.message,
            "lead_score": draft.lead_score,
            "ai_extract": draft.ai_extract.model_dump(),
            "contact": contact,
        }
        for site_key in ("user_ref", "product_id", "category_id"):
            coerced = _as_int(getattr(draft, site_key))
            if coerced is not None:
                body[site_key] = coerced
        if draft.quantity is not None:
            body["quantity"] = draft.quantity
        if draft.params:
            body["params_text"] = "；".join(f"{k}:{v}" for k, v in draft.params.items())
        payload = await self._client.post_json("/internal-api/v1/inquiries", body)
        return _model(InquiryResult, payload)


class VacuumSampleLeadDistribution(LeadDistributionPort):
    async def submit(self, lead: LeadCandidate) -> DistributionResult:
        # marketplace promotion is site-side (scheduled scan); adapter never triggers it
        return DistributionResult(distributed=False, channel="site_scan", reference_id=lead.inquiry_id)


def build_demo_ports() -> AdapterPorts:
    """Runtime entrypoint: configure the adapter from env-backed settings.

    Requires INTERNAL_API_BASE_URL and INTERNAL_API_TOKEN (fail loudly when unset —
    a half-configured real channel must never silently degrade to nothing).
    """
    settings = get_settings()
    return build_vacuum_sample_ports(base_url=settings.internal_api_base_url, token=settings.internal_api_token)


def build_vacuum_sample_ports(base_url: str, token: str) -> AdapterPorts:
    if not base_url or not token:
        raise ConfigError("vacuum_b2b_sample requires INTERNAL_API_BASE_URL and INTERNAL_API_TOKEN")
    client = VacuumInternalClient(base_url=base_url, token=token)
    return AdapterPorts(
        catalog=VacuumSampleProductCatalog(client),
        suppliers=VacuumSampleSupplierDirectory(client),
        inquiry_sink=VacuumSampleInquirySink(client),
        lead_distribution=VacuumSampleLeadDistribution(),
    )
