"""scripts/generate_lesson_stories.py: picking a module, dispatching, reporting.

The database and Celery are faked: the script's own logic is which module it
picks, that it goes through the API's module dispatch (dedup key included)
once per course and language, and what it reports and returns.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.domain.services.story_module_assembly import StoryUnit

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "generate_lesson_stories.py"
_spec = importlib.util.spec_from_file_location("generate_lesson_stories", _SCRIPT)
script = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = script  # dataclasses look their module up while defining
_spec.loader.exec_module(script)

_REPO = _SCRIPT.parent.parent.parent
_WORKFLOW = _REPO / ".github" / "workflows" / "generate-lesson-story.yml"


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


def story_unit(number, role, unit_type=None, order=0):
    return StoryUnit(
        module_unit_id=uuid.uuid4(),
        unit_number=number,
        unit_type=unit_type,
        order_index=order,
        role=role,
        title={"en": f"Unit {number}", "fr": f"Unité {number}"},
    )


def module(number):
    return SimpleNamespace(id=uuid.uuid4(), module_number=number, title_fr=f"Module {number}")


COURSE = SimpleNamespace(
    id=uuid.uuid4(), slug="biologie-cm1", title_fr="Biologie", title_en="Biology"
)
ROSTER = (
    story_unit("1.1", "lesson", None, 0),
    story_unit("1.2", "lesson", "lesson", 1),
    story_unit("1.3", "quiz_checkpoint", "quiz", 2),
    story_unit("1.4", "case_checkpoint", "case-study", 3),
)


@pytest.fixture
def roster(monkeypatch):
    """``load_story_units`` answers ROSTER and records the module it was asked for."""
    asked = []

    async def load_story_units(_session, module_id):
        asked.append(module_id)
        return list(ROSTER)

    monkeypatch.setattr(script, "load_story_units", load_story_units)
    return asked


class TestModuleTarget:
    async def test_picks_the_module_by_number_with_its_units_and_roles(self, roster):
        first, second = module(4), module(7)
        target, why = await script.module_target(FakeSession([first, second]), COURSE, 2)

        assert why == ""
        assert target.module is second and roster == [second.id]
        assert target.units == ROSTER
        assert [u.unit_number for u in target.lessons] == ["1.1", "1.2"]

    async def test_a_module_id_picks_that_module(self, roster):
        first, second = module(1), module(2)
        target, _ = await script.module_target(
            FakeSession([first, second]), COURSE, 1, module_id=second.id
        )
        assert target.module is second

    async def test_a_module_id_outside_the_course_is_reported(self, roster):
        target, why = await script.module_target(
            FakeSession([module(1)]), COURSE, 1, module_id=uuid.uuid4()
        )
        assert target is None and "not in the course" in why

    async def test_reports_a_missing_module(self, roster):
        target, why = await script.module_target(FakeSession([]), COURSE, 1)
        assert target is None and "0 module" in why
        target, why = await script.module_target(FakeSession([module(1)]), COURSE, 2)
        assert target is None and "1 module" in why
        assert roster == []


def chapter(**overrides):
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


def module_story(**overrides):
    units = [
        {"module_unit_id": str(u.module_unit_id), "unit_number": u.unit_number, "role": u.role}
        for u in ROSTER
    ]
    for entry, status in zip(
        units, ["ready", "unavailable", "checkpoint", "checkpoint"], strict=True
    ):
        entry["status"] = status
    values = {
        "slug": "module-abc-fr",
        "status": "published",
        "is_valid": True,
        "max_points": 40,
        "content": {
            "languages": {"target": "fr", "home": "en"},
            "title": {"fr": "Le voyage de {child}", "en": "{child}'s journey"},
            "chapters": [
                {
                    "title": {"fr": "Au marché", "en": "At the market"},
                    "covers": {"unit_number": "1.1", "role": "lesson", "status": "ready"},
                },
                {
                    "title": {"fr": "Le quiz", "en": "The quiz"},
                    "covers": {
                        "unit_number": "1.3",
                        "role": "quiz_checkpoint",
                        "status": "checkpoint",
                    },
                },
            ],
            "questions": [{"id": "u1_1-Q1", "prompt": {"fr": "Qui pique ?", "en": "Who bites?"}}],
            "exercises": [],
            "module_story": {"revision": "0123456789abcdef"},
        },
        "source_rows": {"assembler": 1, "units": units},
        "validation_report": {"ok": True, "errors": [], "warnings": [{"code": "w2"}]},
        "updated_at": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class TestStoryExcerpt:
    def test_title_chapters_with_their_units_and_prompts_in_the_target_language(self):
        assert script.story_excerpt(module_story().content) == [
            "title: Le voyage de {child}",
            "chapter 1.1 lesson ready: Au marché",
            "chapter 1.3 quiz_checkpoint checkpoint: Le quiz",
            "u1_1-Q1: Qui pique ?",
        ]

    def test_no_content(self):
        assert script.story_excerpt(None) == []


class TestSummaries:
    def test_summarises_a_stored_chapter(self):
        summary = script.story_summary(chapter())
        assert summary["stored"] and summary["is_valid"]
        assert summary["questions"] == 2 and summary["exercises"] == 1
        assert summary["questions_from_quiz"] is True
        assert summary["errors"] == [] and summary["warnings"] == ["w1"]

    def test_summarises_a_module_story_from_its_manifest(self):
        summary = script.module_story_summary(module_story())
        assert summary["stored"] and summary["is_valid"] and summary["status"] == "published"
        assert (summary["ready"], summary["unavailable"], summary["checkpoint"]) == (1, 1, 2)
        assert summary["unavailable_units"] == ["1.2"]
        assert summary["chapters"] == 2 and summary["questions"] == 1
        assert summary["max_points"] == 40 and summary["revision"] == "0123456789abcdef"
        assert summary["errors"] == [] and summary["warnings"] == ["w2"]

    def test_the_rally_status_comes_from_the_manifest(self, capsys):
        record = module_story()
        assert script.module_story_summary(record)["rally"] is None
        record.source_rows = {**record.source_rows, "rally": {"status": "draft", "doc": None}}
        summary = script.module_story_summary(record)
        assert summary["rally"] == "draft"
        script.print_module_summary("  ", summary, True)
        assert "    rally=draft" in capsys.readouterr().out

    def test_a_module_story_without_a_manifest_still_summarises(self):
        summary = script.module_story_summary(module_story(source_rows=None, content={}))
        assert (summary["ready"], summary["unavailable"], summary["checkpoint"]) == (0, 0, 0)
        assert summary["revision"] is None and summary["chapters"] == 0

    def test_no_story(self):
        assert script.story_summary(None) == {"stored": False}
        assert script.module_story_summary(None) == {"stored": False}

    def test_the_printed_summary_counts_the_chapters(self, capsys):
        script.print_module_summary("  ", script.module_story_summary(module_story()), True)
        out = capsys.readouterr().out
        assert "module story: module-abc-fr status=published valid=True fresh=True" in out
        assert "chapters=2 (ready=1 unavailable=1 checkpoint=2) questions=1" in out
        assert "unavailable units=['1.2']" in out and "warnings=['w2']" in out


class TestList:
    @pytest.fixture
    def wired(self, monkeypatch):
        target = script.ModuleTarget(COURSE, module(1), ROSTER)
        lesson, untouched = ROSTER[0], ROSTER[1]
        quiz = ROSTER[2]

        async def find_courses(_session, _queries):
            return [SimpleNamespace(**vars(COURSE), status="published", taxonomy_categories=[])]

        async def module_target(_session, _course, module_index, _module_id=None):
            return (target, "") if module_index == 1 else (None, "the course has 1 module(s)")

        async def cached_rows(_session, unit_ids):
            assert set(unit_ids) == {u.module_unit_id for u in ROSTER}
            return {
                (lesson.module_unit_id, "lesson", "fr"): 1,
                (quiz.module_unit_id, "quiz", "fr"): 2,
            }

        async def chapter_rows(_session, unit_ids):
            assert unit_ids == [lesson.module_unit_id, untouched.module_unit_id]
            return {(lesson.module_unit_id, "fr"): chapter()}

        async def chapters_are_fresh(_session, records):
            return [False] * len(records)

        async def find_module_story(_session, _module_id, language):
            return module_story() if language == "fr" else None

        async def module_story_is_fresh(_session, _record, *, units=None):
            assert units == ROSTER
            return True

        monkeypatch.setattr(script, "find_courses", find_courses)
        monkeypatch.setattr(script, "module_target", module_target)
        monkeypatch.setattr(script, "cached_rows", cached_rows)
        monkeypatch.setattr(script, "chapter_rows", chapter_rows)
        monkeypatch.setattr(script, "chapters_are_fresh", chapters_are_fresh)
        monkeypatch.setattr(script, "find_module_story", find_module_story)
        monkeypatch.setattr(script, "module_story_is_fresh", module_story_is_fresh)

    async def test_shows_units_roles_cached_content_chapters_and_the_module_story(
        self, wired, capsys
    ):
        assert await script.main(["list", "--query", "biolog"], session_factory=FakeSession) == 0
        out = capsys.readouterr().out
        assert "1.1 lesson (type=None) Unité 1.1" in out
        assert "1.3 quiz_checkpoint (type=quiz)" in out
        assert "1.4 case_checkpoint (type=case-study)" in out
        assert "[fr] cached lesson=1 quiz=0 case=0" in out
        assert "[fr] cached lesson=0 quiz=2 case=0" in out
        assert "[fr] chapter: lesson-abc-fr status=published valid=True fresh=False" in out
        assert "[en] chapter: none" in out
        assert "[fr] module story: module-abc-fr" in out
        assert "(ready=1 unavailable=1 checkpoint=2)" in out
        assert "[en] module story: none" in out

    async def test_a_missing_module_is_reported(self, wired, capsys):
        argv = ["list", "--query", "biolog", "--module-index", "2"]
        assert await script.main(argv, session_factory=FakeSession) == 0
        assert "no module 2: the course has 1 module(s)" in capsys.readouterr().out


class TestGenerate:
    @pytest.fixture
    def wired(self, monkeypatch):
        """Fake course lookup, module pick, dispatch, Celery wait and story read."""
        target = script.ModuleTarget(COURSE, module(1), ROSTER)
        dispatched = []
        state = SimpleNamespace(target=target, result={"status": "complete"})

        async def resolve_course(_session, ref):
            return COURSE if ref == COURSE.slug else None

        async def module_target(_session, _course, _m, _module_id=None):
            return state.target, ""

        async def dispatch(**kwargs):
            dispatched.append(kwargs)
            return f"task-{len(dispatched)}"

        stored = {}

        async def find_module_story(_session, module_id, language):
            assert module_id == state.target.module.id
            return stored.get(language)

        async def wait_for_task(task_id, _timeout):
            return "SUCCESS", state.result

        from app.api.v1 import story_courses

        monkeypatch.setattr(script, "resolve_course", resolve_course)
        monkeypatch.setattr(script, "module_target", module_target)
        monkeypatch.setattr(story_courses, "dispatch_module_story_generation", dispatch)
        monkeypatch.setattr(script, "find_module_story", find_module_story)
        monkeypatch.setattr(script, "wait_for_task", wait_for_task)
        printed: list[tuple[object, str, object]] = []

        async def print_story(_session, module_id, language, record, dump):
            printed.append((module_id, language, dump))
            for line in script.story_transcript(record.content if record else None):
                print(f"    {line}")

        monkeypatch.setattr(script, "print_story", print_story)
        state.dispatched, state.stored, state.printed = dispatched, stored, printed
        return state

    async def run(self, *argv):
        return await script.main(list(argv), session_factory=FakeSession)

    async def test_the_dump_folder_is_passed_to_every_story(self, wired, tmp_path):
        wired.stored.update(fr=module_story(), en=module_story(slug="module-abc-en"))
        code = await self.run("generate", "--course", COURSE.slug, "--dump", str(tmp_path))
        assert code == 0
        assert [(language, dump) for _m, language, dump in wired.printed] == [
            ("fr", str(tmp_path)),
            ("en", str(tmp_path)),
        ]

    async def test_dispatches_the_module_once_per_language_through_the_api_dedup(self, wired):
        wired.stored.update(fr=module_story(), en=module_story(slug="module-abc-en"))

        code = await self.run("generate", "--course", COURSE.slug)

        assert code == 0
        assert wired.dispatched == [
            {
                "module_id": wired.target.module.id,
                "language": language,
                "country": "CI",
                "level": 1,
                "force_regenerate": False,
            }
            for language in ("fr", "en")
        ]

    async def test_force_level_and_country_are_passed_through(self, wired):
        wired.stored.update(fr=module_story())
        argv = ["--language", "fr", "--force", "--level", "3", "--country", "SN"]
        await self.run("generate", "--course", COURSE.slug, *argv)
        [sent] = wired.dispatched
        assert (sent["force_regenerate"], sent["level"], sent["country"]) == (True, 3, "SN")

    async def test_a_lesson_index_is_ignored_with_a_warning(self, wired, capsys):
        wired.stored.update(fr=module_story())
        argv = ["generate", "--course", COURSE.slug, "--language", "fr", "--lesson-index", "3"]
        assert await self.run(*argv) == 0
        assert wired.dispatched[0]["module_id"] == wired.target.module.id
        assert "--lesson-index is ignored" in capsys.readouterr().err

    async def test_fails_when_a_module_story_is_invalid_or_missing(self, wired):
        wired.stored.update(fr=module_story(is_valid=False, status="draft"))
        assert await self.run("generate", "--course", COURSE.slug) == 1

    async def test_fails_when_the_task_failed_even_if_an_old_story_is_stored(self, wired, capsys):
        wired.stored.update(fr=module_story())
        wired.result = {
            "status": "failed",
            "error": "chapter_generation_failed",
            "failed_units": ["1.2"],
        }
        code = await self.run("generate", "--course", COURSE.slug, "--language", "fr")
        assert code == 1
        assert "failed units=['1.2']" in capsys.readouterr().out

    async def test_fails_for_an_unknown_course_without_dispatching(self, wired):
        assert await self.run("generate", "--course", "nope", "--language", "fr") == 1
        assert wired.dispatched == []

    async def test_a_module_without_lessons_is_not_dispatched(self, wired, capsys):
        wired.target = script.ModuleTarget(COURSE, module(1), ROSTER[2:])
        assert await self.run("generate", "--course", COURSE.slug) == 1
        assert wired.dispatched == []
        assert "no lesson unit" in capsys.readouterr().out

    def test_the_default_wait_fits_the_deploy_workflow(self):
        # Under the workflow's 60-minute SSH command timeout; a continuation is followed.
        for argv in (["generate", "--course", "x"], ["requests", "file.json"]):
            assert script.parse_args(argv).timeout == 3300 < 60 * 60

    def test_a_module_index_below_one_is_refused(self):
        with pytest.raises(SystemExit):
            script.parse_args(["generate", "--course", "x", "--module-index", "0"])


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

    async def test_the_shipped_request_file_is_valid(self, capsys):
        path = Path(script.__file__).parent / "story_requests.json"
        requests = script.load_requests(str(path))
        # #2680 makes every stored story stale once: until the owner approves the
        # v4 story of the staging test module, the deploy pays for that one only.
        assert [str(r["module_id"]) for r in requests] == ["aab749f1-fba3-45d3-bcff-e0f4f925475a"]
        assert requests[0]["languages"] == ("fr",)
        # Module stories only: no entry still asks for a lesson.
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert not any("lesson_index" in entry for entry in raw["requests"])
        assert "Module stories" in raw["_comment"]
        assert capsys.readouterr().err == ""

    def test_a_lesson_index_is_ignored_with_a_warning(self, tmp_path, capsys):
        path = tmp_path / "requests.json"
        path.write_text(
            json.dumps({"requests": [{"query": "x", "lesson_index": 3}]}), encoding="utf-8"
        )
        [request] = script.load_requests(str(path))
        assert "lesson_index" not in request and request["module_index"] == 1
        assert "requests[0].lesson_index is ignored" in capsys.readouterr().err

    def test_a_module_index_below_one_is_refused(self, tmp_path):
        path = tmp_path / "requests.json"
        path.write_text(
            json.dumps({"requests": [{"query": "x", "module_index": 0}]}), encoding="utf-8"
        )
        with pytest.raises(ValueError, match="module_index"):
            script.load_requests(str(path))

    async def test_picks_the_one_published_kids_course_per_query(self, wired):
        path = wired.write(
            [{"query": "biolog", "kids_only": True}, {"query": "math", "kids_only": True}]
        )

        assert await self.run("requests", path) == 0

        assert [s.course.slug for s in wired.generated] == ["bio-kids", "maths-kids"]
        assert all(s.languages == ("fr", "en") for s in wired.generated)
        assert all(s.module_index == 1 and s.module_id is None for s in wired.generated)

    async def test_a_module_index_picks_that_module(self, wired):
        path = wired.write([{"query": "biolog", "kids_only": True, "module_index": 3}])
        assert await self.run("requests", path) == 0
        [spec] = wired.generated
        assert spec.module_index == 3

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
        path = wired.write([{"module_id": str(module_obj.id), "languages": ["fr"]}])

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


class TestWorkflow:
    """.github/workflows/generate-lesson-story.yml runs this script on the server."""

    @pytest.fixture(scope="class")
    def step(self):
        yaml = pytest.importorskip("yaml")
        if not _WORKFLOW.exists():
            pytest.skip("the workflow is not in this checkout")
        workflow = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
        steps = workflow["jobs"]["story"]["steps"]
        return next(s for s in steps if "ssh-action" in s.get("uses", ""))

    def test_a_first_run_of_module_stories_has_an_hour(self, step):
        assert step["with"]["command_timeout"] == "60m"
        # The SSH session outlives every wait the script does.
        assert script.DEFAULT_TIMEOUT_S < 60 * 60

    def test_it_runs_this_script_and_keeps_the_request_file_guard(self, step):
        command = step["with"]["script"]
        assert "scripts/generate_lesson_stories.py" in command
        assert "test -f scripts/story_requests.json" in command
        assert "run requests scripts/story_requests.json" in command

    def test_its_copy_is_about_module_stories(self):
        text = _WORKFLOW.read_text(encoding="utf-8") if _WORKFLOW.exists() else ""
        if not text:
            pytest.skip("the workflow is not in this checkout")
        assert "module stories" in text.lower()
        assert "Story tab" not in text and "lesson 1" not in text


# --------------------------------------------------------------------------
# The transcript (#2680)
# --------------------------------------------------------------------------


def test_the_transcript_reads_the_whole_story_in_its_language():
    from tests.test_story_module_assembly import MODULE_FIXTURE

    fixture = json.loads(MODULE_FIXTURE.read_text(encoding="utf-8"))
    doc = fixture["chapters"]["fr"]["1.1"]
    plan = json.loads(
        (Path(__file__).parent / "fixtures" / "story_module_plan.json").read_text("utf-8")
    )
    lines = script.story_transcript(doc, plan)
    assert lines[0] == "EPISODE «Le panier des mystères»"
    assert lines[1].startswith("LOGLINE: {child} and {friend} must sort")
    assert "== Chapter 1 «L'escargot timide» (lesson ?) ==" in lines
    assert "[La cour de Mamie] ({child}, {friend}, Mariam) props:" in "\n".join(lines)
    assert any(line.startswith("  {friend} (surprised): Un escargot !") for line in lines)
    assert "  [look closely: l'escargot]" in lines
    assert any(line.startswith("  [card «La feuille timide»:") for line in lines)
    assert any(line.startswith("  [question q1: Lequel de ces signes") for line in lines)
    assert any(line.endswith("(refrain)") for line in lines)
