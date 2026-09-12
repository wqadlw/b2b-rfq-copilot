"""LeadDistributionPort (authority: docs/specs/01-port-spec.md §3.5)."""

from typing import Literal, Protocol

from pydantic import BaseModel

from rfq_copilot.ports.inquiry_sink import AiExtract


class LeadCandidate(BaseModel):
    inquiry_id: str
    lead_score: int
    lead_level: Literal["high", "medium", "low"]
    ai_extract: AiExtract
    product_id: str | None = None
    category_id: str | None = None


class DistributionResult(BaseModel):
    distributed: bool
    channel: str
    reference_id: str | None = None


class LeadDistributionPort(Protocol):
    async def submit(self, lead: LeadCandidate) -> DistributionResult: ...
