"""InquirySinkPort (authority: docs/specs/01-port-spec.md §3.4)."""

from typing import Literal, Protocol

from pydantic import BaseModel, Field


class Contact(BaseModel):
    name: str
    company: str | None = None
    phone: str
    email: str | None = None


class AiExtract(BaseModel):
    v: int = 1
    intent: str
    confidence: float = Field(ge=0, le=1)
    entities: dict[str, str | bool] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    needs_human: bool = False
    human_reason: str | None = None
    lead_level: Literal["high", "medium", "low"] = "low"
    lead_market_candidate: bool = False
    retrieved_doc_ids: list[str] = Field(default_factory=list)
    tool_calls: list[str] = Field(default_factory=list)


class InquiryDraft(BaseModel):
    session_id: str
    user_ref: str | None = None
    product_id: str | None = None
    category_id: str | None = None
    quantity: int | None = None
    params: dict[str, str] = Field(default_factory=dict)
    message: str = Field(max_length=1000)
    contact: Contact
    lead_score: int = Field(ge=0, le=100)
    ai_extract: AiExtract
    idempotency_key: str


class InquiryResult(BaseModel):
    inquiry_id: str
    state: Literal["created", "requires_registration", "rejected"]
    missing_fields: list[str] = Field(default_factory=list)


class InquirySinkPort(Protocol):
    def create(self, draft: InquiryDraft) -> InquiryResult: ...
