"""scripts/story_prop_inventory.py: which props the stories ask for (Phase 0).

The database is faked: the script's own logic is how it reads props from
story documents and module plans, counts each once per module and language,
groups search phrases by head noun, matches a list of model names, and what
it reports.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "story_prop_inventory.py"
_spec = importlib.util.spec_from_file_location("story_prop_inventory", _SCRIPT)
script = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = script  # dataclasses look their module up while defining
_spec.loader.exec_module(script)

_FIXTURES = Path(__file__).parent / "fixtures"
_CANDIDATES = _SCRIPT.parent / "story_prop_candidates.json"
_WORKFLOW = _SCRIPT.parent.parent.parent / ".github" / "workflows" / "generate-lesson-story.yml"

COURSE = "6f1c1d2e-0000-4000-8000-000000000001"
MODULE = "6f1c1d2e-0000-4000-8000-0000000000aa"


def _chapters() -> dict:
    return json.loads((_FIXTURES / "module_story_chapters.json").read_text("utf-8"))["chapters"]


def _plan_props() -> list:
    return json.loads((_FIXTURES / "story_module_plan.json").read_text("utf-8"))["props"]


class _Result:
    def __init__(self, rows):
        self._rows = list(rows)

    def all(self):
        return list(self._rows)


class FakeSession:
    """Answers ``execute`` calls in order: story rows, plan rows, courses."""

    def __init__(self, *results):
        self.results = list(results)
        self.calls = 0

    async def execute(self, _statement):
        self.calls += 1
        return _Result(self.results.pop(0))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _story_rows() -> list[tuple]:
    rows = []
    for language, chapters in _chapters().items():
        for index, doc in enumerate(chapters.values()):
            unit = f"unit-{language}-{index}"
            rows.append((f"row-{unit}", MODULE, unit, language, COURSE, "published", doc["props"]))
    return rows


# -- Words ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("word", "expected"),
    [
        ("boxes", "box"),
        ("berries", "berry"),
        ("seeds", "seed"),
        ("dishes", "dish"),
        ("tomatoes", "tomato"),
        ("leaves", "leaf"),
        ("children", "child"),
        ("glass", "glass"),
        ("bus", "bus"),
        ("grass", "grass"),
        ("cactus", "cactus"),
    ],
)
def test_singular(word, expected):
    assert script.singular(word) == expected


def test_tokens_split_model_names_and_fold_accents():
    assert script.tokens("Pebble_Round_1") == ["pebble", "round"]
    assert script.tokens("BigPalmTree") == ["big", "palm", "tree"]
    assert script.tokens("Néré seed") == ["nere", "seed"]


@pytest.mark.parametrize(
    ("query", "head"),
    [
        ("woven straw basket", "basket"),
        ("The wicker baskets", "basket"),
        ("a bowl of rice", "bowl"),
        ("glass of water", "glass"),
        ("school light microscope", "microscope"),
        ("", ""),
    ],
)
def test_head_noun(query, head):
    assert script.head_noun(query) == head


def test_story_scope_by_row_kind():
    assert script.story_scope("m", "u", "r") == ("module:m", "chapter")
    assert script.story_scope("m", None, "r") == ("module:m", "module story")
    assert script.story_scope(None, "u", "r") == ("unit:u", "chapter")
    assert script.story_scope(None, None, "r") == ("week:r", "hand-authored week")


# -- Counting ---------------------------------------------------------------------


def test_a_prop_counts_once_per_module_whatever_the_chapters_and_plan():
    inventory = script.Inventory()
    for row in _story_rows():
        inventory.add(
            row[6], scope=f"module:{MODULE}", language=row[3], course=COURSE, source="chapter"
        )
    inventory.add(
        _plan_props(), scope=f"module:{MODULE}", language="fr", course=COURSE, source="module plan"
    )

    basket = inventory.by_head["basket"]
    assert basket.modules == 1
    assert basket.languages == {"fr", "en"}
    assert len(basket.scopes) == 2  # one use per language
    assert basket.kind == "sticker"
    assert basket.label_fr and basket.label_en and basket.emoji
    assert inventory.by_query["woven straw basket"].modules == 1
    assert inventory.documents["module plan"] == 1


def test_modules_and_weeks_rank_by_reach():
    inventory = script.Inventory()
    basket = [{"query": "woven straw basket", "kind": "sticker"}]
    snail = [{"query": "garden snail", "kind": "real"}]
    for scope in ("module:a", "module:b", "week:c"):
        inventory.add(basket, scope=scope, language="fr", course=scope, source="chapter")
    inventory.add(snail, scope="module:a", language="fr", course="module:a", source="chapter")
    ranked = inventory.ranked(inventory.by_head)
    assert [t.key for t in ranked] == ["basket", "snail"]
    assert ranked[0].modules == 3 and len(ranked[0].courses) == 3


def test_props_without_a_search_phrase_are_skipped_not_fatal():
    inventory = script.Inventory()
    inventory.add(
        [{"id": "x"}, "junk", {"query": "  "}, {"query": "clay pot"}],
        scope="module:a",
        language="en",
        course=None,
        source="chapter",
    )
    inventory.add(None, scope="module:b", language="en", course=None, source="chapter")
    assert list(inventory.by_head) == ["pot"]
    assert inventory.skipped == 3


# -- Library ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "content",
    [
        ["Pebble_Round_1", "Bucket_Wooden_1"],
        [{"name": "Pebble_Round_1"}, {"name": "Bucket_Wooden_1"}],
        {"packs": {"nature": ["Pebble_Round_1"], "farm": ["Bucket_Wooden_1"]}},
    ],
)
def test_load_library_accepts_its_formats(tmp_path, content):
    path = tmp_path / "names.json"
    path.write_text(json.dumps(content), encoding="utf-8")
    index = script.load_library(str(path))
    assert index["pebble"].endswith("Pebble_Round_1")
    assert index["bucket"].endswith("Bucket_Wooden_1")


def test_load_library_rejects_other_shapes(tmp_path):
    path = tmp_path / "names.json"
    path.write_text(json.dumps({"names": "nope"}), encoding="utf-8")
    with pytest.raises(ValueError):
        script.load_library(str(path))


def test_match_and_hit_rate():
    inventory = script.Inventory()
    inventory.add(
        [
            {"query": "grey river pebble", "kind": "real"},
            {"query": "woven straw basket", "kind": "sticker"},
        ],
        scope="module:a",
        language="fr",
        course="c",
        source="chapter",
    )
    script.match_library(inventory, {"pebble": "nature/Pebble_Round_1"})
    assert inventory.by_head["pebble"].match == "nature/Pebble_Round_1"
    assert inventory.by_query["grey river pebble"].match == "nature/Pebble_Round_1"
    assert inventory.by_head["basket"].match is None
    heads = inventory.by_head.values()
    assert script.hit_rate(heads) == (1, 2)
    assert script.hit_rate(heads, "sticker") == (0, 1)
    assert script.hit_rate(heads, "real") == (1, 1)


def test_the_bundled_candidates_load_and_leave_off_theme_packs_out():
    index = script.load_library(str(_CANDIDATES))
    assert "pebble" in index and "bucket" in index
    packs = json.loads(_CANDIDATES.read_text("utf-8"))["packs"]
    assert not [pack for pack in packs if "scifi" in pack or "gun" in pack or "space" in pack]


def test_the_queries_compile_for_postgresql_and_read_only_the_props():
    from sqlalchemy.dialects import postgresql

    dialect = postgresql.dialect()
    stories = str(script.story_statement(published_only=True).compile(dialect=dialect))
    assert "story_courses.content[" in stories
    assert "LEFT OUTER JOIN modules" in stories
    assert "coalesce(story_courses.course_id, modules.course_id)" in stories
    assert "story_courses.status = " in stories
    assert "WHERE" not in str(script.story_statement(published_only=False).compile(dialect=dialect))
    plans = str(script.plan_statement().compile(dialect=dialect))
    assert "story_module_plans.content[" in plans and "JOIN modules" in plans


# -- main -------------------------------------------------------------------------


async def test_main_prints_both_rankings_with_the_library(capsys, tmp_path):
    plans = [(MODULE, "fr", COURSE, _plan_props())]
    session = FakeSession(_story_rows(), plans, [(COURSE, "biology-101")])
    out_json = tmp_path / "props.json"
    code = await script.main(
        ["--library", str(_CANDIDATES), "--json", str(out_json)], session_factory=lambda: session
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "BY HEAD NOUN (the shopping list)" in out and "BY SEARCH PHRASE" in out
    assert "Library match (sticker props, lexical estimate)" in out
    assert "basket" in out and "pebble" in out
    report = json.loads(out_json.read_text("utf-8"))
    assert report["summary"]["modules_or_weeks"] == 1
    assert report["summary"]["documents"]["module plan"] == 1
    assert report["summary"]["library_hit_rate"]["all"]["total"] > 0
    pebble = next(entry for entry in report["by_head"] if entry["key"] == "pebble")
    assert pebble["library_match"] and "Pebble" in pebble["library_match"]


async def test_published_only_reads_no_plans(capsys):
    session = FakeSession(_story_rows(), [(COURSE, "biology-101")])
    code = await script.main(["--published-only"], session_factory=lambda: session)
    assert code == 0
    assert session.calls == 2  # stories and courses, no plans
    assert "module plan" not in capsys.readouterr().out


async def test_course_filter_by_slug(capsys):
    other = "6f1c1d2e-0000-4000-8000-000000000002"
    rows = _story_rows() + [("w", None, None, "en", other, "draft", [{"query": "red clay brick"}])]
    session = FakeSession(rows, [], [(COURSE, "biology-101"), (other, "masonry")])
    code = await script.main(["--course", "masonry"], session_factory=lambda: session)
    assert code == 0
    out = capsys.readouterr().out
    assert "brick" in out and "basket" not in out


async def test_unknown_course_fails_and_bad_values_are_refused(capsys):
    session = FakeSession([], [], [(COURSE, "biology-101")])
    assert await script.main(["--course", "nope"], session_factory=lambda: session) == 1
    assert await script.main(["--course", "a;rm"], session_factory=lambda: FakeSession()) == 2


# -- Workflow ---------------------------------------------------------------------


def test_the_story_workflow_has_a_read_only_props_mode():
    yaml = pytest.importorskip("yaml")
    if not _WORKFLOW.exists():
        pytest.skip("the workflow is not in this checkout")
    workflow = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
    triggers = workflow.get("on", workflow.get(True))  # YAML 1.1 reads a bare "on" as True
    mode = triggers["workflow_dispatch"]["inputs"]["mode"]
    assert "props" in mode["options"]
    step = next(s for s in workflow["jobs"]["story"]["steps"] if "ssh-action" in s.get("uses", ""))
    command = step["with"]["script"]
    assert "test -f scripts/story_prop_inventory.py" in command
    assert "scripts/story_prop_inventory.py --top 100" in command
    assert "--library scripts/story_prop_candidates.json" in command
