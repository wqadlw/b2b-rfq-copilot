"""vacuum_b2b_sample: five ports over the internal HTTP API (sanitized example).

Real deployment reads VACUUM_API_BASE_URL / VACUUM_API_TOKEN from the environment;
nothing here contains real domains, tokens or private field mappings (repo-policy).
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ValidationError

from rfq_copilot.adapters.vacuum_b2b_sample.client import VacuumInternalClient
from rfq_copilot.config.settings import get_settings
from rfq_copilot.ports.bundle import AdapterPorts
from rfq_copilot.ports.errors import ConfigError, UpstreamInvalidResponseError
from rfq_copilot.ports.inquiry_sink import InquiryDraft, InquiryResult, InquirySinkPort
from rfq_copilot.ports.inquiry_status import InquiryStatusPort
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

FALLBACK_TERM_MIN_LEN = 2
FALLBACK_MAX_QUERIES = 3


def _fallback_terms(keyword: str) -> list[str]:
    """零结果回退的候选子查询（站点检索为整串 LIKE，自然复合词会零结果）。

    纯中文复合词按"前缀 2 字 → 后缀 3 字 → 前缀 3 字"排序：
    前缀通常是限定词（"无油…"里的无油），后缀通常是设备大类（"…真空泵"），
    按此顺序合并后，首页结果由更具体的限定词主导。
    含空白/标点的查询先按分隔符切分。最多 3 个候选，避免放大上游调用量。
    """
    kw = keyword.strip()
    candidates: list[str] = []
    if not kw:
        return []
    for part in re.split(r"[\s,\uff0c\u3001;\uff1b/\uff0f]+", kw):
        if part and part != kw:
            candidates.append(part)
    if re.fullmatch(r"[\u4e00-\u9fff]+", kw) and len(kw) > FALLBACK_TERM_MIN_LEN:
        candidates.extend([kw[:2], kw[-3:], kw[:3]])

    seen: set[str] = set()
    out: list[str] = []
    for term in candidates:
        if len(term) >= FALLBACK_TERM_MIN_LEN and term not in seen and term != kw:
            seen.add(term)
            out.append(term)
    return out[:FALLBACK_MAX_QUERIES]


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
        """站点检索（整串 LIKE）+ 零结果回退（拆词重查合并）。

        站点内部 API 只做 `name LIKE %kw% OR model LIKE %kw%`：自然复合词
        （"无油真空泵"）因名字里没有连续整串而零结果，而"无油"有 14 条。
        回退仅在**首页零结果**时触发：按候选子查询依次重查并合并去重，
        本地分页（page>1 不触发，避免分页语义不一致）。
        """
        payload = await self._client.get_json(
            "/internal-api/v1/products/search",
            params={"keyword": query.keyword, "page": query.page, "page_size": query.page_size},
        )
        primary = _model(ProductSearchResult, payload)
        if primary.total > 0 or not query.keyword.strip():
            return primary

        # 零结果回退对任意 page 生效：合并全集后本地分页，保证 page1/page2 语义一致
        # （此前 page>1 不触发回退，会出现"第 1 页有回退结果、第 2 页为空"的断层）。
        terms = _fallback_terms(query.keyword)
        if not terms:
            return primary

        merged: dict[str, Any] = {}
        for term in terms:
            fallback_payload = await self._client.get_json(
                "/internal-api/v1/products/search",
                params={"keyword": term, "page": 1, "page_size": 50},
            )
            for item in _model(ProductSearchResult, fallback_payload).items:
                merged.setdefault(item.id, item)
        merged_list = list(merged.values())
        start = (query.page - 1) * query.page_size
        items = merged_list[start : start + query.page_size]
        return ProductSearchResult(items=items, total=len(merged_list))

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


class VacuumSampleInquiryStatus(InquiryStatusPort):
    """GET /internal-api/v1/inquiries/status?session_id=…（只读状态摘要）。"""

    def __init__(self, client: VacuumInternalClient) -> None:
        self._client = client

    async def by_session(self, session_id: str) -> dict[str, Any]:
        payload = await self._client.get_json_with_params(
            "/internal-api/v1/inquiries/status", params={"session_id": session_id}
        )
        return payload if isinstance(payload, dict) else {"items": [], "total": 0}


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
        inquiry_status=VacuumSampleInquiryStatus(client),
        lead_distribution=VacuumSampleLeadDistribution(),
    )
