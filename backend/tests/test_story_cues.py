"""Animation cues on story steps (#2739): the contract and its warnings.

Pure tests, no database. A bad cue is only ever a warning, generated or not.
"""

import copy
import json
from pathlib import Path

import pytest

from app.api.v1.schemas.story_course import (
    CUE_MARKS,
    CUE_PRIMITIVES,
    CUE_SHOTS,
    CUE_SOUNDS,
    MAX_CUE_WAIT_MS,
    MAX_CUES_PER_STEP,
    StoryCourse,
)
from app.domain.services.story_course_validator import validate_story_course

FIXTURES = Path(__file__).parent / "fixtures"
CUES = FIXTURES / "story_cues_2739.json"
STORED = FIXTURES / "story_module_closeups_2708.json"
W04 = FIXTURES / "story_course_w04.json"


@pytest.fixture
def course() -> dict:
    return json.loads(CUES.read_text(encoding="utf-8"))


def scene(data: dict) -> dict:
    return data["chapters"][0]["scenes"][-1]


def report(data: dict, generated: bool = False):
    return validate_story_course(StoryCourse.model_validate(data), generated=generated)


def cue_issues(data: dict, generated: bool = False):
    result = report(data, generated)
    assert [e for e in result.errors if e.code.startswith("cue_")] == []
    return [w for w in result.warnings if w.code.startswith("cue_")]


def with_cues(data: dict, step: int, cues) -> dict:
    data = copy.deepcopy(data)
    scene(data)["steps"][step]["cues"] = cues
    return data


def test_the_fixture_validates_clean(course):
    result = report(course)
    assert result.errors == []
    assert result.warnings == []
    assert result.ok


def test_the_fixture_uses_every_primitive(course):
    used = {c["do"] for s in scene(course)["steps"] for c in s.get("cues", [])}
    assert used == set(CUE_PRIMITIVES)


def test_the_fixture_without_cues_has_the_same_report(course):
    bare = copy.deepcopy(course)
    for s in scene(bare)["steps"]:
        s.pop("cues", None)
    assert report(bare).model_dump() == report(course).model_dump()


def test_cues_survive_a_dump(course):
    dumped = StoryCourse.model_validate(course).model_dump(mode="json")
    assert dumped["chapters"][0]["scenes"][-1]["steps"][1]["cues"][0] == {
        "do": "enter",
        "who": "papa",
        "at": "right",
    }


def test_the_whitelists():
    assert CUE_MARKS == ("left", "centre", "right", "off")
    assert CUE_SHOTS == ("wide", "two", "close", "insert", "split")
    assert CUE_SOUNDS == ("pop", "whoosh", "correct", "oops", "coin", "fanfare", "star")
    assert (MAX_CUES_PER_STEP, MAX_CUE_WAIT_MS) == (8, 2000)


@pytest.mark.parametrize(
    "cue",
    [
        {"do": "enter", "who": "nandi"},
        {"do": "enter", "who": "nandi", "at": "left"},
        {"do": "exit", "who": "nandi"},
        *[{"do": "move", "who": "nandi", "to": m} for m in CUE_MARKS],
        {"do": "face", "who": "nandi", "toward": "papa"},
        {"do": "face", "who": "nandi", "toward": "left"},
        {"do": "costume", "who": "nandi", "pose": "happy"},
        {"do": "show", "prop": "cash_register"},
        *[{"do": "camera", "shot": s} for s in CUE_SHOTS],
        *[{"do": "sound", "name": n} for n in CUE_SOUNDS],
        {"do": "wait", "ms": 2000},
        {"do": "music", "track": "anything", "loop": True},
        {"do": "music"},
    ],
)
@pytest.mark.parametrize("generated", [False, True])
def test_a_good_cue_is_accepted(course, cue, generated):
    assert cue_issues(with_cues(course, 0, [cue]), generated) == []


def test_machine_on_a_show_step_is_accepted(course):
    assert cue_issues(with_cues(course, 3, [{"do": "machine"}])) == []


