"""The Hero's Journey as a table applied by code (#2749, linear mode).

Pure tests (no model, no database). A bible and a plan with no ``journey`` (every
stored one) are built, told and checked exactly as before: the legacy plan
message is a fixture taken from ``origin/dev`` BEFORE this change.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from app.ai.prompts.story_bible import build_bible_messages
from app.ai.prompts.story_plan import build_plan_user_message, journey_system_block
from app.domain.services import story_journey as table
from app.domain.services.story_bible import StoryBible, normalise_bible
from app.domain.services.story_plan import (
    default_plan,
    global_digest,
    normalise_plan,
    validate_plan,
)
from app.infrastructure.config.platform_defaults import DEFAULTS_BY_KEY
from tests.test_story_bible import MODULE, OTHER
from tests.test_story_bible import course as bible_course
from tests.test_story_cast_policy import modules, request_with
from tests.test_story_screenplay_module import data, make_run, plan_answer
from tests.test_story_v4_builder import build, chapter_ctx, lint_codes, spine

FIXTURES = Path(__file__).parent / "fixtures"

BIBLE_PROMPT_GOLDEN = {
    (True, None): "13cbface20ca2b7f",
    (True, "none"): "f5e37d644078663f",
    (True, "cameo"): "991f821b58c6a808",
    (False, None): "7fe21d9d005b4621",
    (False, "none"): "810d223ca8582642",
    (False, "cameo"): "04d1b4746626ba48",
}
PLAN_SYSTEM_GOLDEN = {
    "ai-prompt-story-plan-kids-system": "4643bd50b0cc028851818c72a28d1d9b6dc863f62a4695b85f98e11a1c5d8f8f",
    "ai-prompt-story-plan-system": "f32eac65d1c79f229154d37e19a14e6836eaae75ee43bb71a01bd8e560fbb515",
}


# --------------------------------------------------------------------------
# The table
# --------------------------------------------------------------------------

START, TRIALS, SUMMIT, RETURN = (
    list(m) for m in (table.START, table.TRIALS, table.SUMMIT, table.RETURN)
)


@pytest.mark.parametrize(
    ("count", "expected"),
    [
        (1, [START + TRIALS + SUMMIT + RETURN]),
        (2, [START, TRIALS + SUMMIT + RETURN]),
        (3, [START, TRIALS + SUMMIT, RETURN]),
        (4, [START, TRIALS, SUMMIT, RETURN]),
        (5, [START, TRIALS, TRIALS, SUMMIT, RETURN]),
        (6, [START, TRIALS, TRIALS, TRIALS, SUMMIT, RETURN]),
    ],
)
def test_the_stages_are_dealt_by_the_number_of_chapters(count, expected):
    assert table.distribute(count) == expected
    flat = [s for stages in table.distribute(count) for s in stages]
    assert flat[-3:] == RETURN  # the Return is played in the last chapter
    assert flat[:5] == START  # the Start in the first
    assert set(flat) == set(range(1, 13))


def test_stage_four_is_left_out_without_a_mentor_and_the_chapter_keeps_the_rest():
    for count in range(1, 7):
        without = table.distribute(count, mentor=False)
        assert all(4 not in stages for stages in without)
        assert without[0] == [1, 2, 3, 5] + ([6, 7, 8, 9, 10, 11, 12] if count == 1 else [])
    assert [table.mentor_in_story(p) for p in ("none", "cameo", "lead", None)] == [
        False,
        True,
        True,
        False,
    ]


def test_the_blocks_of_the_stages():
    assert table.stage_blocks([3]) == ["bet", "mistake"]
    assert table.stage_blocks([8]) == ["bet", "mistake"]
    assert table.stage_blocks([5, 6, 9, 11, 12]) == ["machine", "ask", "card", "ask", "teaser"]
    assert table.stage_blocks([1, 2, 4, 7, 10]) == []
    assert len(table.STAGES) == 12


def test_words_cuts_to_thirty_words_and_ignores_non_text():
    assert len(table.words("w " * 50).split()) == 30
    assert table.words(None) == table.words({"a": 1}) == table.words(True) == ""


# --------------------------------------------------------------------------
# The bible
# --------------------------------------------------------------------------


def make_bible(journey: bool, policy: str | None = "cameo", raw_journey=None):
    raw = copy.deepcopy(data()["bible"])
    if raw_journey is not None:
        raw["journey"] = raw_journey
    return normalise_bible(
        raw, is_kids=True, modules=modules(), country="BF", mentor_policy=policy, journey=journey
    )


def test_a_bible_made_with_the_switch_off_is_byte_identical():
    from app.domain.services.story_bible import bible_digest

    raw = {"journey": {"quest": "x", "shadow": "y"}}
    off = normalise_bible(raw, is_kids=True, mentor_policy="cameo")
    assert "journey" not in off
    assert bible_digest(off) == bible_digest(
        normalise_bible({}, is_kids=True, mentor_policy="cameo")
    )
    assert normalise_bible(raw, is_kids=False) == normalise_bible({}, is_kids=False)


def test_a_bible_made_with_the_switch_on_has_a_quest_and_a_shadow_in_thirty_words():
    long = "word " * 60
    content = make_bible(True, raw_journey={"quest": long, "shadow": "Big numbers are scary"})
    assert content["journey"]["template"] == "heros_journey"
    assert len(content["journey"]["quest"].split()) == 30
    assert content["journey"]["shadow"] == "Big numbers are scary"
    assert content["cast_policy"] == {"mentor": "cameo"}
    empty = make_bible(True)
    assert empty["journey"] == {"template": "heros_journey", "quest": "", "shadow": ""}


def test_a_journey_needs_a_cast_policy():
    assert "journey" not in make_bible(True, policy=None)


def test_the_bible_prompt_asks_for_a_quest_and_a_shadow_only_with_the_switch():
    course = bible_course()
    for (kids, policy), digest in BIBLE_PROMPT_GOLDEN.items():
        system, user = build_bible_messages(
            course, [MODULE, OTHER], is_kids=kids, country="BF", mentor_policy=policy
        )
        assert hashlib.sha256((system + "\n" + user).encode()).hexdigest()[:16] == digest
        assert '"quest"' not in user
    _system, user = build_bible_messages(
        course, [MODULE, OTHER], is_kids=True, country="BF", mentor_policy="cameo", journey=True
    )
    assert '"quest"' in user and '"shadow"' in user and "at most 30 words" in user
    assert user.index('"quest"') < user.index('"__complete"')


def test_the_switch_is_a_setting_that_is_off_by_default(monkeypatch):
    from app.domain.services import platform_settings_service as pss
    from app.domain.services.story_bible import _journey_enabled

    setting = DEFAULTS_BY_KEY["story-journey-enabled"]
    assert setting.default is False and setting.value_type == "boolean"

    class Cache:
        value: object = False

        def get(self, key, default=None):
            assert key == "story-journey-enabled"
            return self.value

    cache = Cache()
    monkeypatch.setattr(pss.SettingsCache, "instance", classmethod(lambda cls: cache))
    assert _journey_enabled() is False
    cache.value = True
    assert _journey_enabled() is True


# --------------------------------------------------------------------------
# The plan
# --------------------------------------------------------------------------


def journey_request(policy: str = "cameo", **kwargs):
    base = request_with(policy)
    content = copy.deepcopy(base.bible.content)
    content["journey"] = {
        "template": "heros_journey",
        "quest": "Read, compare and write any number up to the billions.",
        "shadow": "A longer number is always a bigger idea, whatever its digits.",
    }
    return replace(base, bible=StoryBible.of(content), journey=content["journey"], **kwargs)


def journey_answer(request):
    raw = copy.deepcopy(plan_answer())
    for index, chapter in enumerate(raw["chapters"]):
        chapter["question"] = f"Why does chapter {index + 1} matter to the friends?"
        chapter["ends_on"] = "Next, the friends look for the biggest number of all."
    return raw


def stages_of(plan):
    out = [c["stages"] for c in plan["chapters"]]
    if plan.get("rally"):
        out.append(plan["rally"]["stages"])
    return out


@pytest.mark.parametrize("policy", ["cameo", "lead", "none"])
def test_a_journey_plan_has_stages_and_a_question_on_every_chapter(policy):
    request = journey_request(policy)
    assert request.has_rally
    plan, _gaps = normalise_plan(journey_answer(request), request)
    assert plan["journey"] == {"template": "heros_journey", "mode": "linear"}
    count = len(plan["chapters"]) + 1
    expected = table.distribute(count, mentor=policy != "none")
    assert stages_of(plan) == expected
    assert (4 in expected[0]) == (policy != "none")
    assert all(c["question"] and len(c["question"].split()) <= 30 for c in plan["chapters"])
    assert "question" not in plan["rally"] and plan["rally"]["stages"] == expected[-1]
    assert expected[-1][-3:] == RETURN  # the Return is in the rally


def test_a_journey_plan_without_a_rally_plays_the_return_in_its_last_chapter():
    request = journey_request(has_rally=False)
    raw = journey_answer(request)
    raw.pop("rally", None)
    plan, _ = normalise_plan(raw, request)
    assert "rally" not in plan
    assert stages_of(plan) == table.distribute(len(plan["chapters"]))
    assert plan["chapters"][-1]["stages"][-3:] == RETURN


def test_a_missing_question_is_built_in_code_and_a_long_one_is_cut():
    request = journey_request()
    raw = journey_answer(request)
    raw["chapters"][0]["question"] = ""
    raw["chapters"][1]["question"] = "why " * 80
    plan, gaps = normalise_plan(raw, request)
    first = request.lessons[0].title["en"]
    assert plan["chapters"][0]["question"] == f"What is «{first}» really about?"
    assert len(plan["chapters"][1]["question"].split()) == 30
    assert any("question built" in g for g in gaps)


def test_the_default_plan_of_a_journey_request_has_the_same_keys():
    request = journey_request()
    plan = default_plan(request)
    assert plan["journey"] == {"template": "heros_journey", "mode": "linear"}
    assert stages_of(plan) == table.distribute(len(plan["chapters"]) + 1)
    for chapter, lesson in zip(plan["chapters"], request.lessons, strict=True):
        assert chapter["question"] == f"What is «{lesson.title['en']}» really about?"
    assert plan["cast_policy"] == {"mentor": "cameo"}


def test_a_legacy_default_plan_and_a_new_plan_without_a_journey_have_no_new_keys():
    legacy = default_plan(make_run("en")[1].request)
    assert "journey" not in legacy
    assert all("stages" not in c and "question" not in c for c in legacy["chapters"])
    assert "stages" not in legacy["rally"]
    no_journey = request_with("cameo")  # a new plan whose bible has no journey
    plan, _ = normalise_plan(copy.deepcopy(plan_answer()), no_journey)
    assert "journey" not in plan
    assert all("stages" not in c and "question" not in c for c in plan["chapters"])
    assert "stages" not in plan["rally"]
    # A journey needs a cast policy: a journey with no policy is no journey.
    odd = replace(make_run("en")[1].request, journey={"template": "heros_journey"})
    assert not odd.linear
    assert "journey" not in default_plan(odd)


def test_an_incremental_re_plan_keeps_stages_and_ends_on_and_rewrites_the_question():
    request = journey_request()
    plan, _ = normalise_plan(journey_answer(request), request)
    raw = journey_answer(request)
    unit = request.lessons[1].unit_number
    for chapter in raw["chapters"]:
        chapter["question"] = "A brand new question?"
        chapter["ends_on"] = "Something else entirely."
        chapter["goal"] = "A new goal"
    again, _ = normalise_plan(raw, request, previous=plan, rewritten={unit})
    before = {c["unit"]: c for c in plan["chapters"]}
    for chapter in again["chapters"]:
        old = before[chapter["unit"]]
        assert chapter["stages"] == old["stages"] and chapter["ends_on"] == old["ends_on"]
        if chapter["unit"] == unit:
            assert chapter["question"] == "A brand new question?"
            assert chapter["goal"] == "A new goal"
        else:
            assert chapter == old
    assert again["journey"] == plan["journey"] and again["rally"] == plan["rally"]
    assert global_digest(again) == global_digest(plan)


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


def codes(raw, request) -> set[str]:
    return {i.code for i in validate_plan(raw, request)}


def test_a_journey_plan_passes_with_a_question_and_a_statement_teaser():
    request = journey_request()
    assert codes(journey_answer(request), request) == set()


def test_a_journey_plan_needs_a_short_question_and_a_teaser_that_is_no_question():
    request = journey_request()
    raw = journey_answer(request)
    raw["chapters"][0]["question"] = ""
    assert codes(raw, request) == {"plan_question_missing"}
    raw = journey_answer(request)
    raw["chapters"][0]["question"] = "why " * 31
    assert codes(raw, request) == {"plan_question_long"}
    raw = journey_answer(request)
    raw["chapters"][0]["ends_on"] = "Will the friends find the biggest number?"
    assert codes(raw, request) == {"plan_teaser_is_question"}


def test_the_last_chapter_without_a_rally_may_end_as_it_likes():
    request = journey_request(has_rally=False)
    raw = journey_answer(request)
    raw.pop("rally", None)
    raw["chapters"][-1]["ends_on"] = "Who knows?"
    assert "plan_teaser_is_question" not in codes(raw, request)
    raw["chapters"][-2]["ends_on"] = "Who knows?"
    assert "plan_teaser_is_question" in codes(raw, request)


def test_a_legacy_plan_and_a_plan_without_a_journey_are_validated_as_before():
    for request in (make_run("en")[1].request, request_with("cameo")):
        raw = copy.deepcopy(plan_answer())
        assert codes(raw, request) == set()
        for chapter in raw["chapters"]:
            chapter["ends_on"] = "Will it work?"  # a question is fine, and no question needed
        assert codes(raw, request) == set()


# --------------------------------------------------------------------------
# The prompts
# --------------------------------------------------------------------------


def test_the_message_of_a_legacy_request_is_what_it_was_before():
    expected = json.loads((FIXTURES / "story_plan_message_legacy.json").read_text("utf-8"))
    for language in ("en", "fr"):
        assert build_plan_user_message(make_run(language)[1].request) == expected[language]


def test_the_two_plan_system_prompts_keep_their_default_text():
    for key, digest in PLAN_SYSTEM_GOLDEN.items():
        assert hashlib.sha256(DEFAULTS_BY_KEY[key].default.encode()).hexdigest() == digest


def test_a_journey_message_lists_stages_quest_shadow_and_never_says_unresolved():
    request = journey_request(next_module_title={"en": "Fractions", "fr": "Les fractions"})
    text = build_plan_user_message(request)
    assert "unresolved" not in text.lower()
    assert "THE COURSE QUEST" in text and "Read, compare and write" in text
    assert "THE SHADOW" in text and "A longer number" in text
    assert "=== THE JOURNEY (linear)" in text
    for line in table.stage_lines([1, 2, 3, 5]):
        assert line in text
    assert '"question": "the story question' in text
    assert "not a question" in text
    assert "«Fractions»" in text
    block = journey_system_block(request)
    assert "unresolved" not in block.lower() and "replaces rules 5 and 6" in block


def test_a_journey_message_names_no_next_module_when_there_is_none():
    text = build_plan_user_message(journey_request())
    assert "there is no next module to name" in text


def test_a_journey_message_without_a_rally_does_not_say_unresolved_either():
    text = build_plan_user_message(journey_request(has_rally=False))
    assert "unresolved" not in text.lower() and "never a cliffhanger" in text


def test_a_message_of_a_new_plan_without_a_journey_has_no_journey_words():
    text = build_plan_user_message(request_with("cameo"))
    assert "THE JOURNEY" not in text and "THE COURSE QUEST" not in text
    assert "unresolved" in text


# --------------------------------------------------------------------------
# The chapter prompts and the cold-open lint
# --------------------------------------------------------------------------


def journey_ctx(unit: str):
    from app.ai.prompts.story_from_lesson import _rally_block, _this_chapter_block  # noqa: F401

    ctx = chapter_ctx(unit)
    request = journey_request()
    plan, _ = normalise_plan(journey_answer(request), request)
    ctx.plan = plan
    ctx.plan_entry = next(c for c in plan["chapters"] if c["unit"] == unit)
    return ctx, plan


def test_the_chapter_prompt_prints_stages_and_question_for_a_journey_plan_only():
    from app.ai.prompts.story_from_lesson import _this_chapter_block

    ctx, plan = journey_ctx("1.1")
    text = _this_chapter_block(ctx, {})
    assert "HERO'S JOURNEY STAGES" in text and "1. Ordinary world" in text
    assert (
        f"STORY QUESTION (ask it near the start, answer it by the end): {ctx.plan_entry['question']}"
        in text
    )
    assert "unresolved" not in text.lower()
    legacy = chapter_ctx("1.1")
    assert "JOURNEY" not in _this_chapter_block(legacy, {}) and "STORY QUESTION" not in (
        _this_chapter_block(legacy, {})
    )


def test_the_rally_prompt_prints_its_stages():
    from app.ai.prompts.story_from_lesson import _rally_block

    ctx, plan = journey_ctx("1.1")
    ctx.plan_entry = plan["rally"]
    text = _rally_block(ctx)
    assert "12. Elixir" in text and "STORY QUESTION" not in text


def test_a_journey_chapter_does_not_raise_the_cold_open_lint():
    ctx, plan = journey_ctx("1.2")
    the_spine = spine("1.2")
    first = the_spine["scenes"][0]
    words = " ".join(
        str(s.get("en") or "") for s in first["steps"] if isinstance(s, dict) and s.get("en")
    )
    previous = plan["chapters"][0]
    assert previous["ends_on"].endswith("biggest number of all.")
    # opens_on picks up the previous ends_on, now a next-topic statement.
    ctx.plan_entry = {**ctx.plan_entry, "opens_on": f"{previous['ends_on']} {words}"}
    ctx.previous_scene = {"place": "x", "lines": ["narrator: The friends look at the biggest."]}
    result = build(ctx, the_spine)
    assert "cold_open" not in lint_codes(result)
