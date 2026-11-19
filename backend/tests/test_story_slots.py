"""The slot builder (#2713): code writes the screenplay, the model only fills short lines.

Pure tests (no database, no real model) on the kids biology episode of
``fixtures/story_screenplay_module.json``, told from a NEW plan (no mentor).
The fake model answers each slot from the message it is sent, so the whole
path is exercised: the script, the slot call, the checks, the retry of a bad
slot, the code's own lines, the same builder and validator as a classic
chapter, and the counters of calls and tokens.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any

import pytest

from app.ai.usage_context import usage_tally
from app.api.v1.schemas.story_course import StoryCourse
from app.domain.services import story_beats as beats
from app.domain.services import story_calls, story_slots
from app.domain.services import story_poe as poe
from app.domain.services import story_repair as repair
from app.domain.services.story_course_validator import validate_story_course
from app.domain.services.story_from_lesson_service import PACK_KEYS, StoryFromLessonService
from app.infrastructure.config.platform_defaults import DEFAULTS_BY_KEY
from tests.test_story_cast_policy import none_ctx
from tests.test_story_screenplay_module import pack

MIMOSA = "39fe5905-0000-4000-8000-0000000000aa"
TEXT = {
    "narration": ("The light moves across the yard", "La lumière glisse sur la cour"),
    "hook": ("Look at that clue closely", "Regarde bien cet indice"),
    "hero-line": ("I bet it is simple", "Je parie que c'est simple"),
    "reaction": ("Hmm, so what next", "Hmm, et maintenant"),
    "card-row": ("Cell: the tiny box", "Cellule : la petite boîte"),
    "lead": ("Time to write it down", "Il faut l'écrire"),
    "close": ("The snail slips away at dusk", "L'escargot file au crépuscule"),
    "bet-prompt": ("Which one will win", "Lequel va gagner"),
    "reaction-right": ("Well bet", "Bien parié"),
    "reaction-wrong": ("Not this time", "Pas cette fois"),
    "label": ("left tray", "plateau gauche"),
}
ROW = re.compile(r"^- (\S+) \| (\S+)", re.MULTILINE)


def lines_for(message: str, *, skip: set[str] = frozenset(), edit: dict[str, Any] | None = None):
    """An answer for every slot listed in ``message``: a line per role, a number to tell them apart."""
    out: dict[str, Any] = {}
    for n, match in enumerate(ROW.finditer(message), start=1):
        slot_id, role = match.groups()
        if slot_id in skip:
            continue
        en, fr = TEXT[role]
        out[slot_id] = {"en": f"{en} number {n}", "fr": f"{fr} numéro {n}"}
    out.update(edit or {})
    return out


class SlotModel:
    """Answers a slot call from its message; records every message."""

    def __init__(self, *edits: Any) -> None:
        self.messages: list[str] = []
        self.edits = list(edits)

    async def generate_structured_content(self, system, user, content_type, max_retries=1):
        self.messages.append(user)
        edit = self.edits[len(self.messages) - 1] if len(self.messages) <= len(self.edits) else {}
        edit = edit or {}
        answer = lines_for(user, skip=set(edit.get("skip", ())), edit=edit.get("set"))
        return {**answer, "__complete": True}


def figure_ref() -> dict[str, Any]:
    return {
        "id": MIMOSA,
        "caption_en": "A mimosa leaf folds when it is touched",
        "caption_fr": "Une feuille de mimosa se ferme quand on la touche",
        "alt_text_en": "A mimosa leaf folding",
        "alt_text_fr": "Une feuille de mimosa qui se ferme",
    }


def chapter(*, figure: bool = False):
    ctx = none_ctx()
    if figure:
        ctx.figures = [figure_ref()]
    return ctx, pack("1.1", "en")


def kinds(script: beats.Script, scene: int = 0) -> list[str]:
    out = []
    for step in script.scenes[scene]["steps"]:
        if step["type"] in ("say", "narrate"):
            out.append(f"{step['type']}:{step.get('who', '')}".rstrip(":"))
        elif step["type"] == "show":
            out.append("show:figure" if "figure" in step else f"show:{step.get('visual')}")
        elif step["type"] == "ask":
            out.append(f"ask:{step['ref']}")
        else:
            out.append(step["type"])
    return out


def spine_of(script: beats.Script, the_pack: dict[str, Any]) -> dict[str, Any]:
    return {
        **{k: v for k, v in the_pack.items() if k in PACK_KEYS},
        **script.spine(),
        "chapter_title": {"en": "The shy snail", "fr": "L'escargot timide"},
    }


async def generate(model: SlotModel, *, figure: bool = False, repairs: int = 1):
    ctx, the_pack = chapter(figure=figure)
    service = StoryFromLessonService(model)
    return ctx, await service.generate_slots_story(ctx, the_pack, max_repair_calls=repairs)


# --------------------------------------------------------------------------
# The early lever: settings
# --------------------------------------------------------------------------


def test_the_story_model_has_the_content_models_options_and_falls_back_to_it():
    content, story = DEFAULTS_BY_KEY["ai-model-content"], DEFAULTS_BY_KEY["ai-model-story"]
    assert story.default == "content" and story.value_type == "string"
    assert set(content.allowed_options) <= set(story.allowed_options)
    assert story.default in story.allowed_options


def test_the_repair_budget_and_the_variant_are_settings_with_safe_defaults():
    budget = DEFAULTS_BY_KEY["story-max-repair-calls"]
    assert budget.default == 1 and budget.validation == {"min": 0, "max": 2}
    variant = DEFAULTS_BY_KEY["story-builder-variant"]
    assert variant.default == "classic" and variant.allowed_options == ["classic", "slots"]


@pytest.mark.parametrize(
    ("raw", "model"),
    [(None, None), ("", None), ("content", None), ("kimi-k2.6", "kimi-k2.6")],
)
def test_an_unset_story_model_is_the_content_model(monkeypatch, raw, model):
    monkeypatch.setattr(story_calls, "_setting", lambda key, default: raw)
    assert story_calls.story_model() == model


@pytest.mark.parametrize(
    ("raw", "budget"), [(0, 0), (1, 1), (2, 2), (7, 2), (-3, 0), ("1", 1), ("x", 1), (True, 1)]
)
def test_the_repair_budget_is_clamped_to_0_2(monkeypatch, raw, budget):
    monkeypatch.setattr(story_calls, "_setting", lambda key, default: raw)
    assert story_calls.repair_budget() == budget


@pytest.mark.parametrize(
    ("raw", "variant"),
    [("slots", "slots"), ("SLOTS", "slots"), ("classic", "classic"), ("v5", "classic")],
)
def test_only_slots_turns_the_slot_builder_on(monkeypatch, raw, variant):
    monkeypatch.setattr(story_calls, "_setting", lambda key, default: raw)
    assert story_calls.builder_variant() == variant


def test_a_slots_call_has_its_own_token_cap_sized_to_the_slots():
    assert story_calls.MAX_TOKENS["slots"] == 6_000
    assert story_calls.slots_max_tokens(1) == story_calls.SLOTS_MIN_TOKENS
    assert story_calls.slots_max_tokens(21) == 600 + 90 * 21
    assert story_calls.slots_max_tokens(500) == 6_000
    assert story_calls.CALL_CAPS["slots"] == 6_000 / 25 + 60


# --------------------------------------------------------------------------
# The script: what code writes
# --------------------------------------------------------------------------


def test_a_beat_plays_in_the_order_the_code_decides():
    script = beats.build_script(*chapter())
    assert kinds(script, 0) == [
        "narrate",  # S set
        "say:friend",  # S hook
        "say:hero",  # S hero
        "say:hero",  # the plan's discovery, from code
        "concept",  # the plan's title, S rows
        "ask:q1",
        "ask:q2",
        "say:family",  # S after
    ]
    # The paper task, then a story ending: never a task among the last steps.
    last = kinds(script, 2)
    assert last[-4:] == ["narrate", "photo", "say:hero", "narrate"]


def test_a_picture_is_shown_before_anyone_says_look_when_the_beat_has_evidence():
    script = beats.build_script(*chapter(figure=True))
    assert kinds(script, 0)[:3] == ["narrate", "show:figure", "say:friend"]
    assert script.scenes[0]["steps"][1] == {"type": "show", "figure": 1}
    assert [e["figure"] for e in script.evidence] == [1, None, None]
    # The other beats share no word with it: they are never given a picture.
    assert all("figure" not in s for sc in script.scenes[1:] for s in sc["steps"])


def test_no_evidence_no_picture():
    ctx, the_pack = chapter()
    ctx.figures = [{**figure_ref(), "caption_en": "A truck on a road", "caption_fr": "Un camion"}]
    ctx.figures[0].update({"alt_text_en": "truck", "alt_text_fr": "camion"})
    assert beats.assign_figures(ctx) == {}


def test_every_question_is_asked_once_by_the_beat_of_its_idea():
    ctx, the_pack = chapter()
    script = beats.build_script(ctx, the_pack)
    asked = [s["ref"] for sc in script.scenes for s in sc["steps"] if s["type"] == "ask"]
    assert sorted(asked) == sorted([*ctx.assigned_refs, *[q["id"] for q in the_pack["questions"]]])
    assert len(asked) == len(set(asked))
    assert beats.place_questions(ctx, the_pack) == [["q1", "q2"], ["q3"], ["x1"]]


def test_every_slot_has_an_id_a_known_role_a_hard_cap_and_a_brief():
    script = beats.build_script(*chapter())
    ids = [s.id for s in script.slots]
    assert len(ids) == len(set(ids)) == 21
    for slot in script.slots:
        assert slot.role in beats.ROLES and slot.brief and 0 < slot.cap <= beats.LINE_WORDS
        if slot.role == beats.CARD_ROW:
            assert slot.fact  # a row comes from the lesson's IDEA
    roles = {s.role for s in script.slots}
    assert {beats.NARRATION, beats.HOOK, beats.HERO_LINE, beats.REACTION, beats.CARD_ROW} <= roles
    assert {beats.LEAD, beats.CLOSE} <= roles
    # A card is at most 20 words: its title and its two rows.
    for scene in script.scenes:
        card = next(s for s in scene["steps"] if s["type"] == "concept")
        title = max(beats.words(card["title"]["en"]), beats.words(card["title"]["fr"]))
        caps = [
            s.cap
            for s in script.slots
            if s.role == beats.CARD_ROW and s.id.startswith(f"b{script.scenes.index(scene) + 1}.")
        ]
        assert title + sum(caps) <= 20


def test_the_script_is_deterministic_and_its_variant_is_seeded_per_chapter():
    first, second = beats.build_script(*chapter()), beats.build_script(*chapter())
    assert [(s.id, s.brief) for s in first.slots] == [(s.id, s.brief) for s in second.slots]
    assert first.seed == second.seed
    ctx, the_pack = chapter()
    ctx.chapter_index = 2
    other = beats.build_script(ctx, the_pack)
    assert other.seed != first.seed
    assert story_slots.build_message(ctx, other) != story_slots.build_message(*chapter()[:1], first)


def test_the_message_carries_the_voices_the_gag_and_the_rules_but_no_screenplay():
    ctx, the_pack = chapter()
    script = beats.build_script(ctx, the_pack)
    message = story_slots.build_message(ctx, script)
    assert "RUNNING GAG" in message and "VOICES" in message and "VARIANT" in message
    assert "Detectives, to work!" in message  # the catchphrase, with its budget
    assert "- b1.hook | hook | said by friend | at most 12 words" in message
    assert '"type": "say"' not in message and '"scenes"' not in message
    assert "Aminata" in message  # the names the story must not use


# --------------------------------------------------------------------------
# The bet: only from data the plan gives
# --------------------------------------------------------------------------


def bet_chapter(spec: dict[str, Any], *, figure: bool = True):
    ctx, the_pack = chapter(figure=figure)
    ctx.plan_entry = copy.deepcopy(ctx.plan_entry)
    ctx.plan_entry["beats"][0]["demo"] = spec
    return ctx, the_pack


def test_a_beat_with_no_demo_data_has_no_bet_and_says_so():
    script = beats.build_script(*chapter(figure=True))
    assert [e["bet"] for e in script.evidence] == [False, False, False]


def test_a_compare_bet_takes_its_verdict_from_the_data_and_asks_the_model_only_for_words():
    spec = {"visual": "compare", "params": {"values": [12, 12], "unit": "cm", "scale": "ruler"}}
    ctx, the_pack = bet_chapter(spec)
    script = beats.build_script(ctx, the_pack)
    assert kinds(script, 0)[:6] == [
        "narrate",
        "show:figure",
        "say:friend",
        "say:hero",
        "predict",
        "say:hero",
    ]
    ids = {s.id: s.role for s in script.slots}
    assert ids["b1.label1"] == ids["b1.label2"] == beats.LABEL
    assert (ids["b1.bet"], ids["b1.right"], ids["b1.wrong"]) == (
        beats.BET_PROMPT,
        beats.REACT_RIGHT,
        beats.REACT_WRONG,
    )
    story_slots_filled = lines_for(story_slots.build_message(ctx, script))
    for slot in script.slots:
        slot.apply(story_slots_filled[slot.id])
    beats.finalize(script, ctx)
    step = script.scenes[0]["steps"][4]
    assert [o["is"] for o in step["options"]] == ["a", "b", "equal"]
    assert step["options"][0]["en"] == step["demo"]["params"]["labels"][0]["en"] != ""
    built = poe.clean_demo("compare", step["demo"]["params"])
    assert built["equal"] is True and poe.demo_outcome("compare", built) == "equal"


async def test_an_annotate_bet_has_chips_from_its_labels_and_sits_on_the_figure_shown():
    spec = {
        "visual": "annotate",
        "params": {
            "regions": "halves",
            "labels": [
                {"en": "the left", "fr": "la gauche"},
                {"en": "the right", "fr": "la droite"},
            ],
            "expected": 2,
        },
    }
    ctx, the_pack = bet_chapter(spec)
    script = beats.build_script(ctx, the_pack)
    assert not [s for s in script.slots if s.role == beats.LABEL]
    model = SlotModel()

    async def ask(message, *, repair, max_tokens):
        return await model.generate_structured_content("", message, "story")

    done = await story_slots.fill_script(script, ctx, ask, repairs=1)
    assert done.fallbacks == []
    build = repair.build_story_document(ctx, spine_of(script, the_pack))
    assert not {i.code for i in build.issues} & repair.STORY_CODES
    steps = [s for c in build.doc["chapters"] for sc in c["scenes"] for s in sc["steps"]]
    bets = [s for s in steps if s["type"] == "ask" and s.get("predict")]
    demos = [s for s in steps if s["type"] == "show" and s.get("bet")]
    assert len(bets) == len(demos) == 1
    assert demos[0]["params"]["source_image_id"] == MIMOSA and demos[0]["params"]["expected"] == 2
    question = next(q for q in build.doc["questions"] if q["id"] == bets[0]["ref"])
    assert question["points"] == 0 and question["answer"] == "b" and question["predict"]


# --------------------------------------------------------------------------
# Filling the slots
# --------------------------------------------------------------------------


async def test_a_chapter_is_one_call_valid_and_playable_by_the_current_player():
    model = SlotModel()
    ctx, made = await generate(model, figure=True)
    assert made is not None and made.report.ok and made.variant == "slots"
    assert made.model_calls == 1 and len(model.messages) == 1
    assert made.slot_report["fallbacks"] == [] and made.slot_report["slots"] == 21
    doc = made.doc
    assert doc["sira_builder"] == repair.CHAPTER_BUILDER_VERSION == 4
    course = StoryCourse.model_validate(json.loads(json.dumps(doc)))
    assert validate_story_course(course, generated=True).ok
    steps = [s for c in doc["chapters"] for sc in c["scenes"] for s in sc["steps"]]
    assert sum(1 for s in steps if s["type"] == "ask") == 4
    assert any(s["type"] == "show" and s.get("visual") == "image" for s in steps)
    assert made.report.errors == []


async def test_the_chapter_is_the_same_document_whoever_asks_twice():
    first = (await generate(SlotModel()))[1]
    second = (await generate(SlotModel()))[1]
    assert first.doc == second.doc


async def test_a_slot_over_its_cap_or_missing_is_asked_again_once_alone():
    model = SlotModel(
        {"set": {"b1.hook": {"en": "word " * 30, "fr": "mot " * 30}}, "skip": ["b2.set"]},
    )
    ctx, made = await generate(model)
    assert made.model_calls == 2 and len(model.messages) == 2
    retry = model.messages[1]
    assert "- b1.hook |" in retry and "- b2.set |" in retry and "- b1.set |" not in retry
    assert "at most 12 words" in retry and "2 slots" not in retry.split("REQUEST:")[0]
    assert made.slot_report["invalid"] == ["b1.hook", "b2.set"]
    assert made.slot_report["fallbacks"] == [] and made.report.ok


async def test_a_slot_still_bad_after_the_retry_gets_the_codes_own_line_never_a_failed_chapter():
    bad = {"b1.hook": {"en": "word " * 30, "fr": "mot " * 30}}
    model = SlotModel({"set": bad}, {"set": bad})
    ctx, made = await generate(model)
    assert made is not None and made.report.ok and made.model_calls == 2
    assert made.slot_report["fallbacks"] == ["b1.hook"]
    steps = [s for c in made.doc["chapters"] for sc in c["scenes"] for s in sc["steps"]]
    fallback = {line for lines in beats.FALLBACKS[beats.HOOK] for line in lines[:1]}
    assert any(s.get("en") in fallback for s in steps if s["type"] == "say")


async def test_with_no_repair_budget_a_bad_slot_is_not_asked_again():
    model = SlotModel({"skip": ["b3.after"]})
    ctx, made = await generate(model, repairs=0)
    assert made.model_calls == 1 and len(model.messages) == 1
    assert made.slot_report["fallbacks"] == ["b3.after"] and made.report.ok


async def test_a_card_row_that_fails_is_left_out_not_invented():
    model = SlotModel({"skip": ["b2.row2"]}, {"skip": ["b2.row2"]})
    ctx, made = await generate(model)
    cards = [
        s
        for c in made.doc["chapters"]
        for sc in c["scenes"]
        for s in sc["steps"]
        if s["type"] == "concept" and not s["id"].startswith("situation-")
    ]
    assert made.report.ok and len(cards) == 3 and [len(c["en"]) for c in cards] == [2, 1, 2]


async def test_an_answer_that_is_mostly_unusable_is_told_the_classic_way_not_published():
    model = SlotModel(
        {
            "skip": [
                f"b{n}.{k}"
                for n in (1, 2, 3)
                for k in ("set", "hook", "hero", "row1", "row2", "after")
            ]
        }
    )
    ctx, made = await generate(model, repairs=0)
    assert made is None


@pytest.mark.parametrize(
    ("value", "why"),
    [
        ({"en": "Awa: look at that", "fr": "Awa : regarde ça"}, "speaker"),
        ({"en": "Look at the lesson now", "fr": "Regarde la leçon"}, "lesson"),
        ({"en": "Aminata looks at it", "fr": "Aminata le regarde"}, "name"),
        ({"en": "Regarde le chat dans la cour", "fr": "Regarde le chat dans la cour"}, "French"),
        ({"en": "Look", "fr": ""}, "no fr"),
        ({"en": "Look at that", "fr": "Regarde ça"}, None),
    ],
)
def test_a_slot_value_is_checked_for_names_speakers_meta_talk_and_language(value, why):
    ctx, the_pack = chapter()
    script = beats.build_script(ctx, the_pack)
    slot = script.slot("b1.hook")
    cleaned, problem = story_slots.check_value(slot, value, ctx, story_slots._blocked(ctx))
    assert (problem is None) == (why is None), problem
    assert (cleaned is not None) == (why is None)


def test_quotes_around_a_line_are_stripped_not_refused():
    ctx, the_pack = chapter()
    slot = beats.build_script(ctx, the_pack).slot("b1.hook")
    cleaned, problem = story_slots.check_value(
        slot, {"en": "«Look at that»", "fr": '"Regarde ça"'}, ctx, []
    )
    assert problem is None and cleaned == {"en": "Look at that", "fr": "Regarde ça"}


# --------------------------------------------------------------------------
# What it costs: calls and tokens, by kind
# --------------------------------------------------------------------------


async def test_the_run_counts_its_calls_and_tokens_by_kind_and_a_retry_is_a_repair():
    model = SlotModel({"skip": ["b1.hook"]})
    with usage_tally() as tally:
        await generate(model)
    summary = tally.summary()
    assert summary["slots"]["calls"] == 1 and summary["repair"]["calls"] == 1
    assert summary["slots"]["output_tokens"] > 0 and summary["slots"].get("estimated") is True


async def test_a_chapters_slot_call_is_a_fraction_of_a_screenplay():
    model = SlotModel()
    ctx, made = await generate(model, figure=True)
    answer = json.dumps(lines_for(model.messages[0]), ensure_ascii=False)
    tokens = round(len(answer) / 3.2)
    slots = made.slot_report["slots"]
    assert slots == 21 and tokens < 1_100
    assert story_calls.slots_max_tokens(slots) > tokens * 1.5  # headroom, never a runaway


def test_the_ledger_counts_the_output_tokens_of_the_call_kind():
    from app.ai.usage_context import ai_usage_context, note_usage

    with usage_tally() as tally:
        with ai_usage_context(call_kind="slots"):
            from app.ai.usage_context import current_ai_context

            note_usage(current_ai_context().call_kind, 321)
        note_usage(None, 5)
        note_usage("slots", "many")
    assert tally.summary() == {"slots": {"calls": 0, "output_tokens": 321}}


# --------------------------------------------------------------------------
# Golden: the slot builder's own output is locked
# --------------------------------------------------------------------------


def digest(value: Any) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode()).hexdigest()


async def test_the_chapter_built_from_slots_is_locked_by_a_digest():
    _ctx, made = await generate(SlotModel(), figure=True)
    assert digest(made.doc) == GOLDEN_SLOTS_CHAPTER, digest(made.doc)


GOLDEN_SLOTS_CHAPTER = "285ff3c2569a1307ab5e68903e0856c6a957750400118cdfb30e5273e6f1a8ef"


# --------------------------------------------------------------------------
# Never the same line twice in a module
# --------------------------------------------------------------------------


async def test_a_line_an_earlier_chapter_said_or_another_slot_says_is_asked_again():
    ctx, the_pack = chapter()
    ctx.earlier_line_keys = {
        key: "1.0"
        for key in repair.repeat_keys(
            {
                "type": "say",
                "en": "Look at that clue closely number 2",
                "fr": "Regarde bien cet indice numéro 2",
            }
        )
    }
    model = SlotModel(
        {
            "set": {
                "b2.hook": {
                    "en": "Look at that clue closely number 3",
                    "fr": "Regarde bien cet indice numéro 3",
                }
            }
        }
    )
    made = await StoryFromLessonService(model).generate_slots_story(ctx, the_pack)
    # b1.hook (number 2) is a line of an earlier chapter; b2.hook copies b1.hook's neighbour.
    assert "b1.hook" in made.slot_report["invalid"]
    assert made.model_calls == 2 and made.report.ok


def test_the_lead_ins_of_a_slots_chapter_avoid_those_of_earlier_chapters_and_its_own():
    from app.domain.services.story_leadins import add_leadins, leadin_keys, leadin_step

    def scenes():
        return [
            {"steps": [{"type": "ask", "ref": f"q{n}"}, {"type": "narrate", "en": "x", "fr": "y"}]}
            for n in range(1, 8)
        ]

    classic = scenes()
    assert add_leadins(classic, "1.2") == 7
    # A classic chapter (no ``avoid``) is chosen exactly as before: by the hash and its place.
    assert classic[0]["steps"][0] == leadin_step("1.2:q1", 0)
    earlier = {k for n in range(5) for k in leadin_keys(leadin_step("1.2:q1", n))}
    slotted = scenes()
    assert add_leadins(slotted, "1.2", avoid=set(earlier)) == 7
    keys = [leadin_keys(sc["steps"][0]) for sc in slotted]
    assert all(not k & earlier for k in keys)  # none of the five an earlier chapter has
    assert len({frozenset(k) for k in keys}) == 7  # and the seven of this chapter all differ
