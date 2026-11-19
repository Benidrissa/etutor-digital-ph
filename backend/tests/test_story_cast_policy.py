"""The optional mentor (#2710): the cast policy, the lead-ins, the gates, old stories untouched.

Pure tests (no model, no database), on the kids biology episode of
``fixtures/story_screenplay_module.json``. The ``GOLDEN`` digests were taken on
``origin/dev`` BEFORE this change: they prove that a bible or a plan with no
``cast_policy`` (every stored one) is built byte for byte as it always was, so
no story goes stale and nothing is regenerated.
"""

from __future__ import annotations

import copy
import uuid
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.ai.prompts.audience import AudienceContext
from app.ai.prompts.story_bible import build_bible_messages
from app.ai.prompts.story_plan import build_plan_user_message
from app.domain.services import story_repair as repair
from app.domain.services.story_bible import BibleModule, StoryBible, doc_cast, normalise_bible
from app.domain.services.story_cast_policy import (
    CAMEO,
    LEAD,
    NONE,
    bible_policy,
    choose_cast_policy,
    course_cast_policy,
    module_policy,
    normalise_override,
    policy_of,
)
from app.domain.services.story_leadins import LEADINS, add_leadins, leadin_index, leadin_step
from app.domain.services.story_plan import (
    default_plan,
    normalise_plan,
    plan_cast_policy,
    plan_digest,
    validate_plan,
)
from tests.test_story_screenplay_module import data, make_run, plan_answer
from tests.test_story_v4_builder import build, chapter_ctx, codes, lint_codes, spine

GOLDEN = {
    "bible_empty_kids": "06682ddc0e5222035f1fcf12065ab92aec972b766dd1000813398d42d8ab48d6",
    "bible_empty_adult": "b4c201c58fff771312f9fd38404afcb4cc622f7efcba52ecae41a90b7e10fab2",
    "bible_cast_kids": "150066c6a86a4d314156dbbeeca614da336855a58eb3c6f4558af68cd4e34e2f",
    "bible_cast_adult": "f6e8b9de5a957c9155eb8f0c0e155d49fb4b6f8d3dd9e3e9c15881ce5308b277",
    "bible_fixture": "2a7a07cc0a4a8a90515b2eb5659a7415f89a55df07c99a5429111133d7ca9b15",
    "plan_fixture": "9ab06f6e2821aba1a7ef29ec8c53fa1777c9af317bfab9bb235182464fc604e9",
    "plan_default_en": "b99f6290f3349b4c781a01074c15de0fd802cd621d39a4b71143e8f56b582e64",
}


def course(title: str = "Plants", description: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.UUID(int=1),
        title_en=title,
        title_fr=title,
        description_en=description,
        description_fr="",
        taxonomy_categories=[],
    )


def kids(age_min: int | None, age_max: int | None) -> AudienceContext:
    return AudienceContext(is_kids=True, age_min=age_min, age_max=age_max)


# --------------------------------------------------------------------------
# choose_cast_policy
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "audience", "expected"),
    [
        # 6-9 year-olds, or an apprenticeship: a cameo.
        ("Counting with seeds", kids(6, 9), CAMEO),
        ("Counting with seeds", kids(3, 6), CAMEO),
        ("Counting with seeds", kids(6, 12), CAMEO),  # average 9
        ("Tailoring: a first apprenticeship", kids(10, 14), CAMEO),
        ("Atelier de couture", "adult", CAMEO),
        # 10 and up, adults, unknown ages, inquiry and experiment topics: none.
        ("Counting with seeds", kids(10, 14), NONE),
        ("Counting with seeds", kids(12, 18), NONE),
        ("Counting with seeds", "adult", NONE),
        ("Counting with seeds", "kids", NONE),
        ("Les expériences du vivant", kids(6, 9), NONE),
        ("Investigate the water cycle", kids(6, 9), NONE),
        # Safety and high-risk health: a lead, whatever the age.
        ("First aid for burns", kids(12, 18), LEAD),
        ("Premiers secours", "adult", LEAD),
        ("Vaccination and outbreaks", kids(10, 14), LEAD),
        ("La sécurité au marché", kids(10, 14), LEAD),
    ],
)
def test_the_rules_of_choose_cast_policy(title, audience, expected):
    assert choose_cast_policy(course(title), None, audience) == expected


