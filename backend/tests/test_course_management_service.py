"""Unit tests for CourseManagementService — shared course CRUD logic."""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.domain.services.course_management_service import (
    CostTracker,
    CourseManagementService,
)


def _make_course(
    *,
    course_id: uuid.UUID | None = None,
    created_by: uuid.UUID | None = None,
    status: str = "draft",
    rag_collection_id: str | None = "col-123",
) -> MagicMock:
    course = MagicMock()
    course.id = course_id or uuid.uuid4()
    course.slug = "test-course"
    course.title_fr = "Cours test"
    course.title_en = "Test course"
    course.description_fr = None
    course.description_en = None
    course.course_domain = []
    course.course_level = []
    course.audience_type = []
    course.languages = "fr,en"
    course.estimated_hours = 20
    course.module_count = 0
    course.status = status
    course.cover_image_url = None
    course.created_by = created_by or uuid.uuid4()
    course.rag_collection_id = rag_collection_id
    course.created_at = MagicMock(isoformat=lambda: "2026-01-01T00:00:00")
    course.published_at = None
    return course


def _make_db(course: MagicMock | None = None) -> AsyncMock:
    db = AsyncMock()

    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.return_value = course
    scalar_result.scalar_one.return_value = 0
    db.execute = AsyncMock(return_value=scalar_result)

    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


class TestCreateCourse:
    @pytest.mark.asyncio
    async def test_creates_course_with_unique_slug(self):
        db = _make_db(course=None)
        svc = CourseManagementService()

        actor_id = uuid.uuid4()
        data: dict[str, Any] = {
            "title_fr": "Santé Publique",
            "title_en": "Public Health",
            "course_domain": [],
            "course_level": [],
            "audience_type": [],
        }

        with patch("app.domain.services.course_management_service.uuid") as mock_uuid:
            new_id = uuid.uuid4()
            mock_uuid.uuid4.return_value = new_id

            await svc.create_course(db=db, actor_id=actor_id, data=data)

        db.add.assert_called_once()
        db.commit.assert_called_once()
        db.refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_slug_generated_from_title_en(self):
        db = _make_db(course=None)
        svc = CourseManagementService()
        actor_id = uuid.uuid4()
        data: dict[str, Any] = {
            "title_fr": "Test FR",
            "title_en": "Public Health Basics",
        }
        added_course = None

        def capture_add(course):
            nonlocal added_course
            added_course = course

        db.add = capture_add

        await svc.create_course(db=db, actor_id=actor_id, data=data)
        assert added_course is not None
        assert added_course.slug == "public-health-basics"

    @pytest.mark.asyncio
    async def test_sets_status_draft(self):
        db = _make_db(course=None)
        svc = CourseManagementService()
        actor_id = uuid.uuid4()
        data: dict[str, Any] = {"title_fr": "Test", "title_en": "Test"}
        added_course = None

        def capture_add(course):
            nonlocal added_course
            added_course = course

        db.add = capture_add

        await svc.create_course(db=db, actor_id=actor_id, data=data)
        assert added_course is not None
        assert added_course.status == "draft"


class TestUpdateCourse:
    @pytest.mark.asyncio
    async def test_updates_fields(self):
        actor_id = uuid.uuid4()
        course = _make_course(created_by=actor_id)
        db = _make_db(course=course)
        svc = CourseManagementService()

        data = {"title_en": "Updated Title"}
        result = await svc.update_course(db=db, course_id=course.id, data=data, actor_id=actor_id)
        assert result == course
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_raises_404_when_not_found(self):
        db = _make_db(course=None)
        svc = CourseManagementService()

        with pytest.raises(HTTPException) as exc_info:
            await svc.update_course(
                db=db,
                course_id=uuid.uuid4(),
                data={"title_en": "x"},
                actor_id=uuid.uuid4(),
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_raises_403_on_ownership_mismatch(self):
        owner_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        course = _make_course(created_by=owner_id)
        db = _make_db(course=course)
        svc = CourseManagementService()

        with pytest.raises(HTTPException) as exc_info:
            await svc.update_course(
                db=db,
                course_id=course.id,
                data={"title_en": "x"},
                actor_id=actor_id,
                check_ownership=True,
            )
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_no_ownership_check_by_default(self):
        owner_id = uuid.uuid4()
        other_actor = uuid.uuid4()
        course = _make_course(created_by=owner_id)
        db = _make_db(course=course)
        svc = CourseManagementService()

        result = await svc.update_course(
            db=db,
            course_id=course.id,
            data={"title_en": "x"},
            actor_id=other_actor,
            check_ownership=False,
        )
        assert result == course


class TestPublishCourse:
    @pytest.mark.asyncio
    async def test_raises_400_when_no_rag_chunks(self):
        actor_id = uuid.uuid4()
        course = _make_course(created_by=actor_id)
        db = _make_db(course=course)
        db.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one_or_none=MagicMock(return_value=course)),
                MagicMock(scalar_one=MagicMock(return_value=0)),
            ]
        )
        svc = CourseManagementService()

        with pytest.raises(HTTPException) as exc_info:
            await svc.publish_course(db=db, course_id=course.id, actor_id=actor_id)
        assert exc_info.value.status_code == 400
        assert "RAG indexation" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_raises_403_on_ownership_mismatch_when_check_ownership(self):
        owner_id = uuid.uuid4()
        other_actor = uuid.uuid4()
        course = _make_course(created_by=owner_id)
        db = _make_db(course=course)
        svc = CourseManagementService()

        with pytest.raises(HTTPException) as exc_info:
            await svc.publish_course(
                db=db,
                course_id=course.id,
                actor_id=other_actor,
                check_ownership=True,
            )
        assert exc_info.value.status_code == 403


