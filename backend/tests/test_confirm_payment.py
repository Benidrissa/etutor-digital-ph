"""Unit tests for SubscriptionService.confirm_payment — the provider-API path (#2355).

No DB: the async session is mocked. SettingsCache is stubbed so amounts are
deterministic. These cover activation, idempotency, top-up, and insufficiency.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.domain.models.subscription import PaymentStatus, PaymentType
from app.domain.models.user import UserRole
from app.domain.services.subscription_service import SubscriptionService


def _user(role: UserRole = UserRole.user) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), phone_number="70220689", role=role)


def _payment(
    user_id: uuid.UUID,
    amount: int = 1000,
    status: PaymentStatus = PaymentStatus.pending,
    payment_type: PaymentType = PaymentType.access,
    provider: str = "paystack",
    currency: str = "XOF",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        user_id=user_id,
        amount_xof=amount,
        status=status,
        payment_type=payment_type,
        provider=provider,
        currency=currency,
        provider_reference=None,
        external_reference="sira_abc",
    )


class _StubSettings:
    """SettingsCache stand-in returning the provided default for every key."""

    @staticmethod
    def instance():
        return _StubSettings()

    def get(self, key, default=None):
        return default


def _session_for(payment, subscription=None):
    """AsyncMock session: execute() yields the payment row, then the subscription row."""
    session = AsyncMock()
    payment_result = MagicMock()
    payment_result.scalar_one_or_none.return_value = payment
    sub_result = MagicMock()
    sub_result.scalar_one_or_none.return_value = subscription
    session.execute = AsyncMock(side_effect=[payment_result, sub_result])
    session.add = MagicMock()
    session.commit = AsyncMock()
    return session


class TestConfirmPayment:
    async def test_activates_new_subscription(self):
        service = SubscriptionService()
        user = _user()
        payment = _payment(user.id, amount=1000)
        session = _session_for(payment, subscription=None)
        # get(User, ...) is called by both confirm_payment and get_active_subscription.
        session.get = AsyncMock(return_value=user)

        with patch("app.domain.services.subscription_service.SettingsCache", _StubSettings):
            result = await service.confirm_payment("sira_abc", session)

        assert result["subscription_activated"] is True
        assert payment.status == PaymentStatus.confirmed
        assert payment.payment_type == PaymentType.access
        # A new Subscription was added to the session.
        assert session.add.called

    async def test_idempotent_when_already_confirmed(self):
        service = SubscriptionService()
        user = _user()
        payment = _payment(user.id, status=PaymentStatus.confirmed)
        session = AsyncMock()
        payment_result = MagicMock()
        payment_result.scalar_one_or_none.return_value = payment
        session.execute = AsyncMock(return_value=payment_result)
        session.add = MagicMock()
        session.commit = AsyncMock()

        with patch("app.domain.services.subscription_service.SettingsCache", _StubSettings):
            result = await service.confirm_payment("sira_abc", session)

        assert result["already_confirmed"] is True
        assert result["subscription_activated"] is True  # access payment
        assert not session.add.called  # no new subscription created

    async def test_not_found_returns_gracefully(self):
        service = SubscriptionService()
        session = AsyncMock()
        empty = MagicMock()
        empty.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=empty)

        result = await service.confirm_payment("missing", session)
        assert result["status"] == "not_found"
        assert result["subscription_activated"] is False

    async def test_tops_up_credits_when_subscription_active(self):
        service = SubscriptionService()
        user = _user()
        payment = _payment(user.id, amount=1000, provider="wave")
        active_sub = SimpleNamespace(message_credits=0)
        session = _session_for(payment, subscription=active_sub)
        session.get = AsyncMock(return_value=user)

        with patch("app.domain.services.subscription_service.SettingsCache", _StubSettings):
            result = await service.confirm_payment("sira_abc", session)

        assert result["subscription_activated"] is False
        assert payment.payment_type == PaymentType.messages
        assert active_sub.message_credits > 0  # credits were added

    async def test_stores_provider_reference(self):
        service = SubscriptionService()
        user = _user()
        payment = _payment(user.id, amount=1000)
        session = _session_for(payment, subscription=None)
        session.get = AsyncMock(return_value=user)

        with patch("app.domain.services.subscription_service.SettingsCache", _StubSettings):
            await service.confirm_payment("sira_abc", session, provider_reference="pstk_123")

        assert payment.provider_reference == "pstk_123"
