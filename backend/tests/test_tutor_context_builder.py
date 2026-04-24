"""Unit tests for the shared tutor context builder (#1956).

Uses a mocked async session because the integration db_session fixture is
blocked on #554. The helpers are pure: they call ``session.execute`` for
enrollment lookups and ``session.get`` for Course / Module / User.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.services.tutor_context_builder import (
    build_tutor_context,
    resolve_course,
)


def _fake_course(
    course_id: uuid.UUID,
    title_fr: str = "Santé publique",
    title_en: str = "Public health",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=course_id,
        title_fr=title_fr,
        title_en=title_en,
        rag_collection_id=None,
    )


def _fake_module(
    module_id: uuid.UUID,
    course_id: uuid.UUID | None,
    title_fr: str = "Épidémiologie",
    title_en: str = "Epidemiology",
    module_number: int = 1,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=module_id,
        course_id=course_id,
        title_fr=title_fr,
        title_en=title_en,
        module_number=module_number,
    )


def _fake_user() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        current_level=2,
        preferred_language="fr",
        country="BF",
    )


def _session_with(
    *,
    enrollment_result=None,
    get_map: dict | None = None,
    execute_results: list | None = None,
) -> MagicMock:
    """Build an AsyncSession mock.

    * ``enrollment_result``: what scalar_one_or_none() returns for enrollment
      lookups (default None = not enrolled).
    * ``get_map``: {id: obj} for ``session.get(Type, id)``.
    * ``execute_results``: a queue of Result objects if a test needs multiple
      execute() calls with different return values.
    """

    def _result(scalar_one_or_none=None, scalar=None):
        r = MagicMock()
        r.scalar_one_or_none = MagicMock(return_value=scalar_one_or_none)
        r.scalar = MagicMock(return_value=scalar)
        return r

    session = MagicMock()
    if execute_results is not None:
        session.execute = AsyncMock(side_effect=execute_results)
    else:
        session.execute = AsyncMock(return_value=_result(scalar_one_or_none=enrollment_result))

    if get_map is not None:

        async def _get(cls, obj_id):
            return (get_map or {}).get(obj_id)

        session.get = AsyncMock(side_effect=_get)
    else:
        session.get = AsyncMock(return_value=None)

    return session


class TestResolveCourse:
    async def test_explicit_id_enrolled_returns_course(self):
        course_id = uuid.uuid4()
        user_id = uuid.uuid4()
        course = _fake_course(course_id)
        session = _session_with(
            enrollment_result=SimpleNamespace(course_id=course_id),
            get_map={course_id: course},
        )
        out = await resolve_course(course_id, None, None, user_id, session)
        assert out is course

    async def test_explicit_id_not_enrolled_falls_back_to_module(self):
        course_id = uuid.uuid4()
        mod_course_id = uuid.uuid4()
        user_id = uuid.uuid4()
        mod = _fake_module(uuid.uuid4(), mod_course_id)
        mod_course = _fake_course(mod_course_id, title_fr="Module course")
        # First execute (explicit enrollment check) returns no row;
        # resolve_course falls through and gets the module's course.
        session = _session_with(
            enrollment_result=None,
            get_map={mod_course_id: mod_course},
        )
        out = await resolve_course(course_id, mod.id, mod, user_id, session)
        assert out is mod_course

    async def test_module_only_returns_module_course(self):
        mod_course_id = uuid.uuid4()
        user_id = uuid.uuid4()
        mod = _fake_module(uuid.uuid4(), mod_course_id)
        mod_course = _fake_course(mod_course_id)
        session = _session_with(get_map={mod_course_id: mod_course})
        # No explicit course_id; first query path is the enrollment-fallback.
        session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )
        out = await resolve_course(None, mod.id, mod, user_id, session)
        assert out is mod_course

    async def test_no_course_no_module_no_enrollments_returns_none(self):
        session = _session_with()
        out = await resolve_course(None, None, None, uuid.uuid4(), session)
        assert out is None

    async def test_recent_enrollment_fallback(self):
        course_id = uuid.uuid4()
        user_id = uuid.uuid4()
        course = _fake_course(course_id)
        enrollment = SimpleNamespace(course_id=course_id)
        session = _session_with(
            enrollment_result=enrollment,
            get_map={course_id: course},
        )
        out = await resolve_course(None, None, None, user_id, session)
        assert out is course


class TestBuildTutorContext:
    @pytest.fixture
    def mock_memory(self):
        m = MagicMock()
        m.format_for_prompt = AsyncMock(return_value="(learner memory snippet)")
        return m

    async def test_populates_course_and_module_in_user_language(self, mock_memory):
        course_id = uuid.uuid4()
        module_id = uuid.uuid4()
        user = _fake_user()
        course = _fake_course(course_id, title_fr="Santé publique", title_en="Public health")
        module = _fake_module(
            module_id, course_id, title_fr="Épidémiologie", title_en="Epidemiology", module_number=3
        )
        session = _session_with(
            enrollment_result=SimpleNamespace(course_id=course_id),
            get_map={course_id: course, module_id: module},
        )

        ctx = await build_tutor_context(
            user=user,
            course_id=course_id,
            module_id=module_id,
            locale="fr",
            session=session,
            learner_memory_service=mock_memory,
        )

        assert ctx.user_language == "fr"
        assert ctx.course_title == "Santé publique"
        assert ctx.module_title == "Épidémiologie"
        assert ctx.module_number == 3
        assert ctx.module_id == str(module_id)
        assert ctx.learner_memory == "(learner memory snippet)"
        # Text-tutor-only fields stay empty — voice call doesn't use them.
        assert ctx.previous_session_context == ""
        assert ctx.progress_snapshot == ""

    async def test_english_locale_picks_english_titles(self, mock_memory):
        course_id = uuid.uuid4()
        user = _fake_user()
        course = _fake_course(course_id, title_fr="Santé publique", title_en="Public health")
        session = _session_with(
            enrollment_result=SimpleNamespace(course_id=course_id),
            get_map={course_id: course},
        )
        ctx = await build_tutor_context(
            user=user,
            course_id=course_id,
            module_id=None,
            locale="en",
            session=session,
            learner_memory_service=mock_memory,
        )
        assert ctx.user_language == "en"
        assert ctx.course_title == "Public health"

    async def test_no_course_no_module_yields_minimal_context(self, mock_memory):
        user = _fake_user()
        session = _session_with()
        ctx = await build_tutor_context(
            user=user,
            course_id=None,
            module_id=None,
            locale="fr",
            session=session,
            learner_memory_service=mock_memory,
        )
        assert ctx.course_title is None
        assert ctx.module_title is None
        assert ctx.user_level == 2
        assert ctx.user_country == "BF"

    async def test_invalid_locale_falls_back_to_user_preferred(self, mock_memory):
        user = _fake_user()
        user.preferred_language = "en"
        session = _session_with()
        ctx = await build_tutor_context(
            user=user,
            course_id=None,
            module_id=None,
            locale=None,
            session=session,
            learner_memory_service=mock_memory,
        )
        assert ctx.user_language == "en"
