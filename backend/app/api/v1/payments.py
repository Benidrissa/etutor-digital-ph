"""Provider-API payment endpoints (Orange Money / Wave / Paystack).

Flow: an authenticated user initializes a checkout → we persist a pending
SubscriptionPayment and redirect them to the provider's hosted page → the
provider calls our webhook → we HMAC-verify it and activate the subscription.
The legacy Orange Money SMS relay (``/subscriptions/webhook/validate``) is left
untouched and dormant.
"""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from structlog import get_logger

from app.api.deps import get_db as get_db_session
from app.api.deps_local_auth import get_current_user
from app.domain.models.subscription import (
    PaymentStatus,
    PaymentType,
    SubscriptionPayment,
)
from app.domain.services.platform_settings_service import SettingsCache
from app.domain.services.subscription_service import SubscriptionService
from app.infrastructure.config.settings import get_settings
from app.integrations.payments import (
    PaymentProviderError,
    enabled_providers,
    get_provider,
)
from app.integrations.payments.registry import provider_currency

logger = get_logger(__name__)

router = APIRouter(tags=["Payments"])


class InitializeRequest(BaseModel):
    provider: str
    payment_type: str = "access"  # "access" | "messages"
    amount_xof: int | None = None


class InitializeResponse(BaseModel):
    checkout_url: str
    reference: str
    provider: str


class ProvidersResponse(BaseModel):
    providers: list[str]


def _webhook_base_url(request: Request) -> str:
    """Configured public origin, or the incoming request origin as fallback."""
    configured = (get_settings().payments_callback_base_url or "").rstrip("/")
    if configured:
        return configured
    return str(request.base_url).rstrip("/")


@router.get("/payments/providers", response_model=ProvidersResponse)
async def list_enabled_providers() -> ProvidersResponse:
    """Provider names an admin has enabled — drives the frontend selector."""
    return ProvidersResponse(providers=enabled_providers())


@router.post("/payments/initialize", response_model=InitializeResponse)
async def initialize_payment(
    body: InitializeRequest,
    request: Request,
    current_user=Depends(get_current_user),
    db=Depends(get_db_session),
) -> InitializeResponse:
    if body.provider not in enabled_providers():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Payment provider unavailable")

    if body.payment_type not in ("access", "messages"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid payment_type")

    sc = SettingsCache.instance()
    if body.payment_type == "access":
        amount = int(sc.get("payments-subscription-price-xof", 1000))
    else:
        if not body.amount_xof or body.amount_xof <= 0:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "amount_xof is required for message top-ups",
            )
        amount = int(body.amount_xof)

    user_id = uuid.UUID(current_user.id) if isinstance(current_user.id, str) else current_user.id
    currency = provider_currency(body.provider)
    reference = f"sira_{uuid.uuid4().hex}"

    # Persist the pending row BEFORE redirecting — the webhook may arrive fast,
    # and confirm_payment trusts this server-set amount, not the callback body.
    payment = SubscriptionPayment(
        user_id=user_id,
        phone_number="api",
        amount_xof=amount,
        payment_type=PaymentType.access if body.payment_type == "access" else PaymentType.messages,
        external_reference=reference,
        status=PaymentStatus.pending,
        provider=body.provider,
        currency=currency,
    )
    db.add(payment)
    await db.commit()

    settings = get_settings()
    return_url = f"{settings.frontend_url.rstrip('/')}/subscribe?status=success&ref={reference}"
    notify_url = f"{_webhook_base_url(request)}/api/v1/payments/webhook/{body.provider}"

    try:
        provider = get_provider(body.provider)
        result = await provider.initialize_transaction(
            amount=amount,
            currency=currency,
            reference=reference,
            email=getattr(current_user, "email", None),
            return_url=return_url,
            notify_url=notify_url,
            metadata={"user_id": str(user_id), "payment_type": body.payment_type},
        )
    except PaymentProviderError as exc:
        logger.warning("Payment init failed", provider=body.provider, error=str(exc))
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Payment provider error") from exc

    payment.provider_reference = result.provider_reference
    await db.commit()

    logger.info(
        "Payment initialized",
        provider=body.provider,
        reference=reference,
        user_id=str(user_id),
    )
    return InitializeResponse(
        checkout_url=result.checkout_url, reference=reference, provider=body.provider
    )


@router.post("/payments/webhook/{provider_name}", status_code=status.HTTP_200_OK)
async def payment_webhook(
    provider_name: str,
    request: Request,
    db=Depends(get_db_session),
) -> dict:
    raw_body = await request.body()
    try:
        provider = get_provider(provider_name)
    except PaymentProviderError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown payment provider")

    if not provider.verify_webhook(raw_body, request.headers):
        logger.warning("Payment webhook signature rejected", provider=provider_name)
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid webhook signature")

    try:
        payload = json.loads(raw_body or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid JSON body")

    event = provider.parse_event(payload)
    if event is None:
        return {"status": "ignored"}

    if not event.is_success:
        logger.info(
            "Payment webhook non-success event",
            provider=provider_name,
            reference=event.reference,
            event_status=event.status,
        )
        return {"status": "ok", "subscription_activated": False}

    service = SubscriptionService()
    result = await service.confirm_payment(event.reference, db)
    logger.info(
        "Payment webhook processed",
        provider=provider_name,
        reference=event.reference,
        activated=result.get("subscription_activated"),
    )
    return {
        "status": "ok",
        "subscription_activated": result.get("subscription_activated", False),
    }


@router.get("/payments/verify/{reference}", status_code=status.HTTP_200_OK)
async def verify_payment(
    reference: str,
    current_user=Depends(get_current_user),
    db=Depends(get_db_session),
) -> dict:
    """Return-url poll: confirm a payment without waiting for the async webhook.

    For Paystack we actively call the verify API; other providers rely on the
    webhook and this just reports the stored status.
    """
    from sqlalchemy import select

    user_id = uuid.UUID(current_user.id) if isinstance(current_user.id, str) else current_user.id
    row = await db.execute(
        select(SubscriptionPayment).where(
            SubscriptionPayment.external_reference == reference,
            SubscriptionPayment.user_id == user_id,
        )
    )
    payment = row.scalar_one_or_none()
    if payment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Payment not found")

    if payment.status == PaymentStatus.confirmed:
        return {"status": "confirmed"}

    if payment.provider == "paystack":
        try:
            provider = get_provider("paystack")
            event = await provider.verify_transaction(reference)  # type: ignore[attr-defined]
        except PaymentProviderError:
            event = None
        if event is not None and event.is_success:
            service = SubscriptionService()
            await service.confirm_payment(reference, db)
            return {"status": "confirmed"}

    return {"status": payment.status}
