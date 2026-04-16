"""Question bank analytics service — pass rates, category weaknesses, student progress."""

from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Any

import structlog
from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.organization import OrganizationMember, OrgMemberRole
from app.domain.models.qbank import QBankAttempt, Question, QuestionBank
from app.domain.models.user import User

logger = structlog.get_logger(__name__)


class QBankAnalyticsService:
    async def _get_bank_or_404(self, db: AsyncSession, bank_id: uuid.UUID) -> QuestionBank:
        bank = await db.get(QuestionBank, bank_id)
        if bank is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Question bank not found.",
            )
        return bank

    async def require_org_admin(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> None:
        """Require owner or admin role in the organization."""
        from app.domain.models.user import UserRole

        user = await db.get(User, user_id)
        if user and user.role == UserRole.admin:
            return

        result = await db.execute(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == org_id,
                OrganizationMember.user_id == user_id,
            )
        )
        member = result.scalar_one_or_none()
        if member is None or member.role not in (OrgMemberRole.owner, OrgMemberRole.admin):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Requires org owner or admin role.",
            )

    # ------------------------------------------------------------------
    # Bank-level analytics
    # ------------------------------------------------------------------

    async def get_bank_analytics(
        self,
        db: AsyncSession,
        bank_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Aggregate analytics for a question bank."""
        bank = await self._get_bank_or_404(db, bank_id)

        total_attempts = (
            await db.scalar(
                select(func.count(QBankAttempt.id)).where(QBankAttempt.bank_id == bank_id)
            )
            or 0
        )

        unique_students = (
            await db.scalar(
                select(func.count(func.distinct(QBankAttempt.user_id))).where(
                    QBankAttempt.bank_id == bank_id
                )
            )
            or 0
        )

        agg = await db.execute(
            select(
                func.avg(QBankAttempt.score).label("avg_score"),
                func.avg(QBankAttempt.time_taken_sec).label("avg_time_sec"),
            ).where(QBankAttempt.bank_id == bank_id)
        )
        agg_row = agg.one()
        avg_score = round(float(agg_row.avg_score or 0), 1)
        avg_time_per_q = None
        if agg_row.avg_time_sec is not None:
            total_q = (
                await db.scalar(
                    select(func.count(Question.id)).where(
                        Question.bank_id == bank_id, Question.is_active.is_(True)
                    )
                )
                or 1
            )
            avg_time_per_q = round(float(agg_row.avg_time_sec) / total_q, 1)

        pass_count = (
            await db.scalar(
                select(func.count(QBankAttempt.id)).where(
                    QBankAttempt.bank_id == bank_id,
                    QBankAttempt.passed.is_(True),
                )
            )
            or 0
        )
        pass_rate = round((pass_count / total_attempts * 100) if total_attempts > 0 else 0.0, 1)

        score_distribution = await self._score_distribution(db, bank_id)
        category_pass_rates = await self._category_pass_rates(db, bank_id)
        attempts_over_time = await self._attempts_over_time(db, bank_id)

        logger.info("qbank_analytics_fetched", bank_id=str(bank_id))
        return {
            "bank_id": str(bank_id),
            "bank_title": bank.title,
            "pass_score": bank.pass_score,
            "total_attempts": total_attempts,
            "unique_students": unique_students,
            "avg_score": avg_score,
            "pass_rate": pass_rate,
            "avg_time_per_question_sec": avg_time_per_q,
            "score_distribution": score_distribution,
            "category_pass_rates": category_pass_rates,
            "attempts_over_time": attempts_over_time,
        }

    async def _score_distribution(
        self, db: AsyncSession, bank_id: uuid.UUID
    ) -> list[dict[str, Any]]:
        """Histogram of scores in 10-point buckets (0-9, 10-19, …, 90-100)."""
        result = await db.execute(select(QBankAttempt.score).where(QBankAttempt.bank_id == bank_id))
        scores = [row[0] for row in result.all()]

        buckets: dict[str, int] = {}
        for lower in range(0, 101, 10):
            upper = lower + 9 if lower < 100 else 100
            label = f"{lower}-{upper}"
            buckets[label] = 0

        for s in scores:
            bucket_idx = min(int(s // 10) * 10, 100)
            upper = bucket_idx + 9 if bucket_idx < 100 else 100
            label = f"{bucket_idx}-{upper}"
            buckets[label] = buckets.get(label, 0) + 1

        return [{"range": k, "count": v} for k, v in buckets.items()]

    async def _category_pass_rates(
        self, db: AsyncSession, bank_id: uuid.UUID
    ) -> list[dict[str, Any]]:
        """Pass rate per question category derived from attempt category_breakdown."""
        result = await db.execute(
            select(QBankAttempt.category_breakdown).where(QBankAttempt.bank_id == bank_id)
        )
        rows = result.scalars().all()

        category_totals: dict[str, dict[str, int]] = defaultdict(lambda: {"correct": 0, "total": 0})
        for breakdown in rows:
            if not isinstance(breakdown, dict):
                continue
            for cat, stats in breakdown.items():
                if isinstance(stats, dict):
                    category_totals[cat]["correct"] += stats.get("correct", 0)
                    category_totals[cat]["total"] += stats.get("total", 0)

        output: list[dict[str, Any]] = []
        for cat, totals in sorted(category_totals.items()):
            total = totals["total"]
            correct = totals["correct"]
            rate = round((correct / total * 100) if total > 0 else 0.0, 1)
            output.append(
                {
                    "category": cat,
                    "pass_rate": rate,
                    "correct": correct,
                    "total": total,
                }
            )
        return output

    async def _attempts_over_time(
        self, db: AsyncSession, bank_id: uuid.UUID
    ) -> list[dict[str, Any]]:
        """Daily attempt counts for the last 30 days."""
        result = await db.execute(
            select(
                func.date_trunc("day", QBankAttempt.attempted_at).label("day"),
                func.count(QBankAttempt.id).label("count"),
            )
            .where(QBankAttempt.bank_id == bank_id)
            .group_by(func.date_trunc("day", QBankAttempt.attempted_at))
            .order_by(func.date_trunc("day", QBankAttempt.attempted_at))
        )
        return [{"date": row.day.date().isoformat(), "count": row.count} for row in result.all()]

    # ------------------------------------------------------------------
    # Student list
    # ------------------------------------------------------------------

    async def get_bank_students(
        self,
        db: AsyncSession,
        bank_id: uuid.UUID,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Student list with their latest score and attempt count."""
        await self._get_bank_or_404(db, bank_id)

        latest_attempt_sub = (
            select(
                QBankAttempt.user_id,
                func.max(QBankAttempt.attempted_at).label("latest_at"),
            )
            .where(QBankAttempt.bank_id == bank_id)
            .group_by(QBankAttempt.user_id)
            .order_by(func.max(QBankAttempt.attempted_at).desc())
            .limit(limit)
            .offset(offset)
            .subquery()
        )

        result = await db.execute(
            select(
                latest_attempt_sub.c.user_id,
                latest_attempt_sub.c.latest_at,
                func.count(QBankAttempt.id).label("attempt_count"),
                func.max(QBankAttempt.score).label("best_score"),
            )
            .join(
                QBankAttempt,
                (QBankAttempt.user_id == latest_attempt_sub.c.user_id)
                & (QBankAttempt.bank_id == bank_id),
            )
            .group_by(latest_attempt_sub.c.user_id, latest_attempt_sub.c.latest_at)
        )
        rows = result.all()

        latest_scores: dict[uuid.UUID, float] = {}
        for row in rows:
            latest_result = await db.execute(
                select(QBankAttempt.score).where(
                    QBankAttempt.bank_id == bank_id,
                    QBankAttempt.user_id == row.user_id,
                    QBankAttempt.attempted_at == row.latest_at,
                )
            )
            score_row = latest_result.scalar_one_or_none()
            latest_scores[row.user_id] = float(score_row or 0)

        output: list[dict[str, Any]] = []
        for row in rows:
            user = await db.get(User, row.user_id)
            if not user:
                continue
            output.append(
                {
                    "user_id": str(row.user_id),
                    "name": user.name,
                    "email": user.email,
                    "attempt_count": row.attempt_count,
                    "best_score": round(float(row.best_score or 0), 1),
                    "latest_score": round(latest_scores.get(row.user_id, 0.0), 1),
                    "last_attempt_at": row.latest_at.isoformat() if row.latest_at else None,
                }
            )
        return output

    # ------------------------------------------------------------------
    # Per-student progress
    # ------------------------------------------------------------------

    async def get_student_progress(
        self,
        db: AsyncSession,
        bank_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Attempt history, score trend, and weakest categories for a student."""
        await self._get_bank_or_404(db, bank_id)

        result = await db.execute(
            select(QBankAttempt)
            .where(
                QBankAttempt.bank_id == bank_id,
                QBankAttempt.user_id == user_id,
            )
            .order_by(QBankAttempt.attempted_at.asc())
        )
        attempts = result.scalars().all()

        if not attempts:
            return {
                "bank_id": str(bank_id),
                "user_id": str(user_id),
                "attempt_count": 0,
                "best_score": None,
                "latest_score": None,
                "improvement_trend": None,
                "attempt_history": [],
                "weakest_categories": [],
            }

        attempt_history = [
            {
                "attempt_id": str(a.id),
                "score": round(a.score, 1),
                "passed": a.passed,
                "time_taken_sec": a.time_taken_sec,
                "attempted_at": a.attempted_at.isoformat(),
            }
            for a in attempts
        ]

        scores = [a.score for a in attempts]
        best_score = round(max(scores), 1)
        latest_score = round(scores[-1], 1)

        improvement_trend: float | None = None
        if len(scores) >= 2:
            improvement_trend = round(scores[-1] - scores[0], 1)

        weakest_categories = await self._student_weakest_categories(db, bank_id, user_id)

        return {
            "bank_id": str(bank_id),
            "user_id": str(user_id),
            "attempt_count": len(attempts),
            "best_score": best_score,
            "latest_score": latest_score,
            "improvement_trend": improvement_trend,
            "attempt_history": attempt_history,
            "weakest_categories": weakest_categories,
        }

    async def _student_weakest_categories(
        self,
        db: AsyncSession,
        bank_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> list[dict[str, Any]]:
        """Categories sorted by pass rate ascending (weakest first)."""
        result = await db.execute(
            select(QBankAttempt.category_breakdown).where(
                QBankAttempt.bank_id == bank_id,
                QBankAttempt.user_id == user_id,
            )
        )
        rows = result.scalars().all()

        totals: dict[str, dict[str, int]] = defaultdict(lambda: {"correct": 0, "total": 0})
        for breakdown in rows:
            if not isinstance(breakdown, dict):
                continue
            for cat, stats in breakdown.items():
                if isinstance(stats, dict):
                    totals[cat]["correct"] += stats.get("correct", 0)
                    totals[cat]["total"] += stats.get("total", 0)

        output: list[dict[str, Any]] = []
        for cat, vals in totals.items():
            total = vals["total"]
            correct = vals["correct"]
            rate = round((correct / total * 100) if total > 0 else 0.0, 1)
            output.append({"category": cat, "pass_rate": rate, "correct": correct, "total": total})

        output.sort(key=lambda x: x["pass_rate"])
        return output
