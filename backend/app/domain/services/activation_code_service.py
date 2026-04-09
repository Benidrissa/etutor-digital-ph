"""Activation voucher service — generate, preview, redeem, manual activate, tracking."""

from __future__ import annotations

import secrets
import uuid
from typing import Any

import structlog
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.activation_code import ActivationCode, ActivationCodeRedemption
from app.domain.models.course import Course, UserCourseEnrollment
from app.domain.models.credit import CreditAccount, CreditTransaction, TransactionType
from app.domain.models.user import User, UserRole
from app.domain.services.enrollment_helper import enroll_user_in_course

logger = structlog.get_logger(__name__)

_CODE_PREFIX = "SIRA-"


class ActivationCodeService:
    # ------------------------------------------------------------------
    # Method 1 — generate_codes
    # ------------------------------------------------------------------

    async def generate_codes(
        self,
        db: AsyncSession,
        expert_id: uuid.UUID,
        course_id: uuid.UUID,
        count: int = 1,
        max_uses: int | None = None,
    ) -> list[ActivationCode]:
        """Generate `count` activation codes for a course owned by the caller.

        Caller must have role expert or admin and must own the course.
        Course must be published.
        """
        actor = await db.get(User, expert_id)
        if actor is None or actor.role not in (UserRole.expert, UserRole.admin):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only experts or admins can generate activation codes.",
            )

        course_result = await db.execute(select(Course).where(Course.id == course_id))
        course = course_result.scalar_one_or_none()
        if course is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found.")
        if course.created_by != expert_id and actor.role != UserRole.admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not own this course.",
            )
        if course.status != "published":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Course must be published to generate activation codes.",
            )

        codes: list[ActivationCode] = []
        for _ in range(count):
            raw = secrets.token_urlsafe(16)
            code_str = f"{_CODE_PREFIX}{raw}"
            ac = ActivationCode(
                code=code_str,
                course_id=course_id,
                created_by=expert_id,
                max_uses=max_uses,
            )
            db.add(ac)
            codes.append(ac)

        await db.commit()
        for c in codes:
            await db.refresh(c)

        logger.info(
            "Activation codes generated",
            expert_id=str(expert_id),
            course_id=str(course_id),
            count=count,
        )
        return codes

    # ------------------------------------------------------------------
    # Method 2 — preview_code
    # ------------------------------------------------------------------

    async def preview_code(self, db: AsyncSession, code_str: str) -> dict[str, Any]:
        """Return public info about a code without exposing sensitive data."""
        result = await db.execute(select(ActivationCode).where(ActivationCode.code == code_str))
        ac = result.scalar_one_or_none()
        if ac is None:
            return {"valid": False, "reason": "Code not found."}

        valid = ac.is_active and (ac.max_uses is None or ac.times_used < ac.max_uses)

        course_result = await db.execute(select(Course).where(Course.id == ac.course_id))
        course = course_result.scalar_one_or_none()

        expert_name: str | None = None
        if course and course.created_by:
            expert_result = await db.execute(select(User.name).where(User.id == course.created_by))
            expert_name = expert_result.scalar_one_or_none()

        return {
            "valid": valid,
            "title_fr": course.title_fr if course else None,
            "title_en": course.title_en if course else None,
            "description_fr": course.description_fr if course else None,
            "description_en": course.description_en if course else None,
            "cover_image_url": course.cover_image_url if course else None,
            "expert_name": expert_name,
        }

    # ------------------------------------------------------------------
    # Method 3 — redeem_code
    # ------------------------------------------------------------------

    async def redeem_code(
        self,
        db: AsyncSession,
        code_str: str,
        user_id: uuid.UUID,
        method: str = "code",
        activated_by: uuid.UUID | None = None,
    ) -> UserCourseEnrollment:
        """Redeem an activation code for a user.

        Uses SELECT FOR UPDATE to prevent concurrent race conditions.
        Creates revenue transaction if course has a price.
        """
        ac_result = await db.execute(
            select(ActivationCode).where(ActivationCode.code == code_str).with_for_update()
        )
        ac = ac_result.scalar_one_or_none()
        if ac is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Code not found.")
        if not ac.is_active:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Code is no longer active."
            )
        if ac.max_uses is not None and ac.times_used >= ac.max_uses:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Code has reached its usage limit."
            )

        existing_enrollment = await db.execute(
            select(UserCourseEnrollment).where(
                UserCourseEnrollment.user_id == user_id,
                UserCourseEnrollment.course_id == ac.course_id,
            )
        )
        if existing_enrollment.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="User is already enrolled in this course.",
            )

        existing_redemption = await db.execute(
            select(ActivationCodeRedemption).where(
                ActivationCodeRedemption.code_id == ac.id,
                ActivationCodeRedemption.user_id == user_id,
            )
        )
        if existing_redemption.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This code has already been redeemed by this user.",
            )

        enrollment = await enroll_user_in_course(db, user_id, ac.course_id)

        tx_id: uuid.UUID | None = None
        course_result = await db.execute(select(Course).where(Course.id == ac.course_id))
        course = course_result.scalar_one_or_none()

        if course and course.price_credits > 0 and course.created_by:
            account_result = await db.execute(
                select(CreditAccount).where(CreditAccount.user_id == course.created_by)
            )
            expert_account = account_result.scalar_one_or_none()
            if expert_account:
                new_balance = expert_account.balance + course.price_credits
                tx = CreditTransaction(
                    account_id=expert_account.id,
                    type=TransactionType.course_earning,
                    amount=course.price_credits,
                    balance_after=new_balance,
                    reference_id=ac.course_id,
                    reference_type="course",
                    description=f"Activation code redemption for course {ac.course_id}",
                )
                db.add(tx)
                expert_account.balance = new_balance
                expert_account.total_earned = expert_account.total_earned + course.price_credits
                await db.flush()
                tx_id = tx.id

        redemption = ActivationCodeRedemption(
            code_id=ac.id,
            user_id=user_id,
            method=method,
            activated_by=activated_by,
            credit_transaction_id=tx_id,
        )
        db.add(redemption)

        ac.times_used += 1
        if ac.max_uses is not None and ac.times_used >= ac.max_uses:
            ac.is_active = False

        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This code has already been redeemed by this user.",
            )

        await db.refresh(enrollment)
        logger.info(
            "Activation code redeemed",
            code=code_str,
            user_id=str(user_id),
            method=method,
        )
        return enrollment

    # ------------------------------------------------------------------
    # Method 4 — manual_activate
    # ------------------------------------------------------------------

    async def manual_activate(
        self,
        db: AsyncSession,
        activator_id: uuid.UUID,
        code_id: uuid.UUID,
        learner_email: str,
    ) -> UserCourseEnrollment:
        """Manually activate a code for a learner by email (expert or admin only)."""
        activator = await db.get(User, activator_id)
        if activator is None or activator.role not in (UserRole.expert, UserRole.admin):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only experts or admins can manually activate codes.",
            )

        learner_result = await db.execute(select(User).where(User.email == learner_email))
        learner = learner_result.scalar_one_or_none()
        if learner is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No user found with email {learner_email!r}.",
            )

        ac_result = await db.execute(select(ActivationCode).where(ActivationCode.id == code_id))
        ac = ac_result.scalar_one_or_none()
        if ac is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Code not found.")

        if activator.role != UserRole.admin:
            course_result = await db.execute(
                select(Course).where(
                    Course.id == ac.course_id,
                    Course.created_by == activator_id,
                )
            )
            if course_result.scalar_one_or_none() is None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You do not own the course associated with this code.",
                )

        return await self.redeem_code(
            db=db,
            code_str=ac.code,
            user_id=learner.id,
            method="manual",
            activated_by=activator_id,
        )

    # ------------------------------------------------------------------
    # Method 5 — get_code_redemptions
    # ------------------------------------------------------------------

    async def get_code_redemptions(
        self,
        db: AsyncSession,
        expert_id: uuid.UUID,
        course_id: uuid.UUID,
        code_id: uuid.UUID | None = None,
    ) -> list[dict[str, Any]]:
        """Return redemption records for a course the expert owns."""
        expert = await db.get(User, expert_id)
        if expert is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

        if expert.role != UserRole.admin:
            course_result = await db.execute(
                select(Course).where(
                    Course.id == course_id,
                    Course.created_by == expert_id,
                )
            )
            if course_result.scalar_one_or_none() is None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You do not own this course.",
                )

        query = (
            select(ActivationCodeRedemption, User, CreditTransaction)
            .join(User, User.id == ActivationCodeRedemption.user_id)
            .outerjoin(
                CreditTransaction,
                CreditTransaction.id == ActivationCodeRedemption.credit_transaction_id,
            )
            .join(ActivationCode, ActivationCode.id == ActivationCodeRedemption.code_id)
            .where(ActivationCode.course_id == course_id)
        )
        if code_id is not None:
            query = query.where(ActivationCodeRedemption.code_id == code_id)

        result = await db.execute(query)
        rows = result.all()

        return [
            {
                "learner_name": user.name,
                "learner_email": user.email,
                "redeemed_at": redemption.redeemed_at.isoformat(),
                "method": redemption.method,
                "revenue_amount": tx.amount if tx else 0,
            }
            for redemption, user, tx in rows
        ]
