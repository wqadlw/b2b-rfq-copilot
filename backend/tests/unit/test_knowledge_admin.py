"""knowledge_admin 数据层 + core 增量单测（spec 02 §2.0/§2.2/§2.4）。"""

import pytest

from rfq_copilot.app import knowledge_admin
from rfq_copilot.core.rag.chunking import chunk_document
from rfq_copilot.core.rag.embedding import HashingEmbedder
from rfq_copilot.core.rag.keyword import rrf_fuse, rrf_fuse_scored
from rfq_copilot.core.rag.pipeline import AdminUnsupported, RAGPipeline
from rfq_copilot.core.rag.reranker import NoopReranker
from rfq_copilot.ports.knowledge_source import KnowledgeDocument


def _doc(doc_id: str, content: str, doc_type: str = "product") -> KnowledgeDocument:
    return KnowledgeDocument(
        doc_id=doc_id, title=f"标题{doc_id}", doc_type=doc_type, trust_level="platform", content=content
    )


def test_chunk_propagates_doc_type() -> None:
    chunks = chunk_document(_doc("d1", "第一段。\n\n第二段。", doc_type="selection_guide"))
    assert all(c.doc_type == "selection_guide" for c in chunks)


def test_base_doc_id_strips_family_suffix() -> None:
    assert knowledge_admin.base_doc_id("product-123") == "product-123"
    assert knowledge_admin.base_doc_id("product-123 (2/3)") == "product-123"


def test_family_map_groups_and_sorts() -> None:
    chunks = []
    for doc_id in ("b (1/2)", "a", "b (2/2)"):
        chunks.extend(chunk_document(_doc(doc_id, "内容。")))
    families = knowledge_admin.family_map(chunks)
    assert list(families) == ["a", "b"]  # doc_id 字典序
    assert len(families["b"]) == 2  # 家族归并：(1/2)+(2/2)


def test_doc_summary_hash_source_manifest_wins(tmp_path) -> None:  # type: ignore[no-untyped-def]
    chunks = chunk_document(_doc("d1", "正文内容。"))
    manifest_hashes = {"d1": "abcdef1234567890"}
    summary = knowledge_admin.doc_summary("d1", chunks, manifest_hashes)
    assert summary["hash_source"] == "manifest" and summary["content_hash"] == "abcdef1234567890"
    summary = knowledge_admin.doc_summary("d1", chunks, {})
    assert summary["hash_source"] == "reconstructed"
    assert len(summary["content_hash"]) == 64  # sha256 hex


def test_rrf_fuse_scored_matches_rrf_fuse_order() -> None:
    chunks_a = chunk_document(_doc("a", "真空泵 旋片 无油。"))
    chunks_b = chunk_document(_doc("b", "水环泵 真空 机组。"))
    scored = rrf_fuse_scored(chunks_a, chunks_b, top_k=5)
    plain = rrf_fuse(chunks_a, chunks_b, top_k=5)
    assert [c for c, _ in scored] == plain
    scores = [s for _, s in scored]
    assert scores == sorted(scores, reverse=True)  # 分数降序
    assert all(s > 0 for s in scores)


@pytest.mark.asyncio
async def test_corpus_rejects_non_inmemory() -> None:
    class AlienStore:
        async def count(self) -> int:
            return 0

    pipeline = RAGPipeline(embedder=HashingEmbedder(), store=AlienStore(), reranker=NoopReranker())  # type: ignore[arg-type]
    with pytest.raises(AdminUnsupported):
        await pipeline.corpus()


def test_predict_route_signals() -> None:
    assert knowledge_admin.predict_route("我要询盘")["predicted_route"] == "inquiry_flow"
    # master 词表含「有什么区别」；「哪个更重要」类补词在 citation-url-followups 分支（未合并）
    selection = knowledge_admin.predict_route("旋片泵和螺杆泵有什么区别")
    assert selection["predicted_route"] == "knowledge_flow"
    assert any("selection_consult" in s for s in selection["signals"])
    assert knowledge_admin.predict_route("我的询盘到哪一步了")["predicted_route"] == "inquiry_status"
