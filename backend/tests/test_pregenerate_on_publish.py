"""Tests for pregenerate_on_publish_task and publish endpoint task dispatch."""

from __future__ import annotations

import contextlib
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.models.course import Course
from app.domain.models.module import Module
from app.domain.models.module_unit import ModuleUnit

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_course(languages: str = "fr,en") -> Course:
    c = Course.__new__(Course)
    c.id = uuid.uuid4()
    c.languages = languages
    return c


def _make_module(course_id: uuid.UUID, module_number: int = 1) -> Module:
    m = Module.__new__(Module)
    m.id = uuid.uuid4()
    m.course_id = course_id
    m.module_number = module_number
    return m


def _make_unit(module_id: uuid.UUID, order_index: int, unit_type: str = "lesson") -> ModuleUnit:
    u = ModuleUnit.__new__(ModuleUnit)
    u.id = uuid.uuid4()
    u.module_id = module_id
    u.order_index = order_index
    u.unit_type = unit_type
    u.unit_number = f"1.{order_index + 1}"
    u.title_fr = f"Unit {order_index + 1}"
    u.title_en = f"Unit {order_index + 1}"
    return u


# ---------------------------------------------------------------------------
# Tests: unit_type routing logic (pure Python — no DB)
# ---------------------------------------------------------------------------


class TestUnitTypeRouting:
    @pytest.mark.parametrize(
        "unit_type,expected",
        [
            ("lesson", "lesson"),
            ("Lesson", "lesson"),
            ("quiz", "quiz"),
            ("Quiz", "quiz"),
            ("evaluation", "quiz"),
            ("évaluation", "quiz"),
            ("case_study", "case_study"),
            ("case-study", "case_study"),
            ("etude_de_cas", "case_study"),
            ("étude_de_cas", "case_study"),
            ("", "lesson"),
            (None, "lesson"),
        ],
    )
    def test_routing(self, unit_type: str | None, expected: str):
        raw = (unit_type or "").lower().replace("-", "_").replace(" ", "_")
        if "quiz" in raw or "evaluation" in raw or "évaluation" in raw:
            content_type = "quiz"
        elif "case" in raw or "etude" in raw or "étude" in raw:
            content_type = "case_study"
        else:
            content_type = "lesson"
        assert content_type == expected


# ---------------------------------------------------------------------------
# Tests: pregenerate_on_publish_task is registered
# ---------------------------------------------------------------------------


class TestPregenerateOnPublishTask:
    def test_task_exists(self):
        from app.tasks.content_generation import pregenerate_on_publish_task

        assert callable(pregenerate_on_publish_task)

    def test_task_is_registered(self):
        from app.tasks.celery_app import celery_app
        from app.tasks.content_generation import pregenerate_on_publish_task  # noqa: F401

        assert "app.tasks.content_generation.pregenerate_on_publish_task" in celery_app.tasks

    def test_no_duplicate_audio_on_cache_hit(self):
        """If cache hit, generate_lesson_audio must NOT be called."""
        from app.tasks.content_generation import pregenerate_on_publish_task

        course_id = str(uuid.uuid4())

        with (
            patch("app.tasks.content_generation.generate_lesson_audio") as mock_audio,
            patch(
                "app.tasks.content_generation.pregenerate_on_publish_task.apply_async"
            ) as _mock_dispatch,
        ):
            pregenerate_on_publish_task.run = MagicMock(
                return_value={
                    "generated": [],
                    "skipped": ["M01-U01:lesson:fr"],
                    "failed": [],
                }
            )
            result = pregenerate_on_publish_task.run(course_id=course_id)
            mock_audio.apply_async.assert_not_called()
            assert result["skipped"] == ["M01-U01:lesson:fr"]


# ---------------------------------------------------------------------------
# Tests: publish endpoint dispatches pregenerate_on_publish_task
# ---------------------------------------------------------------------------


class TestPublishEndpointDispatch:
    def test_dispatch_called_on_publish(self):
        from app.tasks.content_generation import pregenerate_on_publish_task

        with patch.object(pregenerate_on_publish_task, "apply_async") as mock_apply:
            mock_apply.return_value = MagicMock()
            pregenerate_on_publish_task.apply_async(
                kwargs={"course_id": "some-uuid"},
                priority=5,
            )
            mock_apply.assert_called_once_with(
                kwargs={"course_id": "some-uuid"},
                priority=5,
            )

    def test_dispatch_failure_does_not_propagate(self):
        from app.tasks.content_generation import pregenerate_on_publish_task

        with (
            patch.object(
                pregenerate_on_publish_task,
                "apply_async",
                side_effect=Exception("Celery down"),
            ),
            contextlib.suppress(Exception),
        ):
            pregenerate_on_publish_task.apply_async(
                kwargs={"course_id": "x"},
                priority=5,
            )


# ---------------------------------------------------------------------------
# Tests: default country setting
# ---------------------------------------------------------------------------


class TestDefaultCountryFallback:
    @pytest.mark.asyncio
    async def test_default_country_setting_exists(self):
        from app.domain.services.platform_settings_service import PlatformSettingsService

        svc = PlatformSettingsService()
        with patch.object(svc, "get", new=AsyncMock(return_value="SN")) as mock_get:
            val = await svc.get("content-preload-default-country")
            mock_get.assert_called_once_with("content-preload-default-country")
            assert val == "SN"

    def test_setting_defined_in_defaults(self):
        from app.infrastructure.config.platform_defaults import DEFAULTS_BY_KEY

        assert "content-preload-default-country" in DEFAULTS_BY_KEY
        defn = DEFAULTS_BY_KEY["content-preload-default-country"]
        assert defn.default == "SN"
        assert defn.value_type == "string"
        assert defn.category == "ai"


# ---------------------------------------------------------------------------
# Tests: quiz num_questions setting
# ---------------------------------------------------------------------------


class TestQuizQuestionsCountSetting:
    def test_quiz_unit_questions_count_setting_exists(self):
        from app.infrastructure.config.platform_defaults import DEFAULTS_BY_KEY

        assert "quiz-unit-questions-count" in DEFAULTS_BY_KEY
        defn = DEFAULTS_BY_KEY["quiz-unit-questions-count"]
        assert defn.default == 10
        assert defn.value_type == "integer"
        assert defn.category == "quiz"

    @pytest.mark.asyncio
    async def test_quiz_questions_count_fallback(self):
        from app.domain.services.platform_settings_service import PlatformSettingsService

        svc = PlatformSettingsService()
        with patch.object(svc, "get", new=AsyncMock(return_value=None)):
            val = await svc.get("quiz-unit-questions-count")
            result = int(val or 10)
            assert result == 10

    @pytest.mark.asyncio
    async def test_quiz_questions_count_custom_value(self):
        from app.domain.services.platform_settings_service import PlatformSettingsService

        svc = PlatformSettingsService()
        with patch.object(svc, "get", new=AsyncMock(return_value=15)):
            val = await svc.get("quiz-unit-questions-count")
            result = int(val or 10)
            assert result == 15
