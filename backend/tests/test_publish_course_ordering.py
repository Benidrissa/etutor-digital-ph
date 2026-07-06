"""Regression tests for the publish-course response ordering (#2543).

`publish_course` commits the publish, then runs best-effort side-effects (pregenerate
dispatch + a quality sweep that itself calls `await db.commit()`). That second commit
expires the `course` ORM instance, so serializing it *after* the sweep lazy-loads an
expired selectin attribute synchronously on the async session and raises MissingGreenlet
— 500ing an already-committed publish and surfacing a bogus "indexation incomplete"
banner in the wizard. The fix builds the response *before* the side-effects and returns
that pre-built object.

These call `publish_course` directly with mocks (the DB-integration course tests are
skipped under the current async-fixture setup — see #554), so they run in CI.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.v1 import admin_courses


def _mock_db(order):
    """A db whose 3 execute() calls return: course, chunk-count(5), module-count(2)."""
    course = MagicMock()
    course.id = uuid.uuid4()
    course.rag_collection_id = str(uuid.uuid4())
    course.published_at = None

    r_course = MagicMock()
    r_course.scalar_one_or_none = MagicMock(return_value=course)
    r_chunks = MagicMock()
    r_chunks.scalar_one = MagicMock(return_value=5)  # > 0 → passes publish gate
    r_modules = MagicMock()
    r_modules.scalar_one = MagicMock(return_value=2)

    db = MagicMock()
    db.execute = AsyncMock(side_effect=[r_course, r_chunks, r_modules])
    db.commit = AsyncMock(side_effect=lambda: order.append("commit"))
    db.refresh = AsyncMock()
    db.rollback = AsyncMock(side_effect=lambda: order.append("rollback"))
    return db, course


def _patches(order, sentinel, assess_side_effect):
    qa_run = MagicMock()
    qa_run.status = "skipped"  # not "queued" → no task dispatch needed
    qa_svc = MagicMock()
    qa_svc.assess_course = AsyncMock(side_effect=assess_side_effect)

    def _build(*_a, **_k):
        order.append("build")
        return sentinel

    return patch.multiple(
        admin_courses,
        _fetch_image_count=AsyncMock(return_value=0),
        _course_to_response=MagicMock(side_effect=_build),
        pregenerate_on_publish_task=MagicMock(),
    ), qa_svc, qa_run


@pytest.mark.asyncio
async def test_response_built_before_quality_sweep_commit():
    """The CourseResponse must be built before the sweep runs its expiring commit."""
    order: list[str] = []
    sentinel = object()
    db, _course = _mock_db(order)

    async def _assess(*_a, **_k):
        order.append("assess")
        return qa_run

    core, qa_svc, qa_run = _patches(order, sentinel, _assess)
    with (
        core,
        patch("app.ai.claude_service.ClaudeService", MagicMock()),
        patch(
            "app.domain.services.quality_agent_service.CourseQualityService",
            MagicMock(return_value=qa_svc),
        ),
        patch("app.tasks.quality_assessment.assess_course_task", MagicMock()),
    ):
        result = await admin_courses.publish_course(
            course_id=uuid.uuid4(), current_user=MagicMock(), db=db
        )

    assert result is sentinel
    # The bug called _course_to_response last; the fix builds it before the sweep.
    assert order.index("build") < order.index("assess")


@pytest.mark.asyncio
async def test_sweep_failure_rolls_back_and_still_returns_response():
    """A failing quality sweep must roll back and NOT 500 the committed publish."""
    order: list[str] = []
    sentinel = object()
    db, _course = _mock_db(order)

    async def _assess(*_a, **_k):
        order.append("assess")
        raise RuntimeError("sweep boom")

    core, qa_svc, _qa_run = _patches(order, sentinel, _assess)
    with (
        core,
        patch("app.ai.claude_service.ClaudeService", MagicMock()),
        patch(
            "app.domain.services.quality_agent_service.CourseQualityService",
            MagicMock(return_value=qa_svc),
        ),
        patch("app.tasks.quality_assessment.assess_course_task", MagicMock()),
    ):
        result = await admin_courses.publish_course(
            course_id=uuid.uuid4(), current_user=MagicMock(), db=db
        )

    assert result is sentinel
    db.rollback.assert_awaited_once()
    assert order.index("build") < order.index("assess")
