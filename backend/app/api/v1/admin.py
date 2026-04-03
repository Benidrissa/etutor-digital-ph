"""Admin API endpoints for content management and review."""

from __future__ import annotations

import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.domain.services.content_reviewer import ContentReviewerService, IssueType

logger = structlog.get_logger()
router = APIRouter(prefix="/admin", tags=["admin"])


class ReviewIssueResponse(BaseModel):
    issue_type: IssueType
    severity: str
    message: str
    details: dict


class ModuleReviewResponse(BaseModel):
    module_id: str
    module_number: int
    title: str
    issues: list[ReviewIssueResponse]
    passed: bool


@router.post("/review-module/{module_id}", response_model=ModuleReviewResponse)
async def review_module(
    module_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ModuleReviewResponse:
    """Review a module for content consistency issues.

    Validates:
    - Module declared hours vs sum of unit estimated_minutes
    - Unit order_index is sequential starting from 1
    - No duplicate unit titles
    - Module has books_sources defined

    Accepts both UUID strings and module codes (e.g. "M01").
    """
    resolved_id: uuid.UUID

    if module_id.upper().startswith("M") and len(module_id) <= 4:
        from sqlalchemy import select

        from app.domain.models.module import Module

        try:
            module_number = int(module_id[1:])
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid module code: {module_id}")

        result = await db.execute(select(Module).where(Module.module_number == module_number))
        module = result.scalar_one_or_none()
        if not module:
            raise HTTPException(status_code=404, detail=f"Module {module_id} not found")
        resolved_id = module.id
    else:
        try:
            resolved_id = uuid.UUID(module_id)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid module identifier: {module_id}")

    service = ContentReviewerService(db)

    try:
        review_result = await service.review_module(resolved_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return ModuleReviewResponse(
        module_id=review_result.module_id,
        module_number=review_result.module_number,
        title=review_result.title,
        issues=[
            ReviewIssueResponse(
                issue_type=issue.issue_type,
                severity=issue.severity,
                message=issue.message,
                details=issue.details,
            )
            for issue in review_result.issues
        ],
        passed=review_result.passed,
    )
