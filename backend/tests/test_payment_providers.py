"""Unit tests for the payment provider integrations (#2355).

Pure unit tests — no DB, no live HTTP. Webhook signature verification and event
parsing are exercised directly; initialize_transaction is driven through an
``httpx.MockTransport`` so no real provider call is made.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import patch

import httpx
import pytest

from app.integrations.payments.base import PaymentProviderError
from app.integrations.payments.orange_money import OrangeMoneyProvider
from app.integrations.payments.paystack import PaystackProvider
from app.integrations.payments.wave import WaveProvider


def _mock_client(handler):
    """Return a factory that builds an AsyncClient bound to a MockTransport."""
    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient
    return lambda **kw: real(transport=transport, **kw)


# ---------------------------------------------------------------------------
# Paystack
# ---------------------------------------------------------------------------


class TestPaystack:
    SECRET = "sk_test_secret"

    def test_verify_webhook_accepts_valid_signature(self):
        provider = PaystackProvider(self.SECRET)
        body = b'{"event":"charge.success"}'
        sig = hmac.new(self.SECRET.encode(), body, hashlib.sha512).hexdigest()
        assert provider.verify_webhook(body, {"x-paystack-signature": sig}) is True

    def test_verify_webhook_rejects_tampered_body(self):
        provider = PaystackProvider(self.SECRET)
        body = b'{"event":"charge.success"}'
        sig = hmac.new(self.SECRET.encode(), body, hashlib.sha512).hexdigest()
        assert (
            provider.verify_webhook(b'{"event":"hacked"}', {"x-paystack-signature": sig}) is False
        )

    def test_verify_webhook_rejects_missing_header(self):
        provider = PaystackProvider(self.SECRET)
        assert provider.verify_webhook(b"{}", {}) is False

    def test_parse_event_success_zero_decimal(self):
        provider = PaystackProvider(self.SECRET)
        event = provider.parse_event(
            {
                "event": "charge.success",
                "data": {"reference": "r1", "amount": 1000, "currency": "XOF", "status": "success"},
            }
        )
        assert event is not None
        assert event.is_success
        assert event.amount == 1000  # XOF has no minor unit
        assert event.reference == "r1"

    def test_parse_event_success_kobo_divided(self):
        provider = PaystackProvider(self.SECRET)
        event = provider.parse_event(
            {
                "event": "charge.success",
                "data": {
                    "reference": "r2",
                    "amount": 500000,
                    "currency": "NGN",
                    "status": "success",
                },
            }
        )
        assert event.amount == 5000  # 500000 kobo → 5000 NGN

    def test_parse_event_non_success(self):
        provider = PaystackProvider(self.SECRET)
        event = provider.parse_event(
            {"event": "charge.failed", "data": {"reference": "r3", "amount": 0, "currency": "XOF"}}
        )
        assert event is not None and not event.is_success

    def test_init_requires_secret(self):
        with pytest.raises(PaymentProviderError):
            PaystackProvider("")

    async def test_initialize_returns_checkout_url(self):
        provider = PaystackProvider(self.SECRET)

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/transaction/initialize"
            return httpx.Response(
                200, json={"data": {"authorization_url": "https://pay.test/x", "reference": "ref"}}
            )

        with patch("app.integrations.payments.paystack.httpx.AsyncClient", _mock_client(handler)):
            result = await provider.initialize_transaction(
                amount=1000,
                currency="XOF",
                reference="ref",
                email="u@example.com",
                return_url="https://app/return",
                notify_url="https://api/webhook",
            )
        assert result.checkout_url == "https://pay.test/x"
        assert result.provider_reference == "ref"


# ---------------------------------------------------------------------------
# Wave
# ---------------------------------------------------------------------------


class TestWave:
    API_KEY = "wave_key"
    SECRET = "wave_webhook_secret"

    def _sign(self, body: bytes, timestamp: str = "12345") -> str:
        signed = f"{timestamp}.".encode() + body
        v1 = hmac.new(self.SECRET.encode(), signed, hashlib.sha256).hexdigest()
        return f"t={timestamp},v1={v1}"

    def test_verify_webhook_accepts_valid_signature(self):
        provider = WaveProvider(self.API_KEY, self.SECRET)
        body = b'{"type":"checkout.session.completed"}'
        assert provider.verify_webhook(body, {"wave-signature": self._sign(body)}) is True

    def test_verify_webhook_rejects_tampered_body(self):
        provider = WaveProvider(self.API_KEY, self.SECRET)
        body = b'{"type":"checkout.session.completed"}'
        header = self._sign(body)
        assert provider.verify_webhook(b'{"type":"hacked"}', {"wave-signature": header}) is False

    def test_verify_webhook_rejects_without_secret(self):
        provider = WaveProvider(self.API_KEY, "")
        body = b"{}"
        assert provider.verify_webhook(body, {"wave-signature": "t=1,v1=abc"}) is False

    def test_parse_event_success(self):
        provider = WaveProvider(self.API_KEY, self.SECRET)
        event = provider.parse_event(
            {
                "type": "checkout.session.completed",
                "data": {"client_reference": "ref9", "amount": "1000", "currency": "XOF"},
            }
        )
        assert event is not None and event.is_success
        assert event.reference == "ref9"
        assert event.amount == 1000

    def test_parse_event_failed_payment_status(self):
        provider = WaveProvider(self.API_KEY, self.SECRET)
        event = provider.parse_event(
            {
                "type": "checkout.session.completed",
                "data": {"client_reference": "r", "amount": "1000", "payment_status": "failed"},
            }
        )
        assert event is not None and not event.is_success

    def test_init_requires_api_key(self):
        with pytest.raises(PaymentProviderError):
            WaveProvider("", self.SECRET)

    async def test_initialize_returns_launch_url(self):
        provider = WaveProvider(self.API_KEY, self.SECRET)

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/v1/checkout/sessions"
            return httpx.Response(
                200, json={"id": "cs_1", "wave_launch_url": "https://wave.test/c"}
            )

        with patch("app.integrations.payments.wave.httpx.AsyncClient", _mock_client(handler)):
            result = await provider.initialize_transaction(
                amount=1000,
                currency="XOF",
                reference="ref",
                email=None,
                return_url="https://app/return",
                notify_url="https://api/webhook",
            )
        assert result.checkout_url == "https://wave.test/c"
        assert result.provider_reference == "cs_1"


# ---------------------------------------------------------------------------
# Orange Money
# ---------------------------------------------------------------------------


class TestOrangeMoney:
    def _provider(self) -> OrangeMoneyProvider:
        return OrangeMoneyProvider(
            client_id="cid", client_secret="csecret", merchant_key="mkey", country="civ"
        )

    def test_init_requires_credentials(self):
        with pytest.raises(PaymentProviderError):
            OrangeMoneyProvider(client_id="", client_secret="", merchant_key="", country="civ")

    def test_parse_event_success(self):
        event = self._provider().parse_event(
            {"status": "SUCCESS", "order_id": "ref5", "amount": 1000}
        )
        assert event is not None and event.is_success
        assert event.reference == "ref5"

    def test_parse_event_failed(self):
        event = self._provider().parse_event({"status": "FAILED", "order_id": "ref6", "amount": 0})
        assert event is not None and not event.is_success

    async def test_initialize_returns_payment_url(self):
        provider = self._provider()

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/oauth/v3/token"):
                return httpx.Response(200, json={"access_token": "tok"})
            assert "webpayment" in request.url.path
            payload = json.loads(request.content)
            assert payload["merchant_key"] == "mkey"
            return httpx.Response(200, json={"payment_url": "https://om.test/p", "pay_token": "pt"})

        with patch(
            "app.integrations.payments.orange_money.httpx.AsyncClient", _mock_client(handler)
        ):
            result = await provider.initialize_transaction(
                amount=1000,
                currency="XOF",
                reference="ref",
                email=None,
                return_url="https://app/return",
                notify_url="https://api/webhook",
            )
        assert result.checkout_url == "https://om.test/p"
        assert result.provider_reference == "pt"
