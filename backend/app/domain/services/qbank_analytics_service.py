"""Question Bank analytics — org-facing aggregate metrics over test attempts.

Numbers are computed with SQL aggregates where possible (``AVG``, ``COUNT``,
``SUM``) so the database does the heavy lifting. Small post-processing (score
buckets, trend direction) happens in Python because it is easier to read than
the equivalent SQL and is always O(attempts-per-bank).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import Integer, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.question_bank import (
    QBankTest,
    QBankTestAttempt,
    QuestionBank,
)
from app.domain.models.user import User
from app.domain.services.organization_service import OrganizationService

SCORE_BUCKETS = [
    ("0-20", 0, 20),
    ("21-40", 21, 40),
    ("41-60", 41, 60),
    ("61-80", 61, 80),
    ("81-100", 81, 100),
]


def build_score_distribution(scores: list[float]) -> list[dict]:
    """Return a 5-bucket histogram for a list of percentage scores."""
    counts = [0] * len(SCORE_BUCKETS)
    for s in scores:
        for i, (_label, lo, hi) in enumerate(SCORE_BUCKETS):
            if lo <= s <= hi:
                counts[i] += 1
                break
    return [
        {"bucket": label, "range": [lo, hi], "count": counts[i]}
        for i, (label, lo, hi) in enumerate(SCORE_BUCKETS)
    ]


def build_category_pass_rates(
    breakdowns: list[dict | None],
    pass_threshold: float,
) -> list[dict]:
    """Aggregate per-category hit rates across many attempts.

    Each ``category_breakdown`` looks like ``{"signs": {"correct": 3, "total": 5}}``.
    We sum correct/total per category across attempts, then compute pass rate
    as ``correct / total * 100`` and flag categories below ``pass_threshold``.
    """
    totals: dict[str, dict[str, int]] = defaultdict(lambda: {"correct": 0, "total": 0})
    for bd in breakdowns:
        if not bd:
            continue
        for cat, vals in bd.items():
            correct = int(vals.get("correct", 0))
            total = int(vals.get("total", 0))
            totals[cat]["correct"] += correct
            totals[cat]["total"] += total

    out: list[dict] = []
    for cat, vals in totals.items():
        total = vals["total"]
        rate = (vals["correct"] / total * 100.0) if total else 0.0
        out.append(
            {
                "category": cat,
                "correct": vals["correct"],
                "total": total,
                "pass_rate": round(rate, 2),
                "weak": total > 0 and rate < pass_threshold,
            }
        )
    out.sort(key=lambda r: r["pass_rate"])
    return out


def build_attempts_over_time(rows: list[tuple[date, int]]) -> list[dict]:
    """Turn ``(date, count)`` DB rows into a dense 30-day series ending today.

    Missing days are filled with zero so the frontend can draw a continuous
    sparkline without worrying about gaps.
    """
    by_date = {d: c for d, c in rows}
    today = datetime.now(UTC).date()
    series: list[dict] = []
    for offset in range(29, -1, -1):
        d = today - timedelta(days=offset)
        series.append({"date": d.isoformat(), "count": int(by_date.get(d, 0))})
    return series


def trend_direction(scores: list[float]) -> str:
    """Return 'up', 'down', or 'flat' comparing first- vs second-half averages."""
    if len(scores) < 2:
        return "flat"
    mid = len(scores) // 2
    first = sum(scores[:mid]) / mid if mid else 0.0
    second = sum(scores[mid:]) / (len(scores) - mid)
    diff = second - first
    if diff > 2.0:
        return "up"
    if diff < -2.0:
        return "down"
    return "flat"


class QBankAnalyticsService:
    def __init__(self) -> None:
        self._org_svc = OrganizationService()

    async def _get_bank_or_404(self, db: AsyncSession, bank_id: uuid.UUID) -> QuestionBank:
        bank = await db.get(QuestionBank, bank_id)
        if bank is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Question bank not found."
            )
        return bank

    async def _require_org_admin(
        self,
        db: AsyncSession,
        bank: QuestionBank,
        actor_id: uuid.UUID,
    ) -> None:
        # Reuse the same membership guard as other qbank endpoints so platform
        # admins bypass, owners/admins pass, other members are rejected.
        from app.domain.models.organization import OrgMemberRole

        await self._org_svc.require_org_role(
            db,
            bank.organization_id,
            actor_id,
            OrgMemberRole.owner,
            OrgMemberRole.admin,
        )

    async def get_bank_analytics(
        self,
        db: AsyncSession,
        bank_id: uuid.UUID,
        actor_id: uuid.UUID,
    ) -> dict:
        bank = await self._get_bank_or_404(db, bank_id)
        await self._require_org_admin(db, bank, actor_id)

        attempts_stmt = (
            select(QBankTestAttempt)
            .join(QBankTest, QBankTestAttempt.test_id == QBankTest.id)
            .where(QBankTest.question_bank_id == bank_id)
        )
        result = await db.execute(attempts_stmt)
        attempts = result.scalars().all()

        if not attempts:
            return {
                "bank_id": str(bank_id),
                "total_attempts": 0,
                "unique_students": 0,
                "average_score": 0.0,
                "pass_rate": 0.0,
                "average_time_per_question_sec": 0.0,
                "score_distribution": build_score_distribution([]),
                "category_pass_rates": [],
                "attempts_over_time": build_attempts_over_time([]),
            }

        scores = [a.score for a in attempts]
        passed = [a for a in attempts if a.passed]
        time_per_q = [
            a.time_taken_sec / a.total_questions for a in attempts if a.total_questions > 0
        ]

        by_day_rows: list[tuple[date, int]] = []
        day_counts: dict[date, int] = defaultdict(int)
        for a in attempts:
            day_counts[a.attempted_at.date()] += 1
        by_day_rows = list(day_counts.items())

        return {
            "bank_id": str(bank_id),
            "total_attempts": len(attempts),
            "unique_students": len({a.user_id for a in attempts}),
            "average_score": round(sum(scores) / len(scores), 2),
            "pass_rate": round(len(passed) / len(attempts) * 100.0, 2),
            "average_time_per_question_sec": (
                round(sum(time_per_q) / len(time_per_q), 2) if time_per_q else 0.0
            ),
            "score_distribution": build_score_distribution(scores),
            "category_pass_rates": build_category_pass_rates(
                [a.category_breakdown for a in attempts],
                pass_threshold=bank.passing_score,
            ),
            "attempts_over_time": build_attempts_over_time(by_day_rows),
        }

    async def get_bank_students(
        self,
        db: AsyncSession,
        bank_id: uuid.UUID,
        actor_id: uuid.UUID,
    ) -> list[dict]:
        bank = await self._get_bank_or_404(db, bank_id)
        await self._require_org_admin(db, bank, actor_id)

        stmt = (
            select(
                QBankTestAttempt.user_id,
                User.email,
                User.name,
                func.count(QBankTestAttempt.id).label("attempt_count"),
                func.avg(QBankTestAttempt.score).label("avg_score"),
                func.max(QBankTestAttempt.attempted_at).label("last_attempt_at"),
                func.sum(cast(QBankTestAttempt.passed, Integer)).label("pass_count"),
            )
            .join(QBankTest, QBankTestAttempt.test_id == QBankTest.id)
            .join(User, User.id == QBankTestAttempt.user_id)
            .where(QBankTest.question_bank_id == bank_id)
            .group_by(QBankTestAttempt.user_id, User.email, User.name)
            .order_by(func.max(QBankTestAttempt.attempted_at).desc())
        )
        rows = (await db.execute(stmt)).all()
        return [
            {
                "user_id": str(row.user_id),
                "email": row.email,
                "name": row.name,
                "attempt_count": int(row.attempt_count),
                "average_score": round(float(row.avg_score or 0.0), 2),
                "pass_count": int(row.pass_count or 0),
                "last_attempt_at": row.last_attempt_at.isoformat() if row.last_attempt_at else None,
            }
            for row in rows
        ]

    async def get_student_progress(
        self,
        db: AsyncSession,
        bank_id: uuid.UUID,
        user_id: uuid.UUID,
        actor_id: uuid.UUID,
    ) -> dict:
        bank = await self._get_bank_or_404(db, bank_id)
        if actor_id != user_id:
            await self._require_org_admin(db, bank, actor_id)

        attempts_stmt = (
            select(QBankTestAttempt)
            .join(QBankTest, QBankTestAttempt.test_id == QBankTest.id)
            .where(
                QBankTest.question_bank_id == bank_id,
                QBankTestAttempt.user_id == user_id,
            )
            .order_by(QBankTestAttempt.attempted_at.asc())
        )
        attempts = (await db.execute(attempts_stmt)).scalars().all()

        if not attempts:
            return {
                "bank_id": str(bank_id),
                "user_id": str(user_id),
                "attempt_count": 0,
                "attempts": [],
                "best_score": 0.0,
                "latest_score": 0.0,
                "trend": "flat",
                "weakest_categories": [],
            }

        scores = [a.score for a in attempts]
        return {
            "bank_id": str(bank_id),
            "user_id": str(user_id),
            "attempt_count": len(attempts),
            "attempts": [
                {
                    "id": str(a.id),
                    "test_id": str(a.test_id),
                    "score": a.score,
                    "passed": a.passed,
                    "attempted_at": a.attempted_at.isoformat(),
                    "attempt_number": a.attempt_number,
                    "time_taken_sec": a.time_taken_sec,
                }
                for a in attempts
            ],
            "best_score": max(scores),
            "latest_score": scores[-1],
            "trend": trend_direction(scores),
            "weakest_categories": [
                c
                for c in build_category_pass_rates(
                    [a.category_breakdown for a in attempts],
                    pass_threshold=bank.passing_score,
                )
                if c["weak"]
            ],
        }
