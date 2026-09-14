"""Capability manifest schema + loader (authority: docs/specs/01-port-spec.md §2)."""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from rfq_copilot.ports.errors import ConfigError

KNOWN_INQUIRY_FIELDS = frozenset({"contact_name", "contact_phone", "company", "email", "quantity", "region"})


def _search_features() -> list[Literal["search", "detail"]]:
    return ["search"]


class ProductCatalogPortCfg(BaseModel):
    enabled: bool = True
    features: list[Literal["search", "detail"]] = Field(default_factory=_search_features)


class SupplierDirectoryCfg(BaseModel):
    enabled: bool = True


class KnowledgeSourceCfg(BaseModel):
    enabled: bool = True
    doc_types: list[str] = Field(default_factory=list)


class InquirySinkCfg(BaseModel):
    enabled: bool = True
    guest_allowed: bool = True
    guest_action: Literal["require_registration", "capture_partial"] | None = None
    required_fields: list[str] = Field(default_factory=list)
    optional_fields: list[str] = Field(default_factory=list)


class LeadDistributionCfg(BaseModel):
    enabled: bool = True
    type: Literal["marketplace", "crm_webhook", "manual", "none"] = "none"


class PortsCfg(BaseModel):
    product_catalog: ProductCatalogPortCfg
    supplier_directory: SupplierDirectoryCfg
    knowledge_source: KnowledgeSourceCfg
    inquiry_sink: InquirySinkCfg
    lead_distribution: LeadDistributionCfg


class CapabilityFlag(BaseModel):
    enabled: bool = False


class CapabilitiesCfg(BaseModel):
    pricing: CapabilityFlag
    lead_time: CapabilityFlag
    stock: CapabilityFlag


class WechatCfg(BaseModel):
    """CS-1.5: WeChat one-on-one contact (site-private QR; demo uses placeholder)."""

    qrcode_url: str | None = None
    contact_name: str | None = None
    guidance_text: str | None = None


class ChatCfg(BaseModel):
    welcome_message: str | None = None
    suggested_questions: list[str] = Field(default_factory=list)
    theme_primary: str | None = None
    wechat: WechatCfg = Field(default_factory=WechatCfg)


class Manifest(BaseModel):
    manifest_version: int
    adapter: str
    display_name: str
    languages: list[str] = Field(default_factory=lambda: ["zh-CN"])
    ports: PortsCfg
    capabilities: CapabilitiesCfg
    chat: ChatCfg = ChatCfg()

    def disabled_capabilities(self) -> list[str]:
        return [name for name in ("pricing", "lead_time", "stock") if not getattr(self.capabilities, name).enabled]

    def enabled_port_names(self) -> list[str]:
        return [
            name
            for name in (
                "product_catalog",
                "supplier_directory",
                "knowledge_source",
                "inquiry_sink",
                "lead_distribution",
            )
            if getattr(self.ports, name).enabled
        ]


def _validate(manifest: Manifest, adapter_dir: Path) -> None:
    # V1 adapter name matches directory
    if manifest.adapter != adapter_dir.name:
        raise ConfigError(f"V1: adapter '{manifest.adapter}' != directory '{adapter_dir.name}'")
    # V3 inquiry field enums + disjoint
    req = set(manifest.ports.inquiry_sink.required_fields)
    opt = set(manifest.ports.inquiry_sink.optional_fields)
    unknown = (req | opt) - KNOWN_INQUIRY_FIELDS
    if unknown:
        raise ConfigError(f"V3: unknown inquiry fields {sorted(unknown)}")
    if req & opt:
        raise ConfigError(f"V3: fields both required and optional: {sorted(req & opt)}")
    # V4 guest rules
    sink = manifest.ports.inquiry_sink
    if sink.guest_allowed and sink.guest_action is not None:
        raise ConfigError("V4: guest_action must be omitted when guest_allowed is true")
    if not sink.guest_allowed and sink.guest_action is None:
        raise ConfigError("V4: guest_action required when guest_allowed is false")
    # V5 lead distribution
    ld = manifest.ports.lead_distribution
    if not ld.enabled and ld.type != "none":
        raise ConfigError("V5: lead_distribution.type must be 'none' when disabled")
    if ld.enabled and ld.type == "none":
        raise ConfigError("V5: lead_distribution.type required when enabled")
    # V6 catalog features
    if manifest.ports.product_catalog.enabled and "search" not in manifest.ports.product_catalog.features:
        raise ConfigError("V6: product_catalog features must contain 'search'")


def load_manifest(adapter_dir: Path) -> Manifest:
    """Load and validate ``manifest.yaml`` from an adapter package directory."""
    path = adapter_dir / "manifest.yaml"
    if not path.is_file():
        raise ConfigError(f"manifest.yaml not found in {adapter_dir}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigError("manifest.yaml must be a mapping")
    # V7: capabilities must be explicit
    caps = raw.get("capabilities")
    if not isinstance(caps, dict) or set(caps) != {"pricing", "lead_time", "stock"}:
        raise ConfigError("V7: capabilities must declare exactly pricing/lead_time/stock")
    manifest = Manifest.model_validate(raw)
    _validate(manifest, adapter_dir)
    return manifest
