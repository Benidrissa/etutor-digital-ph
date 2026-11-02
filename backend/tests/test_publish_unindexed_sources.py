"""Publish refuses while extracted sources have no indexed text (#2663).

A course could be marked indexed while some of its sources never reached the RAG
(a partial run, or a resource added after indexation in a manual-mode course).
Lessons on those sources' topics were then grounded in the other sources. Publish
now refuses with 409 UNINDEXED_SOURCES unless the admin confirms with force=true.

These call `publish_course` directly with mocks (the DB-integration course tests
are skipped under the current async-fixture setup — see #554), so they run in CI.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.v1 import admin_courses


def _result(*, scalar=None, scalar_one=None, rows=None):
    r = MagicMock()
    r.scalar_one_or_none = MagicMock(return_value=scalar)
    r.scalar_one = MagicMock(return_value=scalar_one)
    r.all = MagicMock(return_value=rows or [])
    return r


def _mock_db():
    """course, chunk-count, resources (a indexed, b not), chunk attribution, module-count."""
    course = MagicMock()
    course.id = uuid.uuid4()
    course.rag_collection_id = str(uuid.uuid4())
    course.published_at = None
    indexed_id, unindexed_id = uuid.uuid4(), uuid.uuid4()

    db = MagicMock()
    db.execute = AsyncMock(
        side_effect=[
            _result(scalar=course),
            _result(scalar_one=7),
            _result(
                rows=[
                    (indexed_id, "a", None, "done", True),
                    (unindexed_id, "b", None, "done", True),
                ]
            ),
            _result(rows=[(indexed_id, 7)]),
            _result(scalar_one=2),
        ]
    )
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.rollback = AsyncMock()
    return db, course


@pytest.mark.asyncio
async def test_publish_refuses_unindexed_sources_without_force():
    db, course = _mock_db()

    with pytest.raises(HTTPException) as exc_info:
        await admin_courses.publish_course(
            course_id=course.id, force=False, current_user=MagicMock(), db=db
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "UNINDEXED_SOURCES"
    assert exc_info.value.detail["sources"] == ["b.pdf"]
    db.commit.assert_not_awaited()
    assert course.status != "published"


@pytest.mark.asyncio
async def test_publish_with_force_publishes_despite_unindexed_sources():
    db, course = _mock_db()
    sentinel = object()
    qa_svc = MagicMock()
    qa_svc.assess_course = AsyncMock(return_value=MagicMock(status="skipped"))

    with (
        patch.multiple(
            admin_courses,
            _fetch_image_count=AsyncMock(return_value=0),
            _course_to_response=MagicMock(return_value=sentinel),
            pregenerate_on_publish_task=MagicMock(),
        ),
        patch("app.ai.claude_service.ClaudeService", MagicMock()),
        patch(
            "app.domain.services.quality_agent_service.CourseQualityService",
            MagicMock(return_value=qa_svc),
        ),
        patch("app.tasks.quality_assessment.assess_course_task", MagicMock()),
    ):
        result = await admin_courses.publish_course(
            course_id=course.id, force=True, current_user=MagicMock(), db=db
        )

    assert result is sentinel
    assert course.status == "published"
    assert course.creation_step == "published"
