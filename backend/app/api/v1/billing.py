"""Billing API — balance, packages, purchase, transaction history, usage."""

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.deps_local_auth import AuthenticatedUser, get_current_user
from app.api.v1.schemas.billing import (
    CreditBalanceResponse,
    CreditPackageResponse,
    PaginatedTransactionsResponse,
    PurchaseRequest,
    TransactionResponse,
    UsageSummaryResponse,
)
from app.domain.services.credit_service import (
    CreditService,
    PackageNotFoundError,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/billing", tags=["billing"])


def _get_credit_service(db: AsyncSession = Depends(get_db)) -> CreditService:
    return CreditService(db)


@router.get(
    "/balance",
    response_model=CreditBalanceResponse,
    status_code=status.HTTP_200_OK,
    responses={
        401: {"description": "Unauthorized"},
        500: {"description": "Internal server error"},
    },
)
async def get_balance(
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    credit_service: Annotated[CreditService, Depends(_get_credit_service)],
) -> CreditBalanceResponse:
    """
    Return the current credit balance for the authenticated user.

    Includes total purchased, total spent, and total earned credits.
    """
    try:
        data = await credit_service.get_balance(current_user.id)
        return CreditBalanceResponse(**data)
    except Exception:
        logger.exception("Failed to retrieve credit balance", user_id=current_user.id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "balance_fetch_failed",
                "message": "Unable to retrieve credit balance",
            },
        )


@router.get(
    "/packages",
    response_model=list[CreditPackageResponse],
    status_code=status.HTTP_200_OK,
    responses={
        401: {"description": "Unauthorized"},
        500: {"description": "Internal server error"},
    },
)
async def list_packages(
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    credit_service: Annotated[CreditService, Depends(_get_credit_service)],
) -> list[CreditPackageResponse]:
    """
    Return all active credit packages available for purchase.

    Packages are ordered by price (cheapest first).
    Prices are given in XOF (CFA franc) and USD.
    """
    try:
        packages = await credit_service.list_packages()
        return [CreditPackageResponse.model_validate(p) for p in packages]
    except Exception:
        logger.exception("Failed to list credit packages", user_id=current_user.id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "packages_fetch_failed", "message": "Unable to retrieve packages"},
        )


@router.post(
    "/purchase",
    response_model=TransactionResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        401: {"description": "Unauthorized"},
        404: {"description": "Package not found or inactive"},
        500: {"description": "Internal server error"},
    },
)
async def purchase_credits(
    body: PurchaseRequest,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    credit_service: Annotated[CreditService, Depends(_get_credit_service)],
) -> TransactionResponse:
    """
    Purchase a credit package (virtual payment — Paystack integration coming later).

    Creates a `purchase` transaction and immediately credits the user's balance.
    Returns the resulting transaction record.
    """
    try:
        transaction = await credit_service.purchase(
            user_id=current_user.id,
            package_id=str(body.package_id),
        )
        return TransactionResponse.model_validate(transaction)
    except PackageNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "package_not_found", "message": str(e)},
        )
    except Exception:
        logger.exception(
            "Failed to purchase credits",
            user_id=current_user.id,
            package_id=str(body.package_id),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "purchase_failed", "message": "Unable to complete purchase"},
        )


@router.get(
    "/transactions",
    response_model=PaginatedTransactionsResponse,
    status_code=status.HTTP_200_OK,
    responses={
        401: {"description": "Unauthorized"},
        500: {"description": "Internal server error"},
    },
)
async def list_transactions(
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    credit_service: Annotated[CreditService, Depends(_get_credit_service)],
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)"),
    limit: int = Query(default=20, ge=1, le=100, description="Items per page"),
    type: str | None = Query(
        default=None,
        description="Filter by transaction type: purchase | spend | earn | refund",
    ),
) -> PaginatedTransactionsResponse:
    """
    Return paginated credit transaction history for the authenticated user.

    Supports optional `type` filter to narrow results by transaction type.
    Ordered by most recent first.
    """
    try:
        result = await credit_service.list_transactions(
            user_id=current_user.id,
            page=page,
            limit=limit,
            type_filter=type,
        )
        items = [TransactionResponse.model_validate(t) for t in result["items"]]
        return PaginatedTransactionsResponse(
            items=items,
            total=result["total"],
            page=result["page"],
            limit=result["limit"],
            has_next=result["has_next"],
        )
    except Exception:
        logger.exception("Failed to list transactions", user_id=current_user.id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "transactions_fetch_failed",
                "message": "Unable to retrieve transaction history",
            },
        )


@router.get(
    "/usage",
    response_model=UsageSummaryResponse,
    status_code=status.HTTP_200_OK,
    responses={
        401: {"description": "Unauthorized"},
        500: {"description": "Internal server error"},
    },
)
async def get_usage_summary(
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    credit_service: Annotated[CreditService, Depends(_get_credit_service)],
    period: str = Query(
        default="monthly",
        description="Aggregation period: 'daily' (today) or 'monthly' (current month)",
    ),
) -> UsageSummaryResponse:
    """
    Return AI usage credit summary for the authenticated user.

    - `daily`: aggregates usage for today only
    - `monthly`: aggregates usage since the first day of the current month

    The `breakdown` field groups credits spent by usage type
    (e.g. lesson_generation, tutor_chat, quiz_generation).
    """
    if period not in ("daily", "monthly"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "invalid_period",
                "message": "period must be 'daily' or 'monthly'",
            },
        )
    try:
        data = await credit_service.get_usage_summary(
            user_id=current_user.id,
            period=period,
        )
        return UsageSummaryResponse(**data)
    except Exception:
        logger.exception("Failed to retrieve usage summary", user_id=current_user.id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "usage_fetch_failed", "message": "Unable to retrieve usage summary"},
        )
