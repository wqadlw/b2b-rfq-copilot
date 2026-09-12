"""Contract tests for the vacuum sample adapter (respx-mocked internal API)."""

import httpx
import pytest
import respx

from rfq_copilot.adapters.vacuum_b2b_sample.adapter import build_vacuum_sample_ports
from rfq_copilot.ports.errors import PortTimeoutError, UpstreamAuthError, UpstreamUnavailableError
from rfq_copilot.ports.inquiry_sink import Contact, InquiryDraft, InquiryResult
from rfq_copilot.ports.product_catalog import ProductSearchQuery

BASE = "https://internal-api.example.com"


def _ports() -> tuple:
    ports = build_vacuum_sample_ports(base_url=BASE, token="test-token")
    return ports, ports["catalog"]


def _draft() -> InquiryDraft:
    from rfq_copilot.ports.inquiry_sink import AiExtract

    return InquiryDraft(
        session_id="sess-t",
        product_id="demo-p-001",
        quantity=10,
        params={},
        message="询盘",
        contact=Contact(name="张三", phone="13800000000"),
        lead_score=50,
        ai_extract=AiExtract(intent="inquiry_flow", confidence=0.9),
        idempotency_key="key-1",
    )


@pytest.mark.asyncio
@respx.mock
async def test_search_maps_payload() -> None:
    _, catalog = _ports()
    respx.get(f"{BASE}/internal-api/v1/products/search").respond(
        200,
        json={
            "items": [
                {
                    "id": 1,
                    "name": "旋片泵",
                    "category_name": "真空泵",
                    "supplier_id": 5,
                    "supplier_name": "示例供应商",
                    "specs": {},
                    "price_display": {"mode": "contact", "text": "请联系供应商询价"},
                    "url": "/products/1",
                }
            ],
            "total": 1,
        },
    )
    result = await catalog.search(ProductSearchQuery(keyword="旋片泵"))
    assert result.total == 1 and result.items[0].name == "旋片泵"


@pytest.mark.asyncio
@respx.mock
async def test_server_error_retries_then_raises() -> None:
    _, catalog = _ports()
    route = respx.get(f"{BASE}/internal-api/v1/products/search").respond(500)
    with pytest.raises(UpstreamUnavailableError):
        await catalog.search(ProductSearchQuery(keyword="x"))
    assert route.call_count >= 2  # retry executed


@pytest.mark.asyncio
@respx.mock
async def test_timeout_maps_to_port_timeout() -> None:
    _, catalog = _ports()
    respx.get(f"{BASE}/internal-api/v1/products/search").mock(side_effect=httpx.ConnectTimeout("boom"))
    with pytest.raises(PortTimeoutError):
        await catalog.search(ProductSearchQuery(keyword="x"))


@pytest.mark.asyncio
@respx.mock
async def test_auth_rejection_maps_to_upstream_auth() -> None:
    _, catalog = _ports()
    respx.get(f"{BASE}/internal-api/v1/products/search").respond(403)
    with pytest.raises(UpstreamAuthError):
        await catalog.search(ProductSearchQuery(keyword="x"))


@pytest.mark.asyncio
@respx.mock
async def test_detail_404_maps_to_none() -> None:
    _, catalog = _ports()
    respx.get(f"{BASE}/internal-api/v1/products/999").respond(404)
    assert await catalog.get_detail("999") is None


@pytest.mark.asyncio
@respx.mock
async def test_inquiry_created_and_contract_failure() -> None:
    ports, _ = _ports()
    sink = ports["inquiry_sink"]
    ok = respx.post(f"{BASE}/internal-api/v1/inquiries").respond(201, json={"inquiry_id": 77, "state": "created"})
    result = await sink.create(_draft())
    assert isinstance(result, InquiryResult) and result.inquiry_id == "77"
    assert ok.call_count == 1

    respx.post(f"{BASE}/internal-api/v1/inquiries").respond(201, json={"wrong": "shape"})
    from rfq_copilot.ports.errors import UpstreamInvalidResponseError

    with pytest.raises(UpstreamInvalidResponseError):  # contract violation surfaced, never silent
        await sink.create(_draft())
