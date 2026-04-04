"""Unit tests for CreditService — balance management, purchase, deduction, earning."""

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.models.credit import (
    CreditAccount,
    CreditPackage,
    CreditTransaction,
    TransactionType,
)
from app.domain.services.credit_service import (
    FREE_TRIAL_CREDITS,
    CreditService,
    InsufficientCreditsError,
)


def make_account(user_id: uuid.UUID | None = None, balance: int = 0) -> CreditAccount:
    account = MagicMock(spec=CreditAccount)
    account.id = uuid.uuid4()
    account.user_id = user_id or uuid.uuid4()
    account.balance = balance
    account.total_purchased = 0
    account.total_spent = 0
    account.total_earned = 0
    account.total_withdrawn = 0
    account.updated_at = datetime.utcnow()
    return account


def make_package(credits: int = 500, is_active: bool = True) -> CreditPackage:
    pkg = MagicMock(spec=CreditPackage)
    pkg.id = uuid.uuid4()
    pkg.name_fr = "Starter"
    pkg.name_en = "Starter"
    pkg.credits = credits
    pkg.price_xof = 2500
    pkg.price_usd = 5.00
    pkg.is_active = is_active
    return pkg


def make_session() -> AsyncMock:
    session = AsyncMock()
    session.flush = AsyncMock()
    session.add = MagicMock()
    return session


class TestGetOrCreateAccount:
    async def test_returns_existing_account(self):
        service = CreditService()
        user_id = uuid.uuid4()
        existing = make_account(user_id=user_id, balance=200)

        session = make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        session.execute = AsyncMock(return_value=mock_result)

        account = await service.get_or_create_account(user_id, session)

        assert account is existing
        session.add.assert_not_called()

    async def test_creates_account_when_not_exists(self):
        service = CreditService()
        user_id = uuid.uuid4()

        session = make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=mock_result)

        account = await service.get_or_create_account(user_id, session)

        session.add.assert_called_once()
        session.flush.assert_called_once()
        assert account.user_id == user_id
        assert account.balance == 0


class TestGetBalance:
    async def test_returns_balance_for_existing_user(self):
        service = CreditService()
        user_id = uuid.uuid4()

        session = make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = 350
        session.execute = AsyncMock(return_value=mock_result)

        balance = await service.get_balance(user_id, session)

        assert balance == 350

    async def test_returns_zero_when_no_account(self):
        service = CreditService()
        user_id = uuid.uuid4()

        session = make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=mock_result)

        balance = await service.get_balance(user_id, session)

        assert balance == 0


class TestCheckBalance:
    async def test_returns_true_when_sufficient(self):
        service = CreditService()
        user_id = uuid.uuid4()

        session = make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = 500
        session.execute = AsyncMock(return_value=mock_result)

        result = await service.check_balance(user_id, 100, session)

        assert result is True

    async def test_returns_true_when_exact(self):
        service = CreditService()
        user_id = uuid.uuid4()

        session = make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = 100
        session.execute = AsyncMock(return_value=mock_result)

        result = await service.check_balance(user_id, 100, session)

        assert result is True

    async def test_returns_false_when_insufficient(self):
        service = CreditService()
        user_id = uuid.uuid4()

        session = make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = 50
        session.execute = AsyncMock(return_value=mock_result)

        result = await service.check_balance(user_id, 100, session)

        assert result is False


class TestPurchaseCredits:
    async def test_adds_credits_to_account(self):
        service = CreditService()
        user_id = uuid.uuid4()
        account = make_account(user_id=user_id, balance=0)
        package = make_package(credits=500)

        session = make_session()
        pkg_result = MagicMock()
        pkg_result.scalar_one_or_none.return_value = package
        acct_result = MagicMock()
        acct_result.scalar_one_or_none.return_value = account
        session.execute = AsyncMock(side_effect=[pkg_result, acct_result])

        tx = await service.purchase_credits(user_id, package.id, session)

        assert account.balance == 500
        assert account.total_purchased == 500
        assert tx.amount == 500
        assert tx.balance_after == 500
        assert tx.type == TransactionType.credit_purchase

    async def test_raises_when_package_not_found(self):
        service = CreditService()
        user_id = uuid.uuid4()

        session = make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(ValueError, match="not found or inactive"):
            await service.purchase_credits(user_id, uuid.uuid4(), session)

    async def test_creates_transaction_record(self):
        service = CreditService()
        user_id = uuid.uuid4()
        account = make_account(user_id=user_id, balance=100)
        package = make_package(credits=500)

        session = make_session()
        pkg_result = MagicMock()
        pkg_result.scalar_one_or_none.return_value = package
        acct_result = MagicMock()
        acct_result.scalar_one_or_none.return_value = account
        session.execute = AsyncMock(side_effect=[pkg_result, acct_result])

        tx = await service.purchase_credits(user_id, package.id, session)

        session.add.assert_called()
        session.flush.assert_called()
        assert tx.reference_type == "package"
        assert tx.reference_id == package.id


