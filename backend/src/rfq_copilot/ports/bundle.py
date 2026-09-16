"""Adapter port bundle: the composition contract between adapters and the runtime.

The runtime reads *attributes* (``ports.catalog`` …), never dict keys. Adapters that
return a bare ``dict`` were a latent incompatibility (the vacuum sample did, and the
runtime crashed with AttributeError only when that adapter was selected).
"""

from dataclasses import dataclass

from rfq_copilot.ports.inquiry_sink import InquirySinkPort
from rfq_copilot.ports.inquiry_status import InquiryStatusPort
from rfq_copilot.ports.lead_distribution import LeadDistributionPort
from rfq_copilot.ports.product_catalog import ProductCatalogPort
from rfq_copilot.ports.supplier_directory import SupplierDirectoryPort


@dataclass
class AdapterPorts:
    """Ports an adapter supplies; ``None`` means the manifest disabled that port."""

    catalog: ProductCatalogPort | None = None
    suppliers: SupplierDirectoryPort | None = None
    knowledge: object | None = None
    inquiry_sink: InquirySinkPort | None = None
    inquiry_status: InquiryStatusPort | None = None
    lead_distribution: LeadDistributionPort | None = None
