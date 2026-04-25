"""Shared builder for ``TutorContext``, used by both the text tutor and the
voice-call session endpoint (#1956).

Keeps the two tutor surfaces from drifting — both resolve the same course /
module / audience / learner memory and produce the same system-prompt input.
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.prompts.audience import detect_audience
from app.ai.prompts.tutor import TutorContext
from app.domain.models.course import Course, UserCourseEnrollment
from app.domain.models.module import Module
from app.domain.models.user import User
from app.domain.services.learner_memory_service import LearnerMemoryService

logger = structlog.get_logger(__name__)


async def resolve_course(
    course_id: uuid.UUID | None,
    module_id: uuid.UUID | None,
    module_obj: Module | None,
    user_id: uuid.UUID,
    session: AsyncSession,
) -> Course | None:
    """Resolve course: explicit course_id > module's course > active enrollment.

    When course_id is explicit, verifies the user is enrolled (active) to
    prevent access to paid content. Falls back to enrollment if not.

    Moved from ``TutorService._resolve_course`` so the voice-session endpoint
    can reuse it without instantiating the full TutorService.
    """
    # 1. Explicit course_id — verify enrollment
    if course_id:
        enrolled = await session.execute(
            select(UserCourseEnrollment).where(
                UserCourseEnrollment.user_id == user_id,
                UserCourseEnrollment.course_id == course_id,
                UserCourseEnrollment.status == "active",
            )
        )
        if enrolled.scalar_one_or_none():
            course = await session.get(Course, course_id)
            if course:
                return course
        else:
            logger.warning(
                "Tutor course_id not enrolled, falling back",
                user_id=str(user_id),
                course_id=str(course_id),
            )

    # 2. From module's course_id
    if module_obj and module_obj.course_id:
        course = await session.get(Course, module_obj.course_id)
        if course:
            return course

    # 3. Fallback: most recent active enrollment
    result = await session.execute(
        select(UserCourseEnrollment)
        .where(
            UserCourseEnrollment.user_id == user_id,
            UserCourseEnrollment.status == "active",
        )
        .order_by(UserCourseEnrollment.enrolled_at.desc())
        .limit(1)
    )
    enrollment = result.scalar_one_or_none()
    if enrollment:
        return await session.get(Course, enrollment.course_id)

    return None


async def build_tutor_context(
    user: User,
    course_id: uuid.UUID | None,
    module_id: uuid.UUID | None,
    locale: str | None,
    session: AsyncSession,
    learner_memory_service: LearnerMemoryService | None = None,
    tutor_mode: str = "socratic",
    context_type: str | None = None,
    context_id: uuid.UUID | None = None,
) -> TutorContext:
    """Build a :class:`TutorContext` from user + optional course/module.

    * Effective language comes from the ``locale`` param when it's fr/en, else
      the user's saved preferred_language.
    * Module is loaded once to extract title and number.
    * Course is resolved via :func:`resolve_course`.
    * Audience (is_kids, age range) is derived from the course.
    * Learner memory (≤200 tokens) is loaded via LearnerMemoryService.

    ``previous_session_context`` and ``progress_snapshot`` are intentionally
    not populated here — those are text-tutor specific (compaction + per-
    conversation progress bleed across sessions). The caller can augment if
    needed.
    """
    effective_language = locale if locale in ("fr", "en") else user.preferred_language
    lm_service = learner_memory_service or LearnerMemoryService()

    module_title: str | None = None
    module_number: int | None = None
    module_obj: Module | None = None
    if module_id:
        module_obj = await session.get(Module, module_id)
        if module_obj:
            module_title = (
                module_obj.title_fr if effective_language == "fr" else module_obj.title_en
            )
            module_number = module_obj.module_number

    course = await resolve_course(course_id, module_id, module_obj, user.id, session)

    course_title: str | None = None
    course_domain: str | None = None
    course_syllabus: str | None = None
    if course:
        course_title = course.title_fr if effective_language == "fr" else course.title_en
        course_domain = course_title
        # Same syllabus injection as the text tutor (#1979) so the voice path
        # gives equally well-grounded answers. ``getattr`` keeps test doubles
        # without these attributes happy.
        from app.domain.services.tutor_service import _build_syllabus_for_prompt

        course_syllabus = _build_syllabus_for_prompt(
            getattr(course, "syllabus_context", None),
            getattr(course, "syllabus_json", None),
        )

    audience = detect_audience(course)
    learner_memory = await lm_service.format_for_prompt(user.id, session)

    return TutorContext(
        user_level=user.current_level,
        user_language=effective_language,
        user_country=user.country or "CI",
        module_id=str(module_id) if module_id else None,
        module_title=module_title,
        module_number=module_number,
        context_type=context_type,
        tutor_mode=tutor_mode,
        context_id=str(context_id) if context_id else None,
        course_title=course_title,
        course_domain=course_domain,
        course_syllabus=course_syllabus,
        learner_memory=learner_memory,
        previous_session_context="",
        progress_snapshot="",
        is_kids=audience.is_kids,
        age_min=audience.age_min,
        age_max=audience.age_max,
    )