def test_the_module_and_the_description_count_too():
    module = SimpleNamespace(title_en="Snake bites", title_fr="", description_en="")
    assert choose_cast_policy(course(), module, kids(10, 14)) == LEAD
    described = course("Plants", "How to avoid poisoning from wild fruit")
    assert choose_cast_policy(described, None, kids(10, 14)) == LEAD


@pytest.mark.parametrize(
    ("override", "expected"),
    [("never", NONE), ("always", LEAD), ("auto", CAMEO), ("nonsense", CAMEO), (None, CAMEO)],
)
def test_the_admin_override(override, expected):
    """``never`` and ``always`` beat every rule; anything else is ``auto``."""
    safe = course("First aid")
    young = course("Counting with seeds")
    assert choose_cast_policy(safe, None, kids(6, 9), override="never") == NONE
    assert choose_cast_policy(young, None, kids(10, 14), override="always") == LEAD
    assert choose_cast_policy(young, None, kids(6, 9), override=override) == expected
    assert normalise_override(override) == (override if override in ("never", "always") else "auto")


def test_a_course_is_as_strong_as_its_strongest_module():
    modules = [
        BibleModule(uuid.UUID(int=1), 1, {"en": "Seeds", "fr": "Graines"}),
        BibleModule(uuid.UUID(int=2), 2, {"en": "First aid", "fr": "Secours"}),
    ]
    assert course_cast_policy(course(), modules, kids(10, 14)) == LEAD
    assert course_cast_policy(course(), modules[:1], kids(10, 14)) == NONE


def test_a_module_never_exceeds_what_its_bible_drew():
    none_bible = {"cast_policy": {"mentor": "none"}}
    lead_bible = {"cast_policy": {"mentor": "lead"}}
    assert module_policy(none_bible, LEAD) == NONE
    assert module_policy(lead_bible, CAMEO) == CAMEO
    assert module_policy({}, LEAD) is None  # a legacy bible: the plan carries no policy
    assert plan_cast_policy({}, course(), None, "adult", "always") is None
    assert plan_cast_policy(lead_bible, course(), None, "adult", "always") == LEAD
    assert policy_of({}) == LEAD and bible_policy({}) is None


# --------------------------------------------------------------------------
# The bible
# --------------------------------------------------------------------------


def modules() -> list[BibleModule]:
    module = data()["module"]
    return [BibleModule(uuid.UUID(module["module_id"]), 1, module["module_title"])]


def test_a_bible_with_no_mentor_has_none_in_its_cast_and_its_art():
    raw = data()["bible"]
    content = normalise_bible(raw, is_kids=True, modules=modules(), mentor_policy="none")
    assert [m["id"] for m in content["cast"]] == ["hero", "friend", "family", "margo"]
    assert [m["id"] for m in doc_cast(content)] == ["hero", "friend", "family", "margo"]
    assert content["cast_policy"] == {"mentor": "none"}
    for policy in ("cameo", "lead"):
        with_mentor = normalise_bible(raw, is_kids=True, modules=modules(), mentor_policy=policy)
        assert "mentor" in [m["id"] for m in with_mentor["cast"]]
        assert with_mentor["cast_policy"] == {"mentor": policy}


def test_the_bible_prompt_asks_for_no_mentor_only_when_there_is_none():
    old_system, old_user = build_bible_messages(
        course(), modules(), is_kids=True, country="BF", mentor_policy=None
    )
    assert '"id": "mentor"' in old_user and "hero, friend, mentor, family, margo" in old_user
    system, user = build_bible_messages(
        course(), modules(), is_kids=True, country="BF", mentor_policy="none"
    )
    assert '"id": "mentor"' not in user and "hero, friend, family, margo" in user
    assert "There is no mentor" in user and "no teacher" in system
    cameo = build_bible_messages(
        course(), modules(), is_kids=True, country="BF", mentor_policy="cameo"
    )
    assert "opens or closes" in cameo[1]


# --------------------------------------------------------------------------
# Existing stories are untouched: the digests of everything stored are unchanged
# --------------------------------------------------------------------------


def test_the_digests_of_existing_bibles_are_unchanged():
    from app.domain.services.story_bible import bible_digest

    cast = {"cast": [{"id": "mentor", "name": "Zida", "look": "a tall man"}]}
    cast["cast"].append({"id": "friend", "default_name": "Awa"})
    for kids_, name in ((True, "kids"), (False, "adult")):
        assert bible_digest(normalise_bible({}, is_kids=kids_)) == GOLDEN[f"bible_empty_{name}"]
        built = normalise_bible(cast, is_kids=kids_, country="CI")
        assert bible_digest(built) == GOLDEN[f"bible_cast_{name}"]
        assert "cast_policy" not in built
    assert make_run("en")[1].request.bible.digest == GOLDEN["bible_fixture"]


