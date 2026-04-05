"""Subscription service for Orange Money payment processing and subscription management."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
    async def get_active_subscription(
        self, user_id: UUID, session: AsyncSession
    ) -> Subscription | None:
        now = datetime.now(tz=timezone.utc)
        result = await session.execute(
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
        session: AsyncSession,
    ) -> dict:
        existing_payment = await session.execute(
            select(SubscriptionPayment).where(
                SubscriptionPayment.external_reference == external_reference
            )
        )
        existing = existing_payment.scalar_one_or_none()
        if existing is not None:
            logger.info(
                "Duplicate payment reference, returning existing result",
                external_reference=external_reference,
            )
            return {
                "status": "ok",
                "subscription_activated": existing.payment_type == PaymentType.access,
                "user_found": True,
            }

        user_result = await session.execute(
            select(User).where(User.phone_number == phone_number)
        )
        user = user_result.scalar_one_or_none()
        user_found = user is not None

        if not user_found:
            logger.info(
                "No user found for phone number, recording unprocessed payment",
                phone_number=phone_number,
            )
            return {"status": "ok", "subscription_activated": False, "user_found": False}

        active_sub = await self.get_active_subscription(user.id, session)
        now = datetime.now(tz=timezone.utc)

        if active_sub is None:
            payment = SubscriptionPayment(
                user_id=user.id,
                phone_number=phone_number,
                amount_xof=amount_xof,
                payment_type=PaymentType.access,
                external_reference=external_reference,
                status=PaymentStatus.confirmed,
            )
            session.add(payment)

            subscription = Subscription(
                user_id=user.id,
                phone_number=phone_number,
                status=SubscriptionStatus.active,
                daily_message_limit=20,
                expires_at=now + timedelta(days=28),
                activated_at=now,
            )
            session.add(subscription)
            await session.commit()

            logger.info(
                "New subscription created",
                user_id=str(user.id),
                expires_at=str(now + timedelta(days=28)),
            )
            return {"status": "ok", "subscription_activated": True, "user_found": True}
        else:
            payment = SubscriptionPayment(
                user_id=user.id,
                phone_number=phone_number,
                amount_xof=amount_xof,
                payment_type=PaymentType.messages,
                external_reference=external_reference,
                status=PaymentStatus.confirmed,
            )
            session.add(payment)

            active_sub.daily_message_limit += 50
            await session.commit()

            logger.info(
                "Message top-up applied",
                user_id=str(user.id),
                new_daily_limit=active_sub.daily_message_limit,
            )
            return {"status": "ok", "subscription_activated": False, "user_found": True}

    async def link_phone_number(
        self, user_id: UUID, phone_number: str, session: AsyncSession
    ) -> None:
        user_result = await session.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one_or_none()
        if user is None:
            logger.warning("User not found for phone linking", user_id=str(user_id))
            return

        user.phone_number = phone_number
        await session.flush()

        unprocessed_result = await session.execute(
            select(SubscriptionPayment).where(
                SubscriptionPayment.phone_number == phone_number,
                SubscriptionPayment.status == PaymentStatus.pending,
            )
        )
        unprocessed = unprocessed_result.scalars().all()

        if unprocessed:
            logger.info(
                "Found unprocessed payments for phone, auto-activating",
                phone_number=phone_number,
                count=len(unprocessed),
            )
            for payment in unprocessed:
                await self.process_payment(
                    phone_number=phone_number,
                    amount_xof=payment.amount_xof,
                    external_reference=payment.external_reference,
                    session=session,
                )
        else:
            await session.commit()

    async def expire_subscriptions(self, session: AsyncSession) -> int:
        now = datetime.now(tz=timezone.utc)
        result = await session.execute(
            update(Subscription)
            .where(
                Subscription.status == SubscriptionStatus.active,
                Subscription.expires_at < now,
            )
            .values(status=SubscriptionStatus.expired)
        )
        await session.commit()
        expired_count = result.rowcount
        logger.info("Expired subscriptions updated", count=expired_count)
        return expired_count
