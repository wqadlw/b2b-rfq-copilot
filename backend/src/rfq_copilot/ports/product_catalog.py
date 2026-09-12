"""ProductCatalogPort (authority: docs/specs/01-port-spec.md §3.1)."""

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel, Field


class PriceDisplay(BaseModel):
    """Site-derived display price. AI may only echo ``text`` verbatim when mode=shown."""

    mode: Literal["shown", "contact"]
    text: str


class ProductSearchQuery(BaseModel):
    keyword: str
    category_id: str | None = None
    supplier_id: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=10, ge=1, le=20)


class DocRef(BaseModel):
    doc_id: str
    title: str


class ProductSummary(BaseModel):
    id: str
    name: str
    category_name: str
    brand_name: str | None = None
    supplier_id: str
    supplier_name: str
    specs: dict[str, str]
    price_display: PriceDisplay
    url: str


class ProductDetail(ProductSummary):
    description: str
    params: dict[str, str]
    documents: list[DocRef] = Field(default_factory=list)
    updated_at: datetime | None = None


class ProductSearchResult(BaseModel):
    items: list[ProductSummary]
    total: int


class ProductCatalogPort(Protocol):
    def search(self, query: ProductSearchQuery) -> Awaitable[ProductSearchResult] | ProductSearchResult: ...

    def get_detail(self, product_id: str) -> Awaitable[ProductDetail | None] | ProductDetail | None: ...


ProductCatalogFactory = Callable[[], ProductCatalogPort]
