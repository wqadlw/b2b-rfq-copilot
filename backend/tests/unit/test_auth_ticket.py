"""Unit: AI 身份票据（E1 鉴权桥，Chatwoot/Intercom 同模式）。"""

import time

import pytest

from rfq_copilot.core.auth.ticket import issue_ticket, verify_ticket


@pytest.fixture()
def secret() -> str:
    return "unit-test-secret"


def test_roundtrip(secret: str) -> None:
    ticket = issue_ticket("42", secret)
    result = verify_ticket(ticket, secret)
    assert result.ok and result.user_id == "42"


def test_expired_ticket_rejected(secret: str) -> None:
    ticket = issue_ticket("42", secret, now=int(time.time()) - 600)
    result = verify_ticket(ticket, secret)
    assert not result.ok and result.reason == "expired"


def test_tampered_user_id_rejected(secret: str) -> None:
    ticket = issue_ticket("42", secret)
    forged = ticket.replace("42", "43", 1)
    result = verify_ticket(forged, secret)
    assert not result.ok and result.reason in ("bad_signature", "format")


def test_wrong_secret_rejected(secret: str) -> None:
    ticket = issue_ticket("42", secret)
    assert not verify_ticket(ticket, "other-secret").ok


def test_malformed_inputs_rejected(secret: str) -> None:
    for bad in ("", "   ", "42", "42.999", "a.b.c.d", ".123.abc"):
        result = verify_ticket(bad, secret)
        assert not result.ok


def test_empty_ticket_is_guest(secret: str) -> None:
    assert not verify_ticket("", secret).ok
