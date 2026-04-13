"""Organization reporting service — completion rates, learner progress, CSV export."""

from __future__ import annotations

import csv
import io
import uuid
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.activation_code import ActivationCode, ActivationCodeRedemption
from app.domain.models.course import Course, UserCourseEnrollment
from app.domain.models.curriculum import CurriculumCourse
from app.domain.models.user import User

logger = structlog.get_logger(__name__)


class OrgReportingService:
    # ------------------------------------------------------------------
    # Dashboard summary
    # ------------------------------------------------------------------

    async def get_org_summary(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Aggregate KPIs for an organization's dashboard."""
        # Total codes generated
        total_codes = await db.scalar(
            select(func.count(ActivationCode.id)).where(ActivationCode.organization_id == org_id)
        )

        # Active codes
        active_codes = await db.scalar(
            select(func.count(ActivationCode.id)).where(
                ActivationCode.organization_id == org_id,
                ActivationCode.is_active.is_(True),
            )
        )

        # Total redemptions (unique learners)
        total_redemptions = await db.scalar(
            select(func.count(ActivationCodeRedemption.id))
            .join(ActivationCode, ActivationCode.id == ActivationCodeRedemption.code_id)
            .where(ActivationCode.organization_id == org_id)
        )

        unique_learners = await db.scalar(
            select(func.count(func.distinct(ActivationCodeRedemption.user_id)))
            .join(ActivationCode, ActivationCode.id == ActivationCodeRedemption.code_id)
            .where(ActivationCode.organization_id == org_id)
        )

        # Average completion rate across org learners
        avg_completion = await db.scalar(
            select(func.avg(UserCourseEnrollment.completion_pct))
            .join(
                ActivationCodeRedemption,
                ActivationCodeRedemption.user_id == UserCourseEnrollment.user_id,
            )
            .join(ActivationCode, ActivationCode.id == ActivationCodeRedemption.code_id)
            .where(ActivationCode.organization_id == org_id)
        )

        return {
            "total_codes": total_codes or 0,
            "active_codes": active_codes or 0,
            "total_redemptions": total_redemptions or 0,
            "unique_learners": unique_learners or 0,
            "avg_completion_pct": round(float(avg_completion or 0), 1),
        }

    # ------------------------------------------------------------------
    # Learner progress
    # ------------------------------------------------------------------

    async def get_learner_progress(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        *,
        curriculum_id: uuid.UUID | None = None,
        course_id: uuid.UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Per-learner progress for org's enrolled learners."""
        # Get learner IDs enrolled via org codes
        learner_query = (
            select(
                ActivationCodeRedemption.user_id,
                func.min(ActivationCodeRedemption.redeemed_at).label("first_redeemed"),
            )
            .join(ActivationCode, ActivationCode.id == ActivationCodeRedemption.code_id)
            .where(ActivationCode.organization_id == org_id)
            .group_by(ActivationCodeRedemption.user_id)
            .order_by(func.min(ActivationCodeRedemption.redeemed_at).desc())
            .limit(limit)
            .offset(offset)
        )
        learner_result = await db.execute(learner_query)
        learner_rows = learner_result.all()

        if not learner_rows:
            return []

        # Get course IDs for filtering
        target_course_ids: list[uuid.UUID] | None = None
        if course_id:
            target_course_ids = [course_id]
        elif curriculum_id:
            cc_result = await db.execute(
                select(CurriculumCourse.course_id).where(
                    CurriculumCourse.curriculum_id == curriculum_id
                )
            )
            target_course_ids = [row[0] for row in cc_result.all()]

        results: list[dict[str, Any]] = []
        for learner_id, first_redeemed in learner_rows:
            user = await db.get(User, learner_id)
            if not user:
                continue

            # Get enrollments
            enroll_query = select(UserCourseEnrollment).where(
                UserCourseEnrollment.user_id == learner_id
            )
            if target_course_ids:
                enroll_query = enroll_query.where(
                    UserCourseEnrollment.course_id.in_(target_course_ids)
                )
            enroll_result = await db.execute(enroll_query)
            enrollments = enroll_result.scalars().all()

            avg_pct = 0.0
            if enrollments:
                avg_pct = sum(e.completion_pct or 0 for e in enrollments) / len(enrollments)

            results.append(
                {
                    "user_id": str(learner_id),
                    "name": user.name,
                    "email": user.email,
                    "activated_at": first_redeemed.isoformat() if first_redeemed else None,
                    "courses_enrolled": len(enrollments),
                    "avg_completion_pct": round(avg_pct, 1),
                }
            )

        return results

    # ------------------------------------------------------------------
    # Code usage report
    # ------------------------------------------------------------------

    async def get_code_usage_report(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
    ) -> list[dict[str, Any]]:
        """Per-code usage stats for the organization."""
        result = await db.execute(
            select(ActivationCode)
            .where(ActivationCode.organization_id == org_id)
            .order_by(ActivationCode.created_at.desc())
        )
        codes = result.scalars().all()

        report: list[dict[str, Any]] = []
        for ac in codes:
            course_name = None
            if ac.course_id:
                course = await db.get(Course, ac.course_id)
                if course:
                    course_name = course.title_en or course.title_fr

            report.append(
                {
                    "code_id": str(ac.id),
                    "code": ac.code,
                    "course_name": course_name,
                    "curriculum_id": str(ac.curriculum_id) if ac.curriculum_id else None,
                    "max_uses": ac.max_uses,
                    "times_used": ac.times_used,
                    "is_active": ac.is_active,
                    "created_at": ac.created_at.isoformat(),
                }
            )
        return report

    # ------------------------------------------------------------------
    # Course completion stats
    # ------------------------------------------------------------------

    async def get_course_completion_stats(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        course_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Per-course completion stats for org learners."""
        # Get org learner IDs
        learner_ids_result = await db.execute(
            select(func.distinct(ActivationCodeRedemption.user_id))
            .join(ActivationCode, ActivationCode.id == ActivationCodeRedemption.code_id)
            .where(ActivationCode.organization_id == org_id)
        )
        learner_ids = [row[0] for row in learner_ids_result.all()]

        if not learner_ids:
            return {
                "course_id": str(course_id),
                "enrolled": 0,
                "avg_completion_pct": 0,
                "completed": 0,
            }

        enroll_result = await db.execute(
            select(UserCourseEnrollment).where(
                UserCourseEnrollment.course_id == course_id,
                UserCourseEnrollment.user_id.in_(learner_ids),
            )
        )
        enrollments = enroll_result.scalars().all()

        completed = sum(1 for e in enrollments if (e.completion_pct or 0) >= 100)
        avg_pct = 0.0
        if enrollments:
            avg_pct = sum(e.completion_pct or 0 for e in enrollments) / len(enrollments)

        return {
            "course_id": str(course_id),
            "enrolled": len(enrollments),
            "avg_completion_pct": round(avg_pct, 1),
            "completed": completed,
        }

    # ------------------------------------------------------------------
    # CSV export
    # ------------------------------------------------------------------

    async def export_csv(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
    ) -> str:
        """Export learner progress as CSV string."""
        learners = await self.get_learner_progress(db, org_id, limit=10000, offset=0)

        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "name",
                "email",
                "activated_at",
                "courses_enrolled",
                "avg_completion_pct",
            ],
        )
        writer.writeheader()
        for learner in learners:
            writer.writerow(
                {
                    "name": learner["name"],
                    "email": learner["email"],
                    "activated_at": learner["activated_at"],
                    "courses_enrolled": learner["courses_enrolled"],
                    "avg_completion_pct": learner["avg_completion_pct"],
                }
            )

        return output.getvalue()
