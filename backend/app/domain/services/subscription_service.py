"""Subscription service for Orange Money payment processing and subscription management."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from uuid import UUID

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.subscription import (
    PaymentStatus,
    PaymentType,
    Subscription,
    SubscriptionPayment,
    SubscriptionStatus,
)
from app.domain.models.user import User

logger = structlog.get_logger(__name__)


class SubscriptionService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_active_subscription(self, user_id: UUID) -> Subscription | None:
        now = datetime.now(UTC)
        result = await self.db.execute(
            select(Subscription).where(
                Subscription.user_id == user_id,
                Subscription.status == SubscriptionStatus.active,
                Subscription.expires_at > now,
            )
        )
        return result.scalar_one_or_none()

    async def process_payment(
        self,
        phone_number: str,
        amount_xof: int,
        external_reference: str,
        session: AsyncSession | None = None,
    ) -> dict:
        db = session or self.db

        existing_payment = await db.execute(
            select(SubscriptionPayment).where(
                SubscriptionPayment.external_reference == external_reference
            )
        )
        existing = existing_payment.scalar_one_or_none()
        if existing is not None:
            logger.info(
                "Idempotent payment — already processed",
                external_reference=external_reference,
            )
            return {
                "status": "ok",
                "subscription_activated": existing.payment_type == PaymentType.access,
                "user_found": True,
            }

        user_result = await db.execute(select(User).where(User.phone_number == phone_number))
        user = user_result.scalar_one_or_none()
        user_found = user is not None

        if not user_found:
            logger.warning("Payment received for unknown phone", phone_number=phone_number)
            return {"status": "ok", "subscription_activated": False, "user_found": False}

        now = datetime.now(UTC)
        active_sub = await self._get_active_subscription_for_user(db, user.id)
        subscription_activated = False

        if active_sub is None:
            payment_type = PaymentType.access
            subscription_activated = True

            new_sub = Subscription(
                id=uuid.uuid4(),
                user_id=user.id,
                phone_number=phone_number,
                status=SubscriptionStatus.active,
                daily_message_limit=20,
                expires_at=now + timedelta(days=28),
                activated_at=now,
            )
            db.add(new_sub)
        else:
            payment_type = PaymentType.messages
            active_sub.daily_message_limit += 50

        payment = SubscriptionPayment(
            id=uuid.uuid4(),
            user_id=user.id,
            phone_number=phone_number,
            amount_xof=amount_xof,
            payment_type=payment_type,
            external_reference=external_reference,
            status=PaymentStatus.confirmed,
        )
        db.add(payment)
        await db.commit()

        logger.info(
            "Payment processed",
            user_id=str(user.id),
            payment_type=payment_type,
            subscription_activated=subscription_activated,
        )
        return {
            "status": "ok",
            "subscription_activated": subscription_activated,
            "user_found": True,
        }

    async def link_phone_number(
        self,
        user_id: UUID,
        phone_number: str,
        session: AsyncSession | None = None,
    ) -> None:
        db = session or self.db

        user_result = await db.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one_or_none()
        if user is None:
            logger.warning("link_phone_number: user not found", user_id=str(user_id))
            return

        user.phone_number = phone_number

        pending_result = await db.execute(
            select(SubscriptionPayment).where(
                SubscriptionPayment.phone_number == phone_number,
                SubscriptionPayment.status == PaymentStatus.pending,
            )
        )
        pending_payments = pending_result.scalars().all()

        if pending_payments:
            now = datetime.now(UTC)
            active_sub = await self._get_active_subscription_for_user(db, user_id)

            for payment in pending_payments:
                payment.user_id = user_id
                payment.status = PaymentStatus.confirmed

                if active_sub is None:
                    payment.payment_type = PaymentType.access
                    new_sub = Subscription(
                        id=uuid.uuid4(),
                        user_id=user_id,
                        phone_number=phone_number,
                        status=SubscriptionStatus.active,
                        daily_message_limit=20,
                        expires_at=now + timedelta(days=28),
                        activated_at=now,
                    )
                    db.add(new_sub)
                    active_sub = new_sub
                else:
                    payment.payment_type = PaymentType.messages
                    active_sub.daily_message_limit += 50

        await db.commit()
        logger.info(
            "Phone number linked",
            user_id=str(user_id),
            pending_resolved=len(pending_payments),
        )

    async def expire_subscriptions(self, session: AsyncSession | None = None) -> int:
        db = session or self.db
        now = datetime.now(UTC)

        result = await db.execute(
            update(Subscription)
            .where(
                Subscription.status == SubscriptionStatus.active,
                Subscription.expires_at < now,
            )
            .values(status=SubscriptionStatus.expired)
        )
        await db.commit()
        expired_count = result.rowcount
        logger.info("Subscriptions expired", count=expired_count)
        return expired_count

    @staticmethod
    async def _get_active_subscription_for_user(
        db: AsyncSession, user_id: UUID
    ) -> Subscription | None:
        now = datetime.now(UTC)
        result = await db.execute(
            select(Subscription).where(
                Subscription.user_id == user_id,
                Subscription.status == SubscriptionStatus.active,
                Subscription.expires_at > now,
            )
        )
        return result.scalar_one_or_none()
