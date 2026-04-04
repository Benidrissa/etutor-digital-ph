"""Credit service — balance management, purchase, deduction, and earning."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.credit import (
    CreditAccount,
    CreditPackage,
    CreditTransaction,
    TransactionType,
)

logger = structlog.get_logger()

FREE_TRIAL_CREDITS = 100


class InsufficientCreditsError(Exception):
    """Raised when a deduction would result in a negative balance."""

    def __init__(self, balance: int, required: int) -> None:
        self.balance = balance
        self.required = required
        super().__init__(f"Insufficient credits: have {balance}, need {required}")


class CreditService:
    """Core financial service for all credit operations.

    All mutating methods use SELECT ... FOR UPDATE to prevent race conditions.
    Every mutation creates an immutable CreditTransaction record with a
    balance_after snapshot for full audit trail.
    """

    async def get_or_create_account(self, user_id: UUID, session: AsyncSession) -> CreditAccount:
        """Get existing credit account or create one lazily on first use.

        Args:
            user_id: User UUID
            session: Database session

        Returns:
            CreditAccount for the user
        """
        result = await session.execute(
            select(CreditAccount).where(CreditAccount.user_id == user_id).with_for_update()
        )
        account = result.scalar_one_or_none()

        if account is None:
            account = CreditAccount(
                id=uuid.uuid4(),
                user_id=user_id,
                balance=0,
                total_purchased=0,
                total_spent=0,
                total_earned=0,
                total_withdrawn=0,
            )
            session.add(account)
            await session.flush()
            logger.info("Credit account created", user_id=str(user_id), account_id=str(account.id))

        return account

    async def get_balance(self, user_id: UUID, session: AsyncSession) -> int:
        """Return current credit balance for a user.

        Args:
            user_id: User UUID
            session: Database session

        Returns:
            Current balance in credits (0 if no account exists yet)
        """
        result = await session.execute(
            select(CreditAccount.balance).where(CreditAccount.user_id == user_id)
        )
        balance = result.scalar_one_or_none()
        return balance if balance is not None else 0

    async def check_balance(
        self, user_id: UUID, required_amount: int, session: AsyncSession
    ) -> bool:
        """Check whether user has sufficient credits.

        Args:
            user_id: User UUID
            required_amount: Credits needed
            session: Database session

        Returns:
            True if balance >= required_amount, False otherwise
        """
        balance = await self.get_balance(user_id, session)
        return balance >= required_amount

    async def purchase_credits(
        self,
        user_id: UUID,
        package_id: UUID,
        session: AsyncSession,
        metadata: dict[str, Any] | None = None,
    ) -> CreditTransaction:
        """Add credits from a package purchase and create a transaction record.

        Args:
            user_id: User UUID
            package_id: CreditPackage UUID
            session: Database session
            metadata: Optional extra data (payment reference, provider, etc.)

        Returns:
            The created CreditTransaction

        Raises:
            ValueError: If package not found or not active
        """
        pkg_result = await session.execute(
            select(CreditPackage).where(
                CreditPackage.id == package_id, CreditPackage.is_active.is_(True)
            )
        )
        package = pkg_result.scalar_one_or_none()
        if package is None:
            raise ValueError(f"Credit package {package_id} not found or inactive")

        account = await self.get_or_create_account(user_id, session)

        new_balance = account.balance + package.credits
        account.balance = new_balance
        account.total_purchased += package.credits
        account.updated_at = datetime.utcnow()

        tx = CreditTransaction(
            id=uuid.uuid4(),
            account_id=account.id,
            type=TransactionType.credit_purchase,
            amount=package.credits,
            balance_after=new_balance,
            reference_id=package_id,
            reference_type="package",
            description=f"Achat de crédits — {package.name_fr}",
            metadata_json=metadata,
        )
        session.add(tx)
        await session.flush()

        logger.info(
            "Credits purchased",
            user_id=str(user_id),
            package_id=str(package_id),
            credits=package.credits,
            new_balance=new_balance,
        )
        return tx

    async def deduct(
        self,
        user_id: UUID,
        amount: int,
        transaction_type: TransactionType,
        description: str,
        session: AsyncSession,
        reference_id: UUID | None = None,
        reference_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CreditTransaction:
        """Atomically deduct credits with balance check.

        Uses SELECT FOR UPDATE to prevent concurrent negative-balance issues.

        Args:
            user_id: User UUID
            amount: Credits to deduct (positive integer)
            transaction_type: Type of deduction
            description: Human-readable description
            session: Database session
            reference_id: Optional FK reference (content_id, course_id, etc.)
            reference_type: Optional reference type label
            metadata: Optional extra data

        Returns:
            The created CreditTransaction

        Raises:
            InsufficientCreditsError: If balance < amount
            ValueError: If amount <= 0
        """
        if amount <= 0:
            raise ValueError(f"Deduction amount must be positive, got {amount}")

        account = await self.get_or_create_account(user_id, session)

        if account.balance < amount:
            raise InsufficientCreditsError(balance=account.balance, required=amount)

        new_balance = account.balance - amount
        account.balance = new_balance
        account.total_spent += amount
        account.updated_at = datetime.utcnow()

        tx = CreditTransaction(
            id=uuid.uuid4(),
            account_id=account.id,
            type=transaction_type,
            amount=-amount,
            balance_after=new_balance,
            reference_id=reference_id,
            reference_type=reference_type,
            description=description,
            metadata_json=metadata,
        )
        session.add(tx)
        await session.flush()

        logger.info(
            "Credits deducted",
            user_id=str(user_id),
            amount=amount,
            type=transaction_type.value,
            new_balance=new_balance,
        )
        return tx

    async def earn(
        self,
        user_id: UUID,
        amount: int,
        transaction_type: TransactionType,
        description: str,
        session: AsyncSession,
        reference_id: UUID | None = None,
        reference_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CreditTransaction:
        """Credit expert earnings (course sales, commissions, etc.).

        Args:
            user_id: User UUID (expert)
            amount: Credits to add (positive integer)
            transaction_type: Type of earning (course_earning, commission, etc.)
            description: Human-readable description
            session: Database session
            reference_id: Optional FK reference
            reference_type: Optional reference type label
            metadata: Optional extra data

        Returns:
            The created CreditTransaction

        Raises:
            ValueError: If amount <= 0
        """
        if amount <= 0:
            raise ValueError(f"Earning amount must be positive, got {amount}")

        account = await self.get_or_create_account(user_id, session)

        new_balance = account.balance + amount
        account.balance = new_balance
        account.total_earned += amount
        account.updated_at = datetime.utcnow()

        tx = CreditTransaction(
            id=uuid.uuid4(),
            account_id=account.id,
            type=transaction_type,
            amount=amount,
            balance_after=new_balance,
            reference_id=reference_id,
            reference_type=reference_type,
            description=description,
            metadata_json=metadata,
        )
        session.add(tx)
        await session.flush()

        logger.info(
            "Credits earned",
            user_id=str(user_id),
            amount=amount,
            type=transaction_type.value,
            new_balance=new_balance,
        )
        return tx

    async def grant_free_trial(
        self, user_id: UUID, session: AsyncSession
    ) -> CreditTransaction | None:
        """Grant free trial credits on registration (idempotent).

        Checks whether a free_trial transaction already exists for this user
        before granting, so it is safe to call from the registration flow
        without double-granting.

        Args:
            user_id: User UUID
            session: Database session

        Returns:
            CreditTransaction if credits were granted, None if already granted
        """
        account = await self.get_or_create_account(user_id, session)

        existing = await session.execute(
            select(CreditTransaction)
            .where(
                CreditTransaction.account_id == account.id,
                CreditTransaction.type == TransactionType.free_trial,
            )
            .limit(1)
        )
        if existing.scalar_one_or_none() is not None:
            logger.info("Free trial already granted, skipping", user_id=str(user_id))
            return None

        new_balance = account.balance + FREE_TRIAL_CREDITS
        account.balance = new_balance
        account.total_purchased += FREE_TRIAL_CREDITS
        account.updated_at = datetime.utcnow()

        tx = CreditTransaction(
            id=uuid.uuid4(),
            account_id=account.id,
            type=TransactionType.free_trial,
            amount=FREE_TRIAL_CREDITS,
            balance_after=new_balance,
            reference_id=None,
            reference_type=None,
            description="Crédits d'essai gratuit offerts à l'inscription",
            metadata_json=None,
        )
        session.add(tx)
        await session.flush()

        logger.info(
            "Free trial credits granted",
            user_id=str(user_id),
            credits=FREE_TRIAL_CREDITS,
            new_balance=new_balance,
        )
        return tx

    async def get_transactions(
        self,
        user_id: UUID,
        session: AsyncSession,
        transaction_type: TransactionType | None = None,
        since: datetime | None = None,
        page: int = 1,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Return paginated transaction history for a user.

        Args:
            user_id: User UUID
            session: Database session
            transaction_type: Optional filter by transaction type
            since: Optional lower-bound on created_at (for delta sync)
            page: Page number (1-based)
            limit: Items per page (max 100)

        Returns:
            Dict with keys: items, total, page, limit, has_next
        """
        limit = min(limit, 100)
        offset = (page - 1) * limit

        account_result = await session.execute(
            select(CreditAccount.id).where(CreditAccount.user_id == user_id)
        )
        account_id = account_result.scalar_one_or_none()

        if account_id is None:
            return {"items": [], "total": 0, "page": page, "limit": limit, "has_next": False}

        base_query = select(CreditTransaction).where(CreditTransaction.account_id == account_id)

        if transaction_type is not None:
            base_query = base_query.where(CreditTransaction.type == transaction_type)

        if since is not None:
            base_query = base_query.where(CreditTransaction.created_at > since)

        from sqlalchemy import func as sqlfunc

        count_result = await session.execute(
            select(sqlfunc.count()).select_from(base_query.subquery())
        )
        total = count_result.scalar_one()

        rows_result = await session.execute(
            base_query.order_by(CreditTransaction.created_at.desc()).offset(offset).limit(limit)
        )
        transactions = rows_result.scalars().all()

        items = [
            {
                "id": str(tx.id),
                "type": tx.type.value,
                "amount": tx.amount,
                "balance_after": tx.balance_after,
                "reference_id": str(tx.reference_id) if tx.reference_id else None,
                "reference_type": tx.reference_type,
                "description": tx.description,
                "metadata_json": tx.metadata_json,
                "created_at": tx.created_at.isoformat(),
            }
            for tx in transactions
        ]

        return {
            "items": items,
            "total": total,
            "page": page,
            "limit": limit,
            "has_next": offset + limit < total,
        }
