"""scripts/repair_story_language.py: English back into the French ``en`` fields (#2710).

Only the pure part is tested, on the stored story of ``fixtures/story_module_closeups_2708.json``,
where ``u1_1-q1`` and ``u1_1-q4`` carry French in ``en``. No database, no model.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "repair_story_language.py"
_spec = importlib.util.spec_from_file_location("repair_story_language", _SCRIPT)
script = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = script
_spec.loader.exec_module(script)

FIXTURE = Path(__file__).parent / "fixtures" / "story_module_closeups_2708.json"


@pytest.fixture
def story() -> dict:
    return json.loads(FIXTURE.read_text("utf-8"))


def question(doc: dict, qid: str) -> dict:
    return next(q for q in doc["questions"] if q["id"] == qid)


def english_twins(doc: dict) -> list[dict]:
    return [q for q in doc["questions"] if not script.french_paths(q)]


def quiz_row(doc: dict, qid: str) -> dict:
    """The English quiz question that ``qid``'s English twin was made from."""
    twin = question(doc, qid)
    return {
        "id": twin["derived_from"]["question_id"],
        "question": twin["prompt"]["en"],
        "options": [re.sub(r"^[a-d]\) ", "", c["en"]) for c in twin["choices"]],
        "correct_answer": "abcd".index(twin["answer"]),
        "explanation": twin["explanation"]["en"],
    }


def test_the_two_french_questions_of_the_studied_story_are_found(story):
    flagged = {q["id"] for q in story["questions"] if script.french_paths(q)}
    assert flagged == {"u1_1-q1", "u1_1-q4"}
    paths = {tuple(p) for p in script.french_paths(question(story, "u1_1-q1"))}
    assert ("prompt",) in paths and ("explanation",) in paths and ("choices", 0) in paths


def test_an_english_text_equal_to_its_french_side_is_french_but_a_name_is_not():
    assert script.looks_french("a) C'est quand tu dors", "C'est quand tu dors")
    assert script.looks_french("Que signifie faire une inférence ?", "x")
    assert not script.looks_french("Paris", "Paris")
    assert not script.looks_french("What does it mean to infer?", "Que signifie inférer ?")


def test_the_english_story_of_the_module_gives_the_english_back(story):
    fixed, report = script.repair_document(story, script.Sources(english=english_twins(story)))
    assert report.unfixed == [] and len(report.fixed) == 12
    q1 = question(fixed, "u1_1-q1")
    twin = question(story, "u1_3-q1")
    assert (
        q1["prompt"]["en"]
        == twin["prompt"]["en"]
        == "What does it mean to make an 'inference' in your brain?"
    )
    assert q1["choices"][1]["en"] == twin["choices"][1]["en"]
    assert q1["explanation"]["en"] == twin["explanation"]["en"]
    # The French side, the answer and the other questions are untouched.
    assert q1["prompt"]["fr"] == question(story, "u1_1-q1")["prompt"]["fr"]
    assert q1["answer"] == "b"
    assert question(fixed, "u1_2-q3") == question(story, "u1_2-q3")
    assert [f for f in script.french_paths(q1)] == []
    assert script.french_paths(question(fixed, "u1_1-q4")) == []
    # The original is not changed.
    assert script.french_paths(question(story, "u1_1-q1"))


def test_the_quiz_row_it_was_derived_from_comes_first(story):
    quiz = {("1.3", "q1"): quiz_row(story, "u1_3-q1"), ("1.3", "q4"): quiz_row(story, "u1_3-q4")}
    decoy = [copy.deepcopy(q) for q in english_twins(story)]
    for q in decoy:
        q["prompt"]["en"] = "DECOY"
    fixed, report = script.repair_document(story, script.Sources(quiz=quiz, english=decoy))
    q1 = question(fixed, "u1_1-q1")
    assert q1["prompt"]["en"] == "What does it mean to make an 'inference' in your brain?"
    assert q1["choices"][0]["en"].startswith("a) It is when you sleep")
    assert report.unfixed == [] and {src for _q, _p, src in report.fixed} >= {"quiz row"}


def test_what_has_no_english_source_is_listed_and_left_alone(story):
    fixed, report = script.repair_document(story, script.Sources())
    assert fixed == story
    assert {q for q, _p in report.unfixed} == {"u1_1-q1", "u1_1-q4"} and report.fixed == []
    assert "CANNOT u1_1-q1 prompt" in script.format_report("module-x-fr", report)


def test_a_second_run_finds_nothing_to_do(story):
    sources = script.Sources(english=english_twins(story))
    once, _ = script.repair_document(story, sources)
    twice, report = script.repair_document(once, sources)
    assert twice == once and report.fixed == [] and report.unfixed == []


def test_a_quiz_in_another_order_is_not_trusted(story):
    row = quiz_row(story, "u1_3-q1")
    row["correct_answer"] = 0
    _fixed, report = script.repair_document(story, script.Sources(quiz={("1.3", "q1"): row}))
    assert ("u1_1-q1", "choices.1") in report.unfixed


def test_it_is_a_dry_run_unless_asked():
    assert script.parse_args([]).apply is False
    assert script.parse_args(["--apply"]).apply is True
