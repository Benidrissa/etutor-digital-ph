"""Story assets (#2709): the course's own pictures in a module story, found by code.

Pure logic first (words, scope, noise, dedupe, numbering, binding), then the
re-binding of the stored story the issue studied (``story_module_closeups_2708``
with the catalogue holding the Shepard figure and the lesson illustration),
the catalogue build against a fake session (the test the issue asks for:
nothing from another course or module ever gets in), the chapter builder's
figure binding, the plan's figure props, and the migration.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import sqlalchemy as sa

from app.api.v1.schemas.story_course import StoryCourse
from app.domain.models.story_asset import StoryAssetCatalogue
from app.domain.services import story_assets as sa_
from app.domain.services.story_module_assembly import validate_module_story
from app.domain.services.story_props import PropBook, figure_of, plan_props

FIXTURE = Path(__file__).parent / "fixtures" / "story_module_closeups_2708.json"

COURSE = "course-shepard"
OTHER_COURSE = "course-other"
MODULE = "90aabd75-ef62-4849-af5a-e883948f4010"
OTHER_MODULE = "11111111-1111-4111-8111-111111111111"
LESSON = "aaaaaaaa-0000-4000-8000-000000000001"
OTHER_LESSON = "aaaaaaaa-0000-4000-8000-000000000002"
UNIT = "bbbbbbbb-0000-4000-8000-000000000001"
SHEPARD = "65bb9ff9-1111-4111-8111-111111111111"
SHEPARD_TWIN = "590809b4-1111-4111-8111-111111111111"
ILLUSTRATION = "22222222-2222-4222-8222-222222222222"
FOREIGN_FIGURE = "33333333-3333-4333-8333-333333333333"
FOREIGN_ILLUSTRATION = "44444444-4444-4444-8444-444444444444"


def story() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text("utf-8"))


def shepard_row(**over: Any) -> dict[str, Any]:
    row = {
        "id": SHEPARD,
        "source": COURSE,
        "figure_number": "Figure 1.2",
        "caption_en": "The Shepard tables illusion",
        "caption_fr": "L'illusion des tables de Shepard",
        "alt_text_en": "Two table tops that look different but are identical",
        "alt_text_fr": "Deux plateaux de tables identiques qui paraissent différents",
        "page_number": 21,
        "image_hash": "abc123",
        "figure_kind": "diagram",
        "width": 800,
        "semantic_tags": {"topics": ["perception"]},
        "resource_title": "Perception.pdf",
    }
    row.update(over)
    return row


def illustration_row(**over: Any) -> dict[str, Any]:
    row = {
        "id": ILLUSTRATION,
        "lesson_id": LESSON,
        "module_id": MODULE,
        "concept": "Shepard tables",
        "title_fr": "Croquis des deux tables",
        "title_en": "Sketch of the two tables",
        "alt_text_en": "Two tables drawn by hand in perspective",
        "alt_text_fr": "Deux tables dessinées à la main en perspective",
    }
    row.update(over)
    return row


def catalogue_entries() -> list[dict[str, Any]]:
    return sa_.assemble(
        [
            sa_.figure_entry(shepard_row(), origin="lesson_ref", unit_id=UNIT),
            sa_.illustration_entry(illustration_row(), unit_id=UNIT),
        ],
        course_source=COURSE,
        lesson_ids=[LESSON],
        module_id=MODULE,
    )


# -- scope and noise -----------------------------------------------------------------


def test_words_fold_stem_and_drop_noise():
    assert sa_.words("L'illusion des Tables de Shepard") == {"illusion", "table", "shepard"}
    assert "the" not in sa_.words("the table")
    assert sa_.words({"fr": "chaise", "en": "chair"}, ["Table"]) == {"chaise", "chair", "table"}


def test_noise_kinds_and_stock_thumbnails_are_never_offered():
    assert not sa_.usable_kind("body_text", 900)
    assert not sa_.usable_kind("decorative", 900)
    assert not sa_.usable_kind("photo", 150)
    assert not sa_.usable_kind("photo", None)
    assert sa_.usable_kind("photo", 600)
    assert sa_.usable_kind(None, None)
    assert sa_.usable_kind("diagram", 90)


def test_a_figure_is_in_the_course_only_by_its_source():
    assert sa_.in_course(COURSE, COURSE)
    assert not sa_.in_course(OTHER_COURSE, COURSE)
    assert not sa_.in_course("anything", None)  # a course with no collection owns none


def test_an_illustration_belongs_to_a_lesson_of_the_module_or_to_the_module():
    scope = {"lesson_ids": [LESSON], "module_id": MODULE}
    assert sa_.illustration_in_scope(illustration_row(), **scope)
    # Drawn for a sibling row of the lesson (its other language): the module is enough.
    assert sa_.illustration_in_scope(
        illustration_row(lesson_id=OTHER_LESSON, module_id=MODULE), **scope
    )
    # Another module's lesson, another module: never ours.
    assert not sa_.illustration_in_scope(
        illustration_row(lesson_id=OTHER_LESSON, module_id=OTHER_MODULE), **scope
    )
    # No module on the row: only one of this story's own lessons brings it in.
    assert sa_.illustration_in_scope(illustration_row(module_id=None), **scope)
    assert not sa_.illustration_in_scope(
        illustration_row(lesson_id=OTHER_LESSON, module_id=None), **scope
    )
    assert sa_.illustration_in_scope(illustration_row(lesson_id=None), **scope)
    assert not sa_.illustration_in_scope(
        illustration_row(lesson_id=None, module_id=OTHER_MODULE), **scope
    )


# -- the catalogue ---------------------------------------------------------------------


def test_no_catalogue_entry_ever_comes_from_another_course_or_module():
    foreign = [
        sa_.figure_entry(
            shepard_row(id=FOREIGN_FIGURE, source=OTHER_COURSE, image_hash="zzz"),
            origin="lesson_ref",  # even a figure a lesson cites
            unit_id=UNIT,
        ),
        sa_.figure_entry(
            shepard_row(id=FOREIGN_FIGURE[:-1] + "5", source=OTHER_COURSE, image_hash="yyy"),
            origin="semantic",
            unit_id=UNIT,
        ),
        sa_.illustration_entry(
            illustration_row(
                id=FOREIGN_ILLUSTRATION, lesson_id=OTHER_LESSON, module_id=OTHER_MODULE
            ),
            unit_id=UNIT,
        ),
        sa_.illustration_entry(
            illustration_row(
                id=FOREIGN_ILLUSTRATION[:-1] + "5", lesson_id=None, module_id=OTHER_MODULE
            ),
            unit_id=None,
        ),
    ]
    entries = sa_.assemble(
        [*foreign, sa_.figure_entry(shepard_row(), origin="lesson_ref", unit_id=UNIT)],
        course_source=COURSE,
        lesson_ids=[LESSON],
        module_id=MODULE,
    )
    assert [e["asset_id"] for e in entries] == [SHEPARD]
    assert not sa_.assemble(foreign, course_source=COURSE, lesson_ids=[LESSON], module_id=MODULE)
    # A course with no collection id has no figure at all.
    assert not sa_.assemble(foreign[:2], course_source=None, lesson_ids=[LESSON], module_id=MODULE)


def test_the_catalogue_drops_noise_and_exclusions_and_dedupes_by_hash():
    twin = shepard_row(id=SHEPARD_TWIN)  # same picture, another row (a re-index)
    entries = sa_.assemble(
        [
            sa_.figure_entry(shepard_row(), origin="lesson_ref", unit_id=UNIT),
            sa_.figure_entry(twin, origin="semantic", unit_id="unit-2"),
            sa_.figure_entry(
                shepard_row(id=FOREIGN_FIGURE, image_hash="t", figure_kind="body_text"),
                origin="lesson_ref",
                unit_id=UNIT,
            ),
            sa_.figure_entry(
                shepard_row(id=FOREIGN_FIGURE[:-1] + "9", image_hash="u"),
                origin="lesson_ref",
                unit_id=UNIT,
            ),
            sa_.illustration_entry(illustration_row(), unit_id=UNIT),
        ],
        course_source=COURSE,
        lesson_ids=[LESSON],
        module_id=MODULE,
        exclusions=[FOREIGN_FIGURE[:-1] + "9"],
    )
    assert [(e["id"], e["asset_id"]) for e in entries] == [("A1", SHEPARD), ("A2", ILLUSTRATION)]
    assert entries[0]["units"] == [UNIT, "unit-2"]
    assert entries[0]["credit"] == "course" and entries[1]["credit"] == "course_illustration"
    assert entries[0]["attribution"] == "Perception, p.21"


def test_the_order_is_pinned_then_origin_then_figures_before_illustrations():
    other = shepard_row(id=SHEPARD_TWIN, image_hash="other", caption_en="Other")
    entries = sa_.assemble(
        [
            sa_.illustration_entry(illustration_row(), unit_id=UNIT),
            sa_.figure_entry(other, origin="semantic", unit_id=UNIT),
            sa_.figure_entry(shepard_row(), origin="lesson_ref", unit_id=UNIT),
        ],
        course_source=COURSE,
        lesson_ids=[LESSON],
        module_id=MODULE,
    )
    assert [e["asset_id"] for e in entries] == [SHEPARD, SHEPARD_TWIN, ILLUSTRATION]
    pinned = sa_.assemble(
        [
            sa_.illustration_entry(illustration_row(), unit_id=UNIT),
            sa_.figure_entry(shepard_row(), origin="lesson_ref", unit_id=UNIT),
        ],
        course_source=COURSE,
        lesson_ids=[LESSON],
        module_id=MODULE,
        pins=[ILLUSTRATION],
    )
    assert pinned[0]["asset_id"] == ILLUSTRATION and pinned[0]["pinned"] is True


def test_figures_for_unit_are_the_units_own_then_the_modules():
    entries = sa_.assemble(
        [
            sa_.figure_entry(shepard_row(), origin="lesson_ref", unit_id=UNIT),
            sa_.illustration_entry(illustration_row(lesson_id=None), unit_id=None),
            sa_.figure_entry(
                shepard_row(id=SHEPARD_TWIN, image_hash="o"), origin="lesson_ref", unit_id="u2"
            ),
        ],
        course_source=COURSE,
        lesson_ids=[],
        module_id=MODULE,
    )
    refs = sa_.figures_for_unit({"entries": entries}, UNIT)
    assert [r["id"] for r in refs] == [SHEPARD, ILLUSTRATION]
    assert refs[1]["generated"] is True and refs[1]["asset_kind"] == "illustration"
    assert sa_.figures_for_unit(None, UNIT) == []


def test_the_gap_report_lists_ideas_with_no_evidence():
    entries = catalogue_entries()
    gaps = sa_.gap_report(
        [
            {
                "unit_id": UNIT,
                "unit_number": "1.1",
                "ideas": ["Shepard tables look different", "Memory fades with sleep debt"],
            }
        ],
        entries,
    )
    assert gaps == [
        {"unit": "1.1", "idea": 2, "text": "Memory fades with sleep debt", "evidence": "none"}
    ]


# -- binding --------------------------------------------------------------------------------


def test_each_picture_serves_one_prop_and_a_prop_takes_one_picture():
    props = story()["props"]
    bound = sa_.bind_props(props, catalogue_entries())
    assert {pid: e["asset_id"] for pid, e in bound.items()} == {
        "poster": SHEPARD,
        "table_drawing": ILLUSTRATION,
    }
    # Already bound, or a sticker: never rebound.
    assert sa_.bind_props(props, catalogue_entries(), taken=[SHEPARD, ILLUSTRATION]) == {}
    assert sa_.bind_props([p for p in props if not p["educational"]], catalogue_entries()) == {}


# -- re-binding the stored story -----------------------------------------------------------------


def line_index(doc: dict[str, Any], needle: str) -> tuple[int, int, int]:
    for c, chapter in enumerate(doc["chapters"]):
        for s, scene in enumerate(chapter["scenes"]):
            for i, step in enumerate(scene["steps"]):
                if needle in str(step.get("fr")):
                    return c, s, i
    raise AssertionError(needle)


def shows_of(doc: dict[str, Any], pid: str) -> list[tuple[int, int, int]]:
    return [
        (c, s, i)
        for c, chapter in enumerate(doc["chapters"])
        for s, scene in enumerate(chapter["scenes"])
        for i, step in enumerate(scene["steps"])
        if step.get("visual") == "prop" and step["params"]["prop"] == pid
    ]


def test_rebinding_the_studied_story_shows_the_shepard_figure_before_regardez():
    original = story()
    doc = copy.deepcopy(original)
    result = sa_.rebind_document(doc, catalogue_entries())

    assert result.changed and result.bound == {"poster": SHEPARD, "table_drawing": ILLUSTRATION}
    props = {p["id"]: p for p in doc["props"]}
    assert props["poster"]["kind"] == "figure"
    assert props["poster"]["figure"]["source_image_id"] == SHEPARD
    assert props["poster"]["figure"]["figure_number"] == "Figure 1.2"
    # The lesson illustration is a figure prop of its own kind of id.
    assert props["table_drawing"]["figure"] == {
        "generated_image_id": ILLUSTRATION,
        "caption": {"en": "Sketch of the two tables", "fr": "Croquis des deux tables"},
        "alt": {
            "en": "Two tables drawn by hand in perspective",
            "fr": "Deux tables dessinées à la main en perspective",
        },
    }
    # The poster's close-up comes before « Regardez ! », in chapter 1 scene 1.
    (c, s, i), look = shows_of(doc, "poster")[0], line_index(doc, "Regardez")
    assert (c, s) == look[:2] == (0, 0) and i < look[2]
    assert shows_of(doc, "table_drawing")[0][0] == 0  # the illustration: a chapter 1 close-up
    # Still a valid story, now with figures.
    report = validate_module_story(doc)
    assert not report.errors and report.checks.props["figures"] == 2
    assert doc["module_story"]["revision"] != original["module_story"]["revision"]
    StoryCourse.model_validate(doc)


def test_a_story_whose_closeup_is_missing_gets_it_before_the_look_line():
    doc = story()
    for scene in doc["chapters"][0]["scenes"]:
        scene["steps"] = [
            st
            for st in scene["steps"]
            if not (st.get("visual") == "prop" and st["params"]["prop"] == "poster")
        ]
    result = sa_.rebind_document(doc, catalogue_entries())
    assert result.inserted == [{"chapter": "ch1", "scene": "s1", "prop": "poster"}]
    (c, s, i) = shows_of(doc, "poster")[0]
    assert (c, s) == (0, 0) and i < line_index(doc, "Regardez")[2]
    assert validate_module_story(doc).errors == []


def test_a_closeup_after_the_look_line_is_moved_up():
    doc = story()
    steps = doc["chapters"][0]["scenes"][0]["steps"]
    show = next(
        st for st in steps if st.get("visual") == "prop" and st["params"]["prop"] == "poster"
    )
    steps.remove(show)
    steps.insert(line_index(doc, "Regardez")[2] + 1, show)
    result = sa_.rebind_document(doc, catalogue_entries())
    assert "poster" in [m["prop"] for m in result.moved]
    assert shows_of(doc, "poster")[0][2] < line_index(doc, "Regardez")[2]


def test_rebinding_is_idempotent():
    doc = story()
    sa_.rebind_document(doc, catalogue_entries())
    once = copy.deepcopy(doc)
    again = sa_.rebind_document(doc, catalogue_entries())
    assert not again.changed and doc == once


def test_rebinding_is_reversible():
    original = story()
    doc = copy.deepcopy(original)
    sa_.rebind_document(doc, catalogue_entries())
    assert sa_.revert_document(doc)
    assert doc == original
    assert not sa_.revert_document(doc)  # nothing left to undo
    # Reversible after an insertion and a move too.
    moved = story()
    steps = moved["chapters"][0]["scenes"][0]["steps"]
    show = next(
        st for st in steps if st.get("visual") == "prop" and st["params"]["prop"] == "poster"
    )
    steps.remove(show)
    steps.insert(line_index(moved, "Regardez")[2] + 1, show)
    before = copy.deepcopy(moved)
    sa_.rebind_document(moved, catalogue_entries())
    sa_.revert_document(moved)
    assert moved == before
    gone = story()
    for scene in gone["chapters"][0]["scenes"]:
        scene["steps"] = [
            st
            for st in scene["steps"]
            if not (st.get("visual") == "prop" and st["params"]["prop"] == "poster")
        ]
    before = copy.deepcopy(gone)
    sa_.rebind_document(gone, catalogue_entries())
    sa_.revert_document(gone)
    assert gone == before


def test_the_persisted_binding_survives_a_remerge():
    """A re-merge starts from the chapters again: the saved binding gives the same story."""
    first = story()
    result = sa_.rebind_document(first, catalogue_entries())
    saved = dict(result.bound)
    remerged = story()  # what the assembler makes again from the chapters
    again = sa_.rebind_document(remerged, catalogue_entries(), binding=saved)
    assert again.bound == saved and remerged == first


def test_the_persisted_binding_wins_over_the_words():
    entries = catalogue_entries()
    doc = story()
    # An admin bound the illustration to the poster.
    sa_.rebind_document(doc, entries, binding={"poster": ILLUSTRATION})
    props = {p["id"]: p for p in doc["props"]}
    assert props["poster"]["figure"]["generated_image_id"] == ILLUSTRATION
    # The Shepard figure shares one word only with the sketch: it is left as it was.
    assert "figure" not in props["table_drawing"]


def test_nothing_is_bound_without_enough_shared_words():
    doc = story()
    entries = sa_.assemble(
        [
            sa_.figure_entry(
                shepard_row(
                    caption_en="Kidney anatomy",
                    caption_fr="Anatomie du rein",
                    alt_text_en="",
                    alt_text_fr="",
                    semantic_tags=None,
                ),
                origin="lesson_ref",
                unit_id=UNIT,
            )
        ],
        course_source=COURSE,
        lesson_ids=[],
        module_id=MODULE,
    )
    before = copy.deepcopy(doc)
    result = sa_.rebind_document(doc, entries)
    assert not result.changed and doc == before


# -- the rebind script -----------------------------------------------------------------------------

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "rebind_story_assets.py"
_spec = importlib.util.spec_from_file_location("rebind_story_assets", _SCRIPT)
script = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = script
_spec.loader.exec_module(script)


def catalogue(**over: Any) -> dict[str, Any]:
    base = {"source": COURSE, "entries": catalogue_entries(), "binding": {}}
    base.update(over)
    return base


def test_process_story_reports_and_is_idempotent():
    first = script.process_story(story(), catalogue())
    assert first["changed"] and not first["skipped"]
    assert first["figures_before"] == 0 and first["figures_after"] == 2
    assert first["errors_after"] <= first["errors_before"]
    assert first["revision_before"] != first["revision_after"]
    second = script.process_story(first["doc"], catalogue(binding=first["bound"]))
    assert not second["changed"] and second["doc"] == first["doc"]
    reverted = script.process_story(first["doc"], catalogue(), revert=True)
    assert reverted["changed"] and reverted["doc"]["props"] == story()["props"]
    text = script.render(
        [{"module_id": MODULE, "language": "fr", **first}], applied=False, revert=False
    )
    assert "DRY RUN" in text and "prop poster <- asset" in text and "model calls: 0" in text


def test_process_story_never_binds_a_picture_of_another_course():
    entries = catalogue_entries()
    entries[0]["source"] = OTHER_COURSE  # a corrupted catalogue
    outcome = script.process_story(story(), catalogue(entries=entries))
    assert SHEPARD not in outcome["bound"].values()
    assert outcome["bound"].get("poster") == ILLUSTRATION or "poster" not in outcome["bound"]


def test_the_script_is_a_dry_run_that_writes_nothing():
    args = script.parse_args(["--module", MODULE])
    assert not args.apply and not args.revert and not args.build_catalogue
    with pytest.raises(SystemExit):
        script.parse_args([])  # a module or --all is required


# -- the catalogue build (a fake session) ------------------------------------------------------------


class _Rows:
    def scalars(self):
        return []


class _Session:
    async def execute(self, *_a, **_k):
        return _Rows()


class _Storage:
    def __init__(self, dead=()):
        self.dead, self.calls = set(dead), []

    async def object_exists(self, key):
        self.calls.append(key)
        return key not in self.dead


class _Retriever:
    def __init__(self, linked=None, found=None):
        self.linked, self.found, self.searches = linked or {}, found or [], []

    async def get_linked_images(self, chunk_ids, session, **_kw):
        return self.linked

    async def search_source_images(self, query, **kw):
        self.searches.append((query, kw))
        return self.found


def unit() -> dict[str, Any]:
    return {
        "unit_id": UNIT,
        "unit_number": "1.1",
        "title": {"en": "The Shepard tables", "fr": "Les tables de Shepard"},
        "lesson_id": LESSON,
        "content": {
            "concepts": ["The Shepard tables look different but are identical"],
            "key_points": ["The brain misjudges size"],
            "source_image_refs": [{"id": SHEPARD}, {"id": FOREIGN_FIGURE}],
        },
    }


@pytest.fixture
def rows(monkeypatch):
    table = {
        SHEPARD: {**shepard_row(), "storage_key": "k/shepard"},
        FOREIGN_FIGURE: {
            **shepard_row(id=FOREIGN_FIGURE, source=OTHER_COURSE, image_hash="zzz"),
            "storage_key": "k/foreign",
        },
        SHEPARD_TWIN: {
            **shepard_row(id=SHEPARD_TWIN, image_hash="twin", caption_en="Shepard table height"),
            "storage_key": "k/twin",
        },
    }

    async def source_rows(_session, ids):
        return {str(i): table[str(i)] for i in ids if str(i) in table}

    async def illustrations(_session, _module_id, _units):
        return [
            sa_.illustration_entry(illustration_row(), unit_id=UNIT),
            sa_.illustration_entry(
                illustration_row(
                    id=FOREIGN_ILLUSTRATION, lesson_id=OTHER_LESSON, module_id=OTHER_MODULE
                ),
                unit_id=UNIT,
            ),
        ]

    monkeypatch.setattr(sa_, "_source_rows", source_rows)
    monkeypatch.setattr(sa_, "_illustration_candidates", illustrations)
    return table


async def test_build_catalogue_keeps_only_this_courses_pictures(rows):
    retriever = _Retriever(
        linked={"chunk": [{"id": FOREIGN_FIGURE}]},
        found=[{"id": FOREIGN_FIGURE}, {"id": SHEPARD_TWIN}],
    )
    built = await sa_.build_catalogue(
        _Session(),
        module_id=MODULE,
        course_source=COURSE,
        course_id=None,
        units=[unit()],
        storage=_Storage(),
        retriever=retriever,
    )
    ids = [e["asset_id"] for e in built["entries"]]
    assert FOREIGN_FIGURE not in ids and FOREIGN_ILLUSTRATION not in ids
    assert ids == [SHEPARD, SHEPARD_TWIN, ILLUSTRATION]
    assert built["source"] == COURSE
    # The search was scoped to the course, filtered like get_linked_images, never wider.
    ((query, kwargs),) = retriever.searches
    assert kwargs["source"] == COURSE and kwargs["exclude_noise"] is True
    assert kwargs["min_similarity"] == sa_.MIN_SIMILARITY
    assert "Shepard" in query


async def test_a_figure_found_by_search_needs_a_word_in_common_with_the_lesson(rows):
    rows[SHEPARD_TWIN].update(
        caption_en="Kidney anatomy",
        caption_fr="Anatomie du rein",
        alt_text_en="",
        alt_text_fr="",
        semantic_tags=None,
    )
    built = await sa_.build_catalogue(
        _Session(),
        module_id=MODULE,
        course_source=COURSE,
        course_id=None,
        units=[unit()],
        storage=_Storage(),
        retriever=_Retriever(found=[{"id": SHEPARD_TWIN}]),
    )
    assert SHEPARD_TWIN not in [e["asset_id"] for e in built["entries"]]


async def test_a_dead_binary_is_left_out_and_a_checked_one_is_not_checked_twice(rows):
    storage = _Storage(dead={"k/shepard"})
    built = await sa_.build_catalogue(
        _Session(),
        module_id=MODULE,
        course_source=COURSE,
        course_id=None,
        units=[unit(), {**unit(), "unit_id": "u2"}],
        storage=storage,
        retriever=None,
    )
    assert SHEPARD not in [e["asset_id"] for e in built["entries"]]
    assert storage.calls.count("k/shepard") == sa_.CHECK_TRIES


async def test_pins_exclusions_and_the_binding_are_carried_over_and_gaps_reported(rows):
    built = await sa_.build_catalogue(
        _Session(),
        module_id=MODULE,
        course_source=COURSE,
        course_id=None,
        units=[unit()],
        storage=_Storage(),
        retriever=None,
        previous={"exclusions": [ILLUSTRATION], "pins": [], "binding": {"poster": SHEPARD}},
    )
    assert [e["asset_id"] for e in built["entries"]] == [SHEPARD]
    assert built["exclusions"] == [ILLUSTRATION] and built["binding"] == {"poster": SHEPARD}
    assert {g["evidence"] for g in built["gaps"]} <= {"none"}


# -- the chapter builder and the plan -------------------------------------------------------------------


def book(figures: list[dict[str, Any]], props: list[dict[str, Any]]) -> tuple[PropBook, list]:
    issues: list = []
    return (
        PropBook(
            props,
            known=[],
            figures=figures,
            cast_ids=["hero"],
            issue=lambda *a: issues.append(a),
        ),
        issues,
    )


def scenes_about(pid: str) -> list[dict[str, Any]]:
    return [
        {
            "id": "s1",
            "cast": ["hero"],
            "steps": [
                {"type": "narrate", "en": "A poster hangs.", "fr": "Une affiche.", "props": [pid]},
                {"type": "say", "who": "hero", "en": "Look!", "fr": "Regardez !", "props": [pid]},
                {"type": "narrate", "en": "Later.", "fr": "Plus tard.", "props": []},
            ],
        }
    ]


def test_the_chapter_builder_binds_an_educational_prop_to_a_figure_and_shows_it():
    figures = [sa_.ref_of(e) for e in catalogue_entries()]
    props = [
        {
            "id": "poster",
            "label": {"en": "the table poster", "fr": "l'affiche des tables"},
            "query": "Shepard table illusion poster",
            "kind": "real",
            "at": "back",
        }
    ]
    prop_book, _ = book(figures, props)
    scenes = scenes_about("poster")
    out = prop_book.finish(scenes, module_count=1)
    (prop,) = out
    assert prop["kind"] == "figure" and prop["figure"]["source_image_id"] == SHEPARD
    assert prop["educational"] is True
    assert any(st.get("visual") == "prop" for st in scenes[0]["steps"])


def test_a_prop_that_shares_no_words_with_a_figure_stays_what_it_was():
    figures = [sa_.ref_of(e) for e in catalogue_entries()]
    props = [
        {
            "id": "basket",
            "label": {"en": "the old basket", "fr": "le vieux panier"},
            "query": "wicker basket",
            "kind": "real",
        }
    ]
    prop_book, _ = book(figures, props)
    out = prop_book.finish(scenes_about("basket"), module_count=1)
    assert out[0]["kind"] == "real" and "figure" not in out[0]


def test_figure_of_tells_a_lesson_illustration_from_a_course_figure():
    illustration = sa_.ref_of(catalogue_entries()[1])
    assert figure_of(illustration)["generated_image_id"] == ILLUSTRATION
    assert "source_image_id" not in figure_of(illustration)
    assert figure_of(sa_.ref_of(catalogue_entries()[0]))["source_image_id"] == SHEPARD


def test_a_plan_prop_standing_for_a_catalogue_figure_carries_it():
    plan = {
        "props": [
            {
                "id": "poster",
                "label": {"en": "the poster", "fr": "l'affiche"},
                "query": "Shepard poster",
                "kind": "figure",
                "figure": "A1",
            },
            {
                "id": "ghost",
                "label": {"en": "the ghost", "fr": "le fantôme"},
                "query": "ghost",
                "kind": "figure",
                "figure": "A9",
            },
        ]
    }
    cat = {"entries": catalogue_entries()}
    props = {p["id"]: p for p in plan_props(plan, cat)}
    assert (
        props["poster"]["kind"] == "figure"
        and props["poster"]["figure"]["source_image_id"] == SHEPARD
    )
    assert props["ghost"]["kind"] == "real" and "figure" not in props["ghost"]
    assert {p["id"]: p["kind"] for p in plan_props(plan)} == {"poster": "real", "ghost": "real"}


def test_the_plan_prompt_lists_the_catalogue_and_allows_the_figure_kind():
    from app.ai.prompts.story_plan import build_plan_user_message
    from app.domain.services.story_plan import _plan_prop_kind

    block = sa_.plan_figures_block({"entries": catalogue_entries()})
    assert (
        "FIGURE A1 [figure]: The Shepard tables illusion | L'illusion des tables de Shepard"
        in block
    )
    assert "FIGURE A2 [illustration]" in block
    assert sa_.plan_figures_block(None) == ""
    assert _plan_prop_kind({"kind": "figure", "figure": "A1"}) == "figure"
    assert _plan_prop_kind({"kind": "figure", "figure": "see above"}) == "real"
    assert _plan_prop_kind({"kind": "photo"}) == "real"
    assert callable(build_plan_user_message)


def test_the_chapter_prompt_tells_an_illustration_from_a_figure():
    from app.ai.prompts.story_from_lesson import _figure_lines

    refs = [sa_.ref_of(e) for e in catalogue_entries()]
    lines = _figure_lines(SimpleNamespace(figure_refs=lambda: refs)).splitlines()
    assert lines[1].startswith("FIGURE 1 [diagram]") and lines[2].startswith(
        "FIGURE 2 [illustration]"
    )


def test_a_show_step_names_a_lesson_illustration_by_its_own_key():
    from app.domain.services import story_repair as repair

    refs = [sa_.ref_of(e) for e in catalogue_entries()]
    ctx = SimpleNamespace(figure_refs=lambda: refs)
    step = repair._figure_step(ctx, {"type": "show", "figure": 2})
    assert step["params"]["generated_image_id"] == ILLUSTRATION
    assert "source_image_id" not in step["params"]
    assert (
        repair._figure_step(ctx, {"type": "show", "figure": 1})["params"]["source_image_id"]
        == SHEPARD
    )


# -- the contract and the migration ------------------------------------------------------------------------


def test_a_figure_prop_needs_one_of_the_two_image_ids():
    doc = story()
    prop = next(p for p in doc["props"] if p["id"] == "poster")
    prop["kind"], prop["figure"] = "figure", {"generated_image_id": ILLUSTRATION}
    assert not [
        e
        for e in validate_module_story(copy.deepcopy(doc)).errors
        if e.code == "prop_figure_missing"
    ]
    prop["figure"] = {"figure_number": "1"}
    assert [e.code for e in validate_module_story(copy.deepcopy(doc)).errors] == [
        "prop_figure_missing"
    ]


MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "versions"
    / "113_story_asset_catalogues.py"
)


class _RecordingOp:
    def __init__(self):
        self.tables: dict[str, list[Any]] = {}

    def create_table(self, name, *elements, **_kw):
        self.tables[name] = list(elements)

    def drop_table(self, name):
        self.tables.pop(name, None)


def test_the_migration_matches_the_model_and_chains_after_112():
    spec = importlib.util.spec_from_file_location("migration_113", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    recorder = _RecordingOp()
    module.op = recorder
    module.upgrade()
    assert module.revision == "113_story_asset_catalogues" and len(module.revision) <= 32
    assert module.down_revision == "112_story_prop_library"
    table = StoryAssetCatalogue.__table__
    columns = {e.name: e for e in recorder.tables[table.name] if isinstance(e, sa.Column)}
    assert set(columns) == {c.name for c in table.columns}
    dialect = sa.dialects.postgresql.dialect()
    for name, column in columns.items():
        assert column.nullable == table.columns[name].nullable, name
        assert column.primary_key == table.columns[name].primary_key, name
        assert column.type.compile(dialect=dialect) == table.columns[name].type.compile(
            dialect=dialect
        )
    module.downgrade()
    assert table.name not in recorder.tables


# -- the service: a re-merge binds the saved catalogue ------------------------------------------------------


async def test_a_remerge_binds_the_saved_catalogue_and_saves_the_binding(monkeypatch):
    from app.domain.services import story_module_service as service

    saved: dict[str, Any] = {}

    async def load(_session, _module_id):
        return {"entries": catalogue_entries(), "binding": {}}

    async def save(_session, _module_id, content):
        saved.update(content)

    monkeypatch.setattr(service, "load_catalogue", load)
    monkeypatch.setattr(service, "save_catalogue", save)
    doc = story()
    await service._bind_catalogue(_Savepoint(), MODULE, doc)
    assert doc["checks"] == story()["checks"]  # validation is the caller's
    assert saved["binding"] == {"poster": SHEPARD, "table_drawing": ILLUSTRATION}
    assert {p["id"] for p in doc["props"] if p["kind"] == "figure"} == {"poster", "table_drawing"}


async def test_a_catalogue_that_cannot_be_read_never_fails_the_merge(monkeypatch):
    from app.domain.services import story_module_service as service

    async def broken(_session, _module_id):
        raise RuntimeError("relation does not exist")

    monkeypatch.setattr(service, "load_catalogue", broken)
    doc = story()
    await service._bind_catalogue(_Savepoint(), MODULE, doc)
    assert doc == story()


async def test_without_figure_storage_the_catalogue_is_not_built():
    from app.domain.services.story_module_service import ModuleStoryService

    svc = ModuleStoryService(None, None, None)
    assert await svc._build_catalogue(SimpleNamespace(), None, []) is None


# -- a failing catalogue never poisons the caller's transaction -------------------------------------------------


class _Savepoint:
    """A session that records its savepoints and whether anything rolled back the whole."""

    def __init__(self):
        self.entered = self.failed = 0
        self.rolled_back = False

    def begin_nested(self):
        outer = self

        class _Ctx:
            async def __aenter__(self):
                outer.entered += 1

            async def __aexit__(self, exc_type, *_):
                outer.failed += exc_type is not None
                return False  # the error goes on to the caller's except

        return _Ctx()

    async def rollback(self):
        self.rolled_back = True


async def test_the_binding_reads_and_writes_inside_a_savepoint(monkeypatch):
    from app.domain.services import story_module_service as service

    async def broken(_session, _module_id):
        raise RuntimeError('relation "story_asset_catalogues" does not exist')

    monkeypatch.setattr(service, "load_catalogue", broken)
    session, doc = _Savepoint(), story()
    await service._bind_catalogue(session, MODULE, doc)
    assert (session.entered, session.failed, session.rolled_back) == (1, 1, False)
    assert doc == story()


async def test_the_catalogue_build_fails_inside_a_savepoint_and_never_rolls_back_the_session(
    monkeypatch,
):
    from app.domain.services import story_module_service as service

    async def broken(*_a, **_k):
        raise RuntimeError('relation "story_asset_catalogues" does not exist')

    monkeypatch.setattr(service, "load_catalogue", broken)

    class _Run:
        course_id = None
        module_id = MODULE
        lesson_rows: dict = {}

    svc = service.ModuleStoryService(None, None, None, figure_storage=_Storage())
    session = _Savepoint()
    assert await svc._build_catalogue(_Run(), session, []) is None
    assert (session.entered, session.failed, session.rolled_back) == (1, 1, False)


# --------------------------------------------------------------------------
# Imports made inside functions (found on staging: a wrong module path only
# fails when the function runs, and the fakes above never ran that line)
# --------------------------------------------------------------------------


def test_every_import_made_inside_a_function_resolves():
    import ast
    import importlib
    from pathlib import Path

    backend = Path(__file__).resolve().parent.parent
    for relative in ("app/domain/services/story_assets.py", "scripts/rebind_story_assets.py"):
        tree = ast.parse((backend / relative).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module or node.level:
                continue
            module = importlib.import_module(node.module)
            for alias in node.names:
                assert hasattr(module, alias.name), f"{relative}: {node.module}.{alias.name}"


# -- conservative binding (staging dry run) ----------------------------------------------------------------------


def _prop(pid, fr, en, query, educational=True):
    return {
        "id": pid,
        "label": {"fr": fr, "en": en},
        "query": query,
        "kind": "real" if educational else "sticker",
        "educational": educational,
    }


def _figure(asset, caption, *, page=5, **over):
    row = shepard_row(
        id=asset,
        image_hash=asset,
        caption_en=caption,
        caption_fr=caption,
        caption=caption,
        alt_text_en="",
        alt_text_fr="",
        semantic_tags=None,
        page_number=page,
        figure_number=None,
    )
    row.update(over)
    return sa_.figure_entry(row, origin="semantic", unit_id=UNIT)


def _illustration(asset, fr, en):
    return sa_.illustration_entry(
        illustration_row(id=asset, title_fr=fr, title_en=en, alt_text_en="", alt_text_fr=""),
        unit_id=UNIT,
    )


def _uid(n):
    return f"00000000-0000-4000-8000-{n:012d}"


STAGING_ASSETS = {
    "shepard": _figure(_uid(1), "Illusion créée par le psychologue Roger Shepard."),
    "atoms": _figure(
        _uid(2),
        "Les atomes sont constitués de protons et de neutrons situés dans le noyau, et d'électrons.",
    ),
    "lactic": _figure(_uid(3), "La fermentation lactique est courante dans les muscles."),
    "induced_fit": _figure(
        _uid(4), "Le modèle de l'ajustement induit de l'enzyme : clé et serrure."
    ),
    "detective": _illustration(
        _uid(5),
        "Le détective inconscient : comment le cerveau construit un modèle mental",
        "The unconscious detective: how the brain builds a mental model",
    ),
    "pyruvate": _figure(_uid(6), "Le pyruvate est converti en acétyl-CoA."),
    "levels": _illustration(
        _uid(7), "Propriétés et niveaux du vivant", "Properties and levels of life"
    ),
    "water": _illustration(
        _uid(8), "Cycle de l'eau et nécessité de la vie", "Water cycle and life necessity"
    ),
    "biomolecules": _illustration(
        _uid(9), "Quatre biomolécules essentielles", "Four essential biomolecules of life"
    ),
    "signs": _illustration(
        _uid(10), "Huit signes des organismes vivants", "Eight signs of living organisms"
    ),
    "signs_things": _figure(_uid(11), "Eight signs of living things"),
    "organised": _figure(_uid(12), "Vie organisée en niveaux"),
    "three": _figure(_uid(13), "Ces exemples montrent trois molécules."),
    "taxonomy": _figure(
        _uid(14), "Les niveaux de la hiérarchie taxonomique pour un chien et un chat."
    ),
    "skills": _figure(
        _uid(15), "Les compétences dont les entrepreneurs disposent pour résoudre des problèmes."
    ),
}

STAGING_PROPS = [
    _prop(
        "poster",
        "l'affiche des tables",
        "the table poster",
        "Shepard table illusion hand drawn poster",
    ),
    _prop(
        "atom_diagram",
        "le schéma de l'atome",
        "the atom diagram",
        "simple atom diagram nucleus electrons hand drawn",
    ),
    _prop(
        "lactic_acid_label",
        "l'étiquette d'acide lactique",
        "the lactic acid label",
        "lactic acid label muscle hand drawn",
    ),
    _prop(
        "enzyme_card",
        "la fiche de l'enzyme",
        "the enzyme card",
        "hand drawn enzyme diagram card paper",
    ),
    _prop(
        "mental_schema",
        "le schéma mental",
        "the mental schema",
        "index card filing cabinet brain concept illustration",
    ),
    _prop(
        "atp_synthase_model",
        "le modèle de l'ATP synthase",
        "the ATP synthase model",
        "ATP synthase rotating protein model diagram",
    ),
    _prop(
        "crumpled_diagram",
        "le schéma froissé",
        "the crumpled diagram",
        "crumpled hand-drawn paper diagram",
    ),
    _prop(
        "stained_diagram",
        "le schéma taché",
        "the stained diagram",
        "crumpled stained hand drawn diagram",
    ),
    _prop(
        "courtyard_tap",
        "le robinet de la cour",
        "the courtyard tap",
        "outdoor concrete water tap Africa",
    ),
    _prop(
        "friend_notebook",
        "le cahier de l'ami",
        "the friend's notebook",
        "child notebook pencil diagrams",
    ),
    _prop("vial_three", "la fiole trois", "vial three", "clear sugar syrup glass vial"),
    _prop("mystery_vials", "les fioles mystères", "the mystery vials", "mystery glass vials sugar"),
    _prop("mango_tree", "le manguier", "the mango tree", "mango tree school courtyard Africa"),
    _prop("termite_mound", "la termitière", "the termite mound", "termite mound Africa"),
    _prop("agama_lizard", "le margouillat", "the agama lizard", "agama lizard wall"),
    _prop(
        "levels_ladder",
        "l'échelle des niveaux",
        "the levels ladder",
        "levels of biological organization diagram ladder",
    ),
    _prop(
        "problem_list",
        "la liste des problèmes",
        "the problem list",
        "hand drawn list crossings paper",
    ),
]

GOOD = {
    "poster": "shepard",
    "atom_diagram": "atoms",
    "lactic_acid_label": "lactic",
    "enzyme_card": "induced_fit",
    "mental_schema": "detective",
}


def _catalogue(assets):
    return sa_.assemble(
        list(assets.values()), course_source=COURSE, lesson_ids=[LESSON], module_id=MODULE
    )


def test_the_staging_dry_run_binds_the_five_good_props_and_none_of_the_wrong_ones():
    entries = _catalogue(STAGING_ASSETS)
    ids = {key: STAGING_ASSETS[key]["asset_id"] for key in STAGING_ASSETS}
    evidence: dict = {}
    bound = sa_.bind_props(STAGING_PROPS, entries, evidence=evidence)
    assert {pid: e["asset_id"] for pid, e in bound.items()} == {
        pid: ids[key] for pid, key in GOOD.items()
    }
    # Every binding says why: a score, the shared words, the prop and the caption.
    assert set(evidence) == set(GOOD)
    assert evidence["poster"]["score"] >= 2 and set(evidence["poster"]["words"]) >= {
        "shepard",
        "illusion",
    }
    assert evidence["poster"]["prop"] == "l'affiche des tables"
    assert evidence["poster"]["caption"].startswith("Illusion créée")
    assert evidence["enzyme_card"]["words"] == ["enzym"]  # one word: head noun, rare, in the query


@pytest.mark.parametrize("pid", [p["id"] for p in STAGING_PROPS if p["id"] not in GOOD])
def test_a_wrong_prop_is_never_bound(pid):
    bound = sa_.bind_props(STAGING_PROPS, _catalogue(STAGING_ASSETS))
    assert pid not in bound


def test_a_decor_prop_never_binds_even_on_a_strong_match():
    decor = _prop(
        "poster", "l'affiche des tables", "the table poster", "Shepard table illusion", False
    )
    assert sa_.bind_props([decor], _catalogue(STAGING_ASSETS)) == {}


def test_alt_text_and_tags_do_not_count_as_evidence():
    entry = _figure(
        _uid(40),
        "Une illustration",
        alt_text_en="Shepard table illusion",
        alt_text_fr="Illusion des tables de Shepard",
        semantic_tags={"topics": ["shepard", "illusion", "table"]},
    )
    assert (
        sa_.bind_props(
            STAGING_PROPS[:1],
            sa_.assemble([entry], course_source=COURSE, lesson_ids=[], module_id=MODULE),
        )
        == {}
    )


def test_two_different_props_tied_for_one_picture_bind_neither():
    rival = _prop(
        "banner",
        "la banderole de l'illusion de Shepard",
        "the Shepard illusion banner",
        "Shepard table illusion banner",
    )
    entries = _catalogue({"shepard": STAGING_ASSETS["shepard"]})
    assert sa_.bind_props([STAGING_PROPS[0], rival], entries) == {}


def test_the_same_object_declared_in_two_chapters_shares_its_picture():
    # Staging: chapter 1 declares ``poster`` and the rally ``poster_2``, same
    # name in both languages. They are one object, not two rivals.
    first = STAGING_PROPS[0]
    twin = {**first, "id": "poster_2"}
    entries = _catalogue({"shepard": STAGING_ASSETS["shepard"]})
    evidence: dict = {}
    bound = sa_.bind_props([first, twin], entries, evidence=evidence)
    assert set(bound) == {"poster", "poster_2"}
    assert bound["poster"]["asset_id"] == bound["poster_2"]["asset_id"]
    assert evidence["poster_2"] == evidence["poster"]


def test_the_minimum_score_can_be_raised():
    entries = _catalogue(STAGING_ASSETS)
    assert "poster" in sa_.bind_props(STAGING_PROPS, entries, min_score=2)
    # The poster shares 2 words with its caption: asking for 3 binds none of the 2-word ones.
    assert "poster" not in sa_.bind_props(STAGING_PROPS, entries, min_score=3)


# -- page captures, twins, credits --------------------------------------------------------------------------------

CAPTURE = "590809b4-1111-4111-8111-111111111111"
CAPTURE_TWIN = "65bb9ff9-2222-4222-8222-222222222222"
STUDIED_ILLUSTRATION = "f9430732-3333-4333-8333-333333333333"


def _studied_entries():
    caption = "Illusion créée par le psychologue Roger Shepard."
    page = dict(
        source=COURSE,
        page_number=21,
        figure_number="Figure 1",
        caption_en=caption,
        caption_fr=caption,
        alt_text_en="",
        alt_text_fr="",
        semantic_tags=None,
    )
    return sa_.assemble(
        [
            sa_.figure_entry(
                shepard_row(
                    id=CAPTURE,
                    image_hash="aaa",
                    figure_kind="complex_diagram",
                    width=1024,
                    height=1627,
                    **page,
                ),
                origin="lesson_ref",
                unit_id=UNIT,
            ),
            sa_.figure_entry(
                shepard_row(
                    id=CAPTURE_TWIN,
                    image_hash="bbb",
                    figure_kind="photo",
                    width=284,
                    height=200,
                    **page,
                ),
                origin="lesson_ref",
                unit_id=UNIT,
            ),
            _illustration(
                STUDIED_ILLUSTRATION,
                "L'illusion des tables de Shepard",
                "The Shepard tables illusion",
            ),
        ],
        course_source=COURSE,
        lesson_ids=[LESSON],
        module_id=MODULE,
    )


def test_the_same_page_figure_under_two_hashes_is_one_entry_flagged_as_a_page_capture():
    entries = _studied_entries()
    assert [e["asset_id"] for e in entries] == [CAPTURE, STUDIED_ILLUSTRATION]
    assert entries[0]["page_capture"] is True and "page_capture" not in entries[1]
    assert entries[0]["page"] == 21


def test_a_page_capture_ranks_after_the_lesson_illustration_that_matches_as_strongly():
    entries = _studied_entries()
    poster = STAGING_PROPS[0]
    bound = sa_.bind_props([poster], entries)
    assert bound["poster"]["asset_id"] == STUDIED_ILLUSTRATION
    # With only the page capture, the poster may still use it (nothing better).
    assert sa_.bind_props([poster], entries[:1])["poster"]["asset_id"] == CAPTURE
    # A cropped figure of the same strength still comes first.
    cropped = sa_.figure_entry(
        shepard_row(
            id=SHEPARD,
            image_hash="ccc",
            caption_en="Shepard table illusion",
            caption_fr="Illusion des tables de Shepard",
            page_number=22,
            width=600,
            height=400,
        ),
        origin="lesson_ref",
        unit_id=UNIT,
    )
    both = sa_.assemble(
        [cropped, *_studied_entries()], course_source=COURSE, lesson_ids=[LESSON], module_id=MODULE
    )
    assert sa_.bind_props([poster], both)["poster"]["asset_id"] == SHEPARD


def test_page_like_dimensions_make_a_page_capture():
    assert sa_.is_page_capture("complex_diagram", 300, 200)
    assert sa_.is_page_capture("diagram", 800, 1000) and not sa_.is_page_capture(
        "diagram", 800, 999
    )
    assert not sa_.is_page_capture("diagram", 700, 1600) and not sa_.is_page_capture(
        "photo", None, None
    )


def test_a_catalogue_figure_asks_for_the_original_picture():
    ref = sa_.ref_of(_studied_entries()[0])
    assert figure_of(ref)["original"] is True
    assert "original" not in figure_of(sa_.ref_of(_studied_entries()[1]))


def test_a_raw_file_name_becomes_a_readable_credit():
    raw = "Mindware__Tools_for_Smart_Thinking_Nisbett__Richard_E_2015_Edition_Complete.pdf"
    human = sa_.human_source(raw)
    assert "_" not in human and ".pdf" not in human and len(human) <= 61
    assert human.startswith("Mindware Tools for Smart Thinking")
    assert not human[:-1].endswith(" ")
    entry = sa_.figure_entry(
        shepard_row(attribution=None, resource_title=raw), origin="lesson_ref", unit_id=UNIT
    )
    assert entry["attribution"].endswith(", p.21") and "_" not in entry["attribution"]
    assert sa_.human_source("OpenStax, CC BY 4.0") == "OpenStax, CC BY 4.0"


def test_the_rebind_report_puts_the_prop_and_its_caption_side_by_side():
    outcome = script.process_story(story(), catalogue(entries=_studied_entries()))
    text = script.render(
        [{"module_id": MODULE, "language": "fr", **outcome}], applied=False, revert=False
    )
    assert (
        "l'affiche des tables" in text
        and "L'illusion des tables de Shepard" in text
        and "score" in text
    )
    none = script.process_story(story(), catalogue(entries=_studied_entries()), min_score=9)
    assert not none["bound"]