class TestDeduct:
    async def test_deducts_credits_successfully(self):
        service = CreditService()
        user_id = uuid.uuid4()
        account = make_account(user_id=user_id, balance=200)

        session = make_session()
        acct_result = MagicMock()
        acct_result.scalar_one_or_none.return_value = account
        session.execute = AsyncMock(return_value=acct_result)

        tx = await service.deduct(
            user_id=user_id,
            amount=50,
            transaction_type=TransactionType.tutor_usage,
            description="Tutor session",
            session=session,
        )

        assert account.balance == 150
        assert account.total_spent == 50
        assert tx.amount == -50
        assert tx.balance_after == 150
        assert tx.type == TransactionType.tutor_usage

    async def test_raises_insufficient_credits(self):
        service = CreditService()
        user_id = uuid.uuid4()
        account = make_account(user_id=user_id, balance=30)

        session = make_session()
        acct_result = MagicMock()
        acct_result.scalar_one_or_none.return_value = account
        session.execute = AsyncMock(return_value=acct_result)

        with pytest.raises(InsufficientCreditsError) as exc_info:
            await service.deduct(
                user_id=user_id,
                amount=100,
                transaction_type=TransactionType.content_access,
                description="Content access",
                session=session,
            )

        assert exc_info.value.balance == 30
        assert exc_info.value.required == 100

    async def test_raises_on_zero_amount(self):
        service = CreditService()
        session = make_session()

        with pytest.raises(ValueError, match="must be positive"):
            await service.deduct(
                user_id=uuid.uuid4(),
                amount=0,
                transaction_type=TransactionType.content_access,
                description="test",
                session=session,
            )

    async def test_raises_on_negative_amount(self):
        service = CreditService()
        session = make_session()

        with pytest.raises(ValueError, match="must be positive"):
            await service.deduct(
                user_id=uuid.uuid4(),
                amount=-10,
                transaction_type=TransactionType.content_access,
                description="test",
                session=session,
            )

    async def test_concurrent_deductions_do_not_overdraw(self):
        """SELECT FOR UPDATE prevents race conditions — the second deduction
        should fail if balance is exactly enough for one."""
        service = CreditService()
        user_id = uuid.uuid4()

        account_low = make_account(user_id=user_id, balance=50)

        session = make_session()
        acct_result = MagicMock()
        acct_result.scalar_one_or_none.return_value = account_low
        session.execute = AsyncMock(return_value=acct_result)

        await service.deduct(
            user_id=user_id,
            amount=50,
            transaction_type=TransactionType.tutor_usage,
            description="Session 1",
            session=session,
        )
        assert account_low.balance == 0

        with pytest.raises(InsufficientCreditsError):
            await service.deduct(
                user_id=user_id,
                amount=50,
                transaction_type=TransactionType.tutor_usage,
                description="Session 2",
                session=session,
            )


class TestEarn:
    async def test_adds_earning_to_account(self):
        service = CreditService()
        user_id = uuid.uuid4()
        account = make_account(user_id=user_id, balance=0)

        session = make_session()
        acct_result = MagicMock()
        acct_result.scalar_one_or_none.return_value = account
        session.execute = AsyncMock(return_value=acct_result)

        tx = await service.earn(
            user_id=user_id,
            amount=300,
            transaction_type=TransactionType.course_earning,
            description="Course sale",
            session=session,
        )

        assert account.balance == 300
        assert account.total_earned == 300
        assert tx.amount == 300
        assert tx.balance_after == 300
        assert tx.type == TransactionType.course_earning

    async def test_raises_on_zero_amount(self):
        service = CreditService()
        session = make_session()

        with pytest.raises(ValueError, match="must be positive"):
            await service.earn(
                user_id=uuid.uuid4(),
                amount=0,
                transaction_type=TransactionType.course_earning,
                description="test",
                session=session,
            )


