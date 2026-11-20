"""The place_value and number_line idea machines (#2740), backend half.

Pure tests, no database. The parts table is shared with the frontend ``partsOf``.
"""

import copy
import json
from pathlib import Path

import pytest

from app.api.v1.schemas.story_course import DRAWN_VISUALS, MATHS_VISUALS, StoryCourse
from app.domain.services.story_course_validator import (
    drawn_visual_problem,
    machine_parts,
    validate_story_course,
)

FIXTURES = Path(__file__).parent / "fixtures"
TABLE = json.loads((FIXTURES / "machine_parts_2740.json").read_text(encoding="utf-8"))
MACHINES = FIXTURES / "story_machines_2740.json"


def report(data: dict, generated: bool = False):
    return validate_story_course(StoryCourse.model_validate(data), generated=generated)


def steps(data: dict) -> list[dict]:
    return data["chapters"][0]["scenes"][-1]["steps"]


@pytest.fixture
def course() -> dict:
    return json.loads(MACHINES.read_text(encoding="utf-8"))


def test_the_table_is_big_enough():
    assert len(TABLE) >= 10


@pytest.mark.parametrize("row", TABLE, ids=lambda r: f"{r['visual']}-{r['params']}")
def test_machine_parts_on_the_shared_table(row):
    assert machine_parts(row["visual"], row["params"]) == row["parts"]


def test_machine_parts_ignores_params_that_are_not_a_dict():
    assert machine_parts("place_value", None) == []
    assert machine_parts("number_line", [1, 2]) == []


PLACE = {"n": 4305892176, "reveal": "groups", "highlight": "millions"}
LINE = {"from": 0, "to": 100, "mark": 37, "step": 10, "highlight": "mark"}


@pytest.mark.parametrize(
    ("visual", "params", "ok"),
    [
        ("place_value", PLACE, True),
        ("place_value", {"n": 0}, True),
        ("place_value", {"n": 999999999999, "reveal": "all", "highlight": "billions"}, True),
        ("place_value", {"n": 4.0}, True),
        ("place_value", {"n": 5, "highlight": "ones"}, True),
        ("place_value", {"n": 1000000000000}, False),
        ("place_value", {"n": -1}, False),
        ("place_value", {"n": 2.5}, False),
        ("place_value", {"n": True}, False),
        ("place_value", {"n": "12"}, False),
        ("place_value", {"n": float("nan")}, False),
        ("place_value", {}, False),
        ("place_value", None, False),
        ("place_value", {"n": 7, "reveal": "rain"}, False),
        ("place_value", {"n": 5, "highlight": "millions"}, False),
        ("place_value", {"n": 5, "highlight": "tens"}, False),
        ("number_line", LINE, True),
        ("number_line", {"from": 0, "to": 10}, True),
        ("number_line", {"from": -2.5, "to": 2.5, "mark": 2.5, "highlight": "to"}, True),
        ("number_line", {"from": 0, "to": 100, "mark": 0, "step": 5}, True),
        ("number_line", {"from": 0, "to": 100, "step": 5.0}, True),
        ("number_line", {"from": 5, "to": 5}, False),
        ("number_line", {"from": 9, "to": 3}, False),
        ("number_line", {"from": 0}, False),
        ("number_line", {"from": True, "to": 5}, False),
        ("number_line", {"from": 0, "to": float("inf")}, False),
        ("number_line", {"from": 0, "to": float("nan")}, False),
        ("number_line", {"from": 0, "to": 10, "mark": 11}, False),
        ("number_line", {"from": 0, "to": 10, "mark": -1}, False),
        ("number_line", {"from": 0, "to": 10, "mark": "5"}, False),
        ("number_line", {"from": 0, "to": 100, "step": 1}, False),
        ("number_line", {"from": 0, "to": 100, "step": 0}, False),
        ("number_line", {"from": 0, "to": 100, "step": -5}, False),
        ("number_line", {"from": 0, "to": 10, "highlight": "mark"}, False),
        ("number_line", {"from": 0, "to": 10, "highlight": "middle"}, False),
    ],
)
def test_the_machines_params(visual, params, ok):
    problem = drawn_visual_problem(visual, params)
    assert (problem is None) is ok, problem


def test_twenty_ticks_is_allowed_and_twenty_one_is_not():
    assert drawn_visual_problem("number_line", {"from": 0, "to": 100, "step": 5}) is None
    assert drawn_visual_problem("number_line", {"from": 0, "to": 105, "step": 5}) is not None


def test_a_machine_never_falls_into_the_venn_check():
    for visual, params in (("place_value", PLACE), ("number_line", LINE)):
        assert "venn_primes" not in (drawn_visual_problem(visual, params) or "")


def test_the_machines_are_drawn_but_not_offered_to_a_model():
    assert "place_value" in DRAWN_VISUALS
    assert "number_line" in DRAWN_VISUALS
    assert "place_value" not in MATHS_VISUALS
    assert "number_line" not in MATHS_VISUALS


def test_an_undrawn_visual_still_fails_as_before():
    assert "not a visual the player draws" in drawn_visual_problem("thermometer", {"value": 3})


def test_the_fixture_validates_clean(course):
    result = report(course)
    assert result.errors == []
    assert result.warnings == []
    assert report(course, generated=True).errors == []


def test_the_fixture_has_both_machines_one_with_the_cue(course):
    place, line = steps(course)[1], steps(course)[2]
    assert (place["visual"], line["visual"]) == ("place_value", "number_line")
    assert place["cues"] == [{"do": "wait", "ms": 400}, {"do": "machine"}]
    assert "cues" not in line
    assert place["params"]["highlight"] in machine_parts("place_value", place["params"])
    assert line["params"]["highlight"] in machine_parts("number_line", line["params"])


def test_a_bad_machine_step_is_a_warning_in_a_week_and_an_error_when_generated(course):
    data = copy.deepcopy(course)
    steps(data)[1]["params"]["n"] = 10**12
    assert "visual_not_drawn" in {w.code for w in report(data).warnings}
    assert "visual_not_drawn" in {e.code for e in report(data, generated=True).errors}
