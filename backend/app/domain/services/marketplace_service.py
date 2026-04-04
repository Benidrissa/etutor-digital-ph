"""Marketplace service — browse, purchase, review."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from structlog import get_logger

from app.domain.models.course import Course, UserCourseEnrollment
from app.domain.models.marketplace import (
    CourseMarketplaceListing,
    CourseReview,
    CreditTransaction,
    UserCreditBalance,
)
from app.domain.models.module import Module
from app.domain.models.progress import UserModuleProgress
from app.domain.models.user import User

logger = get_logger(__name__)


class MarketplaceService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Browse
    # ------------------------------------------------------------------

    async def browse_courses(
        self,
        *,
        course_domain: str | None = None,
        course_level: str | None = None,
        audience_type: str | None = None,
        search: str | None = None,
        price_min: int | None = None,
        price_max: int | None = None,
        sort: str = "newest",
        limit: int = 20,
        offset: int = 0,
        current_user_id: str | None = None,
    ) -> dict[str, Any]:
        stmt = (
            select(
                Course,
                CourseMarketplaceListing,
                User.name.label("expert_name"),
                User.avatar_url.label("expert_avatar"),
                func.coalesce(func.avg(CourseReview.rating), 0).label("avg_rating"),
                func.count(CourseReview.id.distinct()).label("review_count"),
                func.count(UserCourseEnrollment.user_id.distinct()).label("enrollment_count"),
            )
            .join(
                CourseMarketplaceListing,
                CourseMarketplaceListing.course_id == Course.id,
            )
            .outerjoin(User, User.id == Course.created_by)
            .outerjoin(
                CourseReview,
                CourseReview.listing_id == CourseMarketplaceListing.id,
            )
            .outerjoin(
                UserCourseEnrollment,
                UserCourseEnrollment.course_id == Course.id,
            )
            .where(
                Course.status == "published",
                CourseMarketplaceListing.is_listed.is_(True),
            )
            .group_by(
                Course.id,
                CourseMarketplaceListing.id,
                User.name,
                User.avatar_url,
            )
        )

        if course_domain:
            stmt = stmt.where(Course.course_domain.any(course_domain))
        if course_level:
            stmt = stmt.where(Course.course_level.any(course_level))
        if audience_type:
            stmt = stmt.where(Course.audience_type.any(audience_type))
        if search:
            q = f"%{search.lower()}%"
            stmt = stmt.where(
                func.lower(Course.title_fr).like(q) | func.lower(Course.title_en).like(q)
            )
        if price_min is not None:
            stmt = stmt.where(CourseMarketplaceListing.price_credits >= price_min)
        if price_max is not None:
            stmt = stmt.where(CourseMarketplaceListing.price_credits <= price_max)

        if sort == "newest":
            stmt = stmt.order_by(Course.published_at.desc())
        elif sort == "popular":
            stmt = stmt.order_by(func.count(UserCourseEnrollment.user_id.distinct()).desc())
        elif sort == "highest_rated":
            stmt = stmt.order_by(func.coalesce(func.avg(CourseReview.rating), 0).desc())
        elif sort == "price_asc":
            stmt = stmt.order_by(CourseMarketplaceListing.price_credits.asc())
        elif sort == "price_desc":
            stmt = stmt.order_by(CourseMarketplaceListing.price_credits.desc())
        else:
            stmt = stmt.order_by(Course.published_at.desc())

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_result = await self._db.execute(count_stmt)
        total = total_result.scalar_one()

        stmt = stmt.offset(offset).limit(limit)
        rows = (await self._db.execute(stmt)).all()

        enrolled_ids: set[str] = set()
        if current_user_id:
            enroll_res = await self._db.execute(
                select(UserCourseEnrollment.course_id).where(
                    UserCourseEnrollment.user_id == uuid.UUID(current_user_id),
                    UserCourseEnrollment.status == "active",
                )
            )
            enrolled_ids = {str(r[0]) for r in enroll_res.all()}

        items = [self._row_to_summary(row, enrolled_ids=enrolled_ids) for row in rows]
        return {"total": total, "items": items}

    # ------------------------------------------------------------------
    # Course detail
    # ------------------------------------------------------------------

    async def get_course_detail(
        self,
        slug: str,
        current_user_id: str | None = None,
    ) -> dict[str, Any] | None:
        stmt = (
            select(
                Course,
                CourseMarketplaceListing,
                User.name.label("expert_name"),
                User.avatar_url.label("expert_avatar"),
                func.coalesce(func.avg(CourseReview.rating), 0).label("avg_rating"),
                func.count(CourseReview.id.distinct()).label("review_count"),
                func.count(UserCourseEnrollment.user_id.distinct()).label("enrollment_count"),
            )
            .join(
                CourseMarketplaceListing,
                CourseMarketplaceListing.course_id == Course.id,
            )
            .outerjoin(User, User.id == Course.created_by)
            .outerjoin(
                CourseReview,
                CourseReview.listing_id == CourseMarketplaceListing.id,
            )
            .outerjoin(
                UserCourseEnrollment,
                UserCourseEnrollment.course_id == Course.id,
            )
            .where(
                Course.slug == slug,
                Course.status == "published",
                CourseMarketplaceListing.is_listed.is_(True),
            )
            .group_by(
                Course.id,
                CourseMarketplaceListing.id,
                User.name,
                User.avatar_url,
            )
        )

        row = (await self._db.execute(stmt)).one_or_none()
        if row is None:
            return None

        course, listing, expert_name, expert_avatar, avg_rating, review_count, enrollment_count = (
            row
        )

        modules_res = await self._db.execute(
            select(Module).where(Module.course_id == course.id).order_by(Module.position).limit(5)
        )
        modules_preview = [
            {
                "id": str(m.id),
                "title_fr": m.title_fr,
                "title_en": m.title_en,
                "position": m.position,
            }
            for m in modules_res.scalars().all()
        ]

        is_enrolled = False
        enrollment_status: str | None = None
        if current_user_id:
            enroll_res = await self._db.execute(
                select(UserCourseEnrollment).where(
                    UserCourseEnrollment.user_id == uuid.UUID(current_user_id),
                    UserCourseEnrollment.course_id == course.id,
                )
            )
            enrollment = enroll_res.scalar_one_or_none()
            if enrollment:
                is_enrolled = enrollment.status == "active"
                enrollment_status = enrollment.status

        return {
            "id": str(course.id),
            "slug": course.slug,
            "title_fr": course.title_fr,
            "title_en": course.title_en,
            "description_fr": course.description_fr,
            "description_en": course.description_en,
            "course_domain": list(course.course_domain or []),
            "course_level": list(course.course_level or []),
            "audience_type": list(course.audience_type or []),
            "estimated_hours": course.estimated_hours,
            "module_count": course.module_count,
            "cover_image_url": course.cover_image_url,
            "languages": course.languages,
            "price_credits": listing.price_credits,
            "avg_rating": float(avg_rating),
            "review_count": int(review_count),
            "enrollment_count": int(enrollment_count),
            "expert_name": expert_name,
            "expert_avatar": expert_avatar,
            "modules_preview": modules_preview,
            "is_enrolled": is_enrolled,
            "enrollment_status": enrollment_status,
        }

    # ------------------------------------------------------------------
    # Purchase
    # ------------------------------------------------------------------

    async def purchase_course(
        self,
        course_id: uuid.UUID,
        user_id: str,
    ) -> dict[str, Any]:
        listing_res = await self._db.execute(
            select(CourseMarketplaceListing).where(
                CourseMarketplaceListing.course_id == course_id,
                CourseMarketplaceListing.is_listed.is_(True),
            )
        )
        listing = listing_res.scalar_one_or_none()
        if listing is None:
            raise ValueError("course_not_found")

        course_res = await self._db.execute(
            select(Course).where(Course.id == course_id, Course.status == "published")
        )
        course = course_res.scalar_one_or_none()
        if course is None:
            raise ValueError("course_not_found")

        uid = uuid.UUID(user_id)

        existing_res = await self._db.execute(
            select(UserCourseEnrollment).where(
                UserCourseEnrollment.user_id == uid,
                UserCourseEnrollment.course_id == course_id,
                UserCourseEnrollment.status == "active",
            )
        )
        if existing_res.scalar_one_or_none():
            raise ValueError("already_enrolled")

        if listing.price_credits > 0:
            balance_res = await self._db.execute(
                select(UserCreditBalance).where(UserCreditBalance.user_id == uid)
            )
            balance_row = balance_res.scalar_one_or_none()
            current_balance = balance_row.balance if balance_row else 0

            if current_balance < listing.price_credits:
                raise ValueError("insufficient_credits")

            if balance_row is None:
                balance_row = UserCreditBalance(user_id=uid, balance=0)
                self._db.add(balance_row)

            balance_row.balance = current_balance - listing.price_credits

            self._db.add(
                CreditTransaction(
                    user_id=uid,
                    amount=-listing.price_credits,
                    transaction_type="purchase",
                    reference_id=listing.id,
                    description=f"Purchase: {course.title_en}",
                )
            )

            if course.created_by:
                expert_balance_res = await self._db.execute(
                    select(UserCreditBalance).where(UserCreditBalance.user_id == course.created_by)
                )
                expert_balance = expert_balance_res.scalar_one_or_none()
                if expert_balance is None:
                    expert_balance = UserCreditBalance(user_id=course.created_by, balance=0)
                    self._db.add(expert_balance)
                expert_balance.balance = expert_balance.balance + listing.price_credits

                self._db.add(
                    CreditTransaction(
                        user_id=course.created_by,
                        amount=listing.price_credits,
                        transaction_type="sale",
                        reference_id=listing.id,
                        description=f"Sale: {course.title_en}",
                    )
                )

        enrollment = UserCourseEnrollment(
            user_id=uid,
            course_id=course_id,
            status="active",
            completion_pct=0.0,
        )
        self._db.add(enrollment)

        modules_res = await self._db.execute(select(Module).where(Module.course_id == course_id))
        for module in modules_res.scalars().all():
            prog_res = await self._db.execute(
                select(UserModuleProgress).where(
                    UserModuleProgress.user_id == uid,
                    UserModuleProgress.module_id == module.id,
                )
            )
            if prog_res.scalar_one_or_none() is None:
                self._db.add(
                    UserModuleProgress(
                        user_id=uid,
                        module_id=module.id,
                        status="locked",
                        completion_pct=0.0,
                        time_spent_minutes=0,
                    )
                )

        await self._db.commit()
        await self._db.refresh(enrollment)

        logger.info(
            "Marketplace purchase complete",
            user_id=user_id,
            course_id=str(course_id),
            credits=listing.price_credits,
        )

        return {
            "course_id": str(enrollment.course_id),
            "user_id": str(enrollment.user_id),
            "status": enrollment.status,
            "enrolled_at": enrollment.enrolled_at.isoformat(),
            "credits_spent": listing.price_credits,
        }

    # ------------------------------------------------------------------
    # Reviews
    # ------------------------------------------------------------------

    async def create_review(
        self,
        course_id: uuid.UUID,
        user_id: str,
        rating: int,
        comment: str | None,
    ) -> dict[str, Any]:
        listing_res = await self._db.execute(
            select(CourseMarketplaceListing).where(CourseMarketplaceListing.course_id == course_id)
        )
        listing = listing_res.scalar_one_or_none()
        if listing is None:
            raise ValueError("listing_not_found")

        uid = uuid.UUID(user_id)

        enrollment_res = await self._db.execute(
            select(UserCourseEnrollment).where(
                UserCourseEnrollment.user_id == uid,
                UserCourseEnrollment.course_id == course_id,
                UserCourseEnrollment.status == "active",
            )
        )
        if enrollment_res.scalar_one_or_none() is None:
            raise ValueError("not_enrolled")

        existing_res = await self._db.execute(
            select(CourseReview).where(
                CourseReview.listing_id == listing.id,
                CourseReview.user_id == uid,
            )
        )
        if existing_res.scalar_one_or_none():
            raise ValueError("review_exists")

        review = CourseReview(
            listing_id=listing.id,
            user_id=uid,
            rating=rating,
            comment=comment,
        )
        self._db.add(review)
        await self._db.commit()
        await self._db.refresh(review)

        logger.info("Review created", user_id=user_id, course_id=str(course_id), rating=rating)

        return {
            "id": str(review.id),
            "listing_id": str(review.listing_id),
            "user_id": str(review.user_id),
            "rating": review.rating,
            "comment": review.comment,
            "created_at": review.created_at.isoformat(),
        }

    async def list_reviews(
        self,
        course_id: uuid.UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        listing_res = await self._db.execute(
            select(CourseMarketplaceListing).where(CourseMarketplaceListing.course_id == course_id)
        )
        listing = listing_res.scalar_one_or_none()
        if listing is None:
            return {"total": 0, "items": []}

        count_res = await self._db.execute(
            select(func.count()).where(CourseReview.listing_id == listing.id)
        )
        total = count_res.scalar_one()

        rows_res = await self._db.execute(
            select(
                CourseReview,
                User.name.label("reviewer_name"),
                User.avatar_url.label("reviewer_avatar"),
            )
            .join(User, User.id == CourseReview.user_id)
            .where(CourseReview.listing_id == listing.id)
            .order_by(CourseReview.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        items = [
            {
                "id": str(row.CourseReview.id),
                "rating": row.CourseReview.rating,
                "comment": row.CourseReview.comment,
                "created_at": row.CourseReview.created_at.isoformat(),
                "reviewer_name": row.reviewer_name,
                "reviewer_avatar": row.reviewer_avatar,
            }
            for row in rows_res.all()
        ]
        return {"total": total, "items": items}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _row_to_summary(
        self,
        row: Any,
        enrolled_ids: set[str],
    ) -> dict[str, Any]:
        course, listing, expert_name, expert_avatar, avg_rating, review_count, enrollment_count = (
            row
        )
        return {
            "id": str(course.id),
            "slug": course.slug,
            "title_fr": course.title_fr,
            "title_en": course.title_en,
            "description_fr": course.description_fr,
            "description_en": course.description_en,
            "course_domain": list(course.course_domain or []),
            "course_level": list(course.course_level or []),
            "audience_type": list(course.audience_type or []),
            "estimated_hours": course.estimated_hours,
            "module_count": course.module_count,
            "cover_image_url": course.cover_image_url,
            "languages": course.languages,
            "price_credits": listing.price_credits,
            "avg_rating": float(avg_rating),
            "review_count": int(review_count),
            "enrollment_count": int(enrollment_count),
            "expert_name": expert_name,
            "expert_avatar": expert_avatar,
            "is_enrolled": str(course.id) in enrolled_ids,
        }
