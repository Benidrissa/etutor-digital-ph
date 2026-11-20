"""The balance, cycle and cause_chain idea machines (#2756), backend half.

Pure tests, no database. The parts table is the one of #2740, shared with the frontend.
"""

import copy
import json
from pathlib import Path

import pytest

from app.api.v1.schemas.story_course import (
    DRAWN_VISUALS,
    MATHS_VISUALS,
    VISUALS,
    StoryCourse,
)
from app.domain.services.story_course_validator import (
    drawn_visual_problem,
    machine_parts,
    validate_story_course,
)
from app.domain.services.story_poe import DEMO_KINDS

FIXTURES = Path(__file__).parent / "fixtures"
TABLE = json.loads((FIXTURES / "machine_parts_2740.json").read_text(encoding="utf-8"))
NEW = ("balance", "cycle", "cause_chain")
MACHINES = FIXTURES / "story_machines_2756.json"


def lab(en: str = "Rain", fr: str = "Pluie") -> dict:
    return {"en": en, "fr": fr}


def side(value=10, label=None) -> dict:
    return {"label": label or lab("Costs", "Coûts"), "value": value}


def items(n: int) -> list[dict]:
    return [lab(f"Item {i}", f"Élément {i}") for i in range(n)]


def report(data: dict, generated: bool = False):
    return validate_story_course(StoryCourse.model_validate(data), generated=generated)


def steps(data: dict) -> list[dict]:
    return data["chapters"][0]["scenes"][-1]["steps"]


@pytest.fixture
def course() -> dict:
    return json.loads(MACHINES.read_text(encoding="utf-8"))


def test_the_table_covers_the_new_machines():
    for name in NEW:
        rows = [r for r in TABLE if r["visual"] == name]
        assert len(rows) >= 7
        assert any(r["parts"] for r in rows) and any(not r["parts"] for r in rows)


@pytest.mark.parametrize(
    "row", [r for r in TABLE if r["visual"] in NEW], ids=lambda r: f"{r['visual']}-{r['parts']}"
)
def test_machine_parts_on_the_shared_table(row):
    assert machine_parts(row["visual"], row["params"]) == row["parts"]


@pytest.mark.parametrize("visual", NEW)
@pytest.mark.parametrize("params", [None, [], "x"])
def test_machine_parts_ignores_params_that_are_not_a_dict(visual, params):
    assert machine_parts(visual, params) == []


def test_the_parts_order():
    assert machine_parts("balance", {"left": side(), "right": side()}) == ["left", "right", "beam"]
    assert machine_parts("cycle", {"stages": items(4)}) == ["stage1", "stage2", "stage3", "stage4"]
    assert machine_parts("cause_chain", {"links": items(3)}) == ["link1", "link2", "link3"]


@pytest.mark.parametrize(
    "visual, params, ok",
    [
        ("balance", {"left": side(3), "right": side(3)}, True),
        ("balance", {"left": side(0), "right": side(100000), "highlight": "beam"}, True),
        ("balance", {"left": side(2.5), "right": side(1), "highlight": "left"}, True),
        ("balance", {"left": side(3)}, False),
        ("balance", {"left": side(-1), "right": side(3)}, False),
        ("balance", {"left": side(100001), "right": side(3)}, False),
        ("balance", {"left": side(True), "right": side(3)}, False),
        ("balance", {"left": side(float("nan")), "right": side(3)}, False),
        ("balance", {"left": side("3"), "right": side(3)}, False),
        ("balance", {"left": side(3, lab("x" * 41, "Coûts")), "right": side(3)}, False),
        ("balance", {"left": side(3, lab("x" * 40, "y" * 40)), "right": side(3)}, True),
        ("balance", {"left": side(3, {"en": "Costs"}), "right": side(3)}, False),
        ("balance", {"left": side(3, lab("  ", "Coûts")), "right": side(3)}, False),
        ("balance", {"left": side(3), "right": side(3), "highlight": "mark"}, False),
        ("cycle", {"stages": items(3)}, True),
        ("cycle", {"stages": items(6), "start": 6, "highlight": "stage6"}, True),
        ("cycle", {"stages": items(4), "start": 2.0}, True),
        ("cycle", {"stages": items(2)}, False),
        ("cycle", {"stages": items(7)}, False),
        ("cycle", {"stages": "rain"}, False),
        ("cycle", {"stages": items(3), "start": 0}, False),
        ("cycle", {"stages": items(3), "start": 4}, False),
        ("cycle", {"stages": items(3), "start": 1.5}, False),
        ("cycle", {"stages": items(3), "start": True}, False),
        ("cycle", {"stages": items(3), "highlight": "stage4"}, False),
        ("cycle", {"stages": items(3), "highlight": "link1"}, False),
        ("cycle", {"stages": items(2) + [lab("x" * 41, "y")]}, False),
        ("cycle", {"stages": items(2) + [{"fr": "Pluie"}]}, False),
        ("cause_chain", {"links": items(2)}, True),
        ("cause_chain", {"links": items(5), "highlight": "link5"}, True),
        ("cause_chain", {"links": items(1)}, False),
        ("cause_chain", {"links": items(6)}, False),
        ("cause_chain", {"links": items(3), "highlight": "link4"}, False),
        ("cause_chain", {"links": items(3), "highlight": "stage1"}, False),
        ("cause_chain", {"links": items(2) + [lab("a", "x" * 41)]}, False),
        ("cause_chain", {}, False),
    ],
)
def test_the_machines_params(visual, params, ok):
    assert (drawn_visual_problem(visual, params) is None) is ok


