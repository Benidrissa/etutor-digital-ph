"""Shared enrollment helper — reused by courses endpoint and activation_code_service."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.course import UserCourseEnrollment
from app.domain.models.module import Module
from app.domain.models.progress import UserModuleProgress


async def enroll_user_in_course(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
) -> UserCourseEnrollment:
    """Create or reactivate a course enrollment and initialize module progress.

    Returns the enrollment row (new or existing active).
    Does NOT commit — caller must commit after any additional work.
    """
    existing_result = await db.execute(
        select(UserCourseEnrollment).where(
            UserCourseEnrollment.user_id == user_id,
            UserCourseEnrollment.course_id == course_id,
        )
    )
    existing = existing_result.scalar_one_or_none()
    if existing:
        if existing.status != "active":
            existing.status = "active"
        return existing

    enrollment = UserCourseEnrollment(
        user_id=user_id,
        course_id=course_id,
        status="active",
        completion_pct=0.0,
    )
    db.add(enrollment)

    modules_result = await db.execute(select(Module).where(Module.course_id == course_id))
    modules = modules_result.scalars().all()

    sorted_modules = sorted(modules, key=lambda m: m.module_number)
    first_module_id = sorted_modules[0].id if sorted_modules else None

    for module in modules:
        prog_result = await db.execute(
            select(UserModuleProgress).where(
                UserModuleProgress.user_id == user_id,
                UserModuleProgress.module_id == module.id,
            )
        )
        if prog_result.scalar_one_or_none() is None:
            db.add(
                UserModuleProgress(
                    user_id=user_id,
                    module_id=module.id,
                    status="in_progress" if module.id == first_module_id else "not_started",
                    completion_pct=0.0,
                    time_spent_minutes=0,
                )
            )

    return enrollment
