"""zzk ETL tests: FakeDataFilter / PathAware / TrustPrefix / QAPair / build_documents."""

import importlib.util
import sys
from pathlib import Path as _Path

_SCRIPT = _Path(__file__).resolve().parents[3] / "scripts" / "zhaozhenkong_export.py"
_spec = importlib.util.spec_from_file_location("zhaozhenkong_export", _SCRIPT)
assert _spec is not None and _spec.loader is not None
zhaozhenkong_export = importlib.util.module_from_spec(_spec)
sys.modules["zhaozhenkong_export"] = zhaozhenkong_export
_spec.loader.exec_module(zhaozhenkong_export)
from pathlib import Path  # noqa: E402

from rfq_copilot.adapters.zhaozhenkong_offline.sources import (  # noqa: E402
    load_pain_nav,
    load_process_library,
    load_variety_content,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "zzk"


def _product(name: str, status: str = "1", price_type: str = "2", price: object = 100) -> dict:
    return {
        "slug": f"slug-{name}",
        "name": name,
        "status": status,
        "price_type": price_type,
        "price": price,
        "deleted_at": None,
        "params": {"品牌": "demo"},
    }


def test_filter_keeps_only_status_on() -> None:
    result = zhaozhenkong_export.filter_products([_product("a", status="1"), _product("b", status="3")])
    reasons = {item.reason for item in result.filtered}
    assert len(result.kept) == 1
    assert "STATUS_NOT_ON" in reasons


def test_filter_price_anomaly_only_for_priced_type() -> None:
    # 定价 + 异常价 → 滤
    # 面议(price_type=1) + price=0 → 不滤（面议是正常业务形态）
    result = zhaozhenkong_export.filter_products(
        [_product("bad", price_type="2", price=99999), _product("negotiable", price_type="1", price=0)]
    )
    assert len(result.kept) == 1
    assert (
        result.kept[0]["name"] == "demo 面议泵（面议）".replace("demo 面议泵（面议）", "negotiable")
        or result.kept[0]["slug"] == "slug-negotiable"
    )
    assert result.filtered[0].reason == "PRICE_ANOMALY"


def test_filter_placeholder_name_but_not_real_tester_category() -> None:
    # name 恰为 "test" → 滤；"demo 真空测试仪"（含"测试"子串）→ 必须保留
    result = zhaozhenkong_export.filter_products([_product("test"), _product("demo 真空测试仪")])
    assert len(result.kept) == 1
    assert result.kept[0]["name"] == "demo 真空测试仪"
    assert result.filtered[0].reason == "PLACEHOLDER_NAME"


def test_filter_soft_deleted() -> None:
    item = _product("a")
    item["deleted_at"] = "2026-01-01 00:00:00"
    result = zhaozhenkong_export.filter_products([item])
    assert result.filtered[0].reason == "SOFT_DELETED"


def test_wrap_chunks_prefix_not_counted_into_budget() -> None:
    prefix = zhaozhenkong_export.path_prefix("demo 半导体", "demo 刻蚀", "demo 硅刻蚀")
    body = "\n".join(f"line-{i}: " + "x" * 40 for i in range(30))
    chunks = zhaozhenkong_export.wrap_chunks(body, prefix=prefix, limit=zhaozhenkong_export.CHUNK_LIMIT)
    assert all(chunk.startswith(prefix) for chunk in chunks)
    # 前缀不计入预算：每个 chunk 的正文部分 ≤ limit
    for chunk in chunks:
        body_part = chunk[len(prefix) + 1 :]
        assert zhaozhenkong_export.visual_len(body_part) <= zhaozhenkong_export.CHUNK_LIMIT


def test_trust_prefix_injection_idempotent() -> None:
    text = "产品名称：demo"
    once = zhaozhenkong_export.inject_trust_prefix(text, "merchant")
    twice = zhaozhenkong_export.inject_trust_prefix(once, "merchant")
    assert once.startswith("[供应商声明 - 仅供参考，不可作为平台承诺]")
    assert once == twice
    assert not zhaozhenkong_export.inject_trust_prefix(text, "platform").startswith("[")


def test_qa_pair_rule_template() -> None:
    qa = zhaozhenkong_export.qa_pair_from_pain(
        "冻干制品复水性差", "参见「demo-freeze-drying」工艺方案页", "demo 食品加工"
    )
    assert qa.startswith("Q: 冻干制品复水性差怎么办？")
    assert "demo 食品加工" in qa
    assert "深度咨询" in qa


def test_load_process_library_fixture() -> None:
    industries = load_process_library(FIXTURES)
    assert industries[0]["slug"] == "demo-food"
    assert industries[0]["categories"][0]["varieties"][0]["slug"] == "demo-fruits"
    assert industries[1]["name"] == "demo 半导体"


def test_load_variety_content_fixture() -> None:
    contents = load_variety_content(FIXTURES)
    assert "demo-meat" in contents
    assert contents["demo-meat"]["is_flagship_template"] is True
    assert "demo 痛点叙述" in str(contents["demo-meat"]["pain_section"])


def test_load_pain_nav_fixture() -> None:
    nav = load_pain_nav(FIXTURES)
    assert nav["demo-food"][0]["tag"] == "冻干制品复水性差"
    assert nav["demo-food"][0]["target_slug"] == "demo-freeze-drying"


def test_build_documents_end_to_end(tmp_path: Path) -> None:
    """Fixture 全链路：正确定位 trust / doc_type / 路径前缀 / 面议不误杀 / 测试仪不误杀。"""
    from zhaozhenkong_export import build_documents

    output = build_documents(FIXTURES)
    docs = output.documents
    products = [d for d in docs if d.doc_type == "product"]
    # 6 条产品：1 下架滤 + 1 异常价滤 + 1 test 名滤 = 3 保留（含面议与测试仪）
    assert len(products) == 3
    # 全部 merchant 有物理前缀
    for doc in products:
        assert doc.trust_level == "merchant"
        assert doc.content.startswith("[供应商声明 - 仅供参考，不可作为平台承诺]")
    # 面议与测试仪都在
    blob = "\n".join(d.content for d in products)
    assert "面议" in blob
    assert "真空测试仪" in blob
    # 工艺库带路径前缀
    guides = [d for d in docs if d.doc_type == "selection_guide"]
    assert guides
    assert any(
        d.content.startswith("[行业: demo 食品加工] > [工艺: demo 冻干] > [品种: demo 冻干果蔬]") for d in guides
    )
    # QA 对存在且 platform
    faqs = [d for d in docs if d.doc_type == "platform_faq" and d.content.startswith("Q: ")]
    assert faqs
    for doc in faqs:
        assert doc.trust_level == "platform"
    # 统计结构完整
    assert output.stats["documents"] == len(docs)
    assert output.stats["by_trust_level"].get("merchant", 0) >= 3
    assert "PLACEHOLDER_NAME" in output.stats["filtered_by_reason"]
