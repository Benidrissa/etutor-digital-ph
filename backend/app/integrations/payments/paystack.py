"""Paystack provider — card / bank / mobile money via the Transactions API.

Docs: https://paystack.com/docs/api/transaction/
- initialize: POST /transaction/initialize → data.authorization_url
- webhook: verify ``x-paystack-signature`` = HMAC-SHA512(raw_body, secret_key)
- success event: ``charge.success`` with data.reference / data.amount / data.currency
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

_API_BASE = "https://api.paystack.co"
_TIMEOUT = 20.0

# Currencies Paystack settles with NO minor unit — amount is passed as-is.
# Everything else (NGN→kobo, GHS→pesewas, USD→cents) is multiplied by 100.
_ZERO_DECIMAL = {"XOF", "XAF"}


class PaystackProvider:
    name = "paystack"

    def __init__(self, secret_key: str) -> None:
        if not secret_key:
            raise PaymentProviderError("Paystack secret key is not configured")
        self._secret_key = secret_key

    def _to_subunit(self, amount: int, currency: str) -> int:
        return amount if currency.upper() in _ZERO_DECIMAL else amount * 100

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
        # Paystack requires a customer email; fall back to a deterministic placeholder.
        customer_email = email or f"{reference}@no-email.sira"
        body = {
            "email": customer_email,
            "amount": self._to_subunit(amount, currency),
            "currency": currency.upper(),
            "reference": reference,
            "callback_url": return_url,
            "metadata": metadata or {},
        }
        headers = {"Authorization": f"Bearer {self._secret_key}"}
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                f"{_API_BASE}/transaction/initialize", json=body, headers=headers
            )
        if resp.status_code >= 400:
            logger.warning("Paystack init failed", status=resp.status_code, body=resp.text)
            raise PaymentProviderError(f"Paystack initialize failed ({resp.status_code})")
        data = resp.json().get("data") or {}
        url = data.get("authorization_url")
        if not url:
            raise PaymentProviderError("Paystack response missing authorization_url")
        return InitResult(checkout_url=url, provider_reference=data.get("reference", reference))

    def verify_webhook(self, raw_body: bytes, headers: Mapping[str, str]) -> bool:
        signature = headers.get("x-paystack-signature", "")
        if not signature:
            return False
        expected = hmac.new(self._secret_key.encode(), raw_body, hashlib.sha512).hexdigest()
        return hmac.compare_digest(expected, signature)

    def parse_event(self, payload: dict[str, Any]) -> PaymentEvent | None:
        event = payload.get("event")
        data = payload.get("data") or {}
        reference = data.get("reference")
        if not reference:
            return None
        currency = (data.get("currency") or "XOF").upper()
        raw_amount = int(data.get("amount") or 0)
        amount = raw_amount if currency in _ZERO_DECIMAL else raw_amount // 100
        status = (
            "success"
            if event == "charge.success" and data.get("status") == "success"
            else ("pending" if event != "charge.success" else "failed")
        )
        return PaymentEvent(
            reference=reference,
            amount=amount,
            currency=currency,
            status=status,
            raw=payload,
        )

    async def verify_transaction(self, reference: str) -> PaymentEvent | None:
        """Server-side poll for the return-url path (GET /transaction/verify/:ref)."""
        headers = {"Authorization": f"Bearer {self._secret_key}"}
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(f"{_API_BASE}/transaction/verify/{reference}", headers=headers)
        if resp.status_code >= 400:
            return None
        data = resp.json().get("data") or {}
        currency = (data.get("currency") or "XOF").upper()
        raw_amount = int(data.get("amount") or 0)
        amount = raw_amount if currency in _ZERO_DECIMAL else raw_amount // 100
        return PaymentEvent(
            reference=data.get("reference", reference),
            amount=amount,
            currency=currency,
            status="success" if data.get("status") == "success" else "pending",
            raw=data,
        )
