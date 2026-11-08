"""scripts/generate_lesson_stories.py: picking lesson 1, dispatching, reporting.

The database and Celery are faked: the script's own logic is which unit it
picks, that it goes through the API's dispatch (dedup key included) once per
course and language, and what it reports and returns.
"""

from __future__ import annotations

import importlib.util
import json
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

    async def test_a_module_id_picks_that_module(self):
        first, second = module(1), module(2)
        lesson = unit("2.1", "lesson", 0)
        session = FakeSession([first, second], [lesson])

        target, _ = await script.lesson_target(session, COURSE, 1, 1, module_id=second.id)

        assert target.module is second and target.unit is lesson

    async def test_a_module_id_outside_the_course_is_reported(self):
        target, why = await script.lesson_target(
            FakeSession([module(1)]), COURSE, 1, 1, module_id=uuid.uuid4()
        )
        assert target is None and "not in the course" in why

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


class TestStoryExcerpt:
    def test_title_chapters_and_prompts_in_the_target_language(self):
        content = {
            "languages": {"target": "fr", "home": "en"},
            "title": {"fr": "Le moustique de {child}", "en": "{child}'s mosquito"},
            "chapters": [{"title": {"fr": "Au marché", "en": "At the market"}}],
            "questions": [{"id": "Q1", "prompt": {"fr": "Qui pique ?", "en": "Who bites?"}}],
        }
        assert script.story_excerpt(content) == [
            "title: Le moustique de {child}",
            "chapter: Au marché",
            "Q1: Qui pique ?",
        ]

    def test_no_content(self):
        assert script.story_excerpt(None) == []


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

        async def lesson_target(_session, _course, _m, _l, _module_id=None):
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


def kids_course(slug, title, *, status="published", kids=True):
    return SimpleNamespace(
        id=uuid.uuid4(),
        slug=slug,
        title_fr=title,
        title_en=title,
        status=status,
        taxonomy_categories=[SimpleNamespace(type="audience", slug="primary_school")]
        if kids
        else [],
    )


class TestRequests:
    @pytest.fixture
    def wired(self, monkeypatch, tmp_path):
        """Fake course search, kids detection and the generation itself."""
        courses = {
            "biolog": [kids_course("bio-kids", "Biologie")],
            "math": [
                kids_course("maths-kids", "Mathématiques"),
                kids_course("maths-adults", "Mathématiques avancées", kids=False),
                kids_course("maths-draft", "Mathématiques brouillon", status="draft"),
            ],
        }
        generated = []

        async def find_courses(_session, queries):
            return list(courses.get(queries[0], []))

        def detect_audience(course):
            return SimpleNamespace(is_kids=bool(course.taxonomy_categories))

        async def run_generation(_factory, specs, **kwargs):
            generated.extend(specs)
            return 0

        monkeypatch.setattr(script, "find_courses", find_courses)
        monkeypatch.setattr(script, "detect_audience", detect_audience)
        monkeypatch.setattr(script, "run_generation", run_generation)

        def write(requests):
            path = tmp_path / "requests.json"
            path.write_text(json.dumps({"requests": requests}), encoding="utf-8")
            return str(path)

        return SimpleNamespace(courses=courses, generated=generated, write=write)

    async def run(self, *argv):
        return await script.main(list(argv), session_factory=FakeSession)

    async def test_the_shipped_request_file_is_valid(self):
        requests = script.load_requests(str(Path(script.__file__).parent / "story_requests.json"))
        kids, test = requests[:2], requests[2:]
        assert [r["query"] for r in kids] == ["biolog", "math"]
        assert all(r["kids_only"] and r["languages"] == ("fr", "en") for r in kids)
        assert all(r["module_index"] == 1 and r["lesson_index"] == 1 for r in kids)
        assert [str(r["module_id"]) for r in test] == ["aab749f1-fba3-45d3-bcff-e0f4f925475a"]
        assert test[0]["languages"] == ("fr",) and test[0]["lesson_index"] == 1

    async def test_picks_the_one_published_kids_course_per_query(self, wired):
        path = wired.write(
            [{"query": "biolog", "kids_only": True}, {"query": "math", "kids_only": True}]
        )

        assert await self.run("requests", path) == 0

        assert [s.course.slug for s in wired.generated] == ["bio-kids", "maths-kids"]
        assert all(s.languages == ("fr", "en") for s in wired.generated)

    async def test_refuses_a_query_matching_too_many_courses(self, wired, capsys):
        path = wired.write([{"query": "math"}, {"query": "biolog", "kids_only": True}])

        assert await self.run("requests", path) == 1

        # The vague query generates nothing; the precise one still does.
        assert [s.course.slug for s in wired.generated] == ["bio-kids"]
        assert "maths-adults" in capsys.readouterr().out

    async def test_no_match_is_skipped_with_the_near_misses(self, wired, capsys):
        """The same file runs on staging and production, where different
        courses exist: a request with no match there must not fail the run."""
        wired.courses["biolog"] = [kids_course("bio-draft", "Biologie", status="draft")]
        path = wired.write([{"query": "biolog", "kids_only": True}])

        assert await self.run("requests", path) == 0

        assert wired.generated == []
        out = capsys.readouterr().out
        assert "skipped" in out and "bio-draft" in out and "status=draft" in out

    async def test_a_module_id_request_targets_that_module(self, wired, tmp_path):
        course = kids_course("santé", "Santé publique", status="draft", kids=False)
        module_obj = SimpleNamespace(id=uuid.uuid4(), course=course)
        path = wired.write(
            [{"module_id": str(module_obj.id), "lesson_index": 1, "languages": ["fr"]}]
        )

        code = await script.main(
            ["requests", path], session_factory=lambda: FakeSession([module_obj])
        )

        assert code == 0
        [spec] = wired.generated
        assert spec.course is course and spec.module_id == module_obj.id
        assert spec.languages == ("fr",)

    async def test_a_module_id_missing_on_this_server_is_skipped(self, wired, capsys):
        path = wired.write([{"module_id": str(uuid.uuid4())}])

        code = await script.main(["requests", path], session_factory=lambda: FakeSession([]))

        assert code == 0 and wired.generated == []
        assert "not on this server" in capsys.readouterr().out

    def test_rejects_a_malformed_request_file(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({"requests": [{"languages": ["fr"]}]}), encoding="utf-8")
        with pytest.raises(ValueError, match="query"):
            script.load_requests(str(bad))
        bad.write_text(
            json.dumps({"requests": [{"query": "x", "languages": ["de"]}]}), encoding="utf-8"
        )
        with pytest.raises(ValueError, match="languages"):
            script.load_requests(str(bad))
        bad.write_text(json.dumps({"requests": [{"module_id": "nope"}]}), encoding="utf-8")
        with pytest.raises(ValueError, match="module_id"):
            script.load_requests(str(bad))
