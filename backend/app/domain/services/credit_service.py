"""Credit management service — balance, packages, purchase, transactions, usage."""

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.billing import ApiUsageLog, CreditPackage, CreditTransaction

logger = structlog.get_logger(__name__)

TRANSACTION_TYPE_PURCHASE = "purchase"
TRANSACTION_TYPE_SPEND = "spend"
TRANSACTION_TYPE_EARN = "earn"
TRANSACTION_TYPE_REFUND = "refund"


class InsufficientCreditsError(Exception):
    pass


class PackageNotFoundError(Exception):
    pass


class CreditService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_balance(self, user_id: str) -> dict[str, int]:
        uid = uuid.UUID(user_id)

        purchased_q = select(func.coalesce(func.sum(CreditTransaction.amount), 0)).where(
            CreditTransaction.user_id == uid,
            CreditTransaction.type == TRANSACTION_TYPE_PURCHASE,
        )
        earned_q = select(func.coalesce(func.sum(CreditTransaction.amount), 0)).where(
            CreditTransaction.user_id == uid,
            CreditTransaction.type == TRANSACTION_TYPE_EARN,
        )
        spent_q = select(func.coalesce(func.sum(func.abs(CreditTransaction.amount)), 0)).where(
            CreditTransaction.user_id == uid,
            CreditTransaction.type == TRANSACTION_TYPE_SPEND,
        )

        purchased_result = await self._session.execute(purchased_q)
        earned_result = await self._session.execute(earned_q)
        spent_result = await self._session.execute(spent_q)

        total_purchased: int = purchased_result.scalar_one()
        total_earned: int = earned_result.scalar_one()
        total_spent: int = spent_result.scalar_one()
        balance: int = total_purchased + total_earned - total_spent

        return {
            "balance": max(0, balance),
            "total_purchased": total_purchased,
            "total_spent": total_spent,
            "total_earned": total_earned,
        }

    async def list_packages(self) -> list[CreditPackage]:
        result = await self._session.execute(
            select(CreditPackage)
            .where(CreditPackage.is_active.is_(True))
            .order_by(CreditPackage.price_xof.asc())
        )
        return list(result.scalars().all())

    async def purchase(self, user_id: str, package_id: str) -> CreditTransaction:
        uid = uuid.UUID(user_id)
        pkg_id = uuid.UUID(package_id)

        pkg_result = await self._session.execute(
            select(CreditPackage).where(
                CreditPackage.id == pkg_id,
                CreditPackage.is_active.is_(True),
            )
        )
        package = pkg_result.scalar_one_or_none()
        if package is None:
            raise PackageNotFoundError(f"Package {package_id} not found or inactive")

        balance_data = await self.get_balance(user_id)
        new_balance = balance_data["balance"] + package.credits

        transaction = CreditTransaction(
            id=uuid.uuid4(),
            user_id=uid,
            package_id=pkg_id,
            type=TRANSACTION_TYPE_PURCHASE,
            amount=package.credits,
            balance_after=new_balance,
            description=f"Purchase: {package.name_fr} / {package.name_en}",
        )
        self._session.add(transaction)
        await self._session.commit()
        await self._session.refresh(transaction)

        logger.info(
            "Credits purchased",
            user_id=user_id,
            package_id=package_id,
            credits=package.credits,
            new_balance=new_balance,
        )
        return transaction

    async def spend_credits(
        self,
        user_id: str,
        amount: int,
        usage_type: str,
        description: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CreditTransaction:
        uid = uuid.UUID(user_id)
        balance_data = await self.get_balance(user_id)

        if balance_data["balance"] < amount:
            raise InsufficientCreditsError(
                f"Insufficient credits: has {balance_data['balance']}, needs {amount}"
            )

        new_balance = balance_data["balance"] - amount

        transaction = CreditTransaction(
            id=uuid.uuid4(),
            user_id=uid,
            type=TRANSACTION_TYPE_SPEND,
            amount=-amount,
            balance_after=new_balance,
            description=description or f"Usage: {usage_type}",
        )
        self._session.add(transaction)

        usage_log = ApiUsageLog(
            id=uuid.uuid4(),
            user_id=uid,
            usage_type=usage_type,
            credits_spent=amount,
            extra=metadata,
        )
        self._session.add(usage_log)

        await self._session.commit()
        await self._session.refresh(transaction)

        logger.info(
            "Credits spent",
            user_id=user_id,
            amount=amount,
            usage_type=usage_type,
            new_balance=new_balance,
        )
        return transaction

    async def list_transactions(
        self,
        user_id: str,
        page: int = 1,
        limit: int = 20,
        type_filter: str | None = None,
    ) -> dict[str, Any]:
        uid = uuid.UUID(user_id)
        base_query = select(CreditTransaction).where(CreditTransaction.user_id == uid)

        if type_filter:
            base_query = base_query.where(CreditTransaction.type == type_filter)

        count_query = select(func.count()).select_from(base_query.subquery())
        count_result = await self._session.execute(count_query)
        total: int = count_result.scalar_one()

        items_query = (
            base_query.order_by(CreditTransaction.created_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
        items_result = await self._session.execute(items_query)
        items = list(items_result.scalars().all())

        return {
            "items": items,
            "total": total,
            "page": page,
            "limit": limit,
            "has_next": (page * limit) < total,
        }

    async def get_usage_summary(
        self,
        user_id: str,
        period: str = "monthly",
    ) -> dict[str, Any]:
        uid = uuid.UUID(user_id)
        now = datetime.now(tz=UTC)

        if period == "daily":
            since = now.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            since = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        total_q = select(func.coalesce(func.sum(ApiUsageLog.credits_spent), 0)).where(
            ApiUsageLog.user_id == uid,
            ApiUsageLog.created_at >= since,
        )
        total_result = await self._session.execute(total_q)
        total_credits_spent: int = total_result.scalar_one()

        breakdown_q = (
            select(ApiUsageLog.usage_type, func.sum(ApiUsageLog.credits_spent).label("total"))
            .where(
                ApiUsageLog.user_id == uid,
                ApiUsageLog.created_at >= since,
            )
            .group_by(ApiUsageLog.usage_type)
        )
        breakdown_result = await self._session.execute(breakdown_q)
        breakdown = {row.usage_type: int(row.total) for row in breakdown_result.all()}

        return {
            "period": period,
            "since": since.isoformat(),
            "total_credits_spent": total_credits_spent,
            "breakdown": breakdown,
        }
