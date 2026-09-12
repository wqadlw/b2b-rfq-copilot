"""Public chat API schemas (authority: docs/specs/03-api-spec.md)."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class ContactInput(BaseModel):
    name: str | None = None
    company: str | None = None
    phone: str | None = None
    email: str | None = None


class ChatRequest(BaseModel):
    session_id: str
    message: str = Field(default="", max_length=2000)
    page_type: str | None = None
    product_id: str | None = None
    visitor_id: str | None = None
    user_ref: str | None = None
    contact: ContactInput | None = None
    quantity: int | None = None
    action: Literal["confirm_inquiry", "cancel_inquiry"] | None = None


class SessionCreateRequest(BaseModel):
    page_type: str | None = None
    page_url: str | None = None
    product_id: str | None = None
    category_id: str | None = None
    visitor_id: str | None = None
    user_ref: str | None = None


class SessionCreateResponse(BaseModel):
    session_id: str
    token: str


class FeedbackRequest(BaseModel):
    session_id: str
    message_id: str
    feedback: Literal["helpful", "not_helpful"]
    comment: str | None = None


class UiConfigResponse(BaseModel):
    adapter: str
    display_name: str
    chat: dict[str, Any]
    theme: dict[str, str | None]
    capabilities: dict[str, bool]
    inquiry: dict[str, Any]
    i18n: str = "zh-CN"


class HealthResponse(BaseModel):
    status: str
    adapter: str
    profile: str
