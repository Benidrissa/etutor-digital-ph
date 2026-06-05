"""Wave provider — mobile money via the Checkout API.

Docs: https://docs.wave.com/business
- initialize: POST /v1/checkout/sessions → wave_launch_url
- webhook: verify ``Wave-Signature`` header of the form ``t=<ts>,v1=<sig>`` where
  sig = HMAC-SHA256(f"{ts}.{raw_body}", webhook_secret)
- success event: ``checkout.session.completed`` with data.client_reference / data.amount
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping
from typing import Any

import httpx
import structlog

from app.integrations.payments.base import (
    InitResult,
    PaymentEvent,
    PaymentProviderError,
)

logger = structlog.get_logger(__name__)

_API_BASE = "https://api.wave.com"
_TIMEOUT = 20.0


class WaveProvider:
    name = "wave"

    def __init__(self, api_key: str, webhook_secret: str) -> None:
        if not api_key:
            raise PaymentProviderError("Wave API key is not configured")
        self._api_key = api_key
        self._webhook_secret = webhook_secret

    async def initialize_transaction(
        self,
        *,
        amount: int,
        currency: str,
        reference: str,
        email: str | None,
        return_url: str,
        notify_url: str,
        metadata: dict[str, Any] | None = None,
    ) -> InitResult:
        # Wave amounts are sent in the major unit as a string (XOF has no minor unit).
        body = {
            "amount": str(amount),
            "currency": currency.upper(),
            "success_url": return_url,
            "error_url": return_url,
            "client_reference": reference,
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                f"{_API_BASE}/v1/checkout/sessions", json=body, headers=headers
            )
        if resp.status_code >= 400:
            logger.warning("Wave init failed", status=resp.status_code, body=resp.text)
            raise PaymentProviderError(f"Wave checkout failed ({resp.status_code})")
        data = resp.json()
        url = data.get("wave_launch_url")
        if not url:
            raise PaymentProviderError("Wave response missing wave_launch_url")
        return InitResult(checkout_url=url, provider_reference=data.get("id", reference))

    def verify_webhook(self, raw_body: bytes, headers: Mapping[str, str]) -> bool:
        sig_header = headers.get("wave-signature", "")
        if not sig_header or not self._webhook_secret:
            return False
        parts = dict(p.split("=", 1) for p in sig_header.split(",") if "=" in p)
        timestamp = parts.get("t")
        provided = parts.get("v1")
        if not timestamp or not provided:
            return False
        signed_payload = f"{timestamp}.".encode() + raw_body
        expected = hmac.new(
            self._webhook_secret.encode(), signed_payload, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, provided)

    def parse_event(self, payload: dict[str, Any]) -> PaymentEvent | None:
        event = payload.get("type") or payload.get("event")
        data = payload.get("data") or {}
        reference = data.get("client_reference") or data.get("id")
        if not reference:
            return None
        currency = (data.get("currency") or "XOF").upper()
        amount = int(float(data.get("amount") or 0))
        status = "success" if event == "checkout.session.completed" else "pending"
        # A session can complete as failed/expired — honor an explicit payment_status.
        if data.get("payment_status") in {"failed", "expired", "cancelled"}:
            status = "failed"
        return PaymentEvent(
            reference=reference,
            amount=amount,
            currency=currency,
            status=status,
            raw=payload,
        )
