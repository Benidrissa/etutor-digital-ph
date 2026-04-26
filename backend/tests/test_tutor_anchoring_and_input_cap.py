"""Tests for #1988 — anchor /tutor in last module, prompt nudge, input cap bump."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.ai.prompts.tutor import TutorContext, get_persona_block_text
from app.api.v1.schemas.tutor import TutorChatRequest
from app.domain.services.tutor_service import TutorService

# --- input cap bump (2 000 → 16 000) -----------------------------------------


def test_message_at_old_cap_now_accepted():
    """A 2 001-char message used to 422; #1988 raises the cap to 16 000."""
    body = TutorChatRequest(message="x" * 2001)
    assert len(body.message) == 2001


def test_message_at_new_cap_accepted():
    body = TutorChatRequest(message="x" * 16000)
    assert len(body.message) == 16000


def test_message_over_new_cap_rejected():
    with pytest.raises(ValidationError):
        TutorChatRequest(message="x" * 16001)


def test_empty_message_still_rejected():
    with pytest.raises(ValidationError):
        TutorChatRequest(message="")


# --- prompt nudge: course-structure-first ------------------------------------


def _ctx(language: str = "fr", tutor_mode: str = "socratic", **overrides) -> TutorContext:
    base = dict(
        user_level=2,
        user_language=language,
        user_country="SN",
        course_title="Santé Publique",
        course_domain="Santé Publique",
        tutor_mode=tutor_mode,
    )
    base.update(overrides)
    return TutorContext(**base)


def test_persona_block_socratic_includes_course_structure_nudge_fr():
    persona = get_persona_block_text(_ctx(language="fr", tutor_mode="socratic"))
    assert "structure du cours d'abord" in persona
    assert "Le manuel" in persona
    assert "JAMAIS le plan principal" in persona


def test_persona_block_explanatory_also_includes_course_structure_nudge():
    persona = get_persona_block_text(_ctx(language="fr", tutor_mode="explanatory"))
    assert "structure du cours d'abord" in persona


def test_persona_block_nudge_lives_above_the_uncached_layer():
    """The nudge MUST be in the persona (cacheable) block, not learner block —
    otherwise it'd be re-tokenised every turn instead of riding the cache."""
    from app.ai.prompts.tutor import get_learner_block_text

    persona = get_persona_block_text(_ctx())
    learner = get_learner_block_text(_ctx())
    assert "structure du cours d'abord" in persona
    assert "structure du cours d'abord" not in learner


# --- get_last_touched_module --------------------------------------------------


@pytest.fixture
def tutor_service():
    from app.ai.rag.embeddings import EmbeddingService
    from app.ai.rag.retriever import SemanticRetriever

    return TutorService(
        anthropic_client=MagicMock(),
        semantic_retriever=AsyncMock(spec=SemanticRetriever),
        embedding_service=AsyncMock(spec=EmbeddingService),
    )


def _user(language: str = "fr") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        preferred_language=language,
    )


def _module(module_id, course_id):
    return SimpleNamespace(
        id=module_id,
        course_id=course_id,
        module_number=3,
        title_fr="Santé maternelle",
        title_en="Maternal health",
    )


def _course(course_id):
    return SimpleNamespace(
        id=course_id,
        title_fr="Santé Publique AOF",
        title_en="Public Health AOF",
    )


def _progress(module_id, last_accessed):
    return SimpleNamespace(
        module_id=module_id,
        last_accessed=last_accessed,
    )


def _session_with(progress, module=None, course=None, user=None):
    """Mock AsyncSession with a queued progress row + targeted .get() returns."""
    scalars = MagicMock()
    scalars.scalar_one_or_none = MagicMock(return_value=progress)
    progress_result = MagicMock()
    progress_result.scalar_one_or_none = MagicMock(return_value=progress)

    session = MagicMock()
    session.execute = AsyncMock(return_value=progress_result)

    async def _get(cls, obj_id):
        # User lookup -> the test user; Module -> module fixture; Course -> course fixture.
        cls_name = getattr(cls, "__name__", "")
        if cls_name == "User":
            return user
        if cls_name == "Module":
            return module
        if cls_name == "Course":
            return course
        return None

    session.get = AsyncMock(side_effect=_get)
    return session


