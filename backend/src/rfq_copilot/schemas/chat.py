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
    ai_ticket: str | None = None  # 宿主站点签发的身份票据（E1 鉴权桥）
    contact: ContactInput | None = None
    quantity: int | None = None
    action: Literal["confirm_inquiry", "cancel_inquiry"] | None = None
    # QA-0003：确认门行内编辑回传（白名单合并规则见 03-api-spec「行内编辑回传」）；
    # graph 侧 resume 后做服务端校验（非白名单键/不合法值静默忽略）
    draft_override: dict[str, Any] | None = None


class SessionCreateRequest(BaseModel):
    page_type: str | None = None
    page_url: str | None = None
    product_id: str | None = None
    category_id: str | None = None
    visitor_id: str | None = None
    user_ref: str | None = None
    ai_ticket: str | None = None  # 宿主站点签发的身份票据（E1 鉴权桥）


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
    # 08-knowledge-export-spec §5：语料新鲜度（离线知识模式携带；demo 模式缺省）
    corpus_age_days: float | None = None
    corpus_stale: bool = False
