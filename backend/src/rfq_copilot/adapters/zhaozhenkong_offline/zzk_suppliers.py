# -*- coding: utf-8 -*-
"""ZZK 供应商目录 v3：处理两种块形态（多行字段块 + 单行压缩块）。"""
from pathlib import Path
import json
import re

from rfq_copilot.ports.supplier_directory import (
    SupplierDirectoryPort,
    SupplierSearchQuery,
    SupplierSearchResult,
    SupplierSummary,
)

SEEDER_PATH = Path(r"D:\AAAAA\zhaozhenkong\database\seeders\SupplierSeeder.php")


def _certs(block: str) -> list[str]:
    certs = []
    if "is_realname' => true" in block:
        certs.append("实名认证")
    if "is_verified' => true" in block:
        certs.append("企业认证")
    if "is_iso' => true" in block:
        certs.append("ISO9001")
    return certs


def _field(block: str, key: str) -> str | None:
    m = re.search(rf"'{key}' => '([^']*)'", block)
    return m.group(1) if m else None


class ZzkSupplierDirectory(SupplierDirectoryPort):
    """真实找真空供应商目录（SupplierSeeder：1 多行块 + 4 单行压缩块 = 5 家）。"""

    def __init__(self, knowledge_data_dir: str | None = None) -> None:
        """与 ZzkProductCatalog 保持一致的签名：接收 knowledge_data_dir（回退数据源）。"""
        self._intros_by_id: dict[str, str] = {}
        self._suppliers: list[SupplierSummary] = []
        self._parse(SEEDER_PATH)
        if not self._suppliers and knowledge_data_dir:
            self._load_from_knowledge_json(Path(knowledge_data_dir))

    def _load_from_knowledge_json(self, data_dir: Path) -> None:
        payload_path = data_dir / "zzk_knowledge.json"
        if not payload_path.is_file():
            return
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        names: dict[str, None] = {}
        for doc in payload.get("documents", []):
            m = re.search(r"供应商（", doc.get("content", ""))
            for hit in re.findall(r"- ([^（]+)（", doc.get("content", "")):
                names.setdefault(hit.strip(), None)
        for i, name in enumerate(names, start=1):
            self._suppliers.append(
                SupplierSummary(
                    id=f"zzk-supplier-fallback-{i:03d}",
                    name=name,
                    region=None,
                    main_products=["真空设备"],
                    certifications=[],
                    url=f"/suppliers/{i}",
                )
            )

    def _parse(self, seeder_path: Path) -> None:
        if not seeder_path.is_file():
            return
        text = seeder_path.read_text(encoding="utf-8")

        # 形态 1：多行块 Supplier::create([ ... 多行字段 ... ])
        for block in re.split(r"Supplier::create\(\[", text)[1:]:
            end = block.find("]);")
            if end == -1:
                continue
            body = block[:end]
            slug = _field(body, "slug")
            name = _field(body, "company_name")
            if not (slug and name):
                continue
            self._intros_by_id[f"zzk-supplier-{slug}"] = _field(body, "intro") or ""
            self._suppliers.append(
                SupplierSummary(
                    id=f"zzk-supplier-{slug}",
                    name=name,
                    region=_field(body, "region"),
                    main_products=[c.strip() for c in (_field(body, "main_categories") or "真空设备").split("，")[0:3]],
                    certifications=_certs(body),
                    url=f"/suppliers/{slug}",
                )
            )

        # 形态 2：单行压缩块 ['slug' => ..., 'company_name' => ..., ...]
        for line in text.splitlines():
            if "['slug' =>" not in line or "company_name" not in line:
                continue
            slug = _field(line, "slug")
            name = _field(line, "company_name")
            if not (slug and name):
                continue
            cats = _field(line, "main_categories") or "真空设备"
            self._suppliers.append(
                SupplierSummary(
                    id=f"zzk-supplier-{slug}",
                    name=name,
                    region=_field(line, "region"),
                    main_products=[c.strip() for c in cats.split("、")[:3]] or ["真空设备"],
                    certifications=_certs(line),
                    url=f"/suppliers/{slug}",
                )
            )

        # 去重（按 id）并按 slug 排序
        seen: set[str] = set()
        unique: list[SupplierSummary] = []
        for s in self._suppliers:
            if s.id not in seen:
                seen.add(s.id)
                unique.append(s)
        self._suppliers = sorted(unique, key=lambda s: s.id)

    @property
    def count(self) -> int:
        return len(self._suppliers)

    async def search(self, query: SupplierSearchQuery) -> SupplierSearchResult:
        kw = (query.keyword or "").strip()
        if kw:
            terms = re.findall(r"[\u4e00-\u9fff]{2}|[A-Za-z0-9-]{2,}", kw)
            hits = [
                s
                for s in self._suppliers
                if any(term in s.name or any(term in m for m in s.main_products) for term in terms)
            ]
        else:
            hits = list(self._suppliers)
        return SupplierSearchResult(items=hits[: query.page_size], total=len(hits))

    async def get_detail(self, supplier_id: str):
        from rfq_copilot.ports.supplier_directory import SupplierDetail

        summary = next((s for s in self._suppliers if s.id == supplier_id), None)
        if summary is None:
            return None
        return SupplierDetail(
            **summary.model_dump(),
            description=self._intros_by_id.get(supplier_id, ""),
        )
