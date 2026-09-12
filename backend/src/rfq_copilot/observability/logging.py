"""Structured logging setup (structlog JSON). PII masking rules: 07-security-spec §5."""

import logging

import structlog


def setup_logging(level: str = "info") -> None:
    logging.basicConfig(level=level.upper(), format="%(message)s")
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ]
    )
