"""Integration: 离线目录按站点语义应用同义词/屏蔽词（fixture 数据目录）。"""

import json
from pathlib import Path

import pytest

from rfq_copilot.adapters.zhaozhenkong_offline.zzk_catalog import ZzkProductCatalog
from rfq_copilot.ports.product_catalog import ProductSearchQuery

pytestmark = pytest.mark.asyncio


def _knowledge(*names) -> dict:
    documents = []
    for i, name in enumerate(names, 1):
        documents.append(
            {
                "doc_id": f"zzk-product-{i}",
                "title": name,
                "content": f"产品名称：{name}\n供应商：示例供应商\n价格：请联系供应商询价\n详情：{name} 设备",
                "doc_type": "product",
            }
        )
    return {"documents": documents}


def _data_dir(tmp_path: Path, names, meta: dict | None) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "zzk_knowledge.json").write_text(json.dumps(_knowledge(*names), ensure_ascii=False), encoding="utf-8")
    if meta is not None:
        (tmp_path / "zzk_search_meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return tmp_path


async def test_synonym_expansion_widens_recall(tmp_path: Path) -> None:
    """核心断言（词集不相交的场景）：无同义词搜不到；有同义词能搜到。

    说明：目录匹配是中文二元组 OR 召回，"螺杆泵" 与 "螺杆式真空泵" 已共享二元组
    「螺杆」，因此那种组合本来就命中——同义词的真实价值在词集完全不相交时体现
    （如 "液环泵" 与 "水环真空泵"：液环/环泵 vs 水环/环真/真空/空泵）。
    """
    names = ["水环真空泵"]
    without = ZzkProductCatalog(str(_data_dir(tmp_path / "a", names, None)))
    result = await without.search(ProductSearchQuery(keyword="液环泵"))
    assert result.total == 0  # 无元数据 → 无扩词 → 词集不相交，搜不到

    with_meta = ZzkProductCatalog(str(_data_dir(tmp_path / "b", names, {"synonyms": {"液环泵": "水环泵"}})))
    result2 = await with_meta.search(ProductSearchQuery(keyword="液环泵"))
    assert result2.total == 1 and result2.items[0].name == "水环真空泵"


async def test_whole_query_synonym_replacement(tmp_path: Path) -> None:
    """站点语义：整串替换（查"无油泵"直接改查"无油真空泵"）。"""
    cat = ZzkProductCatalog(str(_data_dir(tmp_path, ["无油真空泵"], {"synonyms": {"无油泵": "无油真空泵"}})))
    result = await cat.search(ProductSearchQuery(keyword="无油泵"))
    assert result.total == 1


async def test_block_words_return_empty_result(tmp_path: Path) -> None:
    cat = ZzkProductCatalog(str(_data_dir(tmp_path, ["真空泵"], {"block_words": ["赌博"]})))
    blocked = await cat.search(ProductSearchQuery(keyword="赌博 真空泵"))
    assert blocked.total == 0 and blocked.items == []
    allowed = await cat.search(ProductSearchQuery(keyword="真空泵"))
    assert allowed.total == 1


async def test_search_meta_property_exposed(tmp_path: Path) -> None:
    cat = ZzkProductCatalog(str(_data_dir(tmp_path, ["真空泵"], {"synonyms": {"a": "b"}, "block_words": ["c"]})))
    assert cat.search_meta.enabled is True
    assert cat.search_meta.synonyms == {"a": "b"}
