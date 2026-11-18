"""#2708: what a module story shows and how it talks (story_metrics, the validator, the audit).

The fixture is the module story "Le Cerveau Qui Te Ment en Face" as the player
received it from staging on 2026-11-18 (its ``art`` emptied): ``art.props`` is
empty, no prop has a figure, 12 close-ups, 9 educational props.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from app.api.v1.schemas.story_course import StoryCourse
from app.domain.services import story_metrics as m
from app.domain.services.story_course_validator import validate_story_course

_FIXTURE = Path(__file__).parent / "fixtures" / "story_module_closeups_2708.json"
_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "audit_story_assets.py"
_spec = importlib.util.spec_from_file_location("audit_story_assets", _SCRIPT)
audit = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = audit
_spec.loader.exec_module(audit)

NEW_CODES = m.ASSET_CODES


@pytest.fixture
def doc():
    return copy.deepcopy(json.loads(_FIXTURE.read_text(encoding="utf-8")))


def _say(who, en, fr=None):
    return {"type": "say", "who": who, "en": en, "fr": fr or en}


def _story(steps, **extra):
    return {
        "languages": {"home": "en", "target": "fr"},
        "props": [
            {
                "id": "poster",
                "kind": "real",
                "educational": True,
                "label": {"en": "the table poster", "fr": "l'affiche"},
            },
            {"id": "tree", "kind": "sticker", "label": {"en": "the tree", "fr": "l'arbre"}},
        ],
        "chapters": [{"id": "ch1", "scenes": [{"id": "s1", "steps": steps}]}],
        **extra,
    }


# -- the studied story ---------------------------------------------------------------


def test_the_story_still_validates_and_the_new_checks_are_only_warnings(doc):
    report = validate_story_course(StoryCourse.model_validate(doc), generated=True)
    assert report.ok and report.errors == []
    codes = {w.code for w in report.warnings}
    assert codes >= NEW_CODES
    assert report.checks.warnings == len(report.warnings)
    assert not any(e.code in NEW_CODES for e in report.errors)


def test_the_metrics_of_the_studied_story(doc):
    numbers = m.story_metrics(doc)
    assert numbers["closeups"] == 12 and numbers["closeups_with_art"] == 0
    assert numbers["say_run_max"] == 8
    assert numbers["refrain_count"] == 4
    assert numbers["mentor_share"] == 0.15
    assert numbers["words_before_first_card"] > 400 and numbers["card_words_max"] >= 60
    report = validate_story_course(StoryCourse.model_validate(doc), generated=True)
    assert report.checks.story_metrics == numbers


def test_nine_educational_props_have_no_art_and_french_is_found_in_en(doc):
    assert len(m.educational_without_art(doc)) == 9
    bad = {f.path.split(".")[0] for f in m.lang_integrity(doc)}
    assert bad == {"questions[u1_1-q1]", "questions[u1_1-q4]"}


def test_a_chapter_story_is_not_judged_by_the_new_checks(doc):
    """Chapter generation ranks attempts by warning count: only module stories get them."""
    doc.pop("module_story")
    doc["sira_chapter"] = {"plan": True}
    report = validate_story_course(StoryCourse.model_validate(doc), generated=True)
    assert not ({w.code for w in report.warnings} & {"dangling_deixis", "unseen_stimulus"})
    assert report.checks.story_metrics is None
    assert "story_metrics" not in report.checks.model_dump(mode="json")


# -- the checks ----------------------------------------------------------------------


def test_art_comes_from_a_figure_or_the_art_props_map():
    story = _story([])
    assert m.educational_without_art(story) == ["poster"]
    assert (
        m.educational_without_art({**story, "art": {"props": {"poster": {"sticker": "/x"}}}}) == []
    )
    story["props"][0]["figure"] = {"source_image_id": "1"}
    assert m.educational_without_art(story) == []


def test_dangling_deixis_needs_a_show_within_two_steps():
    show = {"type": "show", "visual": "prop", "params": {"prop": "poster"}}
    far = _story(
        [
            _say("friend", "Look at the poster!"),
            _say("hero", "a"),
            _say("hero", "b"),
            _say("hero", "c"),
            show,
        ]
    )
    near = _story([_say("friend", "Look at the poster!"), _say("hero", "a"), show])
    before = _story([show, _say("friend", "Regardez !", "Regardez !")])
    assert [f.code for f in m.dangling_deixis(far)] == ["dangling_deixis"]
    assert m.dangling_deixis(near) == [] and m.dangling_deixis(before) == []
    assert m.dangling_deixis(_story([_say("hero", "She looks tired.")])) == []


def test_an_unseen_stimulus_is_a_prop_named_before_its_close_up():
    question = {
        "id": "q1",
        "prompt": {
            "en": "Which table of the poster is longer?",
            "fr": "Quelle table est plus longue ?",
        },
    }
    ask = {"type": "ask", "ref": "q1"}
    show = {"type": "show", "visual": "prop", "params": {"prop": "poster"}}
    unseen = _story([ask, show], questions=[question])
    seen = _story([show, ask], questions=[question])
    assert [f.code for f in m.unseen_stimulus(unseen)] == ["unseen_stimulus"]
    assert m.unseen_stimulus(seen) == []
    # Decor is never required to be shown.
    decor = _story([ask], questions=[{"id": "q1", "prompt": {"en": "Under the tree?", "fr": "?"}}])
    assert m.unseen_stimulus(decor) == []


def test_french_in_english_needs_two_distinct_stopwords():
    assert m.french_in("Que signifie faire une inférence dans ton cerveau ?")
    assert m.french_in("Why should you be careful about first impressions?") == []
    assert m.french_in("The tree is in Le Caire") == []
    assert m.french_in("Visit Le Corbusier") == []


def test_the_numbers_on_a_small_story():
    steps = [
        _say("mentor", "one two three"),
        _say("mentor", "four"),
        _say("hero", "five", "cinq"),
        {"type": "narrate", "en": "n", "fr": "n"},
        {"type": "say", "who": "friend", "en": "x", "fr": "x", "refrain": True},
        {
            "type": "concept",
            "id": "c1",
            "title": {"fr": "Un titre", "en": "A title"},
            "fr": ["a b c"],
            "en": ["a"],
        },
    ]
    numbers = m.story_metrics(_story(steps))
    assert numbers["say_run_max"] == 3 and numbers["mentor_share"] == 0.5
    assert numbers["refrain_count"] == 1 and numbers["card_words_max"] == 5
    assert numbers["words_before_first_card"] == 3 + 1 + 1 + 1 + 1
    assert m.story_metrics({})["card_words_max"] == 0


# -- the audit script ----------------------------------------------------------------


def test_the_audit_row_counts_library_art_as_art(doc):
    bare = audit.audit_row(doc)
    assert bare["closeups"] == 12 and bare["without_art"] == 12
    assert bare["french_in_en"] == 8 and bare["educational_without_art"] == 9
    with_library = audit.audit_row(doc, {"poster": {"sticker": "/api/v1/story-props/x/data"}})
    assert with_library["without_art"] < 12 and with_library["educational_without_art"] == 8


def test_the_audit_table_has_one_row_per_story_and_a_markdown_form(doc):
    rows = [
        {"story": "a", "lang": "fr", "status": "published", **audit.audit_row(doc)},
        {"story": "b", "lang": "en", "status": "draft", **audit.audit_row({})},
    ]
    text = audit.format_table(rows)
    assert len(text.splitlines()) == 3 and "show no art" in text.splitlines()[0]
    markdown = audit.format_table(rows, markdown=True)
    assert markdown.splitlines()[1].startswith("|---") and markdown.count("\n") == 3
