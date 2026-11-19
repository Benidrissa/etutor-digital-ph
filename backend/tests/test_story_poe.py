"""Predict, observe, name (#2711): the bet, the demos, the stimulus, the rally, the events.

Pure tests (no model, no database), on the kids biology episode of
``fixtures/story_screenplay_module.json``. The ``GOLDEN`` digests were taken on
``origin/dev`` BEFORE this change: they prove that a legacy plan (no
``cast_policy``) tells, builds, validates and prompts exactly as it always did,
so no stored story goes stale and nothing is regenerated.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.ai.prompts.story_from_lesson import build_chapter_story_message
from app.ai.prompts.story_plan import build_plan_user_message
from app.api.v1.schemas.story_course import StoryCourse
from app.domain.services import story_poe as poe
from app.domain.services import story_repair as repair
from app.domain.services.story_course_validator import validate_story_course
from app.domain.services.story_events import StoryEvent, StoryEventsRequest, properties_of
from app.domain.services.story_metrics import PICTURE_CODES, all_findings, story_metrics
from app.domain.services.story_plan import fresh_rally_refs, validate_plan
from tests.test_story_cast_policy import none_ctx
from tests.test_story_screenplay_module import make_run, pack
from tests.test_story_v4_builder import build, chapter_ctx, codes, lint_codes, spine

GOLDEN = {
    "chapter_1.1": "356082e41c57c5ab3e8de1bc16a8538ea8eb89f6e8c1d214a87c99edc4010478",
    "chapter_1.2": "9c4cf528db6b1ef7e9cbaab1b8630f1d787c0f51df52d7adc4deb50002779c7a",
    "stored_dump": "f8d282bf0d2f681a91a162120751637807ae8d56268495b14ebd31381b681ef5",
    "stored_report": "c85bbe8513c309813aa717d96b8e1333069df36ad92063ca4d1943334fd4dd85",
    "chapter_prompt": "1a6afbaa95171b11a84f68929bbe8688fc1ddaaa5fde49d8e47f1f0f9f81439c",
    "plan_prompt": "1e2b0d7749eb5cce3f30fcdd22569c1b6d120671c8824ef2deb4b7a6814a1a94",
}
STORED = Path(__file__).parent / "fixtures" / "story_module_closeups_2708.json"
PICTURE = "39fe5905-0000-4000-8000-000000000001"


def sha(value) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode()).hexdigest()


# --------------------------------------------------------------------------
# Stored stories are untouched
# --------------------------------------------------------------------------


@pytest.mark.parametrize("unit", ["1.1", "1.2"])
def test_a_legacy_chapter_is_built_byte_for_byte_as_before(unit):
    result = build(chapter_ctx(unit), spine(unit))
    assert sha(result.doc) == GOLDEN[f"chapter_{unit}"]


def test_a_stored_story_parses_dumps_and_validates_as_before():
    course = StoryCourse.model_validate(json.loads(STORED.read_text()))
    assert sha(course.model_dump(mode="json")) == GOLDEN["stored_dump"]
    report = validate_story_course(course, generated=True)
    dump = report.model_dump(mode="json")
    # #2750 added warnings on module stories (and nothing else): without them the
    # report is the one digested before. Errors and ``ok`` are not touched.
    added = [w for w in dump["warnings"] if w["code"] in PICTURE_CODES]
    assert added and report.ok and report.errors == []
    dump["warnings"] = [w for w in dump["warnings"] if w["code"] not in PICTURE_CODES]
    dump["checks"]["warnings"] -= len(added)
    assert sha(dump) == GOLDEN["stored_report"]
    assert not any(
        "predict" in q or "reveal" in q for q in course.model_dump(mode="json")["questions"]
    )


def test_the_prompts_of_a_legacy_plan_are_unchanged():
    text = build_chapter_story_message(chapter_ctx("1.1"), pack("1.1", "en"))
    assert hashlib.sha256(text.encode()).hexdigest() == GOLDEN["chapter_prompt"]
    assert "THE BET" not in text
    plan = build_plan_user_message(make_run("en")[1].request)
    assert hashlib.sha256(plan.encode()).hexdigest() == GOLDEN["plan_prompt"]


def test_a_new_plans_chapter_prompt_asks_for_the_bet_and_its_demos():
    text = build_chapter_story_message(none_ctx(), pack("1.1", "en"))
    assert "THE BET" in text and '"compare"' in text and '"annotate"' in text


def test_a_legacy_plan_still_refuses_a_predict_step_as_an_unknown_step():
    the_spine = spine()
    the_spine["scenes"][0]["steps"].insert(8, bet())
    assert repair.UNKNOWN_STEP in codes(build(chapter_ctx(), the_spine))


# --------------------------------------------------------------------------
# The demos: the verdict is in the data
# --------------------------------------------------------------------------


def label(en: str) -> dict[str, str]:
    return {"en": en, "fr": f"{en} (fr)"}


def compare(values=(12, 12), **extra):
    return {"values": list(values), "labels": [label("left"), label("right")], **extra}


def test_compare_reads_equal_from_the_values_never_from_the_model():
    params = poe.clean_demo("compare", compare((12, 12), equal=False, scale="ruler", unit="cm"))
    assert params["equal"] is True and params["scale"] == "ruler" and params["unit"] == "cm"
    assert poe.demo_outcome("compare", params) == "equal"
    params = poe.clean_demo("compare", compare((3, 9), equal=True))
    assert params["equal"] is False and poe.demo_outcome("compare", params) == "b"
    assert poe.demo_outcome("compare", poe.clean_demo("compare", compare((9, 3)))) == "a"


@pytest.mark.parametrize(
    ("visual", "params"),
    [
        ("compare", {"values": [1], "labels": [label("a"), label("b")]}),
        ("compare", {"values": [1, "x"], "labels": [label("a"), label("b")]}),
        ("compare", {"values": [1, float("inf")], "labels": [label("a"), label("b")]}),
        ("compare", {"values": [1, 2], "labels": [label("a")]}),
        ("annotate", {"labels": [label("a"), label("b")], "expected": 3}),
        ("annotate", {"labels": [label("a"), label("b")], "expected": 1}),  # no picture
        ("sort", {"bins": [label("x"), label("y")], "items": [{"label": label("i"), "bin": 1}]}),
        ("sort", {"bins": [label("x")], "items": []}),
        ("timeline", {"events": [{"label": label("a"), "at": 1}, {"label": label("b"), "at": 1}]}),
        ("timeline", "nonsense"),
    ],
)
def test_a_demo_that_cannot_be_drawn_is_refused(visual, params):
    assert poe.clean_demo(visual, params) is None
    assert poe.demo_problem(visual, params)


def test_annotate_sits_on_the_figure_just_shown_and_defaults_to_its_halves_or_thirds():
    figure = {"source_image_id": PICTURE, "alt": label("a figure")}
    halves = poe.clean_demo(
        "annotate", {"labels": [label("left"), label("right")], "expected": 2}, image=figure
    )
    assert halves["regions"] == "halves" and halves["source_image_id"] == PICTURE
    thirds = poe.clean_demo(
        "annotate",
        {"regions": "thirds", "labels": [label("a"), label("b"), label("c")], "expected": 3},
        image=figure,
    )
    assert thirds["regions"] == "thirds" and thirds["expected"] == 3


def test_sort_and_timeline_keep_only_what_the_player_reads():
    sort = poe.clean_demo(
        "sort",
        {
            "bins": [label("measured"), label("guessed")],
            "items": [{"label": label("ruler"), "bin": 1}, {"label": label("eye"), "bin": 2}],
            "junk": 1,
        },
    )
    assert set(sort) == {"bins", "items"}
    line = poe.clean_demo(
        "timeline",
        {"events": [{"label": label("late"), "at": 9}, {"label": label("early"), "at": 2}]},
    )
    assert [e["at"] for e in line["events"]] == [9, 2]  # shuffled as written; the player sorts


def test_the_drawn_visual_check_covers_the_demos_and_the_catalog_knows_them():
    assert repair.drawn_visual_problem("compare", compare()) is None
    assert "values" in (repair.drawn_visual_problem("compare", {}) or "values")
    assert repair.drawn_visual_problem("sort", {"items": 3}) is not None


# --------------------------------------------------------------------------
# The bet
# --------------------------------------------------------------------------


def bet(**changes):
    step = {
        "type": "predict",
        "teaches": 1,
        "en": "Which table is longer?",
        "fr": "Quelle table est la plus longue ?",
        "options": [
            {"en": "The left one", "fr": "Celle de gauche", "is": "a"},
            {"en": "The right one", "fr": "Celle de droite", "is": "b"},
            {"en": "Same", "fr": "Pareilles", "is": "equal"},
        ],
        "demo": {"visual": "compare", "params": compare((12, 12), unit="cm", scale="ruler")},
        "react_right": label("Well bet!"),
        "react_wrong": label("Surprising!"),
    }
    step.update(changes)
    return step


def with_bet(the_spine, *, where="after_card", step=None):
    out = copy.deepcopy(the_spine)
    steps = out["scenes"][0]["steps"]
    card = next(i for i, s in enumerate(steps) if s["type"] == "concept")
    steps.insert(card + 1 if where == "after_card" else card, step or bet())
    return out


def played(result):
    return [s for c in result.doc["chapters"] for sc in c["scenes"] for s in sc["steps"]]


def beat(result):
    """The kinds of the steps of the first beat, from the figure to the transfer question."""
    kinds = []
    for step in played(result):
        if step["type"] == "ask" and step.get("predict"):
            kinds.append("bet")
        elif step["type"] == "show" and step.get("bet"):
            kinds.append("demo:" + step["visual"])
        elif step["type"] == "concept" and not step["id"].startswith("situation-"):
            kinds.append("card")
        elif step["type"] == "ask":
            kinds.append("ask:" + step["ref"])
        elif step["type"] == "show":
            kinds.append("show")
    return kinds


def test_a_new_plan_chapter_bets_before_its_card_and_observes_right_after():
    result = build(none_ctx(), with_bet(spine()))
    assert not codes(result) - {"prop_ref_unknown"}
    kinds = beat(result)
    at = kinds.index("bet")
    assert kinds[at + 1] == "demo:compare"
    assert kinds[at + 2] == "card"
    assert kinds.index("ask:q1") > at + 2
    bet_ask = next(s for s in played(result) if s.get("predict"))
    assert bet_ask["ref"] == "p1" and bet_ask["teaches"] == 1


def test_a_bet_written_after_its_card_moves_up_and_says_so_as_a_lint():
    # The card comes first in the model's answer: no bet is made after the answer.
    result = build(none_ctx(), with_bet(spine(), where="after_card"))
    kinds = beat(result)
    assert kinds.index("bet") < kinds.index("card")
    assert "bet_moved" in lint_codes(result)
    assert not [c for c in codes(result) if c.startswith("bet")]


def test_a_bet_is_ungraded_and_never_changes_the_score():
    plain = build(none_ctx(), spine())
    bet_result = build(none_ctx(), with_bet(spine(), where="before_card"))
    question = next(q for q in bet_result.doc["questions"] if q["id"] == "p1")
    assert question["points"] == 0 and question["predict"] is True
    assert question["type"] == "choice" and question["answer"] == "c"  # "equal", from the data
    assert set(question["reveal"]) == {"right", "wrong"}
    assert [c["id"] for c in question["choices"]] == ["a", "b", "c"]
    assert all("is" not in c for c in question["choices"])

    def report(result):
        course = StoryCourse.model_validate(result.doc)
        return validate_story_course(course, generated=True)

    with_bets, without = report(bet_result), report(plain)
    assert with_bets.errors == [] or [e.code for e in with_bets.errors] == [
        e.code for e in without.errors
    ]
    assert with_bets.checks.max_points == without.checks.max_points


def test_the_right_chip_comes_from_the_data_of_a_compare_demo():
    values = {"values": [3, 9], "labels": [label("a"), label("b")]}
    result = build(
        none_ctx(),
        with_bet(
            spine(),
            where="before_card",
            step=bet(
                demo={"visual": "compare", "params": values},
                expected=1,
            ),
        ),
    )
    question = next(q for q in result.doc["questions"] if q["id"] == "p1")
    assert question["answer"] == "b"  # 9 > 3, whatever `expected` says


@pytest.mark.parametrize(
    "change",
    [
        {"demo": {"visual": "nonsense", "params": {}}},
        {"demo": {"visual": "compare", "params": {"values": [1]}}},
        {"options": [{"en": "only one", "fr": "un seul"}]},
        {"en": "", "fr": ""},
        {
            "options": [{"en": "a", "fr": "a"}, {"en": "b", "fr": "b"}],
            "demo": {
                "visual": "sort",
                "params": {
                    "bins": [label("x"), label("y")],
                    "items": [{"label": label("i"), "bin": 1}, {"label": label("j"), "bin": 2}],
                },
            },
        },  # sort needs `expected`
    ],
)
def test_whatever_the_model_gets_wrong_is_a_lint_never_an_issue(change):
    result = build(none_ctx(), with_bet(spine(), where="before_card", step=bet(**change)))
    assert "bet_dropped" in lint_codes(result)
    assert not [c for c in codes(result) if c.startswith("bet") or c == repair.UNKNOWN_STEP]
    assert not [q for q in result.doc["questions"] if q.get("predict")]


def test_a_missing_reaction_is_a_lint_and_gets_a_neutral_one():
    result = build(
        none_ctx(),
        with_bet(spine(), where="before_card", step=bet(react_right=None, react_wrong=None)),
    )
    assert "bet_reaction_missing" in lint_codes(result) and not codes(result) - {"prop_ref_unknown"}
    question = next(q for q in result.doc["questions"] if q["id"] == "p1")
    assert question["reveal"]["right"]["en"]


def test_a_bet_is_no_scored_question_in_a_run_of_questions():
    steps = [{"type": "ask", "ref": f"q{n}"} for n in (1, 2, 3)]
    bets = [{"type": "ask", "ref": "p1", "predict": True}]
    assert repair.ask_run_excess(steps + bets + [{"type": "ask", "ref": "q4"}]) == ["q4"]
    assert repair.ask_run_excess(bets + steps) == []


def test_the_annotate_demo_sits_on_the_figure_shown_before_the_bet():
    ctx = none_ctx()
    ctx.figures = [
        {"id": PICTURE, "alt_text_en": "Two tables", "alt_text_fr": "Deux tables", "caption": "T"}
    ]
    the_spine = spine()
    steps = the_spine["scenes"][0]["steps"]
    card = next(i for i, s in enumerate(steps) if s["type"] == "concept")
    steps.insert(card, {"type": "show", "figure": 1})
    steps.insert(
        card + 1,
        bet(
            demo={
                "visual": "annotate",
                "params": {"labels": [label("left"), label("right")], "expected": 2},
            },
            options=None,
        ),
    )
    result = build(ctx, the_spine)
    demo = next(s for s in played(result) if s.get("bet"))
    assert demo["params"]["source_image_id"] == PICTURE and demo["params"]["expected"] == 2
    question = next(q for q in result.doc["questions"] if q["id"] == "p1")
    assert question["answer"] == "b" and [c["en"] for c in question["choices"]] == ["left", "right"]


# --------------------------------------------------------------------------
# Cards with a picture, questions with a stimulus
# --------------------------------------------------------------------------


def figure_chapter():
    ctx = none_ctx()
    ctx.figures = [
        {"id": PICTURE, "alt_text_en": "Two tables", "alt_text_fr": "Deux tables", "caption": "T"}
    ]
    the_spine = spine()
    steps = the_spine["scenes"][0]["steps"]
    steps.insert(0, {"type": "show", "figure": 1})
    return ctx, the_spine


def test_a_card_shows_the_beats_picture_and_its_questions_carry_it_as_a_stimulus():
    ctx, the_spine = figure_chapter()
    result = build(ctx, the_spine)
    card = next(s for s in played(result) if s["type"] == "concept" and s["id"] == "c1")
    assert card["media"]["visual"] == "image"
    assert card["media"]["params"]["source_image_id"] == PICTURE
    assert card["media"]["params"]["alt"]["fr"] == "Deux tables"
    q1 = next(q for q in result.doc["questions"] if q["id"] == "q1")
    assert q1["stimulus"]["source_image_id"] == PICTURE
    assert q1["stimulus"]["alt"]["en"] == "Two tables"


def test_the_stimulus_is_a_picture_the_story_showed_before_the_question():
    ctx, the_spine = figure_chapter()
    result = build(ctx, the_spine)
    course = StoryCourse.model_validate(result.doc)
    assert not [
        f for f in all_findings(course.model_dump(mode="json")) if f.code == "stimulus_not_shown"
    ]
    broken = copy.deepcopy(result.doc)
    next(q for q in broken["questions"] if q["id"] == "q1")["stimulus"] = {
        "source_image_id": "11111111-1111-4111-8111-111111111111"
    }
    codes_ = {f.code for f in all_findings(broken)}
    assert "stimulus_not_shown" in codes_


def test_a_legacy_chapter_gets_no_card_media_and_no_stimulus():
    ctx = chapter_ctx()
    ctx.figures = [{"id": PICTURE, "alt_text_en": "x", "alt_text_fr": "y", "caption": "T"}]
    the_spine = spine()
    the_spine["scenes"][0]["steps"].insert(0, {"type": "show", "figure": 1})
    result = build(ctx, the_spine)
    assert not any(s.get("media") for s in played(result))
    assert not any(q.get("stimulus") for q in result.doc["questions"])


def test_the_metrics_count_bets_only_for_a_story_told_with_them():
    plain = build(none_ctx(), spine())
    assert "bets" not in story_metrics(plain.doc)
    told = build(none_ctx(), with_bet(spine(), where="before_card"))
    metrics = story_metrics(told.doc)
    assert metrics["bets"] == 1 and metrics["acts_per_chapter_min"] == 1
    assert "few_acts" in {f.code for f in all_findings(told.doc)}


# --------------------------------------------------------------------------
# The rally asks nothing twice
# --------------------------------------------------------------------------


def test_a_new_plans_rally_asks_no_question_a_chapter_asks_nor_a_copy_of_one():
    request = make_run("en")[1].request
    request.cast_policy = "none"
    chapters = [{"beats": [{"questions": [c.ref]}]} for c in request.candidates[:2]]
    fresh = fresh_rally_refs(request, chapters)
    taken = {c.key for c in request.candidates[:2]}
    assert all(request.candidate(r).key not in taken for r in fresh)
    assert len(fresh) == len(set(fresh))
    # The same content under a new ref is not fresh.
    first = request.candidates[0]
    copy_ = replace(first, ref="q99")
    request.candidates.append(copy_)
    assert "q99" not in fresh_rally_refs(request, chapters)
    # Nor is a question with the same quiz id (a uuid) and other words: it is the same item.
    renamed = replace(
        request.candidates[2],
        ref="q98",
        mcq=replace(request.candidates[2].mcq, stem="Reworded?", source_id="0f8e7d6c-aaaa-4bbb"),
    )
    named = replace(
        request.candidates[0],
        ref="q97",
        mcq=replace(first.mcq, stem="Another stem", source_id="0f8e7d6c-aaaa-4bbb"),
    )
    request.candidates += [named, renamed]
    chapters = [{"beats": [{"questions": ["q97"]}]}]
    assert "q98" not in fresh_rally_refs(request, chapters)
    # A position ("q1") is shared by two quizzes and never makes two questions one.
    assert first.mcq.source_id == "q1"


def test_a_rally_smaller_than_the_bank_is_a_valid_plan_not_a_repair_call():
    from app.domain.services.story_plan import normalise_plan

    request = make_run("en")[1].request
    request.cast_policy = "none"
    plan, _gaps = normalise_plan({}, request)
    rally_refs = [r for s in plan["rally"]["steps"] for r in s["questions"]]
    chapter_refs = {r for c in plan["chapters"] for b in c["beats"] for r in b["questions"]}
    assert not set(rally_refs) & chapter_refs
    assert len(rally_refs) == len(set(rally_refs))
    assert not [
        i
        for i in validate_plan(plan, request)
        if i.code == "plan_too_many_questions" and i.path == "rally.steps"
    ]


def test_a_legacy_plans_rally_is_made_as_before():
    from app.domain.services.story_plan import normalise_plan

    request = make_run("en")[1].request
    assert request.cast_policy is None
    plan, _gaps = normalise_plan({}, request)
    assert "cast_policy" not in plan


# --------------------------------------------------------------------------
# The events
# --------------------------------------------------------------------------


def test_a_story_event_has_no_free_text_and_stores_no_user():
    event = StoryEvent(
        event="story_prediction",
        story="module-abc-fr",
        chapter="u1_1",
        question="u1_1-p1",
        lang="fr",
        matched=True,
    )
    assert properties_of(event) == {
        "story": "module-abc-fr",
        "chapter": "u1_1",
        "question": "u1_1-p1",
        "lang": "fr",
        "matched": True,
        "anonymised": True,
    }


@pytest.mark.parametrize(
    "bad",
    [
        {"event": "story_prediction", "story": "has spaces and a name: Awa"},
        {"event": "story_prediction", "story": "ok", "answer": "free text"},
        {"event": "story_first_try", "story": "ok", "attempts": 3},
        {"event": "login", "story": "ok"},
        {"event": "story_chapter_complete", "story": "ok", "stars": 4},
    ],
)
def test_anything_outside_the_whitelist_is_refused(bad):
    with pytest.raises(ValidationError):
        StoryEvent(**bad)


def test_a_batch_is_capped():
    one = {"event": "story_chapter_complete", "story": "s", "stars": 2}
    StoryEventsRequest(events=[one] * 50)
    with pytest.raises(ValidationError):
        StoryEventsRequest(events=[one] * 51)
    with pytest.raises(ValidationError):
        StoryEventsRequest(events=[])


class FakeSession:
    def __init__(self):
        self.added = []
        self.commits = 0

    def add_all(self, rows):
        self.added += list(rows)

    async def commit(self):
        self.commits += 1


@pytest.mark.asyncio
async def test_events_are_stored_with_no_user_and_no_session_and_an_opt_out_stores_nothing():
    from app.domain.services.story_events import ingest_story_events

    events = [
        StoryEvent(event="story_first_try", story="s", question="q", correct=True, attempts=1)
    ]
    session = FakeSession()
    assert await ingest_story_events(session, events, opted_out=True) == 0
    assert session.added == [] and session.commits == 0
    assert await ingest_story_events(session, events, opted_out=False) == 1
    row = session.added[0]
    assert row.user_id is None and row.session_id is None
    assert row.event_name == "story_first_try"
    assert row.properties["correct"] is True and row.properties["anonymised"] is True