def test_the_digests_of_existing_plans_are_unchanged():
    for language in ("en", "fr"):
        request = make_run(language)[1].request
        assert request.cast_policy is None
        plan, gaps = normalise_plan(copy.deepcopy(plan_answer()), request)
        assert gaps == [] and "cast_policy" not in plan
        assert plan_digest(plan) == GOLDEN["plan_fixture"]
    assert plan_digest(default_plan(make_run("en")[1].request)) == GOLDEN["plan_default_en"]
    # Its beats still carry the mentor, as they always did.
    assert any(
        "mentor" in beat["cast"]
        for c in default_plan(make_run("en")[1].request)["chapters"]
        for beat in c["beats"]
    )


def test_a_stored_plan_fixture_is_left_as_it_is():
    """The stored plan of the repo is read, never rewritten: its digest is a function of it."""
    import json
    from pathlib import Path

    stored = json.loads(
        (Path(__file__).parent / "fixtures" / "story_module_plan.json").read_text("utf-8")
    )
    assert "cast_policy" not in stored
    before = plan_digest(stored)
    assert policy_of(stored) == LEAD
    assert plan_digest(stored) == before


def test_the_plan_prompt_of_a_legacy_request_has_no_policy_note():
    request = make_run("en")[1].request
    text = build_plan_user_message(request)
    assert "NO MENTOR" not in text and "MENTOR CAMEO" not in text
    assert '"mentor": "..."' in text


# --------------------------------------------------------------------------
# The plan
# --------------------------------------------------------------------------


def request_with(policy: str | None, *, mentor: bool = True):
    request = make_run("en")[1].request
    raw = data()["bible"]
    content = normalise_bible(
        raw, is_kids=True, modules=modules(), country="BF", mentor_policy=policy
    )
    if policy is None:
        assert any(m["id"] == "mentor" for m in content["cast"]) and mentor
    return replace(request, bible=StoryBible.of(content), cast_policy=policy)


def test_a_plan_with_no_mentor_names_none_and_says_so():
    request = request_with("none")
    plan, _gaps = normalise_plan(copy.deepcopy(plan_answer()), request)
    assert plan["cast_policy"] == {"mentor": "none"}
    beats = [b for c in plan["chapters"] for b in c["beats"]]
    assert all("mentor" not in b["cast"] and 2 <= len(b["cast"]) <= 3 for b in beats)
    assert "mentor" not in plan["voices"]
    assert all(c.get("who") != "mentor" for c in plan["catchphrases"])
    code_plan = default_plan(request)
    assert all("mentor" not in b["cast"] for c in code_plan["chapters"] for b in c["beats"])
    text = build_plan_user_message(request)
    assert "NO MENTOR" in text and '"mentor": "..."' not in text
    # The model that still writes him is told so (and the plan is repaired once).
    raw = copy.deepcopy(plan_answer())
    raw["chapters"][0]["beats"][0]["cast"] = ["hero", "mentor"]
    issues = [i for i in validate_plan(raw, request) if i.code == "plan_unknown_cast"]
    assert issues and "no mentor" in issues[0].message


def test_a_cameo_mentor_stays_in_the_first_and_the_last_beat_only():
    request = request_with("cameo")
    raw = copy.deepcopy(plan_answer())
    for chapter in raw["chapters"]:
        for beat in chapter["beats"]:
            beat["cast"] = ["hero", "friend", "mentor"]
    plan, _gaps = normalise_plan(raw, request)
    where = [
        (i, j)
        for i, c in enumerate(plan["chapters"])
        for j, b in enumerate(c["beats"])
        if "mentor" in b["cast"]
    ]
    last = len(plan["chapters"]) - 1
    assert where == [(0, 0), (last, len(plan["chapters"][last]["beats"]) - 1)]
    assert plan["cast_policy"] == {"mentor": "cameo"}
    assert "MENTOR CAMEO" in build_plan_user_message(request)


def test_a_lead_mentor_is_a_plan_made_as_before_plus_its_policy():
    request = request_with("lead")
    plan, _gaps = normalise_plan(copy.deepcopy(plan_answer()), request)
    legacy, _ = normalise_plan(copy.deepcopy(plan_answer()), make_run("en")[1].request)
    assert plan.pop("cast_policy") == {"mentor": "lead"}
    assert plan["chapters"] == legacy["chapters"]