@pytest.mark.parametrize(
    "cue, code, key",
    [
        ({"do": "dance"}, "cue_unknown_do", "do"),
        ({"who": "nandi"}, "cue_unknown_do", "do"),
        ({"do": "exit"}, "cue_unknown_actor", "who"),
        ({"do": "exit", "who": "ghost"}, "cue_unknown_actor", "who"),
        ({"do": "exit", "who": 3}, "cue_unknown_actor", "who"),
        ({"do": "enter", "who": "nandi", "at": "off"}, "cue_bad_mark", "at"),
        ({"do": "enter", "who": "nandi", "at": "middle"}, "cue_bad_mark", "at"),
        ({"do": "enter", "who": "nandi", "at": None}, "cue_bad_mark", "at"),
        ({"do": "move", "who": "nandi"}, "cue_bad_mark", "to"),
        ({"do": "move", "who": "nandi", "to": "up"}, "cue_bad_mark", "to"),
        ({"do": "face", "who": "nandi", "toward": "ghost"}, "cue_bad_arg", "toward"),
        ({"do": "face", "who": "nandi"}, "cue_bad_arg", "toward"),
        ({"do": "costume", "who": "nandi", "pose": "flying"}, "cue_bad_arg", "pose"),
        ({"do": "show", "prop": "unicorn"}, "cue_unknown_prop", "prop"),
        ({"do": "show"}, "cue_unknown_prop", "prop"),
        ({"do": "camera", "shot": "drone"}, "cue_bad_arg", "shot"),
        ({"do": "sound", "name": "boom"}, "cue_bad_arg", "name"),
        ({"do": "wait", "ms": "300"}, "cue_bad_arg", "ms"),
        ({"do": "wait", "ms": 1.5}, "cue_bad_arg", "ms"),
        ({"do": "wait", "ms": True}, "cue_bad_arg", "ms"),
        ({"do": "wait", "ms": -5}, "cue_bad_arg", "ms"),
        ({"do": "wait"}, "cue_bad_arg", "ms"),
        ({"do": "machine"}, "cue_machine_without_show", None),
    ],
)
@pytest.mark.parametrize("generated", [False, True])
def test_a_bad_cue_is_a_warning_never_an_error(course, cue, code, key, generated):
    issues = cue_issues(with_cues(course, 0, [cue]), generated)
    assert [i.code for i in issues] == [code]
    base = "chapters[ch1].scenes[cues].steps[0].cues[0]"
    assert issues[0].path == base + (f".{key}" if key else "")
    assert issues[0].severity == "warning"


def test_a_cue_that_is_not_an_object_or_a_list(course):
    assert [i.code for i in cue_issues(with_cues(course, 0, ["enter"]))] == ["cue_bad_shape"]
    assert [i.code for i in cue_issues(with_cues(course, 0, {"do": "enter"}))] == ["cue_bad_shape"]


def test_nine_cues_are_too_many(course):
    nine = [{"do": "sound", "name": "pop"}] * (MAX_CUES_PER_STEP + 1)
    assert [i.code for i in cue_issues(with_cues(course, 0, nine))] == ["cue_too_many"]
    eight = nine[:MAX_CUES_PER_STEP]
    assert cue_issues(with_cues(course, 0, eight)) == []


def test_wait_is_summed_per_step(course):
    over = [{"do": "wait", "ms": 1000}, {"do": "wait", "ms": 1001}]
    issues = cue_issues(with_cues(course, 0, over))
    assert [i.code for i in issues] == ["cue_wait_over_limit"]
    exact = [{"do": "wait", "ms": 1000}, {"do": "wait", "ms": 1000}]
    assert cue_issues(with_cues(course, 0, exact)) == []


def test_a_beat_shows_two_props_at_most(course):
    data = copy.deepcopy(course)
    scene(data)["steps"][0]["props"] = ["coin", "bill"]
    issues = cue_issues(with_cues(data, 0, [{"do": "show", "prop": "cash_register"}]))
    assert "cue_too_many" in {i.code for i in issues}


def test_a_show_repeating_a_step_prop_is_not_counted_twice(course):
    data = copy.deepcopy(course)
    scene(data)["steps"][0]["props"] = ["cash_register", "coin"]
    issues = cue_issues(with_cues(data, 0, [{"do": "show", "prop": "cash_register"}]))
    assert "cue_too_many" not in {i.code for i in issues}


def test_an_actor_must_be_on_stage_in_the_scene(course):
    data = copy.deepcopy(course)
    scene(data)["cast"] = ["nandi", "papa"]
    scene(data)["steps"][4]["who"] = "papa"
    # The fixture moves kabore in step 2: without that cue, kabore is nowhere in the scene.
    scene(data)["steps"][2]["cues"] = [{"do": "move", "who": "nandi", "to": "left"}]
    issues = cue_issues(with_cues(data, 0, [{"do": "enter", "who": "kabore"}]))
    assert [i.code for i in issues] == ["cue_unknown_actor"]


def test_cue_codes_never_trigger_a_repair():
    from app.domain.services import story_repair

    cue_codes = {
        "cue_unknown_do",
        "cue_unknown_actor",
        "cue_bad_mark",
        "cue_unknown_prop",
        "cue_bad_arg",
        "cue_bad_shape",
        "cue_too_many",
        "cue_wait_over_limit",
        "cue_machine_without_show",
    }
    assert not cue_codes & set(story_repair.QUIET_CODES)
    assert not cue_codes & set(story_repair.SETTLEABLE)


@pytest.mark.parametrize("path", [STORED, W04])
def test_a_story_without_cues_gets_no_cue_issue(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    result = report(data, generated=path is STORED)
    assert [i for i in result.errors + result.warnings if i.code.startswith("cue_")] == []
