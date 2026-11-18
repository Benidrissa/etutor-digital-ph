"""Repointing lesson figure refs whose source_images row was deleted (#2707).

Pure logic only: how a replacement is chosen, and how a lesson document is
rewritten. The database walk around it is a thin loop over these.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from app.domain.services.figure_ref_repair import (
    AMBIGUOUS,
    BY_CAPTION,
    BY_FIGURE_NUMBER,
    BY_HASH,
    NO_CANDIDATE,
    Figure,
    Repoint,
    figure_of_ref,
    find_replacement,
    normalise,
    plan_row,
    referenced_ids,
    rewrite_content,
)

OLD_A = "39fe5905-2447-48a0-97c9-9719101462e7"
OLD_B = "8ad97376-ffc4-41e1-a525-dfd4b674ea25"
NEW_PHOTO = "65bb9ff9-1ba2-43f6-8cb3-23fc51fc5135"
NEW_DIAGRAM = "590809b4-6216-4431-9951-888e4bf4488b"
SHEPARD = "Illusion created by the psychologist Roger Shepard."


def _live(
    id_: str,
    *,
    caption: str | None = SHEPARD,
    number: str = "Figure 1",
    kind: str | None = "photo",
    image_type: str = "photo",
    page: int = 21,
    image_hash: str | None = "aaaa",
    order: str = "",
) -> Figure:
    return Figure(
        id=id_,
        figure_number=normalise(number),
        captions=frozenset({normalise(caption)} if caption else set()),
        image_type=image_type,
        figure_kind=kind,
        page_number=page,
        image_hash=image_hash,
        order=order or id_,
    )


def _ref(id_: str, *, caption: str | None = SHEPARD, number: str | None = "Figure 1") -> dict:
    return {
        "id": id_,
        "figure_number": number,
        "caption": caption,
        "caption_fr": "Illusion créée par le psychologue Roger Shepard." if caption else None,
        "caption_en": caption,
        "image_type": "photo",
    }


# The staging case: lesson 1.1 names two deleted rows; the figure was
# re-created as a photo and a complex_diagram with the same bytes.
SHEPARD_LIVE = [
    _live(NEW_PHOTO, order="2026-07-08T15:29:25"),
    _live(NEW_DIAGRAM, kind="complex_diagram", order="2026-07-08T15:29:45"),
]


def test_a_ref_is_matched_by_caption_and_figure_number():
    found, how = find_replacement(figure_of_ref(_ref(OLD_A)), SHEPARD_LIVE)
    assert found.id == NEW_PHOTO
    assert how == BY_CAPTION


def test_caption_matching_ignores_case_spacing_and_the_final_dot():
    ref = _ref(OLD_A, caption="  illusion created by the  Psychologist Roger Shepard ")
    found, _ = find_replacement(figure_of_ref(ref), SHEPARD_LIVE)
    assert found.id == NEW_PHOTO


def test_the_french_caption_alone_is_enough():
    live = [
        Figure(
            id=NEW_PHOTO,
            figure_number="figure 1",
            captions=frozenset({normalise("Illusion créée par le psychologue Roger Shepard.")}),
        )
    ]
    ref = {"id": OLD_A, "caption_fr": "Illusion créée par le psychologue Roger Shepard."}
    found, how = find_replacement(figure_of_ref(ref), live)
    assert (found.id, how) == (NEW_PHOTO, BY_CAPTION)


def test_a_different_figure_number_is_not_the_same_figure():
    live = [_live(NEW_PHOTO, number="Figure 7")]
    found, how = find_replacement(figure_of_ref(_ref(OLD_A)), live)
    assert found is None
    assert how == NO_CANDIDATE


def test_a_caption_that_matches_nothing_never_falls_back_to_the_number():
    live = [_live(NEW_PHOTO, caption="Distribution of IQ scores.")]
    found, how = find_replacement(figure_of_ref(_ref(OLD_A)), live)
    assert found is None
    assert how == NO_CANDIDATE


def test_text_crops_and_decoration_are_never_a_replacement():
    live = [_live(NEW_PHOTO, kind="body_text"), _live(NEW_DIAGRAM, kind="decorative")]
    found, how = find_replacement(figure_of_ref(_ref(OLD_A)), live)
    assert found is None
    assert how == NO_CANDIDATE


def test_without_a_caption_a_number_naming_one_picture_is_accepted():
    ref = figure_of_ref(_ref(OLD_A, caption=None))
    found, how = find_replacement(ref, SHEPARD_LIVE)  # two rows, one hash
    assert (found.id, how) == (NEW_PHOTO, BY_FIGURE_NUMBER)


def test_without_a_caption_a_number_naming_two_pictures_is_ambiguous():
    live = [
        _live(NEW_PHOTO, image_hash="aaaa", page=21),
        _live(NEW_DIAGRAM, image_hash="bbbb", page=90),
    ]
    found, how = find_replacement(figure_of_ref(_ref(OLD_A, caption=None)), live)
    assert found is None
    assert how == AMBIGUOUS


def test_copies_without_a_hash_are_not_assumed_to_be_one_picture():
    live = [_live(NEW_PHOTO, image_hash=None), _live(NEW_DIAGRAM, image_hash=None)]
    found, how = find_replacement(figure_of_ref(_ref(OLD_A, caption=None)), live)
    assert (found, how) == (None, AMBIGUOUS)


def test_a_snapshot_of_the_deleted_row_matches_by_picture_first():
    removed = _live(OLD_A, caption=None, number="", image_hash="bbbb", page=90)
    live = [_live(NEW_PHOTO, image_hash="aaaa"), _live(NEW_DIAGRAM, image_hash="bbbb", page=90)]
    found, how = find_replacement(Figure(id=OLD_A), live, removed=removed)
    assert (found.id, how) == (NEW_DIAGRAM, BY_HASH)


def test_a_snapshot_page_settles_a_repeated_figure_number():
    removed = _live(OLD_A, caption=None, image_hash=None, page=90)
    live = [
        _live(NEW_PHOTO, image_hash="aaaa", page=21),
        _live(NEW_DIAGRAM, image_hash="bbbb", page=90),
    ]
    found, how = find_replacement(figure_of_ref(_ref(OLD_A, caption=None)), live, removed=removed)
    assert (found.id, how) == (NEW_DIAGRAM, BY_FIGURE_NUMBER)


def test_a_marker_with_no_ref_and_no_snapshot_is_left_alone():
    found, how = find_replacement(Figure(id=OLD_A), SHEPARD_LIVE)
    assert (found, how) == (None, NO_CANDIDATE)


def test_ids_are_read_from_refs_and_from_markers_once_each():
    content = {
        "concepts": f"Look: {{{{source_image:{OLD_A.upper()}}}}} and {{{{source_image:{OLD_B}}}}}",
        "source_image_refs": [_ref(OLD_A)],
    }
    assert referenced_ids(content) == [OLD_A, OLD_B]
    assert referenced_ids({"concepts": "no figure"}) == []
    assert referenced_ids(None) == []


def test_two_refs_to_copies_of_a_figure_keep_naming_two_rows():
    content = {"source_image_refs": [_ref(OLD_A), _ref(OLD_B)]}
    repair = plan_row("row", content, {OLD_A, OLD_B}, SHEPARD_LIVE)
    assert [(r.old, r.new) for r in repair.repoints] == [(OLD_A, NEW_PHOTO), (OLD_B, NEW_DIAGRAM)]
    assert repair.unmatched == []


def test_only_dangling_ids_are_planned_and_unmatched_ones_are_reported():
    alive = "11111111-1111-4111-8111-111111111111"
    content = {"source_image_refs": [_ref(alive), _ref(OLD_A), _ref(OLD_B, caption="Unknown")]}
    repair = plan_row("row", content, {OLD_A, OLD_B}, SHEPARD_LIVE)
    assert [(r.old, r.new) for r in repair.repoints] == [(OLD_A, NEW_PHOTO)]
    assert repair.unmatched == [(OLD_B, NO_CANDIDATE)]


def test_a_course_resolves_one_old_id_the_same_way_in_every_row():
    resolved: dict[str, Repoint] = {}
    fr = plan_row(
        "fr", {"source_image_refs": [_ref(OLD_A)]}, {OLD_A}, SHEPARD_LIVE, resolved=resolved
    )
    # The English row names the same deleted row, with no caption this time.
    en = plan_row(
        "en",
        {"source_image_refs": [_ref(OLD_A, caption=None, number=None)]},
        {OLD_A},
        [],
        resolved=resolved,
    )
    assert fr.repoints == en.repoints == [Repoint(OLD_A, NEW_PHOTO, BY_CAPTION)]


def test_rewriting_replaces_refs_and_markers_and_keeps_everything_else():
    content = {
        "introduction": f"See {{{{source_image:{OLD_A}}}}} first.",
        "concepts": [{"body": f"Again {{{{source_image:{OLD_A.upper()}}}}}."}],
        "unit_id": "1.1",
        "source_image_refs": [_ref(OLD_A)],
    }
    rewritten = rewrite_content(content, [Repoint(OLD_A, NEW_PHOTO, BY_CAPTION)])
    assert rewritten["introduction"] == f"See {{{{source_image:{NEW_PHOTO}}}}} first."
    assert rewritten["concepts"][0]["body"] == f"Again {{{{source_image:{NEW_PHOTO}}}}}."
    assert rewritten["source_image_refs"][0]["id"] == NEW_PHOTO
    assert rewritten["source_image_refs"][0]["caption"] == SHEPARD
    assert rewritten["unit_id"] == "1.1"
    assert content["source_image_refs"][0]["id"] == OLD_A  # the input is not changed


def test_two_refs_that_now_name_one_row_are_merged():
    content = {"source_image_refs": [_ref(OLD_A), _ref(OLD_B)]}
    rewritten = rewrite_content(
        content, [Repoint(OLD_A, NEW_PHOTO, BY_CAPTION), Repoint(OLD_B, NEW_PHOTO, BY_CAPTION)]
    )
    assert [ref["id"] for ref in rewritten["source_image_refs"]] == [NEW_PHOTO]


def test_no_repoint_returns_the_document_untouched():
    content = {"source_image_refs": [_ref(OLD_A)]}
    assert rewrite_content(content, []) is content


# --------------------------------------------------------------------------
# The script's report
# --------------------------------------------------------------------------

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "repair_dangling_figure_refs.py"
_spec = importlib.util.spec_from_file_location("repair_dangling_figure_refs", _SCRIPT)
script = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = script
_spec.loader.exec_module(script)


def test_the_script_is_a_dry_run_unless_told_to_apply():
    assert script.parse_args([]).apply is False
    assert script.parse_args(["--apply"]).apply is True
    assert script.parse_args([]).let_stories_regenerate is False


def test_the_report_counts_methods_and_reasons():
    from app.domain.services.figure_ref_repair import RepairReport, RowRepair

    report = RepairReport(
        course_id="c1",
        rows=[
            RowRepair(
                content_id="row",
                repoints=[Repoint(OLD_A, NEW_PHOTO, BY_CAPTION)],
                unmatched=[(OLD_B, AMBIGUOUS)],
            )
        ],
    )
    totals = script.summarise([report, RepairReport(course_id="c2")])
    assert totals["courses_with_dangling_refs"] == 1
    assert totals["repointed_by"] == {BY_CAPTION: 1}
    assert totals["unmatched_because"] == {AMBIGUOUS: 1}
    text = script.render([report], applied=False)
    assert "DRY RUN" in text
    assert f"{OLD_A} -> {NEW_PHOTO}" in text


# --------------------------------------------------------------------------
# The hook the indexation tasks call
# --------------------------------------------------------------------------


async def test_a_failed_repair_never_fails_the_indexation(monkeypatch):
    from app.domain.services import figure_ref_repair
    from app.infrastructure.persistence import database

    def broken_factory():
        raise RuntimeError("database is away")

    monkeypatch.setattr(database, "async_session_factory", broken_factory)
    report = await figure_ref_repair.heal_after_reindex("9caf0bc2-19b4-47cf-ab55-99033396ab80")
    assert report is None


def test_both_reindex_paths_snapshot_then_heal():
    """The two tasks that delete figure rows remember them and repoint afterwards."""
    tasks = Path(__file__).resolve().parent.parent / "app" / "tasks"
    for name in ("image_indexation.py", "rag_indexation.py"):
        source = (tasks / name).read_text(encoding="utf-8")
        assert "snapshot_figures" in source, name
        assert "heal_after_reindex(course_id, removed_figures)" in source, name
        assert source.index("snapshot_figures(") < source.index("heal_after_reindex("), name
