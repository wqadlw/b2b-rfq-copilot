"""知识只读端点的数据层（spec 02-engine-read-api-spec §2）。

家族归并规则与 store.remove_by_doc_id 的家族语义对齐：ETL 预分块会把文档拆成
`doc_id (i/n)` 命名的子文档——base_doc_id 剥后缀归并；chunk_document 产出的分块
天然同 doc_id。content_hash 双来源：离线 export_manifest.json（真值）/
分块重建（近似，超长段硬切边缘用例可能与站点侧不一致——对账以存在性+chunk_count 兜底）。
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from rfq_copilot.core.rag.chunking import Chunk

_FAMILY_SUFFIX = re.compile(r" \(\d+/\d+\)$")


def base_doc_id(doc_id: str) -> str:
    """`x (1/3)` → `x`（家族语义：精确 doc_id + 分块后缀，对齐 remove_by_doc_id）。"""
    return _FAMILY_SUFFIX.sub("", doc_id)


def load_manifest_hashes(knowledge_data_dir: str) -> dict[str, str]:
    """离线模式：export_manifest.json 的 doc_id → content_hash（文件缺失返回空）。"""
    if not knowledge_data_dir:
        return {}
    manifest = Path(knowledge_data_dir) / "export_manifest.json"
    if not manifest.is_file():
        return {}
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return {
        str(doc_id): str(entry.get("content_hash", ""))
        for doc_id, entry in (payload.get("documents") or {}).items()
        if isinstance(entry, dict)
    }


def family_map(corpus: list[Chunk]) -> dict[str, list[Chunk]]:
    """全量分块 → base doc_id 家族（chunks 按 chunk_index 升序）。"""
    families: dict[str, list[Chunk]] = {}
    for chunk in corpus:
        families.setdefault(base_doc_id(chunk.doc_id), []).append(chunk)
    for chunks in families.values():
        chunks.sort(key=lambda c: c.chunk_index)
    return dict(sorted(families.items()))  # doc_id 字典序：列表翻页确定性


def doc_summary(base_id: str, chunks: list[Chunk], manifest_hashes: dict[str, str]) -> dict[str, Any]:
    """家族 → 列表/详情条目（spec 02 §2.2）。无时间戳是数据缺口，v1 不提供。"""
    first = chunks[0]
    manifest_hash = manifest_hashes.get(base_id, "")
    if manifest_hash:
        content_hash, hash_source = manifest_hash, "manifest"
    else:
        reconstructed = "\n\n".join(c.content for c in chunks)
        content_hash, hash_source = hashlib.sha256(reconstructed.encode("utf-8")).hexdigest(), "reconstructed"
    return {
        "doc_id": base_id,
        "title": first.title,
        "doc_type": first.doc_type or "unknown",
        "trust_level": first.trust_level,
        "chunk_count": len(chunks),
        "supplier_id": first.supplier_id,
        "product_id": first.product_id,
        "category_id": first.category_id,
        "params": first.params,
        "content_hash": content_hash,
        "hash_source": hash_source,
    }


def chunk_payload(chunk: Chunk) -> dict[str, Any]:
    return {
        "chunk_index": chunk.chunk_index,
        "doc_id": chunk.doc_id,
        "title": chunk.title,
        "content": chunk.content,
        "trust_level": chunk.trust_level,
        "supplier_id": chunk.supplier_id,
        "product_id": chunk.product_id,
        "category_id": chunk.category_id,
        "params": chunk.params,
    }


def predict_route(query: str) -> dict[str, Any]:
    """确定性 routing 预测（spec 02 §2.4）：三护栏词表纯函数，免 LLM，best-effort。

    局限诚实声明：LLM 意图理解层无法离线复现——此处只报词表信号与保守预测，
    供运营侧理解"该问题大概率走哪条路由"，不作路由决策依据。
    """
    from rfq_copilot.core.agent.routing_guards import (
        INQUIRY_CREATE_MARKERS,
        SELECTION_CONSULT_MARKERS,
        SPEC_ROUTE_GUARDS,
        detect_inquiry_status_query,
    )
    from rfq_copilot.core.rag.spec_matcher import scan_spec_entities

    signals: list[str] = []
    if detect_inquiry_status_query(query):
        signals.append("inquiry_status_query")
    if any(m in query for m in INQUIRY_CREATE_MARKERS):
        signals.append("inquiry_create_marker")
    if any(m in query for m in SELECTION_CONSULT_MARKERS):
        signals.append("selection_consult_marker→knowledge_flow")
    spec_entities = scan_spec_entities(query)
    if spec_entities:
        signals.append(f"spec_entities:{sorted(spec_entities)}")
    if any(m in query for m in SPEC_ROUTE_GUARDS):
        signals.append("spec_route_guard")
    if "inquiry_status_query" in signals:
        predicted = "inquiry_status"
    elif "inquiry_create_marker" in signals:
        predicted = "inquiry_flow"
    elif "selection_consult_marker→knowledge_flow" in signals:
        # 对齐真实图序：选型咨询护栏（apply_selection_guard）压过规格信号——
        # 09-23 实证：规格概念对比问法被护栏改道 knowledge_flow，不进产品/规格匹配
        predicted = "knowledge_flow"
    elif "spec_entities" in signals or "spec_route_guard" in signals:
        predicted = "spec_match_flow"
    else:
        predicted = "knowledge_flow"
    return {"predicted_route": predicted, "signals": signals}
