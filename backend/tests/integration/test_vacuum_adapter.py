"""Contract tests for the vacuum sample adapter (respx-mocked internal API)."""

import json
from typing import Any

import httpx
import pytest
import respx

from rfq_copilot.adapters.vacuum_b2b_sample.adapter import build_demo_ports, build_vacuum_sample_ports
from rfq_copilot.app.runtime import build_runtime
from rfq_copilot.config.settings import get_settings
from rfq_copilot.ports.errors import (
    ConfigError,
    PortTimeoutError,
    UpstreamAuthError,
    UpstreamInvalidResponseError,
    UpstreamUnavailableError,
)
from rfq_copilot.ports.inquiry_sink import Contact, InquiryDraft, InquiryResult
from rfq_copilot.ports.product_catalog import ProductSearchQuery

BASE = "https://internal-api.example.com"


def _ports() -> tuple:
    ports = build_vacuum_sample_ports(base_url=BASE, token="test-token")
    return ports, ports.catalog


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
async def test_search_forwards_query_params() -> None:
    """回归：get_json 必须透传 params（曾因丢弃 params 导致站点侧过滤失效）。"""
    _, catalog = _ports()
    route = respx.get(f"{BASE}/internal-api/v1/products/search").respond(200, json={"items": [], "total": 0})
    await catalog.search(ProductSearchQuery(keyword="2XZ", page=2, page_size=5))
    assert route.called
    sent = route.calls[0].request.url.params
    assert sent["keyword"] == "2XZ" and sent["page"] == "2" and sent["page_size"] == "5"


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
    sink = ports.inquiry_sink
    ok = respx.post(f"{BASE}/internal-api/v1/inquiries").respond(201, json={"inquiry_id": 77, "state": "created"})
    result = await sink.create(_draft())
    assert isinstance(result, InquiryResult) and result.inquiry_id == "77"
    assert ok.call_count == 1

    respx.post(f"{BASE}/internal-api/v1/inquiries").respond(201, json={"wrong": "shape"})
    from rfq_copilot.ports.errors import UpstreamInvalidResponseError

    with pytest.raises(UpstreamInvalidResponseError):  # contract violation surfaced, never silent
        await sink.create(_draft())


# ---------------------------------------------------------------------------
# 阶段二：真通道契约对齐（站点 InternalApiController::storeInquiry 为权威）
# ---------------------------------------------------------------------------


def _sent_body(route: Any) -> dict:
    return json.loads(route.calls[0].request.content)


@pytest.mark.asyncio
@respx.mock
async def test_inquiry_payload_matches_site_contract() -> None:
    """站点要求嵌套 contact.*；扁平 contact_* 会被 422 拒收（回归防护）。"""
    ports, _ = _ports()
    route = respx.post(f"{BASE}/internal-api/v1/inquiries").respond(201, json={"inquiry_id": 77, "state": "created"})
    await ports.inquiry_sink.create(_draft())
    body = _sent_body(route)

    assert body["contact"] == {"name": "张三", "phone": "13800000000"}  # 嵌套，且空值不发送
    assert "contact_name" not in body and "contact_phone" not in body
    assert "source" not in body  # 站点自行标记 source=ai_chat，适配器不得冒名
    assert body["session_id"] == "sess-t"
    assert body["idempotency_key"] == "key-1"
    assert body["lead_score"] == 50
    assert body["ai_extract"]["intent"] == "inquiry_flow"
    # 非数字 product_id（"demo-p-001"）不得发送：站点校验 integer|exists 会直接拒收
    assert "product_id" not in body


@pytest.mark.asyncio
@respx.mock
async def test_inquiry_payload_coerces_numeric_ids_and_params() -> None:
    """数字型端口 id 必须转 int 发送；params 走 params_text 拼接。"""
    ports, _ = _ports()
    route = respx.post(f"{BASE}/internal-api/v1/inquiries").respond(201, json={"inquiry_id": 78, "state": "created"})
    draft = _draft().model_copy(
        update={"product_id": "123", "user_ref": "42", "category_id": "9", "params": {"极限真空度": "1Pa"}}
    )
    await ports.inquiry_sink.create(draft)
    body = _sent_body(route)

    assert body["product_id"] == 123 and isinstance(body["product_id"], int)
    assert body["user_ref"] == 42 and isinstance(body["user_ref"], int)
    assert body["category_id"] == 9
    assert body["params_text"] == "极限真空度:1Pa"


@pytest.mark.asyncio
@respx.mock
async def test_inquiry_idempotent_replay_200_is_success() -> None:
    """站点对同一 idempotency_key 的重放返回 200（非 201）——必须视为成功。"""
    ports, _ = _ports()
    respx.post(f"{BASE}/internal-api/v1/inquiries").respond(
        200, json={"inquiry_id": 77, "state": "created", "missing_fields": []}
    )
    result = await ports.inquiry_sink.create(_draft())
    assert result.inquiry_id == "77" and result.state == "created"


@pytest.mark.asyncio
@respx.mock
async def test_inquiry_validation_rejection_is_contract_failure() -> None:
    """422 是契约失败而非上游故障：必须显式上报，且不得被吞掉。"""
    ports, _ = _ports()
    route = respx.post(f"{BASE}/internal-api/v1/inquiries").respond(422, json={"message": "bad"})
    with pytest.raises(UpstreamInvalidResponseError):
        await ports.inquiry_sink.create(_draft())
    assert route.call_count == 1  # 4xx 不重试（重试坏载荷毫无意义）


def test_build_demo_ports_requires_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    """半配置的真通道必须大声失败，不得静默降级。"""
    get_settings.cache_clear()
    monkeypatch.setenv("INTERNAL_API_BASE_URL", "")
    monkeypatch.setenv("INTERNAL_API_TOKEN", "")
    with pytest.raises(ConfigError):
        build_demo_ports()

    monkeypatch.setenv("INTERNAL_API_BASE_URL", "https://internal-api.example.com")
    monkeypatch.setenv("INTERNAL_API_TOKEN", "unit-test-token")
    get_settings.cache_clear()
    ports = build_demo_ports()
    assert all(
        getattr(ports, name) is not None for name in ("catalog", "suppliers", "inquiry_sink", "lead_distribution")
    )
    get_settings.cache_clear()


def test_runtime_can_select_vacuum_sample_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    """回归：适配器此前缺 build_demo_ports，runtime 选它必然 AttributeError。"""
    get_settings.cache_clear()
    monkeypatch.setenv("INTERNAL_API_BASE_URL", "https://internal-api.example.com")
    monkeypatch.setenv("INTERNAL_API_TOKEN", "unit-test-token")
    monkeypatch.setenv("KNOWLEDGE_DATA_DIR", "")
    get_settings.cache_clear()
    runtime = build_runtime(adapter="vacuum_b2b_sample")
    assert runtime.manifest.adapter == "vacuum_b2b_sample"
    assert runtime.deps.inquiry_sink is not None
    assert runtime.deps.catalog is not None
    get_settings.cache_clear()
