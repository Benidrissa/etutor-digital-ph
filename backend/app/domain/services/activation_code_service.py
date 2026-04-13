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
from app.domain.models.curriculum import Curriculum, CurriculumCourse
from app.domain.models.organization import Organization
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
        """Return public info about a code without exposing sensitive data.

        Handles both single-course codes and curriculum codes.
        """
        result = await db.execute(select(ActivationCode).where(ActivationCode.code == code_str))
        ac = result.scalar_one_or_none()
        if ac is None:
            return {"valid": False, "reason": "Code not found."}

        valid = ac.is_active and (ac.max_uses is None or ac.times_used < ac.max_uses)

        # Curriculum code — return curriculum info + course list
        if ac.curriculum_id:
            curriculum_result = await db.execute(
                select(Curriculum).where(Curriculum.id == ac.curriculum_id)
            )
            curriculum = curriculum_result.scalar_one_or_none()

            org_name: str | None = None
            org_logo: str | None = None
            if ac.organization_id:
                org = await db.get(Organization, ac.organization_id)
                if org:
                    org_name = org.name
                    org_logo = org.logo_url

            courses_list: list[dict[str, Any]] = []
            if curriculum:
                cc_result = await db.execute(
                    select(Course)
                    .join(CurriculumCourse, CurriculumCourse.course_id == Course.id)
                    .where(CurriculumCourse.curriculum_id == curriculum.id)
                )
                for course in cc_result.scalars().all():
                    courses_list.append(
                        {
                            "id": str(course.id),
                            "title_fr": course.title_fr,
                            "title_en": course.title_en,
                            "cover_image_url": course.cover_image_url,
                        }
                    )

            return {
                "valid": valid,
                "type": "curriculum",
                "curriculum_title_fr": curriculum.title_fr if curriculum else None,
                "curriculum_title_en": curriculum.title_en if curriculum else None,
                "curriculum_description_fr": curriculum.description_fr if curriculum else None,
                "curriculum_description_en": curriculum.description_en if curriculum else None,
                "cover_image_url": curriculum.cover_image_url if curriculum else None,
                "organization_name": org_name,
                "organization_logo_url": org_logo,
                "courses": courses_list,
            }

        # Single-course code — existing behavior
        course: Course | None = None
        if ac.course_id:
            course_result = await db.execute(select(Course).where(Course.id == ac.course_id))
            course = course_result.scalar_one_or_none()

        expert_name: str | None = None
        if course and course.created_by:
            expert_result = await db.execute(select(User.name).where(User.id == course.created_by))
            expert_name = expert_result.scalar_one_or_none()

        return {
            "valid": valid,
            "type": "course",
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
    ) -> list[UserCourseEnrollment]:
        """Redeem an activation code for a user.

        Uses SELECT FOR UPDATE to prevent concurrent race conditions.
        Creates revenue transactions if courses have prices.
        Returns a list of enrollments (single for course codes, multiple for curriculum codes).
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

        # Check duplicate redemption
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

        # Resolve target course IDs
        course_ids: list[uuid.UUID] = []
        if ac.curriculum_id:
            cc_result = await db.execute(
                select(CurriculumCourse.course_id).where(
                    CurriculumCourse.curriculum_id == ac.curriculum_id
                )
            )
            course_ids = [row[0] for row in cc_result.all()]
            if not course_ids:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Curriculum has no courses.",
                )
        elif ac.course_id:
            course_ids = [ac.course_id]
        else:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Code has no course or curriculum target.",
            )

        # For single-course codes, check existing enrollment (backward compat)
        if len(course_ids) == 1:
            existing_enrollment = await db.execute(
                select(UserCourseEnrollment).where(
                    UserCourseEnrollment.user_id == user_id,
                    UserCourseEnrollment.course_id == course_ids[0],
                )
            )
            if existing_enrollment.scalar_one_or_none() is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="User is already enrolled in this course.",
                )

        # Enroll in all target courses
        enrollments: list[UserCourseEnrollment] = []
        tx_id: uuid.UUID | None = None
        for cid in course_ids:
            enrollment = await enroll_user_in_course(db, user_id, cid)
            enrollments.append(enrollment)

            # Revenue transaction per course
            course_result = await db.execute(select(Course).where(Course.id == cid))
            course = course_result.scalar_one_or_none()
            if course and course.price_credits > 0 and course.created_by:
                account_result = await db.execute(
                    select(CreditAccount)
                    .where(CreditAccount.user_id == course.created_by)
                    .with_for_update()
                )
                expert_account = account_result.scalar_one_or_none()
                if expert_account:
                    new_balance = expert_account.balance + course.price_credits
                    tx = CreditTransaction(
                        account_id=expert_account.id,
                        type=TransactionType.course_earning,
                        amount=course.price_credits,
                        balance_after=new_balance,
                        reference_id=cid,
                        reference_type="course",
                        description=f"Activation code redemption for course {cid}",
                    )
                    db.add(tx)
                    expert_account.balance = new_balance
                    expert_account.total_earned += course.price_credits
                    await db.flush()
                    if tx_id is None:
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

        for e in enrollments:
            await db.refresh(e)
        logger.info(
            "Activation code redeemed",
            code=code_str,
            user_id=str(user_id),
            method=method,
            courses=len(enrollments),
        )
        return enrollments

    # ------------------------------------------------------------------
    # Method 4 — manual_activate
    # ------------------------------------------------------------------

    async def manual_activate(
        self,
        db: AsyncSession,
        activator_id: uuid.UUID,
        code_id: uuid.UUID,
        learner_email: str,
    ) -> list[UserCourseEnrollment]:
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

    # ------------------------------------------------------------------
    # Method 6 — generate_org_codes (org-scoped, with credit escrow)
    # ------------------------------------------------------------------

    async def generate_org_codes(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        actor_id: uuid.UUID,
        *,
        curriculum_id: uuid.UUID | None = None,
        course_id: uuid.UUID | None = None,
        count: int = 1,
        max_uses: int | None = None,
    ) -> list[ActivationCode]:
        """Generate codes for an organization, with credit escrow.

        Must provide either curriculum_id or course_id.
        Deducts credits from org account as escrow.
        """
        from app.domain.services.organization_service import OrganizationService

        org_svc = OrganizationService()
        await org_svc.require_org_role(db, org_id, actor_id, *[])

        org = await org_svc.get_organization(db, org_id)

        if not curriculum_id and not course_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Must provide curriculum_id or course_id.",
            )

        # Calculate total cost
        total_cost = 0
        if curriculum_id:
            cc_result = await db.execute(
                select(Course)
                .join(CurriculumCourse, CurriculumCourse.course_id == Course.id)
                .where(CurriculumCourse.curriculum_id == curriculum_id)
            )
            courses = cc_result.scalars().all()
            if not courses:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Curriculum has no courses.",
                )
            total_cost = sum(c.price_credits for c in courses if c.price_credits) * count
        elif course_id:
            course_result = await db.execute(select(Course).where(Course.id == course_id))
            course = course_result.scalar_one_or_none()
            if course is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Course not found.",
                )
            total_cost = (course.price_credits or 0) * count

        # Escrow credits from org account
        if total_cost > 0 and org.credit_account_id:
            account_result = await db.execute(
                select(CreditAccount)
                .where(CreditAccount.id == org.credit_account_id)
                .with_for_update()
            )
            account = account_result.scalar_one_or_none()
            if account is None or account.balance < total_cost:
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail=f"Insufficient credits. Need {total_cost}, have {account.balance if account else 0}.",
                )
            new_balance = account.balance - total_cost
            tx = CreditTransaction(
                account_id=account.id,
                type=TransactionType.org_code_escrow,
                amount=-total_cost,
                balance_after=new_balance,
                reference_id=curriculum_id or course_id,
                reference_type="curriculum" if curriculum_id else "course",
                description=f"Escrow for {count} activation code(s)",
            )
            db.add(tx)
            account.balance = new_balance
            account.total_spent += total_cost
            await db.flush()

        codes: list[ActivationCode] = []
        for _ in range(count):
            raw = secrets.token_urlsafe(16)
            code_str = f"{_CODE_PREFIX}{raw}"
            ac = ActivationCode(
                code=code_str,
                course_id=course_id,
                curriculum_id=curriculum_id,
                organization_id=org_id,
                created_by=None,
                max_uses=max_uses,
            )
            db.add(ac)
            codes.append(ac)

        await db.commit()
        for c in codes:
            await db.refresh(c)

        logger.info(
            "org_codes_generated",
            org_id=str(org_id),
            count=count,
            curriculum_id=str(curriculum_id) if curriculum_id else None,
            course_id=str(course_id) if course_id else None,
        )
        return codes

    # ------------------------------------------------------------------
    # Method 7 — revoke_org_code (refund unused)
    # ------------------------------------------------------------------

    async def revoke_org_code(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        code_id: uuid.UUID,
        actor_id: uuid.UUID,
    ) -> None:
        """Revoke an unused org code and refund escrowed credits."""
        from app.domain.services.organization_service import OrganizationService

        org_svc = OrganizationService()
        await org_svc.require_org_role(db, org_id, actor_id, *[])
        org = await org_svc.get_organization(db, org_id)

        ac_result = await db.execute(
            select(ActivationCode)
            .where(
                ActivationCode.id == code_id,
                ActivationCode.organization_id == org_id,
            )
            .with_for_update()
        )
        ac = ac_result.scalar_one_or_none()
        if ac is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Code not found.",
            )
        if ac.times_used > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot revoke a code that has been used.",
            )

        ac.is_active = False

        # Refund escrowed credits
        if org.credit_account_id:
            refund_amount = 0
            if ac.curriculum_id:
                cc_result = await db.execute(
                    select(Course)
                    .join(CurriculumCourse, CurriculumCourse.course_id == Course.id)
                    .where(CurriculumCourse.curriculum_id == ac.curriculum_id)
                )
                courses = cc_result.scalars().all()
                refund_amount = sum(c.price_credits for c in courses if c.price_credits)
            elif ac.course_id:
                course = await db.get(Course, ac.course_id)
                refund_amount = course.price_credits if course and course.price_credits else 0

            if refund_amount > 0:
                account_result = await db.execute(
                    select(CreditAccount)
                    .where(CreditAccount.id == org.credit_account_id)
                    .with_for_update()
                )
                account = account_result.scalar_one_or_none()
                if account:
                    new_balance = account.balance + refund_amount
                    tx = CreditTransaction(
                        account_id=account.id,
                        type=TransactionType.org_code_refund,
                        amount=refund_amount,
                        balance_after=new_balance,
                        reference_id=code_id,
                        reference_type="activation_code",
                        description="Refund for revoked activation code",
                    )
                    db.add(tx)
                    account.balance = new_balance
                    account.total_spent -= refund_amount

        await db.commit()
        logger.info("org_code_revoked", org_id=str(org_id), code_id=str(code_id))

    # ------------------------------------------------------------------
    # Method 8 — list_org_codes
    # ------------------------------------------------------------------

    async def list_org_codes(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        *,
        curriculum_id: uuid.UUID | None = None,
        is_active: bool | None = None,
    ) -> list[ActivationCode]:
        """List activation codes for an organization, with optional filters."""
        query = select(ActivationCode).where(ActivationCode.organization_id == org_id)
        if curriculum_id is not None:
            query = query.where(ActivationCode.curriculum_id == curriculum_id)
        if is_active is not None:
            query = query.where(ActivationCode.is_active == is_active)
        query = query.order_by(ActivationCode.created_at.desc())

        result = await db.execute(query)
        return list(result.scalars().all())