@pytest.mark.parametrize("visual", NEW)
def test_a_missing_required_param_names_it(visual):
    required = [n for n, (req, _) in DRAWN_VISUALS[visual].items() if req]
    assert required
    problem = drawn_visual_problem(visual, {})
    assert problem and problem.startswith(f"{visual} needs params.{required[0]}")


@pytest.mark.parametrize(
    "visual, params",
    [
        ("balance", {"left": side(), "right": side(), "highlight": "beam"}),
        ("cycle", {"stages": items(3)}),
        ("cause_chain", {"links": items(2)}),
    ],
)
def test_a_machine_never_falls_into_another_check(visual, params):
    assert drawn_visual_problem(visual, params) is None
    bad = drawn_visual_problem(visual, {k: "bad" for k in params})
    assert bad and "venn_primes" not in bad and "number_line" not in bad


def test_the_problem_messages_name_the_param():
    assert "params.left of balance" in drawn_visual_problem("balance", {"left": 1, "right": side()})
    assert "params.stages of cycle" in drawn_visual_problem("cycle", {"stages": items(2)})
    assert "params.start of cycle" in drawn_visual_problem(
        "cycle", {"stages": items(3), "start": 9}
    )
    assert "params.links of cause_chain" in drawn_visual_problem("cause_chain", {"links": []})
    assert "one of stage1, stage2, stage3" in drawn_visual_problem(
        "cycle", {"stages": items(3), "highlight": "stage9"}
    )


def test_the_machines_are_declared_drawn_but_not_offered_to_a_model():
    for name in NEW:
        assert name in VISUALS
        assert name in DRAWN_VISUALS
        assert name not in MATHS_VISUALS
        assert name not in DEMO_KINDS


def test_the_fixture_validates_clean(course):
    for generated in (False, True):
        rep = report(course, generated=generated)
        assert not rep.errors, rep.errors
        assert not rep.warnings, rep.warnings


def test_the_fixture_has_one_machine_each_started_by_a_cue(course):
    shows = [s for s in steps(course) if s["type"] == "show"]
    assert [s["visual"] for s in shows] == list(NEW)
    for show in shows:
        parts = machine_parts(show["visual"], show["params"])
        assert show["params"]["highlight"] in parts
        assert show["cues"][-1] == {"do": "machine"}
    assert shows[1]["cues"][0] == {"do": "wait", "ms": 400}


@pytest.mark.parametrize("index", [1, 2, 3])
def test_a_bad_machine_step_is_a_warning_in_a_week_and_an_error_when_generated(course, index):
    data = copy.deepcopy(course)
    step = steps(data)[index]
    key = {"balance": "left", "cycle": "stages", "cause_chain": "links"}[step["visual"]]
    step["params"][key] = None
    week = report(data)
    assert "visual_not_drawn" in {w.code for w in week.warnings}
    assert "visual_not_drawn" not in {e.code for e in week.errors}
    assert "visual_not_drawn" in {e.code for e in report(data, generated=True).errors}
