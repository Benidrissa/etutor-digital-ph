"""The chapter builder of story generator v4 (#2680) and its props (#2681).

Each rule is checked on the fixture chapter (the kids biology episode of
``fixtures/story_screenplay_module.json``) as the pipeline builds it — clean,
then broken in one way. No model, no database.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from app.ai.prompts.story_from_lesson import build_chapter_story_message, build_name_blocklist
from app.api.v1.schemas.story_course import StoryCourse, ValidationIssue, ValidationReport
from app.domain.services import story_repair as repair
from app.domain.services.story_checks import check_story
from app.domain.services.story_course_validator import validate_story_course
from app.domain.services.story_from_lesson_service import pack_issues, validate_document
from app.domain.services.story_props import names_prop
from tests.test_story_screenplay_module import (
    data,
    make_run,
    pack,
    story_answer,
    story_units,
)

LANGUAGE = "en"


def chapter_ctx(unit: str = "1.1", language: str = LANGUAGE) -> repair.LessonStoryContext:
    service, run, ctx = make_run(language)
    lesson = next(u for u in story_units() if u.unit_number == unit)
    return service._chapter_ctx(run, ctx, lesson)


def spine(unit: str = "1.1", language: str = LANGUAGE) -> dict[str, Any]:
    answer = story_answer(unit)
    out = {**pack(unit, language)}
    for key in ("props", "scenes", "facts", "recap", "props_now"):
        out[key] = answer[key]
    out["chapter_title"] = data()["stories"] and {"en": "The shy snail", "fr": "L'escargot timide"}
    return out


def build(ctx: repair.LessonStoryContext, the_spine: dict[str, Any], **kwargs: Any):
    return repair.build_story_document(ctx, the_spine, **kwargs)


def codes(result) -> set[str]:
    return {i.code for i in result.issues}


def lint_codes(result) -> set[str]:
    return {i.code for i in result.lints}


def steps_of(the_spine: dict[str, Any], scene: int) -> list[dict[str, Any]]:
    return the_spine["scenes"][scene]["steps"]


def index_of(steps: list[dict[str, Any]], **match: Any) -> int:
    return next(i for i, s in enumerate(steps) if all(s.get(k) == v for k, v in match.items()))


# --------------------------------------------------------------------------
# The clean chapter
# --------------------------------------------------------------------------


@pytest.mark.parametrize("language", ["en", "fr"])
def test_the_fixture_chapter_builds_with_no_issue_and_no_lint(language):
    result = build(chapter_ctx(language=language), spine(language=language))
    assert result.issues == [] and result.lints == []
    quality = result.quality
    assert set(quality) == {
        "story_lines",
        "steps",
        "ratio",
        "min_gap",
        "lead_ins_missing",
        "reactions_missing",
        "lecture_lines",
        "card_echoes",
        "fallback_cards",
        "names_leaked",
    }
    assert quality["story_lines"] >= 18 and quality["ratio"] >= 0.6 and quality["min_gap"] >= 3
    assert result.doc["checks"]["story_quality"] == quality
    assert result.doc["sira_builder"] == 4
    assert "_src" not in str(result.doc)


def test_a_chapter_without_a_plan_gets_no_story_check():
    ctx = chapter_ctx()
    ctx.plan_entry = None
    the_spine = spine()
    the_spine["scenes"][0]["steps"] = the_spine["scenes"][0]["steps"][:3]
    result = build(ctx, the_spine)
    assert not codes(result) & repair.STORY_CODES and result.quality == {}


# --------------------------------------------------------------------------
# Coverage, the fallback card, placement
# --------------------------------------------------------------------------


@pytest.mark.parametrize("teaches", [2, [2], ["2"], [2, 2]])
def test_teaches_is_an_int_or_a_list(teaches):
    the_spine = spine()
    steps = steps_of(the_spine, 1)
    steps[index_of(steps, type="concept")]["teaches"] = teaches
    result = build(chapter_ctx(), the_spine)
    assert repair.CONCEPT_NOT_COVERED not in codes(result)


def test_a_missing_card_comes_from_the_beat_and_sits_before_its_first_question():
    the_spine = spine()
    steps = steps_of(the_spine, 1)
    del steps[index_of(steps, type="concept")]
    result = build(chapter_ctx(), the_spine, cover_missing_concepts=True)
    issue = next(i for i in result.issues if i.code == repair.CONCEPT_NOT_COVERED)
    assert issue.path == "lesson.concepts[2]" and "card was added" in issue.message
    scene = result.doc["chapters"][0]["scenes"][1]["steps"]
    card = next(s for s in scene if s.get("id") == "cbeat2")
    beat = chapter_ctx().beats[1]
    assert card["title"] == beat["card_title"] and card["teaches"] == [2]
    assert card["en"] == [beat["discovery"]["en"]] and card["fr"] == [beat["discovery"]["fr"]]
    position = scene.index(card)
    # Before the lead-in of q3, the question on IDEA 2.
    assert scene[position + 1]["type"] == "say" and scene[position + 2]["ref"] == "q3"
    assert result.quality["fallback_cards"] == 1


def test_under_a_plan_made_in_code_the_fallback_card_is_the_lessons_whole_paragraph():
    ctx = chapter_ctx()
    ctx.plan_defaulted = True
    long_idea = " ".join(f"Sentence number {n} about cells and life." for n in range(1, 8))
    ctx.lesson["concepts"] = [*ctx.lesson["concepts"][:1], long_idea, *ctx.lesson["concepts"][2:]]
    the_spine = spine()
    steps = steps_of(the_spine, 1)
    del steps[index_of(steps, type="concept")]
    result = build(ctx, the_spine, cover_missing_concepts=True)
    card = next(
        s
        for c in result.doc["chapters"]
        for sc in c["scenes"]
        for s in sc["steps"]
        if s.get("id") == "cfallback2"
    )
    assert len(card["en"]) == 4 and "…" not in " ".join(card["en"])  # never cut (#2678)
    assert " ".join(card["en"]) == long_idea


def test_an_unasked_question_goes_right_after_the_card_of_its_idea():
    the_spine = spine()
    steps = steps_of(the_spine, 1)
    del steps[index_of(steps, type="ask", ref="q3")]
    result = build(chapter_ctx(), the_spine)
    issue = next(i for i in result.issues if i.code == repair.QUESTION_NOT_ASKED)
    assert "after the card of IDEA 2" in issue.message
    scene = result.doc["chapters"][0]["scenes"][1]["steps"]
    card = next(i for i, s in enumerate(scene) if s["type"] == "concept")
    assert scene[card + 1] == {"type": "ask", "ref": "q3"}


def test_a_scene_takes_the_objective_of_its_first_question():
    result = build(chapter_ctx(), spine())
    assert all(s.get("objective") == "o1" for s in result.doc["chapters"][0]["scenes"])


def test_no_fallback_game_without_the_plans_game():
    ctx = chapter_ctx()
    assert ctx.has_game is False
    result = build(ctx, {**spine(), "minigame": pack("1.2", LANGUAGE)["minigame"]})
    assert result.doc["minigames"] == []
    assert all(s["type"] != "game" for s in result.doc["chapters"][0]["scenes"][0]["steps"])
    # It validates without a game: the module story has the episode's one game.
    assert validate_document(result.doc).ok


def test_the_chapter_tutor_is_written_in_code():
    the_spine = {**spine(), "tutor": {"intro": {"en": "Hello, I am Bob", "fr": "Salut"}}}
    result = build(chapter_ctx(), the_spine)
    assert "Bob" not in str(result.doc["tutor"])
    assert "AI" in result.doc["tutor"]["intro"]["en"]


# --------------------------------------------------------------------------
# The story codes: errors while the repair budget lasts, warnings after it
# --------------------------------------------------------------------------


def broken(change) -> set[str]:
    the_spine = spine()
    ctx = chapter_ctx()
    change(the_spine, ctx)
    return codes(build(ctx, the_spine))


def test_ask_not_set_up():
    def change(s, _ctx):
        steps = steps_of(s, 0)
        del steps[index_of(steps, type="ask", ref="q1") - 1]

    assert repair.ASK_NOT_SET_UP in broken(change)


def test_a_situation_card_between_the_lead_in_and_the_ask_is_skipped():
    ctx = chapter_ctx()
    mcq = next(m for m in ctx.mcqs if m.ref == "q3")
    mcq.stem = "In the market, " + "a very long story about a grey pebble " * 6 + "— why?"
    result = build(ctx, spine())
    scene = result.doc["chapters"][0]["scenes"][1]["steps"]
    ask = next(i for i, s in enumerate(scene) if s.get("ref") == "q3")
    assert scene[ask - 1]["id"] == "situation-q3" and scene[ask - 2]["type"] == "say"
    assert repair.ASK_NOT_SET_UP not in codes(result)


def test_ask_not_followed():
    def change(s, _ctx):
        steps = steps_of(s, 1)
        del steps[index_of(steps, type="ask", ref="q3") + 1 :]

    assert repair.ASK_NOT_FOLLOWED in broken(change)


def test_lead_in_gives_answer():
    def change(s, _ctx):
        steps = steps_of(s, 0)
        lead = steps[index_of(steps, type="ask", ref="q1") - 1]
        lead["en"] = "Easy, {child}: it reacts to what happens around it!"

    assert repair.LEAD_IN_GIVES_ANSWER in broken(change)


@pytest.mark.parametrize("cut", ["ratio", "gap", "count"])
def test_story_too_thin(cut):
    def change(s, _ctx):
        if cut == "ratio":
            for scene in s["scenes"]:
                scene["steps"] = [
                    st for i, st in enumerate(scene["steps"]) if st["type"] != "say" or i % 3
                ]
        elif cut == "gap":
            steps = steps_of(s, 2)
            photo = steps.pop(index_of(steps, type="photo"))
            steps.insert(index_of(steps, type="ask", ref="x1") + 2, photo)
        else:
            s["scenes"][2]["steps"] = s["scenes"][2]["steps"][:9]
            s["scenes"][0]["steps"] = s["scenes"][0]["steps"][:-3]

    assert repair.STORY_TOO_THIN in broken(change)


def test_ending_not_story():
    def change(s, _ctx):
        steps = steps_of(s, 2)
        steps.append(steps.pop(index_of(steps, type="photo")))

    assert repair.ENDING_NOT_STORY in broken(change)


def test_margo_self_intro_but_not_jai():
    def add(text_en: str, text_fr: str):
        def change(s, _ctx):
            s["scenes"][2]["cast"] = ["hero", "friend", "margo"]
            steps = steps_of(s, 2)
            for step in steps:
                if step.get("who") == "mentor":
                    step["who"] = "margo"
            steps.insert(2, {"type": "say", "who": "margo", "en": text_en, "fr": text_fr})

        return change

    assert repair.MARGO_SELF_INTRO in broken(
        add("I am an AI, a lizard of hints.", "Je suis une IA.")
    )
    assert repair.MARGO_SELF_INTRO not in broken(
        add("Psst... look at the tiny boxes.", "J'ai un indice : les petites boîtes.")
    )


def test_meta_line():
    def change(s, _ctx):
        steps_of(s, 0)[0]["en"] = "Saturday. Today's lesson is about living things."

    assert repair.META_LINE in broken(change)


def test_name_from_lesson():
    ctx = chapter_ctx()
    assert "Aminata" in ctx.blocklist

    def change(s, _ctx):
        steps_of(s, 0)[1]["en"] = "Aminata sent these treasures for your fair table, children."

    assert repair.NAME_FROM_LESSON in broken(change)


def test_a_line_of_an_earlier_chapter_is_sent_back_unless_it_is_the_refrain():
    ctx = chapter_ctx()
    steps = spine()["scenes"][0]["steps"]
    told = steps[1]
    for key in repair.repeat_keys({"type": "say", "en": told["en"], "fr": told["fr"]}):
        ctx.earlier_line_keys[key] = "1.0"
    refrain = steps[-1]
    for key in repair.repeat_keys({"type": "say", "en": refrain["en"], "fr": refrain["fr"]}):
        ctx.earlier_line_keys[key] = "1.0"
    result = build(ctx, spine())
    repeats = [i for i in result.issues if i.code == repair.REPEATED_LINE]
    assert len(repeats) == 1 and "already said in chapter 1.0" in repeats[0].message
    built = result.doc["chapters"][0]["scenes"][0]["steps"]
    assert built[-1]["refrain"] is True and built[-1]["en"] == "Detectives, to work!"


def test_the_refrain_is_capped_at_four_in_a_module():
    ctx = chapter_ctx()
    ctx.refrains_before = repair.MAX_REFRAINS
    result = build(ctx, spine())
    assert all(
        not s.get("refrain") for sc in result.doc["chapters"][0]["scenes"] for s in sc["steps"]
    )


def test_story_codes_settle_into_warnings_after_the_budget():
    report = ValidationReport(
        ok=False,
        errors=[
            ValidationIssue(severity="error", code=c, path="scenes", message="m")
            for c in repair.STORY_CODES
        ],
    )
    settled = repair.settle_translations(report)
    assert settled.ok and {w.code for w in settled.warnings} == set(repair.STORY_CODES)


# --------------------------------------------------------------------------
# Lints: warnings only, never a repair call
# --------------------------------------------------------------------------


def linted(change, unit: str = "1.1") -> set[str]:
    the_spine = spine(unit)
    ctx = chapter_ctx(unit)
    change(the_spine, ctx)
    result = build(ctx, the_spine)
    report = repair.with_generator_issues(validate_document(result.doc), result)
    assert {w.code for w in result.lints} <= {w.code for w in report.warnings}
    return lint_codes(result)


def test_lint_lecture_line():
    def change(s, _ctx):
        steps_of(s, 0)[1]["en"] = (
            "Remember that a living thing is defined as something that reacts, feeds and grows."
        )

    assert "lecture_line" in linted(change)


def test_lint_card_repeats_dialogue():
    def change(s, _ctx):
        steps = steps_of(s, 0)
        card = steps[index_of(steps, type="concept")]
        card["en"][0] = steps[index_of(steps, type="concept") - 1]["en"]

    assert "card_repeats_dialogue" in linted(change)


def test_lint_card_gives_answer():
    def change(s, _ctx):
        steps = steps_of(s, 2)
        card = steps[index_of(steps, type="concept")]
        card["en"][0] = "Look for cells under the microscope, always."

    assert "card_gives_answer" in linted(change)


def test_lint_mentor_lectures_and_hero_too_quiet():
    def change(s, _ctx):
        for scene in s["scenes"]:
            scene["cast"] = ["hero", "friend", "mentor"]
            for step in scene["steps"]:
                if step.get("who") in ("hero", "family"):
                    step["who"] = "mentor"

    found = linted(change)
    assert {"mentor_lectures", "hero_too_quiet"} <= found


def test_lint_card_title_textbook():
    def change(s, _ctx):
        steps = steps_of(s, 1)
        steps[index_of(steps, type="concept")]["title"] = {"en": "Sign 2: growth", "fr": "Signe 2"}

    assert "card_title_textbook" in linted(change)


def test_lint_cold_open():
    def change(s, ctx):
        ctx.previous_scene = {"place": "x", "lines": ["narrator: The goat eats the poster."]}
        ctx.plan_entry = {**ctx.plan_entry, "opens_on": "A goat eats the poster."}

    assert "cold_open" in linted(change, "1.2")


# --------------------------------------------------------------------------
# Props (#2681)
# --------------------------------------------------------------------------


def built_steps(result) -> list[dict[str, Any]]:
    return [s for sc in result.doc["chapters"][0]["scenes"] for s in sc["steps"]]


def test_props_are_declared_reused_and_shown():
    result = build(chapter_ctx(), spine())
    props = {p["id"]: p for p in result.doc["props"]}
    # The plan's props are reused, never declared again; the chapter's own are added.
    assert set(props) == {"basket", "snail", "mimosa", "nere_seed", "pebble", "microscope"}
    assert props["snail"]["educational"] and props["basket"]["kind"] == "sticker"
    closeups = [s for s in built_steps(result) if s.get("visual") == "prop"]
    assert [c["params"]["prop"] for c in closeups] == [
        "snail",
        "mimosa",
        "nere_seed",
        "pebble",
        "microscope",
    ]
    report = validate_story_course(StoryCourse.model_validate(result.doc), generated=True)
    assert report.ok and report.checks.props["closeups"] == 5
    assert report.checks.props["coverage"] > 0.4


@pytest.mark.parametrize(
    ("text_en", "text_fr", "prop"),
    [
        ("Grandma's snail is back!", "L'escargot de Mamie est là !", "snail"),
        ("Two pebbles, no cells.", "Deux cailloux, pas de cellules.", "pebble"),
        ("Put it in Grandma's basket.", "Mets-le dans le panier de Mamie.", "basket"),
    ],
)
def test_a_line_that_names_a_prop_points_at_it(text_en, text_fr, prop):
    the_spine = spine()
    steps = steps_of(the_spine, 0)
    steps.insert(1, {"type": "narrate", "en": text_en, "fr": text_fr})
    result = build(chapter_ctx(), the_spine)
    line = next(s for s in built_steps(result) if s.get("en") == text_en)
    assert prop in line["props"]
    assert any(i.code == "prop_named_unreferenced" for i in result.issues)


def test_prop_issues_are_warnings_never_a_repair_call_on_their_own():
    the_spine = spine()
    steps_of(the_spine, 0).insert(
        1, {"type": "narrate", "en": "The snail sleeps.", "fr": "L'escargot dort."}
    )
    ctx = chapter_ctx()
    result = build(ctx, the_spine)
    report = repair.with_generator_issues(validate_document(result.doc), result)
    assert report.ok
    assert "prop_named_unreferenced" in {w.code for w in report.warnings}
    assert repair.repair_issues(report) and all(
        i.code in repair.PROP_CODES for i in repair.repair_issues(report)
    )


def test_bad_declarations_are_settled():
    the_spine = spine()
    the_spine["props"] += [
        {
            "id": "Big Rock!",
            "label": {"en": "a big rock", "fr": "un gros rocher"},
            "query": "big granite boulder",
            "kind": "real",
            "emoji": "🪨🪨",
        },
        {
            "id": "kid",
            "label": {"en": "a kid", "fr": "un enfant"},
            "query": "smiling child",
            "kind": "real",
        },
        {
            "id": "snail_two",
            "label": {"en": "a snail", "fr": "un escargot"},
            "query": "garden snails",
            "kind": "real",
        },
        {"id": "nolabel", "label": {"en": "a cup"}, "query": "tin cup", "kind": "sticker"},
    ]
    steps = steps_of(the_spine, 0)
    steps.insert(
        1,
        {
            "type": "narrate",
            "en": "A big rock sits there.",
            "fr": "Un gros rocher.",
            "props": ["Big Rock!", "kid", "ghost"],
        },
    )
    steps.insert(
        2,
        {
            "type": "say",
            "who": "friend",
            "en": "Another snail!",
            "fr": "Un autre escargot !",
            "props": ["snail_two"],
        },
    )
    result = build(chapter_ctx(), the_spine)
    found = codes(result)
    assert {"prop_invalid", "prop_query_people", "duplicate_prop", "prop_ref_unknown"} <= found
    props = {p["id"]: p for p in result.doc["props"]}
    assert "big_rock" in props and "emoji" not in props["big_rock"]
    assert "kid" not in props and "nolabel" not in props and "snail_two" not in props
    line = next(s for s in built_steps(result) if s.get("en") == "Another snail!")
    assert line["props"] == ["snail"]


def test_close_ups_are_settled():
    the_spine = spine()
    steps = steps_of(the_spine, 0)
    # The mimosa's close-up before any line names it; a close-up of a sticker;
    # a second close-up of the snail.
    del steps[index_of(steps, type="show", prop="mimosa")]
    steps.insert(0, {"type": "show", "prop": "mimosa"})
    steps.insert(len(steps) - 1, {"type": "show", "prop": "basket"})
    steps.insert(len(steps) - 1, {"type": "show", "prop": "snail"})
    result = build(chapter_ctx(), the_spine)
    messages = [i.message for i in result.issues if i.code == "closeup_invalid"]
    assert any("sticker" in m for m in messages) and any("already shown" in m for m in messages)
    assert any("before any line names it" in m for m in messages)
    built = built_steps(result)
    closeups = [s["params"]["prop"] for s in built if s.get("visual") == "prop"]
    assert closeups.count("snail") == 1 and "basket" not in closeups
    mimosa_line = next(i for i, s in enumerate(built) if "mimosa" in (s.get("props") or []))
    assert built[mimosa_line + 1]["params"] == {"prop": "mimosa"}
    assert validate_story_course(StoryCourse.model_validate(result.doc), generated=True).ok


def test_a_missing_close_up_is_added_after_the_first_line_naming_it():
    the_spine = spine()
    for scene in the_spine["scenes"]:
        scene["steps"] = [s for s in scene["steps"] if s.get("prop") != "pebble"]
    result = build(chapter_ctx(), the_spine)
    assert "closeup_missing" in codes(result)
    steps = built_steps(result)
    first = next(i for i, s in enumerate(steps) if "pebble" in (s.get("props") or []))
    assert steps[first + 1] == {"type": "show", "visual": "prop", "params": {"prop": "pebble"}}


def test_a_figure_prop_resolves_its_figure_and_a_dangling_one_becomes_real():
    ctx = chapter_ctx()
    ctx.figures = [
        {
            "id": "3f2c0000-0000-0000-0000-000000000001",
            "figure_number": "Figure 1.4",
            "image_hash": "c3c3e1f0f8f8f0e0",
            "caption_en": "Onion cells",
            "caption_fr": "Cellules",
            "figure_kind": "micrograph",
            "attribution": "OpenStax, CC BY 4.0",
        }
    ]
    the_spine = spine()
    the_spine["props"] += [
        {
            "id": "onion_cells",
            "label": {"en": "onion skin cells", "fr": "des cellules d'oignon"},
            "query": "onion epidermis cells microscope",
            "kind": "figure",
            "figure": 1,
        },
        {
            "id": "leaf_cells",
            "label": {"en": "leaf cells", "fr": "des cellules de feuille"},
            "query": "leaf cells microscope",
            "kind": "figure",
            "figure": 7,
        },
    ]
    steps_of(the_spine, 2).insert(
        1,
        {
            "type": "narrate",
            "en": "Onion skin cells and leaf cells.",
            "fr": "Des cellules d'oignon.",
            "props": ["onion_cells", "leaf_cells"],
        },
    )
    the_spine["scenes"][2]["props"] = ["microscope", "nere_seed", "pebble", "onion_cells"]
    result = build(ctx, the_spine)
    props = {p["id"]: p for p in result.doc["props"]}
    figure = props["onion_cells"]["figure"]
    assert (
        figure["source_image_id"].startswith("3f2c") and figure["image_hash"] == "c3c3e1f0f8f8f0e0"
    )
    assert figure["attribution"].startswith("OpenStax")
    assert props["leaf_cells"]["kind"] == "real" and props["leaf_cells"]["educational"]
    assert "figure_prop_dangling" in codes(result)


# --------------------------------------------------------------------------
# The practice pack
# --------------------------------------------------------------------------


def test_the_fixture_packs_are_clean():
    for unit in ("1.1", "1.2", "1.3"):
        assert pack_issues(chapter_ctx(unit), pack(unit, LANGUAGE)) == []


def test_pack_codes():
    ctx = chapter_ctx()
    the_pack = pack("1.1", LANGUAGE)
    the_pack["derived"] = [d for d in the_pack["derived"] if d["ref"] != "q3"]
    the_pack["questions"][0]["idea"] = 9
    found = {i.code for i in pack_issues(ctx, the_pack)}
    assert {"assigned_ref_missing", "question_off_idea", "idea_without_question"} <= found
    # Only pack paths: no story code from the stub scene.
    assert not found & repair.STORY_CODES


def test_the_pack_message_alone_carries_the_wrong_options_and_misconceptions():
    from app.ai.prompts.story_from_lesson import build_pack_message

    message = build_pack_message(chapter_ctx())
    assert "why it is wrong (from the course): SENTINEL" in message
    assert "<- correct" in message
    assert "GAME: no" in message and "exactly 1 of your own" in message
    copy.deepcopy(message)


# --------------------------------------------------------------------------
# The review of #2687: names, close-ups, runs of questions, the prompt
# --------------------------------------------------------------------------


def test_the_blocklist_keeps_the_country_the_bible_the_calendar_and_the_fact_sheet():
    lesson = {
        "introduction": {
            "fr": "Au Burkina Faso, Aminata vend ses mangues à Ouagadougou le Samedi, chez"
            " Mamie Mariam.",
            "en": "In Burkina Faso, Aminata sells mangoes on Friday in March.",
        },
        "aof_example": {
            "fr": "À Bouaké, Moussa Traoré mesure le Soleil chaque Lundi de Mars.",
            "en": "In Bouaké, Moussa Traoré measures the Sun every Monday.",
        },
        "concepts": ["Le Soleil chauffe la Terre, même en Décembre."],
        "key_points": ["La Terre tourne autour du Soleil."],
    }
    blocked = build_name_blocklist(
        [lesson], ["Que vend Koffi au marché ?"], data()["bible"], country="BF"
    )
    for name in ("Aminata", "Bouaké", "Moussa", "Traoré", "Moussa Traoré", "Koffi"):
        assert name in blocked, name
    for word in (
        "Burkina",
        "Faso",
        "Burkina Faso",
        "Ouagadougou",  # a place of the bible
        "Mamie",
        "Mariam",
        "Samedi",
        "Lundi",
        "Mars",
        "Friday",
        "March",
        "Monday",
        "Soleil",  # words of the fact sheet: the story must use them
        "Terre",
    ):
        assert word not in blocked, word


def _name_codes(en: str, fr: str, *, card: str | None = None) -> set[str]:
    ctx = chapter_ctx()
    ctx.blocklist = ["Aminata", "Issa", "Bouaké", "Soleil"]
    the_spine = spine()
    steps = steps_of(the_spine, 0)
    steps[1]["en"], steps[1]["fr"] = en, fr
    if card is not None:
        concept = steps[index_of(steps, type="concept")]
        concept["en"] = [card, *concept["en"][1:]]
    return codes(build(ctx, the_spine))


@pytest.mark.parametrize(
    ("en", "fr"),
    [
        ("Aminata sent these treasures for your fair table.", "Voici mes trésors."),
        ("These are Aminata's treasures for your fair table.", "Voici mes trésors."),
        ("Here are my treasures.", "Les trésors d'Aminata sont pour votre table."),
        ("Here are my treasures.", "Le cahier d’Issa est tombé de la table."),
        ("We found them in Bouake, children.", "Voici mes trésors."),
    ],
)
def test_a_name_from_the_lesson_is_caught_after_elision_before_a_possessive_and_unaccented(en, fr):
    assert repair.NAME_FROM_LESSON in _name_codes(en, fr)


def test_a_name_from_the_lesson_is_matched_as_written_in_story_lines_only():
    # Cards are not checked: the same words in a line would be caught.
    assert repair.NAME_FROM_LESSON not in _name_codes(
        "Here are my treasures for your fair table.",
        "Le soleil tape sur mes trésors pour votre table de la foire.",
        card="Aminata sent these treasures for your fair table.",
    )
    # "le soleil" is not the name "Soleil" the lesson capitalised.
    assert repair.NAME_FROM_LESSON in _name_codes(
        "Here are my treasures.", "Le Soleil tape sur mes trésors."
    )


def test_markdown_bullets_and_labels_never_make_a_word_a_name():
    """A multi-line field is cleaned line by line: a bullet starts a sentence (#2693)."""
    lesson = {
        "aof_example": {
            "en": "In the Kaya district, nurse Aminata Sawadogo counts the cases.\n\n"
            "**Steps taken:**\n* Count the cases each week\n• Compare with last year\n"
            "+ Share the list\n1) Report it\n\n**Result:** The team caught it early.",
            "fr": "Dans le district de Kaya, l'infirmière Aminata Sawadogo compte les cas.\n\n"
            "**Étapes :**\n* Compter les cas chaque semaine\n• Comparer avec l'an passé\n\n"
            "**Résultat :** L'équipe l'a vu tôt.\n«\u00a0Bravo\u00a0», dit-elle.",
        },
    }
    blocked = build_name_blocklist([lesson], [], data()["bible"], country="BF")
    assert {"Aminata", "Sawadogo", "Kaya"} <= set(blocked)
    for word in (
        "Steps",
        "Count",
        "Compare",
        "Share",
        "Report",
        "Result",
        "Étapes",
        "Compter",
        "Comparer",
        "Résultat",
        "Bravo",
    ):
        assert word not in blocked, word


@pytest.mark.parametrize(
    ("line", "label"),
    [
        ("Les cellules de l'oignon sont rangées.", "des cellules d'oignon"),
        ("Le panier de la grand-mère est lourd.", "le panier de Grand-mère"),
        ("La feuille de la mimosa se ferme.", "la feuille de mimosa"),
        ("Les graines des nérés sèchent.", "la graine de néré"),
    ],
)
def test_the_french_matcher_allows_an_article_in_the_complement(line, label):
    assert names_prop(line, {"label": {"fr": label}}, "fr")


def test_a_paper_task_the_model_left_out_never_ends_a_chapter_of_dialogue():
    """The last scene is all lines (a cliffhanger): the task goes before its closing lines."""
    assert [repair._before_closing_lines([{"type": "say"}] * n) for n in (0, 1, 2, 3, 4)] == [
        0,
        0,
        0,
        1,
        2,
    ]
    assert repair._before_closing_lines([{"type": "ask"}, {"type": "say"}]) == 1
    the_spine = spine()
    steps = steps_of(the_spine, 2)
    del steps[index_of(steps, type="photo")]
    last = copy.deepcopy(the_spine["scenes"][2])
    last["props"] = []
    last["steps"] = [
        {"type": "narrate", "en": "Night falls on the school.", "fr": "La nuit tombe sur l'école."},
        {"type": "say", "who": "friend", "en": "Did you hear that?", "fr": "Tu as entendu ?"},
        {
            "type": "say",
            "who": "hero",
            "en": "Something is in the yard!",
            "fr": "Il y a quelque chose dans la cour !",
        },
    ]
    the_spine["scenes"].append(last)
    result = build(chapter_ctx(), the_spine)
    assert repair.UNPLACED_ITEM in codes(result)
    final = result.doc["chapters"][0]["scenes"][-1]["steps"]
    assert [s["type"] for s in final] == ["narrate", "photo", "say", "say"]
    assert repair.ENDING_NOT_STORY not in codes(result)


def test_an_added_close_up_never_splits_a_lead_in_from_its_question():
    """The pebble is first named in the lead-in of q3: its close-up comes after the reaction."""
    the_spine = spine()
    steps = steps_of(the_spine, 1)
    del steps[index_of(steps, type="show", prop="pebble")]
    steps[0].update(
        en="Grandma rolls a brown néré seed along the bench.",
        fr="Mamie fait rouler une graine de néré brune sur le banc.",
        props=["nere_seed"],
    )
    friend = index_of(steps, type="say", who="friend")
    steps[friend].update(
        en="This seed does nothing. No legs, no eyes. Dead as a stone!",
        fr="Cette graine ne fait rien. Pas de pattes, pas d'yeux. Morte comme une pierre !",
        props=["nere_seed"],
    )
    result = build(chapter_ctx(), the_spine)
    assert "closeup_missing" in codes(result)
    scene = result.doc["chapters"][0]["scenes"][1]["steps"]
    ask = index_of(scene, type="ask", ref="q3")
    assert scene[ask - 1]["type"] == "say" and "pebble" in scene[ask - 1]["props"]
    assert scene[ask + 2] == {"type": "show", "visual": "prop", "params": {"prop": "pebble"}}
    assert repair.ASK_NOT_SET_UP not in codes(result)


def test_a_close_up_never_follows_the_line_that_ends_the_chapter():
    the_spine = spine()
    the_spine["props"].append(
        {
            "id": "trail",
            "label": {"en": "the silver trail", "fr": "la trace argentée"},
            "query": "snail slime trail",
            "kind": "real",
        }
    )
    last = steps_of(the_spine, 2)[-1]
    last["props"] = ["trail"]
    result = build(chapter_ctx(), the_spine)
    built = built_steps(result)
    assert built[-1]["type"] == "narrate" and "trail" in built[-1]["props"]
    assert {"type": "show", "visual": "prop", "params": {"prop": "trail"}} not in built
    assert repair.ENDING_NOT_STORY not in codes(result)


def test_model_close_ups_are_capped_at_two_a_scene_and_a_moved_one_is_kept():
    the_spine = spine()
    first = steps_of(the_spine, 0)
    del first[index_of(first, type="show", prop="mimosa")]
    second = steps_of(the_spine, 1)
    at = index_of(second, type="say", who="friend") + 1
    second[at:at] = [
        {
            "type": "say",
            "who": "hero",
            "en": "Like the mimosa, it waits.",
            "fr": "Comme le mimosa, elle attend.",
            "props": ["mimosa"],
        },
        {"type": "show", "prop": "mimosa"},
    ]
    # The microscope's close-up before any line names it, in an earlier scene.
    third = steps_of(the_spine, 2)
    del third[index_of(third, type="show", prop="microscope")]
    first.insert(0, {"type": "show", "prop": "microscope"})
    result = build(chapter_ctx(), the_spine)
    messages = [i.message for i in result.issues if i.code == "closeup_invalid"]
    assert any("close-ups at most" in m for m in messages)
    scenes = result.doc["chapters"][0]["scenes"]

    def closeups(scene):
        return [s["params"]["prop"] for s in scene["steps"] if s.get("visual") == "prop"]

    assert closeups(scenes[1]) == ["nere_seed", "pebble"]
    assert "mimosa" in closeups(scenes[0])  # moved after the line that first names it
    assert "microscope" in closeups(scenes[2])  # moved, and kept (#2687 review)
    line = index_of(scenes[2]["steps"], type="say", who="hero")
    assert scenes[2]["steps"][line + 1]["params"] == {"prop": "microscope"}
    report = validate_story_course(StoryCourse.model_validate(result.doc), generated=True)
    assert report.ok and "too_many_closeups_in_scene" not in {e.code for e in report.errors}


def test_a_close_up_the_model_put_before_a_question_or_at_the_end_is_moved():
    the_spine = spine()
    steps = steps_of(the_spine, 1)
    del steps[index_of(steps, type="show", prop="pebble")]
    steps.insert(index_of(steps, type="ask", ref="q3"), {"type": "show", "prop": "pebble"})
    last = steps_of(the_spine, 2)
    del last[index_of(last, type="show", prop="microscope")]
    last.append({"type": "show", "prop": "microscope"})
    result = build(chapter_ctx(), the_spine)
    found = codes(result)
    assert "closeup_invalid" in found
    assert repair.ASK_NOT_SET_UP not in found and repair.ENDING_NOT_STORY not in found
    scene = result.doc["chapters"][0]["scenes"][1]["steps"]
    assert scene[index_of(scene, type="ask", ref="q3") - 1]["type"] == "say"
    built = built_steps(result)
    assert built[-1]["type"] == "narrate"
    assert sum(1 for s in built if s.get("params") == {"prop": "microscope"}) == 1


def test_the_story_checks_see_through_a_close_up():
    """A close-up is no lead-in and no ending: the line before it is."""
    show = {"type": "show", "visual": "prop", "params": {"prop": "snail"}}
    lines = [
        {"type": "say", "who": "friend", "en": f"Line {n} of the scene.", "fr": f"Ligne {n}."}
        for n in range(6)
    ]
    scenes = [
        {
            "steps": [
                lines[0],
                lines[1],
                copy.deepcopy(show),
                {"type": "ask", "ref": "q1"},
                copy.deepcopy(show),
                lines[2],
                lines[3],
                copy.deepcopy(show),
            ]
        }
    ]
    found: list[str] = []
    check_story(chapter_ctx(), scenes, {}, lambda code, path, message: found.append(code))
    assert repair.ASK_NOT_SET_UP not in found
    assert repair.ASK_NOT_FOLLOWED not in found
    assert repair.ENDING_NOT_STORY not in found


def test_a_close_up_never_separates_two_runs_of_questions():
    show = {"type": "show", "visual": "prop", "params": {"prop": "snail"}}

    def ask(ref: str) -> dict[str, Any]:
        return {"type": "ask", "ref": ref}

    steps = [ask("a"), ask("b"), show, ask("c"), ask("d")]
    assert repair.ask_run_excess(steps) == ["d"]
    assert not repair.joins_ask_runs(steps, 2)  # removing a close-up joins nothing
    joined = [ask("a"), ask("b"), {"type": "say"}, ask("c"), show, ask("d")]
    assert repair.joins_ask_runs(joined, 2)
    scenes = [{"steps": copy.deepcopy(steps)}]
    assert repair._cap_ask_runs(scenes) == {"d"}
    # The validator counts a run through a close-up too.
    result = build(chapter_ctx(), spine())
    doc = copy.deepcopy(result.doc)
    flat = [s for sc in doc["chapters"][0]["scenes"] for s in sc["steps"]]
    closeup = next(s for s in flat if s.get("visual") == "prop")
    for scene in doc["chapters"][0]["scenes"]:
        scene["steps"] = [s for s in scene["steps"] if s.get("type") != "ask" and s is not closeup]
    first = doc["chapters"][0]["scenes"][0]["steps"]
    at = index_of(first, type="concept") + 1
    first[at:at] = [ask("q1"), ask("q2"), closeup, ask("q3"), ask("x1")]
    report = validate_story_course(StoryCourse.model_validate(doc), generated=True)
    assert "too_many_questions_in_a_row" in {e.code for e in report.errors}


NERE = {"label": {"en": "the néré seed", "fr": "la graine de néré"}}


@pytest.mark.parametrize(
    ("line", "named"),
    [
        ("Mamie fait rouler une graine de néré brune.", True),
        ("Les graines du néré sont là.", True),
        ("Cette graine ne fait rien.", True),
        ("La graine de haricot germe.", False),
    ],
)
def test_the_french_matcher_reads_the_whole_label_first(line, named):
    assert names_prop(line, NERE, "fr") is named


def test_a_shared_head_or_a_cast_name_is_never_matched_alone():
    leaf = {"label": {"fr": "la feuille de mimosa"}}
    assert not names_prop("Les feuilles du manguier tombent.", leaf, "fr")
    assert not names_prop("Une feuille tombe.", leaf, "fr", shared_heads={"feuille"})
    assert names_prop("La feuille de mimosa se ferme.", leaf, "fr", shared_heads={"feuille"})
    stone = {"label": {"en": "a stone", "fr": "une pierre"}}
    assert not names_prop("Pierre, viens voir !", stone, "fr", names={"pierre"})
    assert names_prop("Une pierre roule.", stone, "fr")
    onion = {"label": {"fr": "des cellules d'oignon"}}
    assert names_prop("Regarde ces cellules d’oignon !", onion, "fr")


def test_the_example_puts_the_figure_four_lines_before_the_card():
    ctx = chapter_ctx()
    ctx.figures = [
        {
            "id": "3f2c0000-0000-0000-0000-000000000001",
            "caption_en": "Cells",
            "caption_fr": "Cellules",
        }
    ]
    message = build_chapter_story_message(ctx, pack("1.1", LANGUAGE))
    example = message.split("=== OUTPUT ===", 1)[1]
    figure = example.index('{"type": "show", "figure": 1}')
    card = example.index('{"type": "concept"')
    assert example[figure:card].count('"type": "say"') == 4
    assert "its figure comes early, 4 story lines before the card" in example


def test_margo_speaks_only_in_a_scene_whose_cast_lists_her():
    message = build_chapter_story_message(chapter_ctx(), pack("1.1", LANGUAGE))
    assert 'Margo speaks only in a scene whose "cast" lists "margo"' in message


def test_the_last_chapter_of_a_module_without_a_rally_resolves_the_episode():
    ctx = chapter_ctx("1.3")
    assert ctx.chapter_index == ctx.chapter_count == 3
    with_rally = build_chapter_story_message(ctx, pack("1.3", LANGUAGE))
    assert "THE LAST CHAPTER:" not in with_rally and "never a cliffhanger" not in with_rally
    ctx.plan = {**ctx.plan, "rally": None}
    message = build_chapter_story_message(ctx, pack("1.3", LANGUAGE))
    assert "THE LAST CHAPTER: this module has no rally" in message
    assert "ENDS ON is its warm last image, never a cliffhanger" in message
    middle = chapter_ctx("1.2")
    middle.plan = {**middle.plan, "rally": None}
    assert "THE LAST CHAPTER:" not in build_chapter_story_message(middle, pack("1.2", LANGUAGE))


class _PackModel:
    """Answers the pack call with ``first``, raises ``then`` on every later call."""

    def __init__(self, first: Any, then: Exception) -> None:
        self.first, self.then, self.calls = first, then, 0

    async def generate_structured_content(self, system, user, content_type, max_retries=1):
        self.calls += 1
        if self.calls > 1:
            raise self.then
        if isinstance(self.first, Exception):
            raise self.first
        return copy.deepcopy(self.first)


def test_a_provider_error_on_a_pack_repair_keeps_the_paid_pack():
    import asyncio

    from app.domain.services.story_from_lesson_service import StoryFromLessonService

    ctx = chapter_ctx()
    bad = pack("1.1", LANGUAGE)
    bad["derived"] = [d for d in bad["derived"] if d["ref"] != "q3"]  # sent back for repair
    model = _PackModel({**bad, "__complete": True}, RuntimeError("529 overloaded"))
    result = asyncio.run(StoryFromLessonService(model).generate_pack(ctx, system_prompt="s"))
    assert model.calls == 2 and result.model_calls == 2
    assert result.pack["derived"] == bad["derived"]
    assert "assigned_ref_missing" in {i.code for i in result.issues}
    # No readable answer at all: the provider's error is the run's.
    failing = _PackModel(RuntimeError("401 invalid key"), RuntimeError("never"))
    with pytest.raises(RuntimeError, match="401"):
        asyncio.run(StoryFromLessonService(failing).generate_pack(ctx, system_prompt="s"))
