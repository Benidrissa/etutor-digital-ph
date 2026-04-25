"""SMTP relay tests for EmailService.

We mock aiosmtplib.send so the test never touches a real socket — the only
thing we care about is that the service builds a proper EmailMessage and
hands it to aiosmtplib with the configured host/port/auth.
"""

from email.message import EmailMessage
from unittest.mock import AsyncMock, patch

import pytest

from app.domain.services.email_service import EmailService


@pytest.mark.asyncio
async def test_send_otp_email_uses_smtp_relay():
    svc = EmailService()
    with patch("app.domain.services.email_service.aiosmtplib.send", new=AsyncMock()) as mock_send:
        ok = await svc.send_otp_email("user@example.com", "123456", "registration", "fr")
    assert ok is True
    assert mock_send.called
    kwargs = mock_send.call_args.kwargs
    assert kwargs["hostname"] == svc.smtp_host
    assert kwargs["port"] == svc.smtp_port
    assert kwargs["use_tls"] == svc.smtp_use_tls
    assert kwargs["start_tls"] is False

    # The first positional arg is the EmailMessage
    msg: EmailMessage = mock_send.call_args.args[0]
    assert msg["To"] == "user@example.com"
    assert "vérification" in msg["Subject"].lower() or "verification" in msg["Subject"].lower()
    # Body must contain the OTP code
    assert "123456" in msg.as_string()


@pytest.mark.asyncio
async def test_send_otp_skips_synthetic_emails():
    svc = EmailService()
    with patch("app.domain.services.email_service.aiosmtplib.send", new=AsyncMock()) as mock_send:
        ok = await svc.send_otp_email("phone@sira.app", "123456", "login", "fr")
    assert ok is False
    assert not mock_send.called


@pytest.mark.asyncio
async def test_send_otp_returns_false_on_smtp_failure():
    svc = EmailService()
    with patch(
        "app.domain.services.email_service.aiosmtplib.send",
        new=AsyncMock(side_effect=ConnectionRefusedError("boom")),
    ):
        ok = await svc.send_otp_email("user@example.com", "123456", "login", "en")
    assert ok is False


@pytest.mark.asyncio
async def test_magic_link_includes_token_in_url():
    svc = EmailService()
    captured: dict = {}

    async def fake_send(message, **kwargs):
        captured["message"] = message
        captured["kwargs"] = kwargs

    with patch("app.domain.services.email_service.aiosmtplib.send", new=fake_send):
        ok = await svc.send_magic_link("user@example.com", "tok-abc", "en")
    assert ok is True
    body = captured["message"].as_string()
    assert "tok-abc" in body