# --------------------------------------------------------------------------
# Chapters: no mentor in the cast, the art or the lines
# --------------------------------------------------------------------------


def none_ctx():
    ctx = chapter_ctx()
    ctx.bible = normalise_bible(
        data()["bible"], is_kids=True, modules=modules(), country="BF", mentor_policy="none"
    )
    ctx.plan = {**ctx.plan, "cast_policy": {"mentor": "none"}}
    return ctx


def test_the_who_aliases_of_the_mentor_go_to_the_friend_when_there_is_none():
    cast = repair._Cast(doc_cast(none_ctx().bible))
    for alias in ("mentor", "teacher", "supervisor"):
        assert cast.resolve(alias) == "friend"
    legacy = repair._Cast(doc_cast(chapter_ctx().bible_content))
    assert legacy.resolve("teacher") == "mentor"


def test_a_kids_chapter_with_no_mentor_has_none_in_its_cast_or_lines_and_still_asks():
    ctx = none_ctx()
    result = build(ctx, spine())
    assert not codes(result) & repair.STORY_CODES
    doc = result.doc
    assert "mentor" not in [m["id"] for m in doc["cast"]]
    steps = [s for c in doc["chapters"] for sc in c["scenes"] for s in sc["steps"]]
    assert "mentor" not in {s.get("who") for s in steps}
    assert all("mentor" not in sc["cast"] for c in doc["chapters"] for sc in c["scenes"])
    assert any(s["type"] == "ask" for s in steps)


# --------------------------------------------------------------------------
# Lead-ins
# --------------------------------------------------------------------------


def test_there_are_twelve_neutral_leadins_in_both_languages_chosen_without_chance():
    assert len(LEADINS) == 12 and len(set(LEADINS)) == 12
    for en, fr in LEADINS:
        assert en and fr and len(en.split()) <= 12 and len(fr.split()) <= 12
    assert leadin_index("1.1:q1") == leadin_index("1.1:q1")
    assert leadin_step("1.1:q1") == leadin_step("1.1:q1")
    assert leadin_step("1.1:q1", 1) != leadin_step("1.1:q1", 0)
    assert leadin_step("a")["leadin"] is True and leadin_step("a")["type"] == "narrate"


def test_leadins_say_nothing_the_checks_object_to():
    from app.domain.services.story_checks import _META_RE

    for en, fr in LEADINS:
        assert not _META_RE.search(en) and not _META_RE.search(fr)
        assert " you " not in f" {en.lower()} " and " tu " not in f" {fr.lower()} "


def test_add_leadins_puts_one_before_a_run_with_no_line_and_is_idempotent():
    scenes = [
        {
            "steps": [
                {"type": "say", "who": "hero", "en": "Hi", "fr": "Salut"},
                {"type": "say", "who": "friend", "en": "Look", "fr": "Regarde"},
                {"type": "ask", "ref": "q1"},
                {"type": "ask", "ref": "q2"},
                {"type": "narrate", "en": "Then", "fr": "Puis"},
                {"type": "show", "visual": "prop", "params": {"prop": "leaf"}},
                {"type": "concept", "id": "situation-q3", "en": ["x"], "fr": ["x"]},
                {"type": "ask", "ref": "q3"},
            ]
        }
    ]
    assert add_leadins(scenes, "1.1") == 1
    steps = scenes[0]["steps"]
    # q1 and q2 follow a say: nothing; q3 follows a narrate and a close-up: a lead-in before its card.
    assert steps[2]["type"] == "ask" and steps[3]["type"] == "ask"
    lead = steps[steps.index(next(s for s in steps if s.get("leadin")))]
    assert steps[steps.index(lead) + 1]["id"] == "situation-q3"
    assert add_leadins(scenes, "1.1") == 0
    again = copy.deepcopy(scenes)
    assert add_leadins(again, "1.1") == 0 and again == scenes


