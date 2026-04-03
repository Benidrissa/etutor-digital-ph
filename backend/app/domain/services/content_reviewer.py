"""Content review service for validating curriculum consistency."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.models.module import Module
from app.domain.models.module_unit import ModuleUnit

logger = structlog.get_logger()

WORDS_PER_MINUTE = 200
MARGIN_FACTOR = 0.25


class IssueType(StrEnum):
    MODULE_HOURS_MISMATCH = "module_hours_mismatch"
    UNIT_READING_TIME_MISMATCH = "unit_reading_time_mismatch"
    UNIT_NUMBERING_GAP = "unit_numbering_gap"
    DUPLICATE_UNIT_CONTENT = "duplicate_unit_content"
    MISSING_SOURCES = "missing_sources"


@dataclass
class ReviewIssue:
    issue_type: IssueType
    severity: str
    message: str
    details: dict


@dataclass
class ModuleReviewResult:
    module_id: str
    module_number: int
    title: str
    issues: list[ReviewIssue]
    passed: bool


def _reading_time_minutes(word_count: int) -> int:
    return max(1, round(word_count / WORDS_PER_MINUTE))


class ContentReviewerService:
    """Validates curriculum consistency for a module."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def review_module(self, module_id: uuid.UUID) -> ModuleReviewResult:
        result = await self.session.execute(
            select(Module).options(selectinload(Module.units)).where(Module.id == module_id)
        )
        module = result.scalar_one_or_none()

        if not module:
            raise ValueError(f"Module {module_id} not found")

        issues: list[ReviewIssue] = []

        units: list[ModuleUnit] = sorted(module.units, key=lambda u: u.order_index)

        issues.extend(self._check_hours_consistency(module, units))
        issues.extend(self._check_unit_numbering(units))
        issues.extend(self._check_duplicate_titles(units))
        issues.extend(self._check_module_sources(module, units))

        logger.info(
            "Module review complete",
            module_id=str(module_id),
            issue_count=len(issues),
        )

        return ModuleReviewResult(
            module_id=str(module_id),
            module_number=module.module_number,
            title=module.title_fr,
            issues=issues,
            passed=len(issues) == 0,
        )

    def _check_hours_consistency(
        self, module: Module, units: list[ModuleUnit]
    ) -> list[ReviewIssue]:
        issues: list[ReviewIssue] = []
        total_minutes = sum(u.estimated_minutes for u in units)
        total_hours_from_units = total_minutes / 60
        declared_hours = module.estimated_hours
        margin = declared_hours * MARGIN_FACTOR

        if abs(total_hours_from_units - declared_hours) > margin:
            issues.append(
                ReviewIssue(
                    issue_type=IssueType.MODULE_HOURS_MISMATCH,
                    severity="error",
                    message=(
                        f"Module declares {declared_hours}h but unit minutes sum to "
                        f"{total_minutes} min ({total_hours_from_units:.1f}h). "
                        f"Allowed margin: ±{margin:.1f}h."
                    ),
                    details={
                        "declared_hours": declared_hours,
                        "unit_total_minutes": total_minutes,
                        "unit_total_hours": round(total_hours_from_units, 2),
                        "margin_hours": round(margin, 2),
                    },
                )
            )
        return issues

    def _check_unit_numbering(self, units: list[ModuleUnit]) -> list[ReviewIssue]:
        issues: list[ReviewIssue] = []
        if not units:
            return issues

        order_indices = [u.order_index for u in units]
        expected = list(range(1, len(units) + 1))

        if order_indices != expected:
            issues.append(
                ReviewIssue(
                    issue_type=IssueType.UNIT_NUMBERING_GAP,
                    severity="error",
                    message=(
                        f"Unit order_indices {order_indices} are not sequential "
                        f"starting from 1 (expected {expected})."
                    ),
                    details={
                        "actual_order_indices": order_indices,
                        "expected_order_indices": expected,
                    },
                )
            )
        return issues

    def _check_duplicate_titles(self, units: list[ModuleUnit]) -> list[ReviewIssue]:
        issues: list[ReviewIssue] = []
        seen_titles: set[str] = set()
        for unit in units:
            title = unit.title_fr.strip().lower()
            if title in seen_titles:
                issues.append(
                    ReviewIssue(
                        issue_type=IssueType.DUPLICATE_UNIT_CONTENT,
                        severity="warning",
                        message=f"Duplicate unit title detected: '{unit.title_fr}'",
                        details={
                            "unit_number": unit.unit_number,
                            "title_fr": unit.title_fr,
                        },
                    )
                )
            seen_titles.add(title)
        return issues

    def _check_module_sources(self, module: Module, units: list[ModuleUnit]) -> list[ReviewIssue]:
        issues: list[ReviewIssue] = []
        if not module.books_sources:
            issues.append(
                ReviewIssue(
                    issue_type=IssueType.MISSING_SOURCES,
                    severity="warning",
                    message="Module has no books_sources defined.",
                    details={"module_number": module.module_number},
                )
            )
        return issues
