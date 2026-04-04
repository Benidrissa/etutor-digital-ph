"""Billing API schemas."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class CreditBalanceResponse(BaseModel):
    balance: int = Field(description="Current credit balance")
    total_purchased: int = Field(description="Total credits purchased")
    total_spent: int = Field(description="Total credits spent")
    total_earned: int = Field(description="Total credits earned (bonuses, etc.)")

    model_config = {
        "json_schema_extra": {
            "example": {
                "balance": 350,
                "total_purchased": 500,
                "total_spent": 150,
                "total_earned": 0,
            }
        }
    }


class CreditPackageResponse(BaseModel):
    id: uuid.UUID
    name_fr: str
    name_en: str
    credits: int
    price_xof: int
    price_usd: float

    model_config = {
        "from_attributes": True,
        "json_schema_extra": {
            "example": {
                "id": "10000000-0000-0000-0000-000000000002",
                "name_fr": "Essentiel",
                "name_en": "Essential",
                "credits": 500,
                "price_xof": 8000,
                "price_usd": 12.0,
            }
        },
    }


class PurchaseRequest(BaseModel):
    package_id: uuid.UUID = Field(description="ID of the credit package to purchase")


class TransactionResponse(BaseModel):
    id: uuid.UUID
    type: str
    amount: int
    balance_after: int
    description: str | None
    created_at: datetime

    model_config = {
        "from_attributes": True,
        "json_schema_extra": {
            "example": {
                "id": "aaaaaaaa-0000-0000-0000-000000000001",
                "type": "purchase",
                "amount": 500,
                "balance_after": 500,
                "description": "Purchase: Essentiel / Essential",
                "created_at": "2026-04-04T11:00:00Z",
            }
        },
    }


class PaginatedTransactionsResponse(BaseModel):
    items: list[TransactionResponse]
    total: int
    page: int
    limit: int
    has_next: bool


class UsageSummaryResponse(BaseModel):
    period: str = Field(description="Period: 'daily' or 'monthly'")
    since: str = Field(description="ISO 8601 start of the period")
    total_credits_spent: int
    breakdown: dict[str, Any] = Field(description="Credits spent per usage type")

    model_config = {
        "json_schema_extra": {
            "example": {
                "period": "monthly",
                "since": "2026-04-01T00:00:00+00:00",
                "total_credits_spent": 120,
                "breakdown": {"lesson_generation": 80, "tutor_chat": 40},
            }
        }
    }
