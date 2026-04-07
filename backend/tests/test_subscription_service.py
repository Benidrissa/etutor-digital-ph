"""Tests for SubscriptionService — phone normalization, pending payments, settings, message credits."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.domain.models.subscription import (
    PaymentStatus,
    PaymentType,
    Subscription,
    SubscriptionStatus,
)
from app.domain.models.user import UserRole
from app.domain.services.sms_parser import normalize_phone
from app.domain.services.subscription_service import SubscriptionService

# ---------------------------------------------------------------------------
# Helper factories — use SimpleNamespace to avoid SQLAlchemy instrumentation
# ---------------------------------------------------------------------------


def _make_user(
    phone: str | None = "70220689",
    role: UserRole = UserRole.user,
) -> SimpleNamespace:
    uid = uuid.uuid4()
    return SimpleNamespace(
        id=uid,
        email=f"user_{uid}@example.com",
        name="Test User",
        phone_number=phone,
        preferred_language="fr",
        country="BF",
        professional_role="nurse",
        current_level=1,
        streak_days=0,
        avatar_url=None,
        role=role,
        is_active=True,
    )


def _make_subscription(
    user_id: uuid.UUID,
    daily_limit: int = 20,
    message_credits: int = 0,
    expires_in_days: int = 30,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        user_id=user_id,
        phone_number="70220689",
        status=SubscriptionStatus.active,
        daily_message_limit=daily_limit,
        message_credits=message_credits,
        expires_at=datetime.now(tz=UTC) + timedelta(days=expires_in_days),
        activated_at=datetime.now(tz=UTC),
        pending_expires_at=None,
    )


def _make_pending_payment(
    user_id: uuid.UUID | None,
    phone: str,
    amount: int,
    reference: str,
    status: PaymentStatus = PaymentStatus.pending,
    payment_type: PaymentType = PaymentType.access,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        user_id=user_id,
        phone_number=phone,
        amount_xof=amount,
        payment_type=payment_type,
        external_reference=reference,
        status=status,
        created_at=datetime.now(tz=UTC),
    )


# ---------------------------------------------------------------------------
# Phone normalization tests
# ---------------------------------------------------------------------------


class TestNormalizePhone:
    def test_normalize_burkina_international(self):
        assert normalize_phone("+22670220689") == "70220689"

    def test_normalize_burkina_international_00(self):
        assert normalize_phone("0022670220689") == "70220689"

    def test_normalize_local_unchanged(self):
        assert normalize_phone("70220689") == "70220689"

    def test_normalize_senegal_international(self):
        assert normalize_phone("+221776801718") == "776801718"

    def test_normalize_guinea_international(self):
        assert normalize_phone("+22476801718") == "76801718"

    def test_normalize_leading_zero(self):
        assert normalize_phone("070220689") == "70220689"

    def test_normalize_strips_spaces(self):
        assert normalize_phone("  70220689  ") == "70220689"

    def test_normalize_already_normalized(self):
        assert normalize_phone("70220689") == "70220689"


# ---------------------------------------------------------------------------
# process_payment — phone mismatch fix
# ---------------------------------------------------------------------------


class TestProcessPaymentPhoneMismatch:
    async def test_matches_international_phone(self):
        """User stored as +22670220689, payment phone 70220689 → match."""
        service = SubscriptionService()
        user = _make_user(phone="+22670220689")

        session = AsyncMock()
        existing_payment_result = MagicMock()
        existing_payment_result.scalar_one_or_none.return_value = None
        user_result = MagicMock()
        user_result.scalar_one_or_none.return_value = user

        session.execute = AsyncMock(side_effect=[existing_payment_result, user_result])
        session.add = MagicMock()
        session.commit = AsyncMock()

        with patch.object(service, "get_active_subscription", new=AsyncMock(return_value=None)), patch(
            "app.domain.services.subscription_service.SettingsCache.instance"
        ) as mock_sc:
            mock_sc.return_value.get.side_effect = lambda key, default=None: {
                "payments-subscription-price-xof": 1000,
                "payments-subscription-duration-days": 30,
            }.get(key, default)
            result = await service.process_payment(
                phone_number="70220689",
                amount_xof=1000,
                external_reference="TXN001",
                session=session,
            )

        assert result["user_found"] is True
        assert result["subscription_activated"] is True

    async def test_matches_local_phone(self):
        """User stored as 70220689, payment phone 70220689 → match."""
        service = SubscriptionService()
        user = _make_user(phone="70220689")

        session = AsyncMock()
        existing_payment_result = MagicMock()
        existing_payment_result.scalar_one_or_none.return_value = None
        user_result = MagicMock()
        user_result.scalar_one_or_none.return_value = user

        session.execute = AsyncMock(side_effect=[existing_payment_result, user_result])
        session.add = MagicMock()
        session.commit = AsyncMock()

        with patch.object(service, "get_active_subscription", new=AsyncMock(return_value=None)), patch(
            "app.domain.services.subscription_service.SettingsCache.instance"
        ) as mock_sc:
            mock_sc.return_value.get.side_effect = lambda key, default=None: {
                "payments-subscription-price-xof": 1000,
                "payments-subscription-duration-days": 30,
            }.get(key, default)
            result = await service.process_payment(
                phone_number="70220689",
                amount_xof=1000,
                external_reference="TXN002",
                session=session,
            )

        assert result["user_found"] is True
        assert result["subscription_activated"] is True

    async def test_no_match_wrong_number(self):
        """Different phone number → no match → pending payment saved."""
        service = SubscriptionService()

        session = AsyncMock()
        existing_payment_result = MagicMock()
        existing_payment_result.scalar_one_or_none.return_value = None
        user_result = MagicMock()
        user_result.scalar_one_or_none.return_value = None

        session.execute = AsyncMock(side_effect=[existing_payment_result, user_result])
        session.add = MagicMock()
        session.commit = AsyncMock()

        result = await service.process_payment(
            phone_number="70000000",
            amount_xof=1000,
            external_reference="TXN003",
            session=session,
        )

        assert result["user_found"] is False
        assert result["subscription_activated"] is False
        session.add.assert_called_once()


# ---------------------------------------------------------------------------
# process_payment — subscription activation
# ---------------------------------------------------------------------------


class TestSubscriptionActivation:
    async def test_first_payment_activates_subscription(self):
        """1000 XOF, no existing sub → subscription created."""
        service = SubscriptionService()
        user = _make_user()

        session = AsyncMock()
        existing_payment_result = MagicMock()
        existing_payment_result.scalar_one_or_none.return_value = None
        user_result = MagicMock()
        user_result.scalar_one_or_none.return_value = user

        session.execute = AsyncMock(side_effect=[existing_payment_result, user_result])
        session.add = MagicMock()
        session.commit = AsyncMock()

        with patch.object(service, "get_active_subscription", new=AsyncMock(return_value=None)), patch(
            "app.domain.services.subscription_service.SettingsCache.instance"
        ) as mock_sc:
            mock_sc.return_value.get.side_effect = lambda key, default=None: {
                "payments-subscription-price-xof": 1000,
                "payments-subscription-duration-days": 30,
            }.get(key, default)
            result = await service.process_payment(
                phone_number="70220689",
                amount_xof=1000,
                external_reference="TXN010",
                session=session,
            )

        assert result["subscription_activated"] is True
        assert result["user_found"] is True
        assert session.add.call_count == 2

    async def test_first_payment_uses_settings_duration(self):
        """Verify expires_at uses payments-subscription-duration-days setting."""
        service = SubscriptionService()
        user = _make_user()

        added_objects: list = []
        session = AsyncMock()
        existing_payment_result = MagicMock()
        existing_payment_result.scalar_one_or_none.return_value = None
        user_result = MagicMock()
        user_result.scalar_one_or_none.return_value = user

        session.execute = AsyncMock(side_effect=[existing_payment_result, user_result])
        session.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))
        session.commit = AsyncMock()

        with patch.object(service, "get_active_subscription", new=AsyncMock(return_value=None)), patch(
            "app.domain.services.subscription_service.SettingsCache.instance"
        ) as mock_sc:
            mock_sc.return_value.get.side_effect = lambda key, default=None: {
                "payments-subscription-price-xof": 1000,
                "payments-subscription-duration-days": 45,
            }.get(key, default)
            await service.process_payment(
                phone_number="70220689",
                amount_xof=1000,
                external_reference="TXN011",
                session=session,
            )

        subscriptions = [o for o in added_objects if isinstance(o, Subscription)]
        assert len(subscriptions) == 1
        sub = subscriptions[0]
        delta = sub.expires_at - sub.activated_at
        assert 44 <= delta.days <= 46

    async def test_payment_below_minimum_does_not_activate(self):
        """500 XOF < 1000 min → subscription_activated=False, payment saved as pending."""
        service = SubscriptionService()
        user = _make_user()

        added_objects: list = []
        session = AsyncMock()
        existing_payment_result = MagicMock()
        existing_payment_result.scalar_one_or_none.return_value = None
        user_result = MagicMock()
        user_result.scalar_one_or_none.return_value = user

        session.execute = AsyncMock(side_effect=[existing_payment_result, user_result])
        session.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))
        session.commit = AsyncMock()

        with patch.object(service, "get_active_subscription", new=AsyncMock(return_value=None)), patch(
            "app.domain.services.subscription_service.SettingsCache.instance"
        ) as mock_sc:
            mock_sc.return_value.get.side_effect = lambda key, default=None: {
                "payments-subscription-price-xof": 1000,
            }.get(key, default)
            result = await service.process_payment(
                phone_number="70220689",
                amount_xof=500,
                external_reference="TXN012",
                session=session,
            )

        assert result["subscription_activated"] is False
        assert result.get("insufficient_amount") is True
        from app.domain.models.subscription import SubscriptionPayment
        payments = [o for o in added_objects if isinstance(o, SubscriptionPayment)]
        assert len(payments) == 1
        assert payments[0].status == PaymentStatus.pending

    async def test_duplicate_reference_returns_existing(self):
        """Same external_reference twice → idempotent."""
        service = SubscriptionService()
        existing = _make_pending_payment(
            user_id=uuid.uuid4(),
            phone="70220689",
            amount=1000,
            reference="TXN013",
            status=PaymentStatus.confirmed,
            payment_type=PaymentType.access,
        )

        session = AsyncMock()
        existing_payment_result = MagicMock()
        existing_payment_result.scalar_one_or_none.return_value = existing

        session.execute = AsyncMock(return_value=existing_payment_result)
        session.add = MagicMock()

        result = await service.process_payment(
            phone_number="70220689",
            amount_xof=1000,
            external_reference="TXN013",
            session=session,
        )

        assert result["status"] == "ok"
        session.add.assert_not_called()


# ---------------------------------------------------------------------------
# process_payment — message credits top-up
# ---------------------------------------------------------------------------


class TestMessageCredits:
    async def test_topup_adds_message_credits(self):
        """5000 XOF while subscribed → message_credits += 1000 (at 5 XOF/msg)."""
        service = SubscriptionService()
        user = _make_user()
        active_sub = _make_subscription(user.id, message_credits=0)

        session = AsyncMock()
        existing_payment_result = MagicMock()
        existing_payment_result.scalar_one_or_none.return_value = None
        user_result = MagicMock()
        user_result.scalar_one_or_none.return_value = user

        session.execute = AsyncMock(side_effect=[existing_payment_result, user_result])
        session.add = MagicMock()
        session.commit = AsyncMock()

        with patch.object(
            service, "get_active_subscription", new=AsyncMock(return_value=active_sub)
        ), patch(
            "app.domain.services.subscription_service.SettingsCache.instance"
        ) as mock_sc:
            mock_sc.return_value.get.side_effect = lambda key, default=None: {
                "payments-subscription-price-xof": 1000,
                "payments-message-price-xof": 5,
            }.get(key, default)
            result = await service.process_payment(
                phone_number="70220689",
                amount_xof=5000,
                external_reference="TXN020",
                session=session,
            )

        assert result["subscription_activated"] is False
        assert active_sub.message_credits == 1000

    async def test_topup_uses_message_price_setting(self):
        """Credits calculation uses payments-message-price-xof."""
        service = SubscriptionService()
        user = _make_user()
        active_sub = _make_subscription(user.id, message_credits=10)

        session = AsyncMock()
        existing_payment_result = MagicMock()
        existing_payment_result.scalar_one_or_none.return_value = None
        user_result = MagicMock()
        user_result.scalar_one_or_none.return_value = user

        session.execute = AsyncMock(side_effect=[existing_payment_result, user_result])
        session.add = MagicMock()
        session.commit = AsyncMock()

        with patch.object(
            service, "get_active_subscription", new=AsyncMock(return_value=active_sub)
        ), patch(
            "app.domain.services.subscription_service.SettingsCache.instance"
        ) as mock_sc:
            mock_sc.return_value.get.side_effect = lambda key, default=None: {
                "payments-subscription-price-xof": 1000,
                "payments-message-price-xof": 10,
            }.get(key, default)
            await service.process_payment(
                phone_number="70220689",
                amount_xof=1000,
                external_reference="TXN021",
                session=session,
            )

        assert active_sub.message_credits == 10 + 100


# ---------------------------------------------------------------------------
# process_payment — pending payments for unknown phones
# ---------------------------------------------------------------------------


class TestPendingPayments:
    async def test_payment_unknown_phone_saved_as_pending(self):
        """No user for phone → SubscriptionPayment created with status=pending, user_id=None."""
        from app.domain.models.subscription import SubscriptionPayment

        service = SubscriptionService()

        added_objects: list = []
        session = AsyncMock()
        existing_payment_result = MagicMock()
        existing_payment_result.scalar_one_or_none.return_value = None
        user_result = MagicMock()
        user_result.scalar_one_or_none.return_value = None

        session.execute = AsyncMock(side_effect=[existing_payment_result, user_result])
        session.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))
        session.commit = AsyncMock()

        result = await service.process_payment(
            phone_number="70111222",
            amount_xof=2000,
            external_reference="TXN030",
            session=session,
        )

        assert result["user_found"] is False
        assert result["subscription_activated"] is False
        payments = [o for o in added_objects if isinstance(o, SubscriptionPayment)]
        assert len(payments) == 1
        assert payments[0].user_id is None
        assert payments[0].status == PaymentStatus.pending

    async def test_link_phone_processes_pending_payments(self):
        """Save pending payment, then link phone → subscription activated."""
        service = SubscriptionService()
        user = _make_user(phone=None)
        pending = _make_pending_payment(None, "70220689", 1000, "TXN031", PaymentStatus.pending)

        session = AsyncMock()
        user_result = MagicMock()
        user_result.scalar_one_or_none.return_value = user

        pending_result = MagicMock()
        pending_result.scalars.return_value.all.return_value = [pending]

        session.execute = AsyncMock(side_effect=[user_result, pending_result])
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        session.add = MagicMock()

        process_mock = AsyncMock(
            return_value={"status": "ok", "subscription_activated": True, "user_found": True}
        )
        with patch.object(service, "process_payment", process_mock):
            await service.link_phone_number(
                user_id=user.id,
                phone_number="+22670220689",
                session=session,
            )

        process_mock.assert_called_once_with(
            phone_number="70220689",
            amount_xof=1000,
            external_reference="TXN031",
            session=session,
        )

    async def test_link_phone_processes_multiple_pending(self):
        """Multiple pending payments → all processed."""
        service = SubscriptionService()
        user = _make_user(phone=None)
        pending1 = _make_pending_payment(None, "70220689", 1000, "TXN040", PaymentStatus.pending)
        pending2 = _make_pending_payment(None, "70220689", 2000, "TXN041", PaymentStatus.pending)

        session = AsyncMock()
        user_result = MagicMock()
        user_result.scalar_one_or_none.return_value = user

        pending_result = MagicMock()
        pending_result.scalars.return_value.all.return_value = [pending1, pending2]

        session.execute = AsyncMock(side_effect=[user_result, pending_result])
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        session.add = MagicMock()

        process_mock = AsyncMock(
            return_value={"status": "ok", "subscription_activated": True, "user_found": True}
        )
        with patch.object(service, "process_payment", process_mock):
            await service.link_phone_number(
                user_id=user.id,
                phone_number="70220689",
                session=session,
            )

        assert process_mock.call_count == 2


# ---------------------------------------------------------------------------
# Admin subscription regression
# ---------------------------------------------------------------------------


class TestAdminSubscription:
    async def test_admin_auto_provision(self):
        """ensure_admin_subscription creates non-expiring sub for admin."""
        service = SubscriptionService()
        user_id = uuid.uuid4()

        session = AsyncMock()
        existing_result = MagicMock()
        existing_result.scalar_one_or_none.return_value = None

        session.execute = AsyncMock(return_value=existing_result)
        session.add = MagicMock()
        session.commit = AsyncMock()

        sub = await service.ensure_admin_subscription(user_id, session)

        assert sub.daily_message_limit == 9999
        assert sub.expires_at.year == 2099

    async def test_admin_get_active_subscription_auto_provisions(self):
        """get_active_subscription auto-provisions for admin user."""
        service = SubscriptionService()
        admin_user = _make_user(role=UserRole.admin)

        session = AsyncMock()
        no_active_sub = MagicMock()
        no_active_sub.scalar_one_or_none.return_value = None

        session.execute = AsyncMock(return_value=no_active_sub)
        session.get = AsyncMock(return_value=admin_user)

        ensure_mock = AsyncMock(return_value=_make_subscription(admin_user.id, daily_limit=9999))
        with patch.object(service, "ensure_admin_subscription", ensure_mock):
            sub = await service.get_active_subscription(admin_user.id, session)

        assert sub is not None
        ensure_mock.assert_called_once_with(admin_user.id, session)
