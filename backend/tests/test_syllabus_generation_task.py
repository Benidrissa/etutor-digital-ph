"""Unit tests for the syllabus generation Celery task."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tasks.syllabus_generation import generate_course_syllabus


def _make_module_dict(i: int) -> dict:
    return {
        "title_fr": f"Module {i} FR",
        "title_en": f"Module {i} EN",
        "description_fr": f"Desc {i} FR",
        "description_en": f"Desc {i} EN",
        "estimated_hours": 10,
        "bloom_level": "understand",
        "units": [
            {
                "title_fr": f"Unité {i}.1",
                "title_en": f"Unit {i}.1",
                "description_fr": f"Unité desc FR",
                "description_en": f"Unit desc EN",
            }
        ],
    }


def _make_mock_course(course_id: uuid.UUID) -> MagicMock:
    cat1 = MagicMock()
    cat1.slug = "epidemiology"
    cat1.type = "domain"

    cat2 = MagicMock()
    cat2.slug = "beginner"
    cat2.type = "level"

    course = MagicMock()
    course.id = course_id
    course.title_fr = "Santé publique"
    course.title_en = "Public Health"
    course.estimated_hours = 40
    course.rag_collection_id = "rag-col-1"
    course.taxonomy_categories = [cat1, cat2]
    course.module_count = 0
    course.syllabus_json = None
    return course


@pytest.fixture
def mock_task_request():
    req = MagicMock()
    req.id = "task-id-abc"
    return req


class TestGenerateCourseSyllabusTask:
    """Tests for generate_course_syllabus Celery task."""

    def _invoke(self, course_id: str, estimated_hours: int = 30) -> dict:
        task = generate_course_syllabus
        task.request = MagicMock(id="test-task-id")
        task.update_state = MagicMock()
        return task.run(course_id, estimated_hours)

    @patch("app.tasks.syllabus_generation.asyncio.run")
    def test_task_calls_asyncio_run(self, mock_asyncio_run):
        mock_asyncio_run.return_value = {
            "status": "complete",
            "modules_count": 2,
            "modules": [],
        }
        task = generate_course_syllabus
        task.request = MagicMock(id="test-task-id")
        task.update_state = MagicMock()

        result = task.run(str(uuid.uuid4()), 30)

        mock_asyncio_run.assert_called_once()
        assert result["status"] == "complete"

    @patch("app.tasks.syllabus_generation.asyncio.run")
    def test_task_propagates_exception(self, mock_asyncio_run):
        mock_asyncio_run.side_effect = RuntimeError("DB error")
        task = generate_course_syllabus
        task.request = MagicMock(id="test-task-id")
        task.update_state = MagicMock()

        with pytest.raises(RuntimeError, match="DB error"):
            task.run(str(uuid.uuid4()), 30)

    @patch("app.tasks.syllabus_generation.asyncio.run")
    def test_update_state_called_on_complete(self, mock_asyncio_run):
        mock_asyncio_run.return_value = {
            "status": "complete",
            "modules_count": 3,
            "modules": [{"id": str(uuid.uuid4()), "module_number": i} for i in range(3)],
        }
        task = generate_course_syllabus
        task.request = MagicMock(id="test-task-id")
        task.update_state = MagicMock()

        task.run(str(uuid.uuid4()), 30)

        calls = task.update_state.call_args_list
        final_call_kwargs = calls[-1][1] if calls[-1][1] else calls[-1][0][0]
        assert task.update_state.called


class TestGenerateCourseSyllabusInner:
    """Tests for the inner _run_generation async function via mocking the session."""

    @pytest.mark.asyncio
    async def test_returns_failed_when_course_not_found(self):
        course_id = str(uuid.uuid4())

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_session_factory = MagicMock(return_value=mock_session)

        with (
            patch("app.tasks.syllabus_generation.asyncio.run") as mock_run,
            patch(
                "app.infrastructure.persistence.database.async_session_factory",
                mock_session_factory,
            ),
        ):
            inner_coro = None

            def capture_coro(coro):
                nonlocal inner_coro
                inner_coro = coro
                return {"status": "failed", "error": f"Course not found: {course_id}", "modules_count": 0, "modules": []}

            mock_run.side_effect = capture_coro

            task = generate_course_syllabus
            task.request = MagicMock(id="test-task-id")
            task.update_state = MagicMock()
            result = task.run(course_id, 30)

        assert result["status"] == "failed"
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_no_flush_between_inserts(self):
        """Regression: session.flush() must NOT be called between module inserts."""
        course_id = str(uuid.uuid4())
        course = _make_mock_course(uuid.UUID(course_id))

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = course

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.flush = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        module_dicts = [_make_module_dict(i) for i in range(3)]

        mock_agent = AsyncMock()
        mock_agent.generate_course_structure = AsyncMock(return_value=module_dicts)

        async def run_inner():
            from sqlalchemy import delete, select

            from app.domain.models.course import Course
            from app.domain.models.module import Module
            from app.domain.models.module_unit import ModuleUnit

            async with mock_session:
                result = await mock_session.execute(select(Course).where(Course.id == uuid.UUID(course_id)))
                course_obj = result.scalar_one_or_none()
                if not course_obj:
                    return {"status": "failed", "error": "not found", "modules_count": 0, "modules": []}

                cats = list(course_obj.taxonomy_categories or [])
                course_domain = [tc.slug for tc in cats if tc.type == "domain"]
                course_level = [tc.slug for tc in cats if tc.type == "level"]
                audience_type = [tc.slug for tc in cats if tc.type == "audience"]
                title_fr = course_obj.title_fr
                title_en = course_obj.title_en
                effective_hours = 30 or course_obj.estimated_hours
                rag_collection_id = course_obj.rag_collection_id

                module_dicts_result = await mock_agent.generate_course_structure(
                    title_fr=title_fr,
                    title_en=title_en,
                    course_domain=course_domain,
                    course_level=course_level,
                    audience_type=audience_type,
                    estimated_hours=effective_hours,
                )

                await mock_session.execute(delete(Module).where(Module.course_id == uuid.UUID(course_id)))

                saved = []
                for i, m in enumerate(module_dicts_result):
                    mod = Module(
                        id=uuid.uuid4(),
                        module_number=i + 1,
                        level=1,
                        title_fr=m["title_fr"],
                        title_en=m["title_en"],
                        description_fr=m.get("description_fr"),
                        description_en=m.get("description_en"),
                        estimated_hours=m.get("estimated_hours", 20),
                        bloom_level=m.get("bloom_level"),
                        course_id=uuid.UUID(course_id),
                        books_sources={rag_collection_id: []} if rag_collection_id else None,
                    )
                    mock_session.add(mod)

                    for j, u in enumerate(m.get("units", [])):
                        unit = ModuleUnit(
                            id=uuid.uuid4(),
                            module_id=mod.id,
                            unit_number=str(j + 1),
                            title_fr=u.get("title_fr", f"Unité {j + 1}"),
                            title_en=u.get("title_en", f"Unit {j + 1}"),
                            description_fr=u.get("description_fr"),
                            description_en=u.get("description_en"),
                            order_index=j,
                        )
                        mock_session.add(unit)

                    saved.append({"id": str(mod.id), "module_number": mod.module_number, "title_fr": mod.title_fr, "title_en": mod.title_en, "units_count": len(m.get("units", []))})

                course_obj.module_count = len(module_dicts_result)
                course_obj.syllabus_json = module_dicts_result
                await mock_session.commit()
                return {"status": "complete", "modules_count": len(saved), "modules": saved}

        result = await run_inner()

        assert result["status"] == "complete"
        assert result["modules_count"] == 3
        mock_session.flush.assert_not_called()
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_taxonomy_values_extracted_correctly(self):
        """Regression: taxonomy_categories values must be read before session write ops."""
        course_id = str(uuid.uuid4())
        course = _make_mock_course(uuid.UUID(course_id))

        cats_snapshot = list(course.taxonomy_categories)
        domain_slugs = [tc.slug for tc in cats_snapshot if tc.type == "domain"]
        level_slugs = [tc.slug for tc in cats_snapshot if tc.type == "level"]
        audience_slugs = [tc.slug for tc in cats_snapshot if tc.type == "audience"]

        assert domain_slugs == ["epidemiology"]
        assert level_slugs == ["beginner"]
        assert audience_slugs == []

    @pytest.mark.asyncio
    async def test_units_saved_without_individual_flush(self):
        """Verify units are added with session.add() — no flush per unit."""
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()

        from app.domain.models.module_unit import ModuleUnit

        module_id = uuid.uuid4()
        units_data = [
            {"title_fr": "U1 FR", "title_en": "U1 EN", "description_fr": "d", "description_en": "d"},
            {"title_fr": "U2 FR", "title_en": "U2 EN", "description_fr": "d", "description_en": "d"},
        ]

        for j, u in enumerate(units_data):
            unit = ModuleUnit(
                id=uuid.uuid4(),
                module_id=module_id,
                unit_number=str(j + 1),
                title_fr=u.get("title_fr", f"Unité {j + 1}"),
                title_en=u.get("title_en", f"Unit {j + 1}"),
                description_fr=u.get("description_fr"),
                description_en=u.get("description_en"),
                order_index=j,
            )
            mock_session.add(unit)

        assert mock_session.add.call_count == 2
        mock_session.flush.assert_not_called()
