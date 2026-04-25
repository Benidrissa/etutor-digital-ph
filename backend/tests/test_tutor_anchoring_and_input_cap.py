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
