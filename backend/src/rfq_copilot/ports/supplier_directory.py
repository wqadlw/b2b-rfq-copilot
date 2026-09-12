"""SupplierDirectoryPort (authority: docs/specs/01-port-spec.md §3.2)."""

from typing import Protocol

from pydantic import BaseModel, Field


class SupplierSummary(BaseModel):
    id: str
    name: str
    region: str | None = None
    main_products: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    is_verified: bool = False
    url: str


class SupplierDetail(SupplierSummary):
    description: str | None = None
    founded_year: int | None = None
    scale: str | None = None


class SupplierSearchQuery(BaseModel):
    keyword: str | None = None
    product_id: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=10, ge=1, le=20)


class SupplierSearchResult(BaseModel):
    items: list[SupplierSummary]
    total: int


class SupplierDirectoryPort(Protocol):
    async def search(self, query: SupplierSearchQuery) -> SupplierSearchResult: ...

    async def get_detail(self, supplier_id: str) -> SupplierDetail | None: ...
