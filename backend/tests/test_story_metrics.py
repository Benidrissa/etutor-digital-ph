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
    judged = {"dangling_deixis", "unseen_stimulus"} | m.PICTURE_CODES
    assert not ({w.code for w in report.warnings} & judged)
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


# -- "the picture carries the idea" (#2750) ------------------------------------------

_FIGURE = {"type": "show", "visual": "image", "params": {"source_image_id": "img-1"}}
_COMPARE = {
    "type": "show",
    "visual": "compare",
    "params": {"values": [45, 4.5], "labels": [{"en": "a", "fr": "a"}, {"en": "b", "fr": "b"}]},
    "bet": "p1",
}
_CARD = {"type": "concept", "id": "c1", "teaches": 1, "title": {"en": "T", "fr": "T"}}
_BET = {"type": "ask", "ref": "p1", "predict": True, "teaches": 1}


def _codes(findings):
    return [f.code for f in findings]


def test_a_card_needs_a_picture_before_it_or_of_its_own():
    assert _codes(m.card_without_picture(_story([_say("hero", "a"), _CARD]))) == [
        "card_without_picture"
    ]
    assert m.card_without_picture(_story([_FIGURE, _say("hero", "a"), _CARD])) == []
    assert m.card_without_picture(_story([_COMPARE, _CARD])) == []
    assert m.card_without_picture(_story([{**_CARD, "media": {"visual": "image"}}])) == []
    assert m.card_without_picture(_story([{"type": "show", "visual": "factor_tree"}, _CARD])) == []
    # A picture counts for one card only, and a situation card is not judged.
    second = {**_CARD, "id": "c2"}
    assert len(m.card_without_picture(_story([_FIGURE, _CARD, second]))) == 1
    assert m.card_without_picture(_story([{"type": "concept", "id": "situation-1"}])) == []


def test_a_closeup_is_a_picture_only_with_art():
    closeup = {"type": "show", "visual": "prop", "params": {"prop": "poster"}}
    assert _codes(m.card_without_picture(_story([closeup, _CARD]))) == ["card_without_picture"]
    art = {"art": {"props": {"poster": {"sticker": "/x"}}}}
    assert m.card_without_picture(_story([closeup, _CARD], **art)) == []


def test_bet_demo_card_in_that_order():
    assert m.beat_out_of_order(_story([_BET, _COMPARE, _CARD])) == []
    late = m.beat_out_of_order(_story([_CARD, _BET, _COMPARE]))
    assert _codes(late) == ["beat_out_of_order"] and "after the card" in late[0].message
    assert "after the card" in m.beat_out_of_order(_story([_BET, _CARD, _COMPARE]))[0].message
    assert "before the bet" in m.beat_out_of_order(_story([_COMPARE, _BET, _CARD]))[0].message


def test_beat_order_is_quiet_with_no_bet_or_no_matching_card():
    assert m.beat_out_of_order(_story([_CARD, _COMPARE])) == []
    assert m.beat_out_of_order(_story([_BET, _COMPARE, {**_CARD, "teaches": 2}])) == []
    assert m.beat_out_of_order(_story([_CARD, {**_BET, "teaches": 2}, _COMPARE])) == []


def test_more_than_three_lines_without_a_visible_change():
    four = [_say("hero", str(i)) for i in range(4)]
    assert _codes(m.line_run_over_3(_story(four))) == ["line_run_over_3"]
    assert m.line_run_over_3(_story(four[:3])) == []
    broken = [*four[:2], _FIGURE, *four[:2]]
    assert m.line_run_over_3(_story(broken)) == []
    narrated = [*four[:2], {"type": "narrate", "en": "n", "fr": "n"}, four[0]]
    assert len(m.line_run_over_3(_story(narrated))) == 1
    moved = [*four[:2], {**four[2], "cues": [{"type": "move"}]}, four[3]]
    assert m.line_run_over_3(_story(moved)) == []


def test_a_scene_change_ends_a_run_of_lines():
    story = _story([_say("hero", "a")] * 3)
    story["chapters"][0]["scenes"].append({"id": "s2", "steps": [_say("hero", "b")] * 3})
    assert m.line_run_over_3(story) == []


def test_pointing_needs_a_target_only_judged_by_cues_in_a_cued_chapter():
    look = _say("hero", "Look at this!")
    pad = [_say("hero", "a")] * 3
    cued = {**pad[0], "cues": [{"type": "move"}]}
    # No cue in the chapter: as before, only a show within two steps counts.
    assert m.dangling_deixis(_story([{**look, "props": ["poster"]}, *pad])) != []
    # A cued chapter: a prop in the line's props, or a highlight, is a target.
    assert m.dangling_deixis(_story([{**look, "props": ["poster"]}, *pad, cued])) == []
    assert m.dangling_deixis(_story([{**look, "cues": [{"type": "highlight"}]}, *pad])) == []
    assert _codes(m.dangling_deixis(_story([look, *pad, cued]))) == ["dangling_deixis"]
    assert m.dangling_deixis(_story([look, _FIGURE, *pad, cued])) == []


def test_machine_numbers_come_from_the_facts_of_the_chapter():
    def card(text):
        return {"type": "concept", "id": "c1", "en": [text], "fr": [text]}

    bad = _story([_BET, _COMPARE, card("The till says 45 million.")], questions=[])
    assert _codes(m.demo_number_not_in_facts(bad)) == ["demo_number_not_in_facts"]
    good = _story([_BET, _COMPARE, card("The till says 45 and the sign 4,5.")])
    assert m.demo_number_not_in_facts(good) == []
    # Separators and a decimal comma are read; the bet's own question is not a source.
    big = {**_COMPARE, "params": {**_COMPARE["params"], "values": [4305892176, 2.5]}}
    text = card("Cost: 4 305 892 176 FCFA, and 2,5 km.")
    assert m.demo_number_not_in_facts(_story([_BET, big, text])) == []
    question = {"id": "p1", "prompt": {"en": "45 or 4.5?", "fr": "45 ou 4,5 ?"}}
    only_bet = _story([_BET, _COMPARE, card("Nothing here.")], questions=[question])
    assert len(m.demo_number_not_in_facts(only_bet)) == 1
    # A question of the chapter (stem, choices, explanation) counts.
    graded = {
        "id": "q1",
        "prompt": {"en": "Is 45 bigger?", "fr": "?"},
        "explanation": {"en": "4.5"},
    }
    ask = {"type": "ask", "ref": "q1"}
    assert m.demo_number_not_in_facts(_story([_BET, _COMPARE, ask], questions=[graded])) == []
    # No reference text: not judged. A timeline's ``at`` is a fact too.
    assert m.demo_number_not_in_facts(_story([_BET, _COMPARE])) == []
    line = {
        "type": "show",
        "visual": "timeline",
        "params": {"events": [{"at": 1990}, {"at": 2001}]},
    }
    assert len(m.demo_number_not_in_facts(_story([line, card("In 1990.")]))) == 1


def test_the_new_findings_reach_the_audit_row_and_the_validator(doc):
    row = audit.audit_row(_story([_CARD, _BET, _COMPARE]))
    assert row["beat_out_of_order"] == 1 and row["card_without_picture"] == 1
    titles = [title for _key, title in audit.COLUMNS]
    assert {"card no pic", "beat order", "run>3", "demo nbr"} <= set(titles)
    report = validate_story_course(StoryCourse.model_validate(doc), generated=True)
    assert report.ok and report.errors == []
    assert not any(e.code in m.PICTURE_CODES for e in report.errors)
