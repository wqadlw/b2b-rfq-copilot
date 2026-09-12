"""Observability: structured logging (M0); Langfuse tracing (M2)."""

from rfq_copilot.observability.logging import setup_logging

setup_logging()

__all__ = ["setup_logging"]
