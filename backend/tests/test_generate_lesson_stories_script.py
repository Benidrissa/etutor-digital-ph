"""scripts/generate_lesson_stories.py: picking lesson 1, dispatching, reporting.

The database and Celery are faked: the script's own logic is which unit it
picks, that it goes through the API's dispatch (dedup key included) once per
course and language, and what it reports and returns.
"""

from __future__ import annotations

import importlib.util
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "generate_lesson_stories.py"
_spec = importlib.util.spec_from_file_location("generate_lesson_stories", _SCRIPT)
script = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = script  # dataclasses look their module up while defining
_spec.loader.exec_module(script)


class _Result:
    def __init__(self, items):
        self._items = list(items)

    def scalars(self):
        return self

    def all(self):
        return list(self._items)

    def scalar_one_or_none(self):
        return self._items[0] if self._items else None


class FakeSession:
    """Answers ``execute`` calls in order with the queued result lists."""

    def __init__(self, *results):
        self.results = list(results)

    async def execute(self, _statement):
        return _Result(self.results.pop(0))

    async def get(self, _model, _key):
        return None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def unit(number, unit_type, order):
    return SimpleNamespace(
        id=uuid.uuid4(),
        unit_number=number,
        unit_type=unit_type,
        order_index=order,
        title_fr=f"Unité {number}",
        title_en=f"Unit {number}",
    )


def module(number):
    return SimpleNamespace(id=uuid.uuid4(), module_number=number, title_fr=f"Module {number}")


COURSE = SimpleNamespace(
    id=uuid.uuid4(), slug="biologie-cm1", title_fr="Biologie", title_en="Biology"
)


class TestLessonTarget:
    async def test_picks_the_first_lesson_of_the_first_module_in_teaching_order(self):
        quiz = unit("1.3", "quiz", 2)
        second = unit("1.2", "lesson", 1)
        first = unit("1.1", None, 0)  # untyped units are lessons
        session = FakeSession([module(4), module(7)], [quiz, second, first])

        target, why = await script.lesson_target(session, COURSE, 1, 1)

        assert why == ""
        assert target.module.module_number == 4
        assert target.unit is first
        assert target.quiz_unit is quiz

    async def test_skips_quiz_and_case_study_units(self):
        quiz = unit("1.1", "quiz", 0)
        case = unit("1.2", "case-study", 1)
        lesson = unit("1.3", "lesson", 2)
        session = FakeSession([module(1)], [quiz, case, lesson])

        target, _ = await script.lesson_target(session, COURSE, 1, 1)

        assert target.unit is lesson
        assert target.quiz_unit is quiz  # nearest quiz before, none after

    async def test_reports_a_missing_module_or_lesson(self):
        target, why = await script.lesson_target(FakeSession([]), COURSE, 1, 1)
        assert target is None and "0 module" in why

        target, why = await script.lesson_target(
            FakeSession([module(1)], [unit("1.1", "quiz", 0)]), COURSE, 1, 1
        )
        assert target is None and "0 lesson" in why


def record(**overrides):
    values = {
        "slug": "lesson-abc-fr",
        "status": "published",
        "is_valid": True,
        "max_points": 24,
        "content": {
            "questions": [{"id": "Q1"}, {"id": "Q2"}],
            "exercises": [{"id": "E1"}],
            "sources": [{"kind": "lesson"}, {"kind": "test"}],
        },
        "validation_report": {"ok": True, "errors": [], "warnings": [{"code": "w1"}]},
        "source_quiz_content_id": uuid.uuid4(),
        "updated_at": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class TestStorySummary:
    def test_summarises_a_stored_story(self):
        summary = script.story_summary(record())
        assert summary["stored"] and summary["is_valid"]
        assert summary["questions"] == 2 and summary["exercises"] == 1
        assert summary["questions_from_quiz"] is True
        assert summary["errors"] == [] and summary["warnings"] == ["w1"]

    def test_no_story(self):
        assert script.story_summary(None) == {"stored": False}


class TestGenerate:
    @pytest.fixture
    def wired(self, monkeypatch):
        """Fake course lookup, lesson pick, dispatch, Celery wait and story read."""
        lesson = unit("1.1", "lesson", 0)
        target = script.LessonTarget(COURSE, module(1), lesson, None)
        dispatched = []

        async def resolve_course(_session, ref):
            return COURSE if ref == COURSE.slug else None

        async def lesson_target(_session, _course, _m, _l):
            return target, ""

        async def dispatch(**kwargs):
            dispatched.append(kwargs)
            return f"task-{len(dispatched)}"

        stored = {}

        async def find_unit_story(_session, _unit_id, language):
            return stored.get(language)

        async def wait_for_task(task_id, _timeout):
            return "SUCCESS", {"status": "complete"}

        from app.api.v1 import story_courses

        monkeypatch.setattr(script, "resolve_course", resolve_course)
        monkeypatch.setattr(script, "lesson_target", lesson_target)
        monkeypatch.setattr(story_courses, "_dispatch_story_generation", dispatch)
        monkeypatch.setattr(script, "find_unit_story", find_unit_story)
        monkeypatch.setattr(script, "wait_for_task", wait_for_task)
        return SimpleNamespace(target=target, dispatched=dispatched, stored=stored)

    async def run(self, *argv):
        return await script.main(list(argv), session_factory=FakeSession)

    async def test_dispatches_once_per_language_through_the_api_dedup(self, wired):
        wired.stored.update(fr=record(), en=record(slug="lesson-abc-en"))

        code = await self.run("generate", "--course", COURSE.slug)

        assert code == 0
        assert [d["language"] for d in wired.dispatched] == ["fr", "en"]
        first = wired.dispatched[0]
        assert first["module_unit_id"] == wired.target.unit.id
        assert first["unit_id"] == "1.1"
        assert first["force_regenerate"] is False

    async def test_force_is_passed_through(self, wired):
        wired.stored.update(fr=record())
        await self.run("generate", "--course", COURSE.slug, "--language", "fr", "--force")
        assert wired.dispatched[0]["force_regenerate"] is True

    async def test_fails_when_a_story_is_invalid_or_missing(self, wired):
        wired.stored.update(fr=record(is_valid=False, status="draft"))
        assert await self.run("generate", "--course", COURSE.slug) == 1

    async def test_fails_for_an_unknown_course_without_dispatching(self, wired):
        assert await self.run("generate", "--course", "nope", "--language", "fr") == 1
        assert wired.dispatched == []