@pytest.mark.asyncio
async def test_get_last_touched_module_returns_none_when_no_progress(tutor_service):
    user = _user()
    session = _session_with(progress=None, user=user)
    result = await tutor_service.get_last_touched_module(user.id, session)
    assert result is None


@pytest.mark.asyncio
async def test_get_last_touched_module_returns_progress_record_translated(tutor_service):
    user = _user(language="fr")
    course_id = uuid.uuid4()
    module_id = uuid.uuid4()
    course = _course(course_id)
    module = _module(module_id, course_id)
    progress = _progress(module_id, datetime.now(UTC))

    session = _session_with(progress=progress, module=module, course=course, user=user)
    result = await tutor_service.get_last_touched_module(user.id, session)
    assert result is not None
    assert result["module_id"] == module_id
    assert result["module_number"] == 3
    assert result["module_title"] == "Santé maternelle"  # FR
    assert result["course_id"] == course_id
    assert result["course_title"] == "Santé Publique AOF"
    assert result["last_accessed"] == progress.last_accessed


@pytest.mark.asyncio
async def test_get_last_touched_module_picks_english_when_user_prefers_en(tutor_service):
    user = _user(language="en")
    course_id = uuid.uuid4()
    module_id = uuid.uuid4()
    course = _course(course_id)
    module = _module(module_id, course_id)
    progress = _progress(module_id, datetime.now(UTC))

    session = _session_with(progress=progress, module=module, course=course, user=user)
    result = await tutor_service.get_last_touched_module(user.id, session)
    assert result is not None
    assert result["module_title"] == "Maternal health"  # EN
    assert result["course_title"] == "Public Health AOF"


@pytest.mark.asyncio
async def test_get_last_touched_module_returns_none_when_module_was_deleted(tutor_service):
    """Defensive: progress row pointing at a now-deleted module shouldn't 500."""
    user = _user()
    progress = _progress(uuid.uuid4(), datetime.now(UTC))
    # session.get(Module, ...) returns None — module deleted.
    session = _session_with(progress=progress, module=None, course=None, user=user)
    result = await tutor_service.get_last_touched_module(user.id, session)
    assert result is None


@pytest.mark.asyncio
async def test_get_last_touched_module_handles_missing_course(tutor_service):
    """Module row with course_id=None or course gone -> return module-only payload."""
    user = _user()
    module_id = uuid.uuid4()
    module = SimpleNamespace(
        id=module_id,
        course_id=None,
        module_number=1,
        title_fr="Solo",
        title_en="Solo",
    )
    progress = _progress(module_id, datetime.now(UTC))
    session = _session_with(progress=progress, module=module, course=None, user=user)
    result = await tutor_service.get_last_touched_module(user.id, session)
    assert result is not None
    assert result["course_id"] is None
    assert result["course_title"] is None


# --- #1992 — course-scoped lookup + structured renderer ---------------------


@pytest.mark.asyncio
async def test_get_last_touched_module_filters_by_course_when_provided(tutor_service):
    """When ``course_id`` is supplied, the SELECT should JOIN Module and filter."""
    user = _user(language="fr")
    session = MagicMock()
    captured: list = []

    async def _execute(stmt):
        captured.append(stmt)
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=None)
        return result

    session.execute = AsyncMock(side_effect=_execute)
    session.get = AsyncMock(return_value=user)

    target_course_id = uuid.uuid4()
    await tutor_service.get_last_touched_module(user.id, session, course_id=target_course_id)
    assert captured, "execute() should have been called with the scoped query"
    sql = str(captured[0])
    # The scoped query must reference Module.course_id; the no-scope
    # variant won't contain it. Crude but effective check.
    assert "module" in sql.lower() and "course_id" in sql.lower()


