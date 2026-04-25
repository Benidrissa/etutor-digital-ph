"""Tests for WhatsAppService — stub mode and HTTP payload shape."""

from unittest.mock import patch

import pytest

from app.domain.services.whatsapp_service import WhatsAppService


@pytest.mark.asyncio
async def test_stub_mode_when_credentials_missing(monkeypatch):
    # Default settings have empty creds → stub mode auto-enables.
    svc = WhatsAppService()
    assert svc.stub_mode is True
    ok = await svc.send_otp_template("+221770000001", "654321", "fr")
    assert ok is True


@pytest.mark.asyncio
async def test_real_send_posts_authentication_template(monkeypatch):
    monkeypatch.setattr(
        "app.domain.services.whatsapp_service.settings.whatsapp_phone_number_id", "PNID"
    )
    monkeypatch.setattr(
        "app.domain.services.whatsapp_service.settings.whatsapp_access_token", "TKN"
    )
    monkeypatch.setattr(
        "app.domain.services.whatsapp_service.settings.whatsapp_otp_template_name", "sira_otp"
    )
    monkeypatch.setattr(
        "app.domain.services.whatsapp_service.settings.whatsapp_stub_mode", False
    )

    svc = WhatsAppService()
    assert svc.stub_mode is False

    captured: dict = {}

    class FakeResp:
        status_code = 200
        text = "ok"

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def post(self, url, json=None, headers=None):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return FakeResp()

    with patch("app.domain.services.whatsapp_service.httpx.AsyncClient", lambda **kw: FakeClient()):
        ok = await svc.send_otp_template("+221770000002", "987654", "en")

    assert ok is True
    assert "PNID/messages" in captured["url"]
    assert captured["headers"]["Authorization"] == "Bearer TKN"

    template = captured["json"]["template"]
    assert template["name"] == "sira_otp"
    assert template["language"]["code"] == "en_US"
    body_param = template["components"][0]["parameters"][0]
    button_param = template["components"][1]["parameters"][0]
    assert body_param["text"] == "987654"
    assert button_param["text"] == "987654"


@pytest.mark.asyncio
async def test_real_send_returns_false_on_4xx(monkeypatch):
    monkeypatch.setattr(
        "app.domain.services.whatsapp_service.settings.whatsapp_phone_number_id", "PNID"
    )
    monkeypatch.setattr(
        "app.domain.services.whatsapp_service.settings.whatsapp_access_token", "TKN"
    )
    monkeypatch.setattr(
        "app.domain.services.whatsapp_service.settings.whatsapp_stub_mode", False
    )

    svc = WhatsAppService()

    class FakeResp:
        status_code = 400
        text = '{"error":"bad template"}'

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def post(self, *a, **kw):
            return FakeResp()

    with patch("app.domain.services.whatsapp_service.httpx.AsyncClient", lambda **kw: FakeClient()):
        ok = await svc.send_otp_template("+221770000003", "111222", "fr")

    assert ok is False
