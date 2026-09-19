"""Chunking: documents → ordered chunks with propagated trust metadata."""

from dataclasses import dataclass

from rfq_copilot.ports.knowledge_source import KnowledgeDocument, TrustLevel

MAX_CHARS = 500


@dataclass(frozen=True)
class Chunk:
    doc_id: str
    chunk_index: int
    title: str
    content: str
    trust_level: TrustLevel
    supplier_id: str | None = None
    product_id: str | None = None
    category_id: str | None = None
    # 01-port-spec §6.4.1：结构化产品参数（随文档透传到所有分块；非产品块为 None）
    params: dict[str, str] | None = None


def chunk_document(doc: KnowledgeDocument, max_chars: int = MAX_CHARS) -> list[Chunk]:
    """Paragraph-pack chunking: split on blank lines, greedily pack up to max_chars."""
    base = {
        "doc_id": doc.doc_id,
        "title": doc.title,
        "trust_level": doc.trust_level,
        "supplier_id": doc.supplier_id,
        "product_id": doc.product_id,
        "category_id": doc.category_id,
        "params": doc.params,
    }
    paragraphs = [p.strip() for p in doc.content.replace("\r\n", "\n").split("\n\n") if p.strip()]
    if not paragraphs:
        paragraphs = [doc.content.strip()]
    packed: list[str] = []
    buffer = ""
    for para in paragraphs:
        if len(para) > max_chars:  # oversized paragraph: hard-split, flushing any pending buffer
            if buffer:
                packed.append(buffer)
                buffer = ""
            for start in range(0, len(para), max_chars):
                packed.append(para[start : start + max_chars])
            continue
        candidate = f"{buffer}\n\n{para}" if buffer else para
        if len(candidate) <= max_chars or not buffer:
            buffer = candidate[:max_chars]
        else:
            packed.append(buffer)
            buffer = para[:max_chars]
    if buffer:
        packed.append(buffer)
    return [
        Chunk(chunk_index=index, content=text, **base)  # type: ignore[arg-type]
        for index, text in enumerate(packed)
    ]