@pytest.mark.asyncio
async def test_get_last_touched_module_no_scope_does_not_filter_by_course(tutor_service):
    """Without ``course_id`` the original behaviour (most-recent-globally) holds."""
    user = _user(language="fr")
    session = MagicMock()
    captured: list = []

    async def _execute(stmt):
        captured.append(stmt)
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=None)
        return result

    session.execute = AsyncMock(side_effect=_execute)
    session.get = AsyncMock(return_value=user)

    await tutor_service.get_last_touched_module(user.id, session)  # no course_id
    sql = str(captured[0]).lower()
    # The unscoped query selects from user_module_progress without joining Module.
    # We assert by absence of the JOIN keyword between the two tables.
    assert "user_module_progress" in sql
    # The scoped variant adds an explicit ``JOIN modules`` clause; absence
    # confirms we're on the unscoped path.
    assert " join modules" not in sql


@pytest.mark.asyncio
async def test_module_section_lists_all_units_regardless_of_count(tutor_service):
    """#1992 spec: a 9-unit module must show all 9 units; no truncation
    after the first 2-3 (the bug the user reported on staging)."""
    from app.domain.services.tutor_service import _build_current_module_section

    units = []
    for i in range(9):
        units.append(
            SimpleNamespace(
                unit_number=str(i),
                title_fr=f"Unité {i} titre",
                title_en=f"Unit {i} title",
                description_fr=f"Description de l'unité {i}.",
                description_en=f"Unit {i} description.",
                estimated_minutes=15,
                order_index=i,
            )
        )
    module = SimpleNamespace(
        id=uuid.uuid4(),
        title_fr="Fondements de la santé publique",
        title_en="Foundations",
        module_number=1,
        description_fr="Module description",
        description_en="Module description",
        estimated_hours=8,
        case_study_fr=None,
        case_study_en=None,
        units=units,
    )

    exec_result = MagicMock()
    exec_result.all = MagicMock(return_value=[])
    exec_result.scalar_one_or_none = MagicMock(return_value=None)
    session = MagicMock()
    session.execute = AsyncMock(return_value=exec_result)

    section = await _build_current_module_section(module, "fr", session)
    assert section is not None
    # Every unit number must be present in the rendered section.
    for i in range(9):
        assert f"Unité {i}" in section, f"Unit {i} missing from rendered section"
    # Module-level metadata must be present per the user's spec.
    assert "8 h" in section
    assert "Fondements" in section


@pytest.mark.asyncio
async def test_module_section_includes_unit_descriptions_and_reading_time(tutor_service):
    """Each unit shows: number + title + reading time + description bullet."""
    from app.domain.services.tutor_service import _build_current_module_section

    units = [
        SimpleNamespace(
            unit_number="3",
            title_fr="Mesures de morbidité",
            title_en="Morbidity measures",
            description_fr="Explication des proportions, ratios, taux.",
            description_en="Proportions, ratios, rates.",
            estimated_minutes=15,
            order_index=3,
        )
    ]
    module = SimpleNamespace(
        id=uuid.uuid4(),
        title_fr="M",
        title_en="M",
        module_number=1,
        description_fr=None,
        description_en=None,
        estimated_hours=None,
        case_study_fr=None,
        case_study_en=None,
        units=units,
    )
    exec_result = MagicMock()
    exec_result.all = MagicMock(return_value=[])
    exec_result.scalar_one_or_none = MagicMock(return_value=None)
    session = MagicMock()
    session.execute = AsyncMock(return_value=exec_result)

    section = await _build_current_module_section(module, "fr", session)
    assert section is not None
    assert "Unité 3" in section
    assert "Mesures de morbidité" in section
    assert "15 min de lecture" in section
    assert "Explication des proportions, ratios, taux." in section
