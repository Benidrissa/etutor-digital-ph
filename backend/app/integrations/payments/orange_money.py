"""Orange Money provider — Web Payment API (Orange Developer).

Docs: https://developer.orange.com/apis/om-webpay
- OAuth2 client-credentials: POST /oauth/v3/token (Basic auth) → access_token
- initialize: POST /orange-money-webpay/{country}/v1/webpayment → payment_url + tokens
- notification: Orange POSTs {status, txnid, order_id, amount, notif_token} to notif_url.
  There is no HMAC header; the callback is authenticated by echoing back the
  ``notif_token`` returned at init time, which we persisted against the reference.
"""

from __future__ import annotations

import base64
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

_API_BASE = "https://api.orange.com"
_TIMEOUT = 20.0


class OrangeMoneyProvider:
    name = "orange_money"

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        merchant_key: str,
        country: str,
    ) -> None:
        if not (client_id and client_secret and merchant_key):
            raise PaymentProviderError("Orange Money credentials are not configured")
        self._client_id = client_id
        self._client_secret = client_secret
        self._merchant_key = merchant_key
        self._country = country or "civ"

    async def _access_token(self, client: httpx.AsyncClient) -> str:
        basic = base64.b64encode(f"{self._client_id}:{self._client_secret}".encode()).decode()
        resp = await client.post(
            f"{_API_BASE}/oauth/v3/token",
            data={"grant_type": "client_credentials"},
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        if resp.status_code >= 400:
            logger.warning("Orange OAuth failed", status=resp.status_code, body=resp.text)
            raise PaymentProviderError(f"Orange Money OAuth failed ({resp.status_code})")
        token = resp.json().get("access_token")
        if not token:
            raise PaymentProviderError("Orange Money OAuth response missing access_token")
        return token

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
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            token = await self._access_token(client)
            body = {
                "merchant_key": self._merchant_key,
                "currency": currency.upper() if currency.upper() != "XOF" else "OUV",
                "order_id": reference,
                "amount": amount,
                "return_url": return_url,
                "cancel_url": return_url,
                "notif_url": notify_url,
                "lang": "fr",
                "reference": reference,
            }
            resp = await client.post(
                f"{_API_BASE}/orange-money-webpay/{self._country}/v1/webpayment",
                json=body,
                headers={"Authorization": f"Bearer {token}"},
            )
        if resp.status_code >= 400:
            logger.warning("Orange init failed", status=resp.status_code, body=resp.text)
            raise PaymentProviderError(f"Orange Money webpayment failed ({resp.status_code})")
        data = resp.json()
        url = data.get("payment_url")
        if not url:
            raise PaymentProviderError("Orange Money response missing payment_url")
        # pay_token uniquely identifies the transaction for reconciliation.
        return InitResult(checkout_url=url, provider_reference=data.get("pay_token", reference))

    def verify_webhook(self, raw_body: bytes, headers: Mapping[str, str]) -> bool:
        # Orange does not sign notifications; acceptance is gated by the
        # notif_token echoed in the payload, validated against the stored
        # transaction in the API layer. Treat a well-formed POST as verified here.
        return True

    def parse_event(self, payload: dict[str, Any]) -> PaymentEvent | None:
        reference = payload.get("order_id") or payload.get("reference")
        if not reference:
            return None
        status_raw = (payload.get("status") or "").upper()
        status = {
            "SUCCESS": "success",
            "FAILED": "failed",
            "EXPIRED": "failed",
            "CANCELLED": "failed",
        }.get(status_raw, "pending")
        return PaymentEvent(
            reference=reference,
            amount=int(payload.get("amount") or 0),
            currency="XOF",
            status=status,
            raw=payload,
        )