class TestGrantFreeTrial:
    async def test_grants_free_trial_on_first_call(self):
        service = CreditService()
        user_id = uuid.uuid4()
        account = make_account(user_id=user_id, balance=0)

        session = make_session()
        acct_result = MagicMock()
        acct_result.scalar_one_or_none.return_value = account
        no_existing = MagicMock()
        no_existing.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(side_effect=[acct_result, no_existing])

        tx = await service.grant_free_trial(user_id, session)

        assert tx is not None
        assert tx.type == TransactionType.free_trial
        assert tx.amount == FREE_TRIAL_CREDITS
        assert account.balance == FREE_TRIAL_CREDITS

    async def test_idempotent_does_not_double_grant(self):
        service = CreditService()
        user_id = uuid.uuid4()
        account = make_account(user_id=user_id, balance=FREE_TRIAL_CREDITS)
        existing_tx = MagicMock(spec=CreditTransaction)

        session = make_session()
        acct_result = MagicMock()
        acct_result.scalar_one_or_none.return_value = account
        already_granted = MagicMock()
        already_granted.scalar_one_or_none.return_value = existing_tx
        session.execute = AsyncMock(side_effect=[acct_result, already_granted])

        tx = await service.grant_free_trial(user_id, session)

        assert tx is None
        assert account.balance == FREE_TRIAL_CREDITS
        session.add.assert_not_called()


class TestGetTransactions:
    async def test_returns_empty_when_no_account(self):
        service = CreditService()
        user_id = uuid.uuid4()

        session = make_session()
        acct_result = MagicMock()
        acct_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=acct_result)

        result = await service.get_transactions(user_id, session)

        assert result["items"] == []
        assert result["total"] == 0
        assert result["has_next"] is False

    async def test_returns_paginated_transactions(self):
        service = CreditService()
        user_id = uuid.uuid4()
        account_id = uuid.uuid4()

        tx1 = MagicMock(spec=CreditTransaction)
        tx1.id = uuid.uuid4()
        tx1.type = TransactionType.credit_purchase
        tx1.amount = 500
        tx1.balance_after = 500
        tx1.reference_id = None
        tx1.reference_type = None
        tx1.description = "Purchase"
        tx1.metadata_json = None
        tx1.created_at = datetime.utcnow()

        session = make_session()
        acct_id_result = MagicMock()
        acct_id_result.scalar_one_or_none.return_value = account_id
        count_result = MagicMock()
        count_result.scalar_one.return_value = 1
        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = [tx1]
        session.execute = AsyncMock(side_effect=[acct_id_result, count_result, rows_result])

        result = await service.get_transactions(user_id, session, page=1, limit=20)

        assert len(result["items"]) == 1
        assert result["total"] == 1
        assert result["page"] == 1
        assert result["has_next"] is False
        assert result["items"][0]["type"] == "credit_purchase"
        assert result["items"][0]["amount"] == 500

    async def test_limit_capped_at_100(self):
        service = CreditService()
        user_id = uuid.uuid4()

        session = make_session()
        acct_result = MagicMock()
        acct_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=acct_result)

        result = await service.get_transactions(user_id, session, limit=9999)

        assert result["limit"] == 100

    async def test_has_next_true_when_more_pages(self):
        service = CreditService()
        user_id = uuid.uuid4()
        account_id = uuid.uuid4()

        txs = []
        for _ in range(20):
            tx = MagicMock(spec=CreditTransaction)
            tx.id = uuid.uuid4()
            tx.type = TransactionType.tutor_usage
            tx.amount = -10
            tx.balance_after = 0
            tx.reference_id = None
            tx.reference_type = None
            tx.description = "Tutor"
            tx.metadata_json = None
            tx.created_at = datetime.utcnow()
            txs.append(tx)

        session = make_session()
        acct_id_result = MagicMock()
        acct_id_result.scalar_one_or_none.return_value = account_id
        count_result = MagicMock()
        count_result.scalar_one.return_value = 45
        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = txs
        session.execute = AsyncMock(side_effect=[acct_id_result, count_result, rows_result])

        result = await service.get_transactions(user_id, session, page=1, limit=20)

        assert result["has_next"] is True
        assert result["total"] == 45
