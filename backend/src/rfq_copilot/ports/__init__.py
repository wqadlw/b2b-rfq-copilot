"""Engine ports. Core depends only on this package (import-linter enforced).

Six ports per ADR-0006: catalog / suppliers / knowledge / inquiry_sink /
lead_distribution / inquiry_status. Adding a 7th requires a new ADR.
"""

from rfq_copilot.ports.errors import (
    CapabilityDisabledError,
    ConfigError,
    ConfirmationRequiredError,
    ContentPolicyRefusalError,
    CopilotError,
    GuestNotAllowedError,
    MissingRequiredFieldsError,
    PolicyError,
    PortError,
    PortTimeoutError,
    RateLimitError,
    UpstreamAuthError,
    UpstreamInvalidResponseError,
    UpstreamUnavailableError,
)
from rfq_copilot.ports.industry_knowledge import (
    Case,
    CasesPort,
    Solution,
    SolutionsPort,
)
from rfq_copilot.ports.inquiry_sink import (
    AiExtract,
    Contact,
    InquiryDraft,
    InquiryResult,
    InquirySinkPort,
)
from rfq_copilot.ports.inquiry_status import InquiryStatusPort
from rfq_copilot.ports.knowledge_source import (
    DocType,
    IngestScope,
    KnowledgeDocument,
    KnowledgeSourcePort,
    TrustLevel,
)
from rfq_copilot.ports.lead_distribution import (
    DistributionResult,
    LeadCandidate,
    LeadDistributionPort,
)
from rfq_copilot.ports.product_catalog import (
    DocRef,
    PriceDisplay,
    ProductCatalogPort,
    ProductDetail,
    ProductSearchQuery,
    ProductSearchResult,
    ProductSummary,
)
from rfq_copilot.ports.supplier_directory import (
    SupplierDetail,
    SupplierDirectoryPort,
    SupplierSearchQuery,
    SupplierSearchResult,
    SupplierSummary,
)

__all__ = [
    "AiExtract",
    "CapabilityDisabledError",
    "Case",
    "CasesPort",
    "ConfigError",
    "ConfirmationRequiredError",
    "Contact",
    "ContentPolicyRefusalError",
    "CopilotError",
    "DocRef",
    "DocType",
    "DistributionResult",
    "GuestNotAllowedError",
    "IngestScope",
    "InquiryDraft",
    "InquiryResult",
    "InquirySinkPort",
    "InquiryStatusPort",
    "KnowledgeDocument",
    "KnowledgeSourcePort",
    "LeadCandidate",
    "LeadDistributionPort",
    "MissingRequiredFieldsError",
    "PolicyError",
    "PortError",
    "PortTimeoutError",
    "PriceDisplay",
    "ProductCatalogPort",
    "ProductDetail",
    "ProductSearchQuery",
    "ProductSearchResult",
    "ProductSummary",
    "RateLimitError",
    "Solution",
    "SolutionsPort",
    "SupplierDetail",
    "SupplierDirectoryPort",
    "SupplierSearchQuery",
    "SupplierSearchResult",
    "SupplierSummary",
    "TrustLevel",
    "UpstreamAuthError",
    "UpstreamInvalidResponseError",
    "UpstreamUnavailableError",
]
