"""Subscription API endpoints for Orange Money payment processing."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, field_validator
from structlog import get_logger

from app.api.deps import get_db as get_db_session
from app.api.deps_local_auth import get_current_user
from app.domain.services.subscription_service import SubscriptionService
from app.infrastructure.config.settings import get_settings

logger = get_logger(__name__)

router = APIRouter(tags=["Subscriptions"])


class WebhookPayload(BaseModel):
    phone_number: str
    amount_xof: int
    reference: str


class WebhookResponse(BaseModel):
    status: str
    subscription_activated: bool


class FreeTierInfo(BaseModel):
    daily_messages: int
    first_lesson_free: bool


class SubscriptionStatusResponse(BaseModel):
    has_subscription: bool
    subscription_status: str | None = None
    days_remaining: int | None = None
    daily_message_limit: int | None = None
    message_credits: int = 0
    expires_at: str | None = None
    free_tier: FreeTierInfo | None = None


class PhoneNumberRequest(BaseModel):
    phone_number: str

    @field_validator("phone_number")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        cleaned = re.sub(r"[\s\-\(\)]", "", v)
        if not re.match(r"^\+?[0-9]{8,15}$", cleaned):
            raise ValueError("Phone number must be international format with 8-15 digits")
        return cleaned


class PhoneNumberResponse(BaseModel):
    phone_number: str
    message: str


@router.post(
    "/subscriptions/webhook/validate",
    response_model=WebhookResponse,
    status_code=status.HTTP_200_OK,
)
async def validate_webhook(
    payload: WebhookPayload,
    x_webhook_secret: str | None = Header(default=None),
    db=Depends(get_db_session),
) -> WebhookResponse:
    settings = get_settings()
    if not x_webhook_secret or x_webhook_secret != settings.subscription_webhook_secret:
        logger.warning("Webhook secret mismatch", provided=bool(x_webhook_secret))
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

    logger.info(
        "Webhook processed",
        reference=payload.reference,
        activated=result.get("subscription_activated"),
    )

    return WebhookResponse(
        status=result["status"],
        subscription_activated=result["subscription_activated"],
    )


@router.get(
    "/subscriptions/me",
    response_model=SubscriptionStatusResponse,
    status_code=status.HTTP_200_OK,
)
async def get_my_subscription(
    current_user=Depends(get_current_user),
    db=Depends(get_db_session),
) -> SubscriptionStatusResponse:
    user_id = uuid.UUID(current_user.id) if isinstance(current_user.id, str) else current_user.id

    service = SubscriptionService()
    subscription = await service.get_active_subscription(user_id=user_id, session=db)

    if subscription is None:
        return SubscriptionStatusResponse(
            has_subscription=False,
            free_tier=FreeTierInfo(daily_messages=5, first_lesson_free=True),
        )

    now = datetime.now(tz=UTC)
    delta = subscription.expires_at - now
    days_remaining = max(0, delta.days)

    return SubscriptionStatusResponse(
        has_subscription=True,
        subscription_status=subscription.status,
        days_remaining=days_remaining,
        daily_message_limit=subscription.daily_message_limit,
        message_credits=subscription.message_credits,
        expires_at=subscription.expires_at.isoformat(),
    )


@router.post(
    "/users/phone",
    response_model=PhoneNumberResponse,
    status_code=status.HTTP_200_OK,
)
async def update_phone_number(
    payload: PhoneNumberRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_db_session),
) -> PhoneNumberResponse:
    user_id = uuid.UUID(current_user.id) if isinstance(current_user.id, str) else current_user.id

    service = SubscriptionService()
    await service.link_phone_number(
        user_id=user_id,
        phone_number=payload.phone_number,
        session=db,
    )

    logger.info("Phone number linked", user_id=str(user_id), phone=payload.phone_number)

    return PhoneNumberResponse(
        phone_number=payload.phone_number,
        message="Phone number updated and pending payments resolved",
    )
