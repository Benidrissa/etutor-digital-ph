"""The director-script paper test (#2737): grammar v0, harness, export, storyboards.

Pure tests: no database, no real model, no network. The model is a fake that
answers from a queue; a test fails if the harness would build a real one.
The 17-line example of the epic (#2734) is the parser's test case.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))

grammar = importlib.import_module("story_script_grammar")
board = importlib.import_module("story_script_storyboard")
harness = importlib.import_module("story_script_paper_test")
export = importlib.import_module("story_script_export")

from story_script_grammar import Header, validate_script  # noqa: E402

_FIXTURES = Path(__file__).parent / "fixtures"

EXAMPLE = """\
scene family_home  cast=hero,friend,family
say family  "Une nouvelle route coûtera 4 305 892 176 FCFA !"  mood=surprised
open L1  "Comment lit-on un nombre aussi long ?"
bet L1
mistake friend  "Quatre mille... trois cents ?"
machine place_value  n=4305892176  reveal=groups
point hero  target=machine.millions
say hero  "Des groupes de trois, en partant de la droite !"  mood=happy
close L1
card groups_of_three
ask Q1 Q2
scene market  cast=hero,friend
show cash_register
say friend  "La caisse affiche 45 millions, l'enseigne 4,5 !"  mood=surprised
open L2  "Qui a raison ?"
bet L2
cliff L2
""".splitlines()


def example_header(**over) -> Header:
    base = {
        "chapter": "example",
        "languages": ["fr"],
        "mode": "open_loop",
        "stages": [3, 5, 9],
        "opens": {"L1": "reading a long number", "L2": "who is right"},
        "closes": ["L1"],
        "quiz": {"Q1": "q one", "Q2": "q two"},
        "cards": {"groups_of_three": "Groups of three"},
        "cast": ["hero", "friend", "family"],
        "places": ["family_home", "market"],
        "objects": {"cash_register": "the cash register"},
        "machines": ["place_value", "compare"],
        "numbers": ["4305892176", "45"],
    }
    base.update(over)
    return Header(**base)


def codes(result) -> list[str]:
    return [e.code for e in result.errors]


# -- the grammar ---------------------------------------------------------------------------


def test_the_17_line_example_parses_and_validates_in_open_loop_mode():
    statements, errors = grammar.parse_script(EXAMPLE)
    assert errors == []
    assert len(statements) == 17
    assert statements[0].macro == "scene" and statements[0].named["cast"] == "hero,friend,family"
    assert statements[1].texts == ["Une nouvelle route coûtera 4 305 892 176 FCFA !"]
    result = validate_script(EXAMPLE, example_header())
    assert result.errors == [], grammar.format_errors(result.errors, EXAMPLE)


def test_the_example_in_linear_mode_refuses_only_the_cliff():
    result = validate_script(EXAMPLE, example_header(mode="linear"))
    assert [(e.line, e.code) for e in result.errors] == [(17, "mode_refused")]


def test_a_long_dialogue_line_is_refused_with_its_line_number():
    lines = list(EXAMPLE)
    lines[7] = 'say hero  "' + "x" * 61 + '"  mood=happy'
    result = validate_script(lines, example_header())
    assert [(e.line, e.code) for e in result.errors] == [(8, "too_long")]
    assert "61 characters" in result.errors[0].message


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda ls: ls.__setitem__(0, "scene garage  cast=hero,friend"), "unknown_place"),
        (lambda ls: ls.__setitem__(12, "show moon"), "unknown_object"),
        (lambda ls: ls.__setitem__(5, "machine abacus  n=1"), "unknown_machine"),
        (lambda ls: ls.__setitem__(9, "card nothing"), "unknown_card"),
        (lambda ls: ls.__setitem__(10, "ask Q1 Q9"), "unknown_question"),
        (lambda ls: ls.__setitem__(1, 'say mentor "Bonjour"'), "role_not_in_cast"),
        (
            lambda ls: ls.__setitem__(11, "scene market  cast=hero,friend,mentor"),
            "role_not_in_cast",
        ),
        (lambda ls: ls.__setitem__(4, 'mistake hero "Quatre mille ?"'), "mistake_by_hero"),
        (lambda ls: ls.__setitem__(1, 'dance hero "x"'), "unknown_macro"),
        (lambda ls: ls.__setitem__(1, 'say family "pas fini'), "bad_syntax"),
        (lambda ls: ls.__setitem__(1, "say family  mood=happy"), "text_count"),
        (lambda ls: ls.__setitem__(1, 'say family  mood=angry "Non"'), "bad_value"),
        (lambda ls: ls.__setitem__(6, "point hero"), "missing_arg"),
        (
            lambda ls: ls.__setitem__(6, "point hero  target=machine.millions  speed=3"),
            "unknown_arg",
        ),
        (lambda ls: ls.__setitem__(5, "machine place_value  reveal=groups"), "missing_arg"),
        (lambda ls: ls.__setitem__(3, "bet L2"), "bet_without_open"),
        (lambda ls: ls.__setitem__(0, "narrate"), "scene_first"),
    ],
)
def test_each_class_of_mistake_has_its_own_code(mutate, code):
    lines = list(EXAMPLE)
    mutate(lines)
    result = validate_script(lines, example_header())
    assert code in codes(result), (code, codes(result))
    assert all(
        e.line > 0 or e.code.endswith("_missing") or e.code == "empty" for e in result.errors
    )


def test_skipping_asking_twice_and_omitting_are_refused():
    skip = [ln for ln in EXAMPLE if not ln.startswith("ask")]
    result = validate_script(skip, example_header())
    assert {"question_missing", "block_missing"} & set(codes(result))
    assert sorted(e.message for e in result.script_errors if e.code == "question_missing") == [
        "quiz question Q1 is never asked (ask Q1)",
        "quiz question Q2 is never asked (ask Q2)",
    ]

    twice = [*EXAMPLE[:11], "ask Q1", *EXAMPLE[11:]]
    result = validate_script(twice, example_header())
    assert [(e.line, e.code) for e in result.errors] == [(12, "question_twice")]

    no_card = [ln for ln in EXAMPLE if not ln.startswith("card")]
    assert "card_missing" in codes(validate_script(no_card, example_header()))
    no_machine = [ln for ln in EXAMPLE if not ln.startswith(("machine", "point"))]
    assert "block_missing" in codes(validate_script(no_machine, example_header()))
    unclosed = [ln for ln in EXAMPLE if not ln.startswith("close")]
    assert "close_missing" in codes(validate_script(unclosed, example_header()))


def test_a_close_before_its_open_and_a_double_open_are_refused():
    lines = ["scene market  cast=hero,friend", "close L1", 'open L1 "a"', 'open L1 "b"']
    result = validate_script(lines, example_header(mode="linear", stages=[], quiz={}, cards={}))
    assert "close_before_open" in codes(result)
    assert "open_twice" in codes(result)


def test_a_teaser_states_the_next_topic_and_is_last():
    header = example_header(stages=[12], mode="linear", opens={}, closes=[], quiz={}, cards={})
    ok = ["scene market  cast=hero,friend", 'teaser "Demain, les fractions."']
    assert validate_script(ok, header).errors == []
    bad = ["scene market  cast=hero,friend", 'teaser "Et demain ?"']
    assert codes(validate_script(bad, header)) == ["teaser_is_question"]
    notlast = ["scene market  cast=hero,friend", 'teaser "Demain."', 'narrate "Fin."']
    assert "teaser_not_last" in codes(validate_script(notlast, header))
    missing = ["scene market  cast=hero,friend", 'narrate "Fin."']
    assert "block_missing" in codes(validate_script(missing, header))


def test_the_script_is_capped_at_80_statements_with_a_warning_over_70():
    header = example_header(stages=[], mode="linear", opens={}, closes=[], quiz={}, cards={})
    lines = ["scene market  cast=hero,friend", *['narrate "x"'] * 71]
    result = validate_script(lines, header)
    assert result.valid
    assert "lines_over_target" in [w.code for w in result.warnings]
    lines = ["scene market  cast=hero,friend", *['narrate "x"'] * 80]
    result = validate_script(lines, header)
    assert [(e.line, e.code) for e in result.errors] == [(81, "too_many_lines")]


def test_the_pair_form_limits_each_language_and_counts_its_texts():
    header = example_header(languages=["fr", "en"], mode="linear", opens={}, closes=[],
                            quiz={}, cards={}, stages=[])  # fmt: skip
    ok = ["scene market  cast=hero,friend", 'say hero  "Bonjour !" | "Hello!"']
    assert validate_script(ok, header).errors == []
    one = ["scene market  cast=hero,friend", 'say hero  "Bonjour !"']
    assert codes(validate_script(one, header)) == ["text_count"]
    long_en = ["scene market  cast=hero,friend", 'say hero  "Court" | "' + "e" * 61 + '"']
    result = validate_script(long_en, header)
    assert codes(result) == ["too_long"] and "en text" in result.errors[0].message
    dangling = ["scene market  cast=hero,friend", 'say hero  "a" |']
    assert codes(validate_script(dangling, header)) == ["bad_syntax"]
    single = example_header(stages=[], mode="linear", opens={}, closes=[], quiz={}, cards={})
    assert codes(validate_script(ok, single)) == ["text_count"]


def test_the_picture_checks_are_warnings_not_errors():
    header = example_header(stages=[], mode="linear", opens={}, closes=[], quiz={})
    lines = [
        "scene market  cast=hero,friend",
        'say hero "Regarde cela !"',
        'say friend "A"',
        'say hero "B"',
        'say friend "C"',
        "machine place_value  n=777",
        "card groups_of_three",
    ]
    result = validate_script(lines, header)
    assert result.valid
    warned = {w.code for w in result.warnings}
    assert {"deictic_without_target", "silent_run", "number_not_in_facts"} <= warned
    early_card = ["scene market  cast=hero,friend", "card groups_of_three"]
    assert validate_script(early_card, header).valid
    assert "card_before_picture" in {w.code for w in validate_script(early_card, header).warnings}


def test_bet_machine_card_out_of_order_warns():
    lines = ["scene family_home  cast=hero,friend", "card groups_of_three", "machine place_value  n=45",
             'open L1 "Q ?"', "bet L1", 'mistake friend "Non"', "close L1", "ask Q1 Q2"]  # fmt: skip
    result = validate_script(lines, example_header(stages=[3, 5, 9], mode="linear"))
    assert "order_bet_machine_card" in {w.code for w in result.warnings}


def test_error_format_names_the_line_the_code_and_the_line_text():
    lines = list(EXAMPLE)
    lines[7] = 'say hero  "' + "x" * 70 + '"'
    result = validate_script(lines, example_header())
    text = grammar.format_errors(result.errors, lines)
    assert text.startswith("line 8 [too_long] error: say:")
    assert text.splitlines()[1].startswith("  > say hero")
    whole = grammar.format_errors([grammar.ScriptError(0, "question_missing", "Q1 is never asked")])
    assert whole.startswith("script [question_missing] error")


def test_repair_replaces_one_line_deletes_or_inserts_before_the_teaser():
    lines = ["a", "b", "c"]
    assert grammar.apply_repair(lines, 2, "```\nB\n```") == ["a", "B", "c"]
    assert grammar.apply_repair(lines, 2, "DELETE") == ["a", "c"]
    assert grammar.apply_repair(lines, 9, "x") == lines
    assert grammar.insert_missing(["a", 'teaser "t"'], "ask Q1\n") == ["a", "ask Q1", 'teaser "t"']
    assert grammar.insert_missing(["a"], "ask Q1") == ["a", "ask Q1"]


def test_stage_distribution_follows_the_table_of_2749():
    d = grammar.distribute_stages
    assert d(1, 1) == list(range(1, 13))
    assert d(1, 2) == [1, 2, 3, 4, 5] and d(2, 2) == [6, 7, 8, 9, 10, 11, 12]
    assert [d(i, 3) for i in (1, 2, 3)] == [[1, 2, 3, 4, 5], [6, 7, 8, 9], [10, 11, 12]]
    assert [d(i, 4) for i in (1, 2, 3, 4)] == [[1, 2, 3, 4, 5], [6], [7, 8, 9], [10, 11, 12]]
    assert [d(i, 6) for i in range(1, 7)][1:4] == [[6], [6], [6]]
    assert 4 not in d(1, 4, mentor=False)
    assert grammar.required_blocks([3, 5, 9, 11, 12]) == [
        "bet",
        "mistake",
        "machine",
        "card",
        "ask",
        "teaser",
    ]


# -- the export step -----------------------------------------------------------------------


def _fixture() -> dict:
    return json.loads((_FIXTURES / "story_screenplay_module.json").read_text("utf-8"))


def _bundle(unit: str = "1.1", *, maths: bool = False) -> dict:
    from tests.test_story_screenplay_module import pack

    data = _fixture()
    plan = json.loads((_FIXTURES / "story_module_plan.json").read_text("utf-8"))
    lesson = {k: v["en"] for k, v in data["lessons"][unit]["lesson"].items() if isinstance(v, dict)}
    title = {"en": "Arithmetic", "fr": "Calcul"} if maths else {"en": "Biology", "fr": "Biologie"}
    stored = {
        "cast": [{"id": "hero"}, {"id": "friend"}, {"id": "family"}, {"id": "margo"}],
        "places": [{"id": "courtyard", "title": {"en": "The courtyard", "fr": "La cour"}}],
        "props": [{"id": "snail", "label": {"en": "the snail", "fr": "l'escargot"}}],
        "questions": [{"id": "q1", "prompt": {"en": "Is the snail alive?", "fr": "L'escargot vit ?"}}],
        "chapters": [{"scenes": [{"place": "courtyard", "cast": ["hero", "friend"], "steps": [
            {"type": "narrate", "en": "Saturday.", "fr": "Samedi."},
            {"type": "say", "who": "friend", "mood": "surprised", "en": "A snail!", "fr": "Un escargot !", "props": ["snail"]},
            {"type": "concept", "title": {"en": "Alive", "fr": "Vivant"}, "en": ["reacts"], "fr": ["réagit"]},
            {"type": "ask", "ref": "q1"},
        ]}]}],
    }  # fmt: skip
    return export.build_bundle(
        course_title=title, module_title=title, module_id="6f1c1d2e-0000", language="en",
        unit=unit, plan=plan, pack=pack(unit, "en"), lesson=lesson, stored=stored,
    )  # fmt: skip


def test_export_builds_a_chapter_file_from_plan_pack_lesson_and_stored_chapter():
    bundle = _bundle()
    assert bundle["id"] == "6f1c1d2e-1.1-en"
    assert (
        bundle["chapter_index"] == 1 and bundle["chapter_count"] == 4
    )  # three lessons + the rally
    assert bundle["plan_entry"]["title"]["en"] == "The shy snail"
    assert "chapters" not in bundle["plan_global"]
    assert bundle["fact_sheet"]["ideas"] and bundle["pack"]["derived"]
    json.dumps(bundle)  # a file


def test_export_picks_three_maths_and_three_other_chapters_one_module_first():
    items = [{"id": str(i), "module_id": f"m{i % 3}", "is_maths": i % 2 == 0} for i in range(12)]
    six = export.pick_six(items)
    assert len(six) == 6
    assert sum(b["is_maths"] for b in six) == 3
    assert export.looks_like_maths({"en": "Arithmetic"}, {"en": "x"})
    assert not export.looks_like_maths({"en": "Biology"}, {"en": "Cells"})


def test_export_only_selects():
    source = (_SCRIPTS / "story_script_export.py").read_text("utf-8")
    assert "SET TRANSACTION READ ONLY" in source
    for write in (
        ".commit(",
        "session.add",
        "insert(User",
        ".update(",
        "delete(",
        "INSERT ",
        "UPDATE ",
        "DELETE ",
    ):
        assert write not in source, write


# -- the harness -------------------------------------------------------------------------------


class FakeModel:
    """Answers from a queue; counts what was asked."""

    def __init__(self, replies, name="fake-model"):
        self.name = name
        self.replies = list(replies)
        self.asked: list[tuple[str, str]] = []

    async def complete(self, system, user, max_tokens):
        assert max_tokens == harness.MAX_TOKENS == 3000
        self.asked.append((system, user))
        return self.replies.pop(0)


def Reply(text, out=100, inp=50, stop="end_turn"):  # noqa: N802
    return harness.Reply(text, out, inp, stop)


def good_script(header: Header) -> list[str]:
    """A script the validator accepts, made from the header alone."""
    place = header.places[0]
    lines = [f"scene {place}  cast=hero,friend"]
    for ref in header.opens:
        lines += [f'open {ref}  "Question ?"', f"bet {ref}", 'mistake friend  "Je crois que non."']
        lines += [f"machine {header.machines[0]}  n=1", "point hero  target=machine.part"]
        lines += [f"close {ref}"]
    lines += [f"card {c}" for c in header.cards]
    lines += [f"ask {' '.join(header.quiz)}"] if header.quiz else []
    if "teaser" in header.required:
        lines.append('teaser "Demain, la suite."')
    return lines


def test_header_is_built_from_plan_pack_and_fact_sheet_with_hand_assignments():
    bundle = _bundle()
    header = harness.build_header(
        bundle, {"stages": [3, 5, 9], "wrong": {"L1": "Elle est morte."}}, ["fr"]
    )
    assert header.stages == [3, 5, 9] and header.required[:4] == [
        "bet",
        "mistake",
        "machine",
        "card",
    ]
    assert list(header.opens) == ["L1", "L2", "L3"]
    assert header.closes == ["L1", "L2", "L3"]
    assert header.bets["L1"]["wrong"] == "Elle est morte."
    assert header.bets["L2"]["right"].startswith("Une graine")
    assert set(header.places) == set(harness.STOCK_PLACES)
    assert "tutor" in header.cast and "hero" in header.cast
    assert "place_value" not in header.machines
    assert "place_value" in harness.build_header(_bundle(maths=True), {}, ["fr"]).machines
    assert header.quiz and all(k.startswith("Q") for k in header.quiz) and len(header.quiz) <= 4
    assert header.cards and all(len(k) <= 30 for k in header.cards)
    default = harness.build_header(bundle, {}, ["fr", "en"])
    assert default.pair and default.stages == grammar.distribute_stages(
        1, 4, mentor=False
    )  # no mentor in this cast


def test_header_reads_a_pack_as_it_is_stored_under_spine_and_the_stored_wording():
    bundle = _bundle()
    plain = harness.build_header(bundle, {}, ["fr"])
    # ``story_courses.source_rows["pack"]`` wraps the questions: {"spine": ..., "stems": ..., "inputs": ...}
    stored = {**bundle, "pack": {"spine": bundle["pack"], "stems": {}, "inputs": "digest"}}
    wrapped = harness.build_header(stored, {}, ["fr"])
    assert wrapped.quiz == plain.quiz and len(wrapped.quiz) >= 1
    # a derived question takes the wording the stored chapter gives it, in the script's language
    refs = [r for b in bundle["plan_entry"]["beats"] for r in b.get("questions") or []]
    told = {**stored, "stored": {**bundle["stored"], "questions": [
        {"id": refs[0], "prompt": {"en": "Is it alive?", "fr": "Est-ce vivant ?"}}
    ]}}  # fmt: skip
    assert harness.build_header(told, {}, ["fr"]).quiz["Q1"] == "Est-ce vivant ?"


def test_prompts_carry_the_grammar_the_header_and_the_facts_and_no_secret():
    bundle = _bundle()
    header = harness.build_header(bundle, {}, ["fr", "en"])
    system, user = harness.grammar_reference(header), harness.build_user_message(bundle, header)
    for macro in ("scene", "say", "mistake", "machine", "bet", "teaser"):
        assert macro in system
    assert "cliff" not in system  # loops are not offered in linear mode
    assert '"<fr>" | "<en>"' in system and '"fr" first' in system
    assert "QUIZ questions" in user and "KEY FACTS" in user and "L1" in user
    assert "ANTHROPIC" not in system + user


def test_a_valid_first_answer_costs_one_call_and_no_repair():
    bundle = _bundle()
    header = harness.build_header(bundle, {"stages": [3, 5, 9]}, ["fr"])
    model = FakeModel([Reply("```\n" + "\n".join(good_script(header)) + "\n```", out=900)])
    run = asyncio.run(harness.run_one(model, bundle, header, 0))
    assert run.first_valid and run.final_valid and run.repair_calls == 0
    assert run.first_tokens == run.total_tokens == 900 and len(model.asked) == 1


def test_one_faulty_line_is_repaired_alone_with_one_call_and_its_tokens_are_counted():
    bundle = _bundle()
    header = harness.build_header(bundle, {"stages": [3, 5, 9]}, ["fr"])
    script = good_script(header)
    script[1] = 'open L1  "' + "x" * 100 + '"'
    model = FakeModel(
        [Reply("\n".join(script), out=800), Reply('open L1  "Une question ?"', out=30)]
    )
    run = asyncio.run(harness.run_one(model, bundle, header, 0))
    assert not run.first_valid and run.final_valid
    assert run.repair_calls == 1 and run.first_tokens == 800 and run.total_tokens == 830
    assert run.first_errors == ["2:too_long"]
    repair_user = model.asked[1][1]
    assert "line 2 [too_long]" in repair_user and "x" * 100 in repair_user
    assert "THE BEATS" not in repair_user  # the line alone, not the chapter again


def test_a_missing_item_costs_one_insert_call_and_the_repair_is_one_round_only():
    bundle = _bundle()
    header = harness.build_header(bundle, {"stages": [3, 5, 9]}, ["fr"])
    script = [ln for ln in good_script(header) if not ln.startswith("ask")]
    model = FakeModel([Reply("\n".join(script)), Reply("ask " + " ".join(header.quiz))])
    run = asyncio.run(harness.run_one(model, bundle, header, 0))
    assert run.final_valid and run.repair_calls == 1

    still_bad = FakeModel([Reply("\n".join(script)), Reply('narrate "rien"')])
    run = asyncio.run(harness.run_one(still_bad, bundle, header, 0))
    assert not run.final_valid and run.repair_calls == 1 and len(still_bad.asked) == 2


def test_a_runaway_answer_is_invalid_and_is_not_repaired():
    bundle = _bundle()
    header = harness.build_header(bundle, {"stages": [3, 5, 9]}, ["fr"])
    model = FakeModel([Reply("\n".join(good_script(header)), out=3000, stop="max_tokens")])
    run = asyncio.run(harness.run_one(model, bundle, header, 0))
    assert not run.final_valid and run.repair_calls == 0 and run.stop_reason == "max_tokens"


def test_the_matrix_is_two_models_three_runs_and_the_pair_form_of_one_model():
    rows = harness.plan_matrix([f"c{i}" for i in range(6)])
    one_language = [r for r in rows if r[2] == ("fr",)]
    assert len(one_language) == 36
    assert {r[1] for r in one_language} == set(harness.MODELS)
    pair = [r for r in rows if r[2] == ("fr", "en")]
    assert len(pair) == 18 and {r[1] for r in pair} == {harness.PAIR_MODEL}
    assert harness.estimate(len(rows))["calls"] == 54


def test_the_summary_applies_the_gate_per_model():
    def run(model, first, final, tokens, first_tokens=900, repairs=0):
        return harness.Run("c", model, ["fr"], 0, first_valid=first, final_valid=final,
                           total_tokens=tokens, first_tokens=first_tokens, repair_calls=repairs)  # fmt: skip

    runs = [run("big", True, True, 900)] * 9 + [run("big", False, True, 1400, repairs=1)]
    runs += [run("small", False, False, 700)] * 4 + [run("small", True, True, 700)] * 6
    rows = {r["model"]: r for r in harness.summarise(runs)}
    assert rows["big"]["valid_after_repair"] == 1.0 and rows["big"]["valid_first"] == 0.9
    assert rows["big"]["meets_gate"] and rows["big"]["repair_calls"] == 1
    assert not rows["small"]["meets_gate"]  # 60 % valid
    over = [run("big", True, True, 1600)] * 3
    assert not harness.summarise(over)[0]["meets_gate"]
    assert "FAIL" in harness.report_markdown(runs) and "PASS" in harness.report_markdown(runs)


def test_run_without_spend_builds_no_model_and_sends_nothing(tmp_path, monkeypatch, capsys):
    (tmp_path / "chapter-a.json").write_text(json.dumps(_bundle()), "utf-8")

    def boom(*_a, **_k):
        raise AssertionError("a model was built")

    monkeypatch.setattr(harness, "AnthropicModel", boom)
    code = harness.main(["run", "--chapters", str(tmp_path), "--out", str(tmp_path / "out")])
    assert code == 0 and "dry run: nothing was sent" in capsys.readouterr().out
    assert not (tmp_path / "out" / "results.json").exists()


def test_a_paid_run_keeps_every_finished_run_and_resumes_without_buying_them_again(
    tmp_path, monkeypatch
):
    (tmp_path / "chapter-a.json").write_text(json.dumps(_bundle()), "utf-8")
    bundle = _bundle()
    header = harness.build_header(bundle, {}, ["fr"])
    ok = "\n".join(good_script(header))

    class Flaky:
        """Answers ``budget`` calls, then fails as an overloaded API does."""

        def __init__(self, name, budget):
            self.name, self.budget, self.calls = name, budget, 0

        def named(self, name):
            self.name = name
            return self

        async def complete(self, system, user, max_tokens):
            self.calls += 1
            if self.calls > self.budget:
                raise RuntimeError("529 overloaded")
            return harness.Reply(ok, 100, 50)

    out = tmp_path / "out"
    args = ["run", "--chapters", str(tmp_path), "--out", str(out), "--spend"]
    first = Flaky("m", 4)  # a chapter's matrix is 9 runs
    monkeypatch.setattr(harness, "AnthropicModel", lambda name: first.named(name))
    with pytest.raises(RuntimeError):
        harness.main(args)
    kept = json.loads((out / "results.json").read_text("utf-8"))
    assert 0 < len(kept) < 9  # nothing paid for is lost

    second = Flaky("m", 1000)
    monkeypatch.setattr(harness, "AnthropicModel", lambda name: second.named(name))
    started = []
    real_run_one = harness.run_one

    async def counting(model, bundle, header, index, **kw):
        started.append(1)
        return await real_run_one(model, bundle, header, index, **kw)

    monkeypatch.setattr(harness, "run_one", counting)
    assert harness.main(args) == 0
    assert len(json.loads((out / "results.json").read_text("utf-8"))) == 9  # one chapter: 9 rows
    assert len(started) == 9 - len(kept)  # only what was missing


def test_the_harness_finds_the_provider_layer_when_run_as_a_script(tmp_path):
    """``python scripts/story_script_paper_test.py`` puts only ``scripts/`` on the path."""
    import subprocess

    code = (
        "import sys; sys.path[:] = [p for p in sys.path if not p.endswith('backend')];"
        f"sys.path.insert(0, {str(_SCRIPTS)!r});"
        "import story_script_paper_test, importlib;"
        "importlib.import_module('app.ai.providers.anthropic_provider')"
    )
    done = subprocess.run(
        [sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True, env={"PATH": ""}
    )
    assert done.returncode == 0, done.stderr


def test_the_harness_never_uses_the_recording_wrapper_or_prints_a_key():
    source = (_SCRIPTS / "story_script_paper_test.py").read_text("utf-8")
    assert "resolve_provider" not in source.replace("``resolve_provider``", "")
    assert "RecordingLLMProvider" not in source
    assert "print(key" not in source and "environ" in source


def test_prompts_command_writes_files_and_calls_no_model(tmp_path, monkeypatch):
    (tmp_path / "chapter-a.json").write_text(json.dumps(_bundle()), "utf-8")
    monkeypatch.setattr(harness, "AnthropicModel", lambda *_a, **_k: pytest.fail("model built"))
    assert harness.main(["prompts", "--chapters", str(tmp_path), "--out", str(tmp_path / "p")]) == 0
    names = sorted(p.name for p in (tmp_path / "p").iterdir())
    assert any(n.endswith("-fr.user.txt") for n in names) and any(
        n.endswith("-fr+en.header.json") for n in names
    )


# -- the storyboards and the blind pairs --------------------------------------------------------------


def test_stored_chapter_and_script_render_with_the_same_template():
    bundle = _bundle()
    stored = board.storyboard_stored(bundle["stored"], "en")
    assert stored.startswith("Scene 1 - The courtyard - on stage: hero, friend")
    assert "friend: A snail!  (points at the snail)" in stored  # margo would read tutor
    assert (
        "[card: Alive  (reacts)]" in stored
        and "[question for the learner: Is the snail alive?]" in stored
    )

    statements, _ = grammar.parse_script(EXAMPLE)
    new = board.storyboard_script(statements, example_header())
    assert new.startswith("Scene 1 - family_home - on stage: hero, friend, family")
    assert "[picture: place_value  (n=4305892176 reveal=groups)]" in new
    assert "[hero points at machine.millions]" in new
    assert "friend: Quatre mille... trois cents ?  [wrong idea]" in new
    assert "[on stage: the cash register]" in new
    assert "[question for the learner: q one]" in new
    assert "Scene 2 - market" in new
    for text in (stored, new):  # neither says which one is the new one
        assert "script" not in text.lower() and "stored" not in text.lower()


def test_blind_pairs_hide_the_origin_and_the_key_is_deterministic():
    pairs = [(f"chap{i:02d}-x", f"STORED{i}", f"NEW{i}") for i in range(6)]
    sheet, key = board.blind_pairs(pairs, seed=1)
    assert board.blind_pairs(pairs, seed=1) == (sheet, key)
    assert board.blind_pairs(pairs, seed=2)[1] != key
    assert "STORED" in sheet and "NEW" in sheet  # the boards themselves, under neutral headings
    assert "origin" not in sheet.lower()
    assert sheet.count("### Chapter A") == 6 and sheet.count("### Chapter B") == 6
    assert set(key) == {p[0] for p in pairs}
    assert all(set(v.values()) == {"stored", "new"} for v in key.values())
    # the chapter in position A is the one the key says
    for chapter_id, _stored, new in pairs:
        block = sheet.split(f"(ref {chapter_id[:8]})")[1].split("## Pair")[0]
        first = block.split("### Chapter B")[0]
        assert (new in first) == (key[chapter_id]["A"] == "new")


def test_a_pair_is_won_by_the_majority_of_its_readers_and_the_gate_needs_four_of_six():
    key = {f"c{i}": {"A": "new", "B": "stored"} for i in range(6)}
    votes = {
        "c0": ["A", "A", "B"], "c1": ["A", "A", "A"], "c2": ["B", "B", "A"],
        "c3": ["A", "B", "A"], "c4": ["A", "A", "B"], "c5": ["B", "B", "B"],
    }  # fmt: skip
    result = board.tally(key, votes)
    assert result["new_wins"] == 4 and result["passes"]
    votes["c4"] = ["B", "A", "B"]
    assert not board.tally(key, votes)["passes"]
    flipped = {"c0": {"A": "stored", "B": "new"}}
    assert board.tally(flipped, {"c0": ["B", "B", "A"]})["new_wins"] == 1


def test_blind_command_writes_the_sheet_the_key_and_the_fact_check(tmp_path):
    bundle = _bundle()
    header = harness.build_header(bundle, {"stages": [3, 5, 9]}, ["fr"])
    run = harness.Run(bundle["id"], "m", ["fr"], 0, script=good_script(header), final_valid=True)
    results = tmp_path / "results.json"
    results.write_text(json.dumps([run.__dict__]), "utf-8")
    (tmp_path / "chapter-a.json").write_text(json.dumps(bundle), "utf-8")
    code = harness.main(["blind", "--results", str(results), "--chapters", str(tmp_path),
                         "--out", str(tmp_path / "o"), "--model", "m"])  # fmt: skip
    assert code == 0
    out = tmp_path / "o"
    assert "Chapter A" in (out / "blind-sheet.md").read_text("utf-8")
    assert json.loads((out / "blind-key.json").read_text("utf-8"))
    assert "Facts:" in (out / "fact-check.md").read_text("utf-8")
    assert "blind-key" not in (out / "blind-sheet.md").read_text("utf-8")
