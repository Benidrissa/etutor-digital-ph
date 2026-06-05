"""Subscription service for Orange Money payment processing and subscription management."""

from __future__ import annotations

import datetime
from datetime import timedelta
from uuid import UUID

import structlog
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.subscription import (
    PaymentStatus,
    PaymentType,
    Subscription,
    SubscriptionPayment,
    SubscriptionStatus,
)
from app.domain.models.user import User, UserRole
from app.domain.services.platform_settings_service import SettingsCache
from app.domain.services.sms_parser import normalize_phone

logger = structlog.get_logger(__name__)

_ADMIN_EXPIRES = datetime.datetime(2099, 12, 31, tzinfo=datetime.UTC)
_ADMIN_DAILY_LIMIT = 9999


class SubscriptionService:
    async def get_active_subscription(
        self, user_id: UUID, session: AsyncSession
    ) -> Subscription | None:
        now = datetime.datetime.now(tz=datetime.UTC)
        result = await session.execute(
            select(Subscription).where(
                Subscription.user_id == user_id,
                Subscription.status == SubscriptionStatus.active,
                Subscription.expires_at > now,
            )
        )
        sub = result.scalar_one_or_none()
        if sub is not None:
            return sub

        user = await session.get(User, user_id)
        if user and user.role == UserRole.admin:
            return await self.ensure_admin_subscription(user_id, session)

        return None

    async def ensure_admin_subscription(self, user_id: UUID, session: AsyncSession) -> Subscription:
        """Auto-create non-expiring subscription for admin users."""
        existing = await session.execute(
            select(Subscription).where(
                Subscription.user_id == user_id,
                Subscription.status == SubscriptionStatus.active,
            )
        )
        found = existing.scalar_one_or_none()
        if found:
            return found

        subscription = Subscription(
            user_id=user_id,
            phone_number="admin",
            status=SubscriptionStatus.active,
            daily_message_limit=_ADMIN_DAILY_LIMIT,
            expires_at=_ADMIN_EXPIRES,
            activated_at=datetime.datetime.now(tz=datetime.UTC),
        )
        session.add(subscription)
        await session.commit()
        logger.info("Admin subscription auto-provisioned", user_id=str(user_id))
        return subscription

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
                "subscription_activated": existing.payment_type == PaymentType.access
                and existing.status == PaymentStatus.confirmed,
                "user_found": existing.user_id is not None,
            }

        normalized = normalize_phone(phone_number)
        candidates = list({phone_number, normalized})
        if len(normalized) == 8:
            candidates.append(f"+226{normalized}")
        user_result = await session.execute(select(User).where(User.phone_number.in_(candidates)))
        user = user_result.scalar_one_or_none()

        if user is None:
            logger.info(
                "No user found for phone number, saving pending payment",
                phone_number=phone_number,
            )
            payment = SubscriptionPayment(
                user_id=None,
                phone_number=normalized,
                amount_xof=amount_xof,
                payment_type=PaymentType.access,
                external_reference=external_reference,
                status=PaymentStatus.pending,
            )
            session.add(payment)
            await session.commit()
            return {"status": "ok", "subscription_activated": False, "user_found": False}

        sc = SettingsCache.instance()
        min_price: int = sc.get("payments-subscription-price-xof", 1000)
        active_sub = await self.get_active_subscription(user.id, session)
        now = datetime.datetime.now(tz=datetime.UTC)

        if active_sub is None:
            if amount_xof < min_price:
                logger.info(
                    "Payment below minimum activation price, saving as pending",
                    user_id=str(user.id),
                    amount_xof=amount_xof,
                    min_price=min_price,
                )
                payment = SubscriptionPayment(
                    user_id=user.id,
                    phone_number=normalized,
                    amount_xof=amount_xof,
                    payment_type=PaymentType.access,
                    external_reference=external_reference,
                    status=PaymentStatus.pending,
                )
                session.add(payment)
                await session.commit()
                return {
                    "status": "ok",
                    "subscription_activated": False,
                    "user_found": True,
                    "insufficient_amount": True,
                }

            duration_days: int = sc.get("payments-subscription-duration-days", 30)
            payment = SubscriptionPayment(
                user_id=user.id,
                phone_number=normalized,
                amount_xof=amount_xof,
                payment_type=PaymentType.access,
                external_reference=external_reference,
                status=PaymentStatus.confirmed,
            )
            session.add(payment)

            subscription = Subscription(
                user_id=user.id,
                phone_number=normalized,
                status=SubscriptionStatus.active,
                daily_message_limit=20,
                expires_at=now + timedelta(days=duration_days),
                activated_at=now,
            )
            session.add(subscription)
            await session.commit()

            logger.info(
                "New subscription created",
                user_id=str(user.id),
                expires_at=str(now + timedelta(days=duration_days)),
            )
            return {"status": "ok", "subscription_activated": True, "user_found": True}
        else:
            message_price: int = sc.get("payments-message-price-xof", 5)
            credits = amount_xof // max(1, message_price)

            payment = SubscriptionPayment(
                user_id=user.id,
                phone_number=normalized,
                amount_xof=amount_xof,
                payment_type=PaymentType.messages,
                external_reference=external_reference,
                status=PaymentStatus.confirmed,
            )
            session.add(payment)

            active_sub.message_credits += credits
            await session.commit()

            logger.info(
                "Message credits top-up applied",
                user_id=str(user.id),
                credits_added=credits,
                new_credits=active_sub.message_credits,
            )
            return {"status": "ok", "subscription_activated": False, "user_found": True}

    async def _grant_access_or_topup(
        self, user: User, amount_xof: int, session: AsyncSession
    ) -> dict:
        """Activate a new subscription, or top up message credits if one is active.

        Mutates the subscription only — callers own the SubscriptionPayment row.
        Returns ``{subscription_activated, insufficient_amount?, credits_added?}``.
        """
        sc = SettingsCache.instance()
        min_price: int = sc.get("payments-subscription-price-xof", 1000)
        active_sub = await self.get_active_subscription(user.id, session)
        now = datetime.datetime.now(tz=datetime.UTC)

        if active_sub is None:
            if amount_xof < min_price:
                return {"subscription_activated": False, "insufficient_amount": True}
            duration_days: int = sc.get("payments-subscription-duration-days", 30)
            subscription = Subscription(
                user_id=user.id,
                phone_number=(normalize_phone(user.phone_number) if user.phone_number else "api"),
                status=SubscriptionStatus.active,
                daily_message_limit=20,
                expires_at=now + timedelta(days=duration_days),
                activated_at=now,
            )
            session.add(subscription)
            return {"subscription_activated": True}

        message_price: int = sc.get("payments-message-price-xof", 5)
        credits = amount_xof // max(1, message_price)
        active_sub.message_credits += credits
        return {"subscription_activated": False, "credits_added": credits}

    async def confirm_payment(
        self,
        external_reference: str,
        session: AsyncSession,
        *,
        provider_reference: str | None = None,
    ) -> dict:
        """Confirm a pending provider-API payment and grant access/credits.

        Idempotent: a second call for an already-confirmed reference is a no-op.
        Uses the server-trusted ``amount_xof`` stored on the pending row (set at
        initialize time), never an amount taken from the webhook body.
        """
        result = await session.execute(
            select(SubscriptionPayment).where(
                SubscriptionPayment.external_reference == external_reference
            )
        )
        payment = result.scalar_one_or_none()
        if payment is None:
            logger.warning(
                "confirm_payment: no pending payment for reference",
                external_reference=external_reference,
            )
            return {"status": "not_found", "subscription_activated": False}

        if payment.status == PaymentStatus.confirmed:
            return {
                "status": "ok",
                "subscription_activated": payment.payment_type == PaymentType.access,
                "already_confirmed": True,
            }

        if provider_reference and not payment.provider_reference:
            payment.provider_reference = provider_reference

        user = await session.get(User, payment.user_id) if payment.user_id else None
        if user is None:
            payment.status = PaymentStatus.confirmed
            await session.commit()
            logger.warning(
                "confirm_payment: payment has no user, marked confirmed only",
                external_reference=external_reference,
            )
            return {"status": "ok", "subscription_activated": False}

        grant = await self._grant_access_or_topup(user, payment.amount_xof, session)
        if grant.get("insufficient_amount"):
            await session.commit()
            logger.info(
                "confirm_payment: amount below activation price, left pending",
                external_reference=external_reference,
                amount_xof=payment.amount_xof,
            )
            return {
                "status": "ok",
                "subscription_activated": False,
                "insufficient_amount": True,
            }

        payment.status = PaymentStatus.confirmed
        payment.payment_type = (
            PaymentType.access if grant["subscription_activated"] else PaymentType.messages
        )
        await session.commit()
        logger.info(
            "confirm_payment: payment confirmed",
            external_reference=external_reference,
            provider=payment.provider,
            activated=grant["subscription_activated"],
        )
        return {"status": "ok", "subscription_activated": grant["subscription_activated"]}

    async def link_phone_number(
        self, user_id: UUID, phone_number: str, session: AsyncSession
    ) -> None:
        user_result = await session.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one_or_none()
        if user is None:
            logger.warning("User not found for phone linking", user_id=str(user_id))
            return

        normalized = normalize_phone(phone_number)
        user.phone_number = normalized
        await session.flush()

        unprocessed_result = await session.execute(
            select(SubscriptionPayment).where(
                or_(
                    SubscriptionPayment.phone_number == phone_number,
                    SubscriptionPayment.phone_number == normalized,
                ),
                SubscriptionPayment.status == PaymentStatus.pending,
            )
        )
        unprocessed = unprocessed_result.scalars().all()

        if unprocessed:
            logger.info(
                "Found unprocessed payments for phone, auto-activating",
                phone_number=normalized,
                count=len(unprocessed),
            )
            for payment in unprocessed:
                await self.process_payment(
                    phone_number=normalized,
                    amount_xof=payment.amount_xof,
                    external_reference=payment.external_reference,
                    session=session,
                )
        else:
            await session.commit()

    async def expire_subscriptions(self, session: AsyncSession) -> int:
        now = datetime.datetime.now(tz=datetime.UTC)
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
