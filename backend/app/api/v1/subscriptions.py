"""Subscription management endpoints for Orange Money payment processing."""

from __future__ import annotations

import re

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.deps_local_auth import get_current_user
from app.domain.models.subscription import SubscriptionStatus
from app.domain.services.subscription_service import SubscriptionService
from app.infrastructure.config.settings import get_settings

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["Subscriptions"])


class WebhookPayload(BaseModel):
    phone_number: str
    amount_xof: int
    reference: str


class WebhookResponse(BaseModel):
    status: str
    subscription_activated: bool


class PhoneUpdateRequest(BaseModel):
    phone_number: str

    @field_validator("phone_number")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        cleaned = re.sub(r"\s+", "", v)
        if not re.match(r"^\+?\d{8,15}$", cleaned):
            raise ValueError(
                "Invalid phone number format. Must be 8-15 digits (international format)."
            )
        return cleaned


class PhoneUpdateResponse(BaseModel):
    phone_number: str
    pending_payments_resolved: bool


class FreeTierInfo(BaseModel):
    daily_messages: int
    first_lesson_free: bool


class SubscriptionStatusResponse(BaseModel):
    has_subscription: bool
    status: str | None = None
    daily_message_limit: int | None = None
    expires_at: str | None = None
    days_remaining: int | None = None
    free_tier: FreeTierInfo | None = None


@router.post("/subscriptions/webhook/validate", response_model=WebhookResponse)
async def validate_webhook(
    payload: WebhookPayload,
    x_webhook_secret: str | None = Header(default=None, alias="X-Webhook-Secret"),
    db: AsyncSession = Depends(get_db),
) -> WebhookResponse:
    settings = get_settings()
    expected_secret = settings.subscription_webhook_secret

    if not expected_secret or x_webhook_secret != expected_secret:
        logger.warning(
            "Webhook secret mismatch",
            phone_number=payload.phone_number,
            reference=payload.reference,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid webhook secret",
        )

    service = SubscriptionService()
    result = await service.process_payment(
        phone_number=payload.phone_number,
        amount_xof=payload.amount_xof,
        external_reference=payload.reference,
        session=db,
    )

    return WebhookResponse(
        status=result["status"],
        subscription_activated=result["subscription_activated"],
    )


@router.get("/subscriptions/me", response_model=SubscriptionStatusResponse)
async def get_subscription_status(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubscriptionStatusResponse:
    service = SubscriptionService()
    subscription = await service.get_active_subscription(current_user.id, session=db)

    if subscription is None:
        return SubscriptionStatusResponse(
            has_subscription=False,
            free_tier=FreeTierInfo(daily_messages=5, first_lesson_free=True),
        )

    import datetime

    now = datetime.datetime.now(tz=datetime.UTC)
    days_remaining = max(0, (subscription.expires_at - now).days)

    return SubscriptionStatusResponse(
        has_subscription=True,
        status=subscription.status.value
        if subscription.status != SubscriptionStatus.active
        else "active",
        daily_message_limit=subscription.daily_message_limit,
        expires_at=subscription.expires_at.isoformat(),
        days_remaining=days_remaining,
    )


@router.post("/users/phone", response_model=PhoneUpdateResponse)
async def update_phone_number(
    request: PhoneUpdateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PhoneUpdateResponse:
    service = SubscriptionService()
    await service.link_phone_number(
        user_id=current_user.id,
        phone_number=request.phone_number,
        session=db,
    )

    logger.info(
        "Phone number updated",
        user_id=str(current_user.id),
        phone_number=request.phone_number,
    )

    return PhoneUpdateResponse(
        phone_number=request.phone_number,
        pending_payments_resolved=True,
    )