def test_a_new_plan_gets_a_code_leadin_instead_of_a_repair_call_and_an_old_one_does_not():
    def drop_leadin(ctx):
        the_spine = spine()
        steps = the_spine["scenes"][0]["steps"]
        position = next(i for i, s in enumerate(steps) if s.get("ref") == "q1")
        del steps[position - 1]
        return build(ctx, the_spine)

    assert repair.ASK_NOT_SET_UP in codes(drop_leadin(chapter_ctx()))
    result = drop_leadin(none_ctx())
    assert repair.ASK_NOT_SET_UP not in codes(result)
    steps = [s for c in result.doc["chapters"] for sc in c["scenes"] for s in sc["steps"]]
    placed = [s for s in steps if s.get("leadin")]
    assert placed and all(s["type"] == "narrate" for s in placed)
    # The same chapter always gets the same lines.
    again = drop_leadin(none_ctx())
    assert result.doc == again.doc


# --------------------------------------------------------------------------
# Gates
# --------------------------------------------------------------------------


def test_the_new_caps_are_warnings_on_a_new_kids_plan_only():
    old = build(chapter_ctx(), spine())
    assert not lint_codes(old) & {"line_too_long_for_kids", "card_too_long_for_kids"}
    new = build(none_ctx(), spine())
    assert {"line_too_long_for_kids", "card_too_long_for_kids"} <= lint_codes(new)
    assert not codes(new) & {"line_too_long_for_kids", "card_too_long_for_kids", "line_run_long"}
    assert new.quality["kids_long_lines"] > 0 and "say_run_max" in new.quality


def test_a_run_of_more_than_six_lines_is_a_warning():
    ctx = none_ctx()
    the_spine = spine()
    steps = the_spine["scenes"][0]["steps"]
    for n in range(8):
        steps.insert(2, {"type": "narrate", "en": f"Short {n}.", "fr": f"Court {n}."})
    assert "line_run_long" in lint_codes(build(ctx, the_spine))


def test_french_in_an_english_line_is_a_warning_never_an_error():
    ctx = chapter_ctx()
    the_spine = spine()
    the_spine["scenes"][0]["steps"][0]["en"] = "Dans le jardin, les enfants sont très contents."
    result = build(ctx, the_spine)
    assert "lang_integrity" in lint_codes(result)
    assert "lang_integrity" not in codes(result)


def test_a_story_that_shows_more_than_it_talks_is_not_too_thin():
    from app.domain.services.story_checks import STORY_TYPES, TEACHING

    assert "show" in STORY_TYPES and "show" not in TEACHING

    from app.domain.services.story_checks import check_story

    ctx = chapter_ctx()
    scenes = [
        {
            "steps": [
                *[{"type": "narrate", "en": f"Line {n}.", "fr": f"Ligne {n}."} for n in range(6)],
                {"type": "say", "who": "hero", "en": "One.", "fr": "Un."},
                {"type": "say", "who": "friend", "en": "Two.", "fr": "Deux."},
                {"type": "show", "visual": "figure", "params": {}},
                {
                    "type": "concept",
                    "id": "c1",
                    "title": {"en": "T", "fr": "T"},
                    "en": ["a"],
                    "fr": ["a"],
                },
                {"type": "show", "visual": "figure", "params": {}},
                {"type": "say", "who": "hero", "en": "Three.", "fr": "Trois."},
                {
                    "type": "concept",
                    "id": "c2",
                    "title": {"en": "T", "fr": "T"},
                    "en": ["a"],
                    "fr": ["a"],
                },
                {"type": "narrate", "en": "Four.", "fr": "Quatre."},
                {"type": "narrate", "en": "Five.", "fr": "Cinq."},
            ]
        }
    ]
    found: list[str] = []
    check_story(ctx, scenes, {}, lambda code, _path, message: found.append(f"{code}: {message}"))
    assert not any(f.startswith("story_too_thin") for f in found), found


def test_the_setting_has_three_options_and_defaults_to_auto():
    from app.infrastructure.config.platform_defaults import SETTING_DEFINITIONS

    setting = next(d for d in SETTING_DEFINITIONS if d.key == "story-mentor-policy")
    assert setting.default == "auto" and setting.allowed_options == ["auto", "never", "always"]


def test_the_prompts_of_the_chapter_follow_the_policy():
    from app.ai.prompts.story_from_lesson import _cast_policy_note

    assert _cast_policy_note(None) == "" and _cast_policy_note({"cast_policy": {}}) == ""
    assert "NO MENTOR" in _cast_policy_note({"cast_policy": {"mentor": "none"}})
    assert "CAMEO" in _cast_policy_note({"cast_policy": {"mentor": "cameo"}})
    assert _cast_policy_note({"cast_policy": {"mentor": "lead"}}) == ""