class TestGenerateStructure:
    @pytest.mark.asyncio
    async def test_calls_agent_and_saves_modules(self):
        actor_id = uuid.uuid4()
        course = _make_course(created_by=actor_id)
        svc = CourseManagementService()

        mock_module_dicts = [
            {
                "title_fr": "Module 1",
                "title_en": "Module 1",
                "description_fr": "Desc FR",
                "description_en": "Desc EN",
                "estimated_hours": 10,
                "bloom_level": "remember",
            }
        ]

        call_count = [0]

        async def multi_execute(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                r = MagicMock()
                r.scalar_one_or_none.return_value = course
                return r
            elif call_count[0] == 2:
                r = MagicMock()
                r.scalar_one.return_value = 0
                return r
            else:
                r = MagicMock()
                r.scalar_one.return_value = 0
                return r

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=multi_execute)
        db.add = MagicMock()
        db.commit = AsyncMock()

        with patch("app.domain.services.course_management_service.CourseAgentService") as MockAgent:
            mock_agent = AsyncMock()
            mock_agent.generate_course_structure = AsyncMock(return_value=mock_module_dicts)
            MockAgent.return_value = mock_agent

            result = await svc.generate_structure(
                db=db,
                course_id=course.id,
                actor_id=actor_id,
                estimated_hours=20,
                deduct_credits=False,
            )

        assert result["count"] == 1
        assert len(result["modules"]) == 1
        db.add.assert_called_once()
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_raises_402_when_insufficient_credits(self):
        actor_id = uuid.uuid4()
        course = _make_course(created_by=actor_id)
        db = _make_db(course=course)
        svc = CourseManagementService()

        mock_tracker = AsyncMock()
        mock_tracker.check_balance = AsyncMock(return_value=False)

        with pytest.raises(HTTPException) as exc_info:
            await svc.generate_structure(
                db=db,
                course_id=course.id,
                actor_id=actor_id,
                deduct_credits=True,
                cost_tracker=mock_tracker,
            )
        assert exc_info.value.status_code == 402

    @pytest.mark.asyncio
    async def test_raises_500_when_deduct_credits_without_tracker(self):
        actor_id = uuid.uuid4()
        course = _make_course(created_by=actor_id)
        db = _make_db(course=course)
        svc = CourseManagementService()

        with pytest.raises(HTTPException) as exc_info:
            await svc.generate_structure(
                db=db,
                course_id=course.id,
                actor_id=actor_id,
                deduct_credits=True,
                cost_tracker=None,
            )
        assert exc_info.value.status_code == 500


class TestIndexResources:
    @pytest.mark.asyncio
    async def test_raises_404_when_course_not_found(self):
        db = _make_db(course=None)
        svc = CourseManagementService()

        with pytest.raises(HTTPException) as exc_info:
            await svc.index_resources(db=db, course_id=uuid.uuid4(), actor_id=uuid.uuid4())
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_raises_400_when_no_rag_collection_id(self):
        actor_id = uuid.uuid4()
        course = _make_course(created_by=actor_id, rag_collection_id=None)
        db = _make_db(course=course)
        svc = CourseManagementService()

        with pytest.raises(HTTPException) as exc_info:
            await svc.index_resources(db=db, course_id=course.id, actor_id=actor_id)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_raises_402_when_insufficient_credits(self):
        actor_id = uuid.uuid4()
        course = _make_course(created_by=actor_id)
        db = _make_db(course=course)
        svc = CourseManagementService()

        mock_tracker = AsyncMock()
        mock_tracker.check_balance = AsyncMock(return_value=False)

        with pytest.raises(HTTPException) as exc_info:
            await svc.index_resources(
                db=db,
                course_id=course.id,
                actor_id=actor_id,
                deduct_credits=True,
                cost_tracker=mock_tracker,
            )
        assert exc_info.value.status_code == 402

    @pytest.mark.asyncio
    async def test_triggers_celery_task(self):
        actor_id = uuid.uuid4()
        course_id = uuid.uuid4()
        course = _make_course(course_id=course_id, created_by=actor_id)
        db = _make_db(course=course)
        svc = CourseManagementService()

        mock_task = MagicMock()
        mock_task.id = "task-abc-123"

        with patch(
            "app.domain.services.course_management_service.index_course_resources"
        ) as mock_celery:
            mock_celery.delay.return_value = mock_task
            result = await svc.index_resources(db=db, course_id=course_id, actor_id=actor_id)

        assert result["task_id"] == "task-abc-123"
        assert result["status"] == "started"
        mock_celery.delay.assert_called_once_with(str(course_id), course.rag_collection_id)


class TestCostTrackerProtocol:
    def test_protocol_is_runtime_checkable(self):
        class FakeTracker:
            async def deduct(self, user_id: uuid.UUID, amount: int, reason: str) -> None:
                pass

            async def check_balance(self, user_id: uuid.UUID, required: int) -> bool:
                return True

        tracker = FakeTracker()
        assert isinstance(tracker, CostTracker)

    def test_non_conformant_class_not_instance(self):
        class NotATracker:
            pass

        assert not isinstance(NotATracker(), CostTracker)
