"""KnowledgeSourcePort (authority: docs/specs/01-port-spec.md §3.3).

Document *provider* for ingestion: chunking/embedding/retrieval live in core rag.
"""

from collections.abc import Iterator
from typing import Literal, Protocol

from pydantic import BaseModel

TrustLevel = Literal["platform", "merchant", "ugc"]
DocType = Literal["platform_faq", "selection_guide", "policy", "product", "merchant_article"]


class KnowledgeDocument(BaseModel):
    doc_id: str
    title: str
    doc_type: DocType
    trust_level: TrustLevel
    content: str
    supplier_id: str | None = None
    product_id: str | None = None
    category_id: str | None = None
    # 01-port-spec §6.4.1：结构化产品参数（键值对，值须为字符串；非产品块为 None）
    params: dict[str, str] | None = None
    version: str = "1"
    language: str = "zh-CN"


class IngestScope(BaseModel):
    doc_types: list[DocType] | None = None


class KnowledgeSourcePort(Protocol):
    def iter_documents(self, scope: IngestScope | None = None) -> Iterator[KnowledgeDocument]: ...

    def fingerprint(self) -> str: ...
