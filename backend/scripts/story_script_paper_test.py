#!/usr/bin/env python3
"""Offline harness of the director-script paper test (#2737).

A SPIKE: nothing here is imported by ``app/``, nothing is written to a
database, and a model is called ONLY with ``--spend`` (the owner's go-ahead).
Every other command, and the tests, use no model at all.

Input: chapter files exported once by ``story_script_export.py`` (six existing
chapters, three maths and three from other subjects), and an
``assignments.json`` that holds, per chapter, what code will assign later and
a person assigns by hand now: the journey stages (the table of #2749), the
questions to open and close, the hand-written wrong choice of each bet.

Commands::

    prompts   build every header and prompt, call nothing (check what would be sent)
    run       ask the models (needs --spend and ANTHROPIC_API_KEY in the environment)
    report    the figures of the issue, from the results file
    blind     the blind sheet (A/B in random order) and its key, from the results file
    tally     the readers' votes against the key

The model layer is the provider layer's ``AnthropicLLMProvider`` WITHOUT the
recording wrapper of ``resolve_provider``, which writes ledger rows. The key
comes from the environment and is never logged or stored. ``max_tokens`` is
3,000, so a runaway answer costs cents.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

# ``scripts/`` for the sibling modules, ``backend/`` for ``app`` (the provider layer), as the export does.
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

import story_script_storyboard as board  # noqa: E402
from story_script_grammar import (  # noqa: E402
    DIALOGUE_LIMIT,
    MACROS,
    MAX_LINES,
    MOODS,
    ROLES,
    TARGET_LINES,
    Header,
    ScriptError,
    ValidationResult,
    apply_repair,
    distribute_stages,
    extract_lines,
    format_errors,
    insert_missing,
    validate_script,
)

MAX_TOKENS = 3000
RUNS_PER_CHAPTER = 3
#: The two models of the test; the first also runs the two-language form.
MODELS = ("claude-sonnet-4-6", "claude-haiku-4-5")
PAIR_MODEL = MODELS[0]
#: The hand-made menu (the library menu is #2742): the stock places and the drawn visuals.
STOCK_PLACES = (
    "home",
    "kitchen",
    "market",
    "classroom",
    "school_yard",
    "mango_farm",
    "bus_station",
)
GENERIC_MACHINES = ("compare", "annotate", "sort", "timeline")
MATHS_MACHINES = ("place_value", "number_line", "hundred_square", "factor_tree", "division_ladder")
#: Gate of the phase 0 exit test.
GATE_VALID = 0.90
GATE_TOKENS = 1500
GATE_WINS = 4
#: The issue's estimate: about 6,000 input and 1,500 output tokens per call.
ASSUMED_INPUT, ASSUMED_OUTPUT = 6000, 1500

# -- the model layer -----------------------------------------------------------------


@dataclass
class Reply:
    text: str
    output_tokens: int = 0
    input_tokens: int = 0
    stop_reason: str = "end_turn"


class Model(Protocol):
    name: str

    async def complete(self, system: str, user: str, max_tokens: int) -> Reply: ...


class AnthropicModel:
    """A real model, through the provider layer without its recording wrapper."""

    def __init__(self, name: str) -> None:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise SystemExit("ANTHROPIC_API_KEY is not set in the environment")
        from app.ai.providers.anthropic_provider import AnthropicLLMProvider

        self.name = name
        self._provider = AnthropicLLMProvider(api_key=key)

    async def complete(self, system: str, user: str, max_tokens: int) -> Reply:
        result = await self._provider.complete(
            system=system,
            messages=[{"role": "user", "content": user}],
            max_tokens=max_tokens,
            temperature=0.7,
            model=self.name,
        )
        usage = result.usage or {}
        return Reply(
            result.text,
            int(usage.get("output_tokens") or 0),
            int(usage.get("input_tokens") or 0),
            result.stop_reason,
        )


# -- the header and the prompts ------------------------------------------------------------


def _pair(value: Any, language: str) -> str:
    if isinstance(value, dict):
        value = value.get(language) or next((v for v in value.values() if v), "")
    return " ".join(str(value or "").split())


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")[:30] or "card"


def _digits(text: str) -> set[str]:
    return {re.sub(r"\D", "", m) for m in re.findall(r"\d[\d\s.,]*\d|\d", text)} - {""}


def build_header(
    bundle: dict[str, Any], assignment: dict[str, Any], languages: list[str]
) -> Header:
    """The header code will build later (#2746), assigned by hand where it cannot yet."""
    lang = languages[0]
    entry = bundle.get("plan_entry") or {}
    beats = [b for b in entry.get("beats") or [] if isinstance(b, dict)]
    pack = bundle.get("pack") or {}
    sheet = bundle.get("fact_sheet") or {}
    stored_cast = [m.get("id") for m in (bundle.get("stored") or {}).get("cast") or []]
    roles = ["hero", "friend"] + [
        r for r in dict.fromkeys(board._ROLE_OF.get(c, c) for c in stored_cast)
        if r in ROLES and r not in ("hero", "friend")
    ]  # fmt: skip
    # quiz questions: the beats' refs first, then the pack's extra questions
    stems: dict[str, str] = {}
    derived = {d.get("ref"): d for d in pack.get("derived") or [] if isinstance(d, dict)}
    for beat in beats:
        for ref in beat.get("questions") or []:
            d = derived.get(ref) or {}
            stems.setdefault(ref, _pair(d.get("prompt_home") or d.get("prompt"), lang) or ref)
    for q in pack.get("questions") or []:
        if isinstance(q, dict) and q.get("id"):
            stems.setdefault(q["id"], _pair(q.get("prompt"), lang))
    quiz = {f"Q{i}": stem for i, stem in enumerate(list(stems.values())[:4], start=1)}
    cards = {}
    for beat in beats:
        title = _pair(beat.get("card_title"), lang)
        if title:
            cards[_slug(_pair(beat.get("card_title"), "en") or title)] = title
    opens = assignment.get("opens") or {
        f"L{i}": _pair(b.get("problem"), lang) or _pair(entry.get("goal"), lang)
        for i, b in enumerate(beats[:3], start=1)
    }
    closes = assignment.get("closes", list(opens))
    bets, wrong = {}, assignment.get("wrong") or {}
    for i, ref in enumerate(opens):
        beat = beats[min(i, len(beats) - 1)] if beats else {}
        bets[ref] = {
            "right": _pair(beat.get("discovery"), lang),
            "wrong": wrong.get(ref) or _pair(beat.get("problem"), lang) or _pair(entry.get("obstacle"), lang),
        }  # fmt: skip
    objects = {}
    for prop in (bundle.get("plan_global") or {}).get("props") or []:
        if isinstance(prop, dict) and prop.get("id"):
            objects[str(prop["id"])] = _pair(prop, lang)
    for n, fig in enumerate(sheet.get("figures") or [], start=1):
        objects[f"fig{n}"] = (fig[2] if lang == "fr" else fig[1]) or f"figure {n}"
        if n == 3:
            break
    count, index = int(bundle.get("chapter_count") or 1), int(bundle.get("chapter_index") or 1)
    machines = list(GENERIC_MACHINES) + (list(MATHS_MACHINES) if bundle.get("is_maths") else [])
    numbers: set[str] = set()
    for text in [*sheet.get("ideas", []), *sheet.get("key_facts", []), *quiz.values()]:
        numbers |= _digits(str(text))
    return Header(
        chapter=str(bundle.get("id")),
        languages=languages,
        mode="linear",
        stages=list(
            assignment.get("stages") or distribute_stages(index, count, mentor="mentor" in roles)
        ),
        opens=opens,
        closes=closes,
        quiz=quiz,
        cards=cards,
        cast=roles,
        places=list(assignment.get("places") or STOCK_PLACES),
        objects=objects,
        machines=machines,
        numbers=sorted(numbers),
        bets=bets,
    )


def grammar_reference(header: Header) -> str:
    """The system prompt: the grammar, built from the macro table so the two cannot drift."""
    rows = []
    for macro in MACROS.values():
        if macro.loop_only:
            continue
        args = " ".join(f"<{a.name}>" for a in macro.positional)
        args += "..." if macro.variadic else ""
        named = " ".join(
            f"[{a.name}=..]" if not a.required else f"{a.name}=.." for a in macro.named
        )
        pair_form = f' "<{header.languages[0]}>" | "<{header.languages[-1]}>"'
        text = (
            pair_form
            if macro.text == "one" and header.pair
            else (' "text"' if macro.text == "one" else "")
        )
        limit = (
            f"   (text at most {macro.limit} characters"
            + (" in each language)" if header.pair else ")")
            if macro.limit
            else ""
        )
        rows.append(f"  {macro.name} {args} {named}{text}{limit}".rstrip())
    pair = (
        f'Write every text in two languages, "{header.languages[0]}" first, a "|", then "{header.languages[1]}".'
        if header.pair
        else f"Write every text in {header.languages[0]} only."
    )
    return (
        "You write the director script of ONE chapter of an educational story. A script is a short\n"
        "list of lines, one statement per line, nothing else (no comment, no explanation).\n\n"
        "MACROS:\n" + "\n".join(rows) + "\n\n"
        f"- {pair}\n"
        f"- About {TARGET_LINES} lines at most {MAX_LINES}; about 40 of them lines said by characters. "
        f"A said line has at most {DIALOGUE_LIMIT} characters.\n"
        f"- Roles only: {', '.join(ROLES)}. Never a first name. The hero is the learner.\n"
        f"- mood is one of: {', '.join(MOODS)}.\n"
        "- Start with a scene. A scene has 2 or 3 roles on stage in cast=a,b,c; only they speak.\n"
        "- Order of an idea: open the question, bet, a character says the wrong idea (mistake, never the hero), "
        "machine shows it, point at it, card names the rule, close the question.\n"
        "- A line that says 'this' or 'look' is preceded by a point, show or machine.\n"
        "- At most 3 lines in a row without a visible change (scene, show, machine, point, card, bet, ask).\n"
        "- Use ONLY the ids, numbers and facts of the header and the lesson. Never invent a fact.\n"
        "- A teaser (if asked) states the next topic and does not end with a question mark.\n"
        "- Answer with the script only, in a code block."
    )


def build_user_message(bundle: dict[str, Any], header: Header) -> str:
    """What the model sees for one chapter: the header code imposes, then the lesson's facts."""
    lang = header.languages[0]
    entry = bundle.get("plan_entry") or {}
    plan = bundle.get("plan_global") or {}
    sheet = bundle.get("fact_sheet") or {}
    lines = [
        f"CHAPTER {bundle.get('chapter_index')} of {bundle.get('chapter_count')}: «{_pair(entry.get('title'), lang)}»",
        f"EPISODE: «{_pair(plan.get('episode_title'), lang)}» - {plan.get('logline', '')}",
        f"GOAL: {_pair(entry.get('goal'), lang)}    OBSTACLE: {_pair(entry.get('obstacle'), lang)}",
        f"STAGES of the journey this chapter plays: {', '.join(str(s) for s in header.stages)}",
        f"REQUIRED blocks: {', '.join(header.required)}",
        "",
        f"SCENES allowed (places): {', '.join(header.places)}",
        f"ROLES in the cast: {', '.join(header.cast)}",
        f"MACHINES: {', '.join(header.machines)}",
        "OBJECTS: " + (", ".join(f"{k} ({v})" for k, v in header.objects.items()) or "none"),
        "",
        "QUESTIONS to open and close (write each one's wording in the open line):",
    ]
    for ref, hint in header.opens.items():
        bet = header.bets.get(ref, {})
        lines.append(
            f"  {ref}: about «{hint}». The bet offers: «{bet.get('right', '')}» / «{bet.get('wrong', '')}» / I don't know."
        )
    lines.append(
        "QUIZ questions to place (ask each once): "
        + "; ".join(f"{k} «{v}»" for k, v in header.quiz.items())
    )
    lines.append("CARDS to place: " + "; ".join(f"{k} «{v}»" for k, v in header.cards.items()))
    lines.append("")
    lines.append("THE BEATS (ideas to show, in order):")
    for n, beat in enumerate(entry.get("beats") or [], start=1):
        lines.append(
            f"  {n}. problem: {beat.get('problem', '')} | discovery: {_pair(beat.get('discovery'), lang)}"
        )
    lines.append("")
    lines.append("LESSON IDEAS: " + " | ".join(sheet.get("ideas", [])))
    lines.append("KEY FACTS: " + " | ".join(sheet.get("key_facts", [])))
    lines.append("")
    lines.append("Write the script.")
    return "\n".join(lines)


def repair_message(header: Header, lines: list[str], error: ScriptError) -> str:
    """The repair of ONE faulty line: the line, its error and a little context; nothing else."""
    before = lines[error.line - 2] if error.line >= 2 else ""
    return (
        "One line of your script is wrong. Answer with the corrected line only (no explanation, no code block),"
        " or DELETE if the line must go.\n\n"
        + format_errors([error], lines)
        + f"\nThe line before it: {before}\n"
        f"Allowed: places {', '.join(header.places)}; roles {', '.join(header.cast)}; machines {', '.join(header.machines)};"
        f" objects {', '.join(header.objects) or 'none'}; quiz {', '.join(header.quiz)}; cards {', '.join(header.cards)}."
    )


def missing_message(header: Header, errors: list[ScriptError]) -> str:
    return (
        "Your script lacks something. Answer with the missing line(s) only, one statement per line"
        " (no explanation).\n\n" + format_errors(errors)
    )


# -- one run ---------------------------------------------------------------------------------


@dataclass
class Run:
    chapter: str
    model: str
    languages: list[str]
    run: int
    script: list[str] = field(default_factory=list)
    first_valid: bool = False
    final_valid: bool = False
    first_tokens: int = 0
    total_tokens: int = 0
    input_tokens: int = 0
    repair_calls: int = 0
    stop_reason: str = ""
    first_errors: list[str] = field(default_factory=list)
    final_errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    dialogue: int = 0
    statements: int = 0


def _codes(errors: list[ScriptError]) -> list[str]:
    return [f"{e.line}:{e.code}" for e in errors]


async def run_one(
    model: Model,
    bundle: dict[str, Any],
    header: Header,
    index: int,
    *,
    max_tokens: int = MAX_TOKENS,
) -> Run:
    """Ask once, validate, repair each faulty line alone with one call, validate again."""
    system, user = grammar_reference(header), build_user_message(bundle, header)
    out = Run(str(bundle.get("id")), model.name, list(header.languages), index)
    reply = await model.complete(system, user, max_tokens)
    out.first_tokens = out.total_tokens = reply.output_tokens
    out.input_tokens = reply.input_tokens
    out.stop_reason = reply.stop_reason
    lines = extract_lines(reply.text)
    result = validate_script(lines, header)
    out.first_valid = result.valid
    out.first_errors = _codes(result.errors)
    if not result.valid and reply.stop_reason != "max_tokens":
        lines, result = await _repair(model, header, lines, result, out, max_tokens)
    out.script = lines
    out.final_valid = result.valid and reply.stop_reason != "max_tokens"
    out.final_errors = _codes(result.errors)
    out.warnings = _codes(result.warnings)
    out.dialogue, out.statements = result.stats["dialogue"], result.stats["statements"]
    return out


async def _repair(model, header, lines, result: ValidationResult, out: Run, max_tokens):
    """One round: a call per faulty line (first error of each), one call for what is missing."""
    by_line: dict[int, ScriptError] = {}
    for error in result.errors:
        if error.line:
            by_line.setdefault(error.line, error)
    answers: dict[int, str] = {}
    for number, error in by_line.items():
        reply = await model.complete(
            grammar_reference(header), repair_message(header, lines, error), max_tokens
        )
        out.repair_calls += 1
        out.total_tokens += reply.output_tokens
        out.input_tokens += reply.input_tokens
        answers[number] = reply.text
    fixed = list(lines)
    for number in sorted(answers, reverse=True):  # from the end, so numbers above stay valid
        fixed = apply_repair(fixed, number, answers[number])
    missing = result.script_errors
    if missing:
        reply = await model.complete(
            grammar_reference(header), missing_message(header, missing), max_tokens
        )
        out.repair_calls += 1
        out.total_tokens += reply.output_tokens
        out.input_tokens += reply.input_tokens
        fixed = insert_missing(fixed, reply.text)
    return fixed, validate_script(fixed, header)


# -- the matrix, the report -------------------------------------------------------------------


def plan_matrix(
    chapters: list[str], models: tuple[str, ...] = MODELS
) -> list[tuple[str, tuple[str, ...], int]]:
    """``(model, languages, run)`` for each chapter: 2 models x 3 runs in one language, plus the pair form."""
    rows = []
    for chapter in chapters:
        for model in models:
            for run in range(RUNS_PER_CHAPTER):
                rows.append((chapter, model, ("fr",), run))
        for run in range(RUNS_PER_CHAPTER):
            rows.append((chapter, PAIR_MODEL, ("fr", "en"), run))
    return rows


def estimate(rows: int) -> dict[str, int]:
    """The issue's own assumptions, before any call (repairs not counted)."""
    return {
        "calls": rows,
        "input_tokens": rows * ASSUMED_INPUT,
        "output_tokens": rows * ASSUMED_OUTPUT,
    }


def summarise(runs: list[Run]) -> list[dict[str, Any]]:
    """Per (model, languages): validity before and after repair, tokens first and with repairs."""
    groups: dict[tuple[str, str], list[Run]] = {}
    for r in runs:
        groups.setdefault((r.model, "+".join(r.languages)), []).append(r)
    rows = []
    for (model, langs), items in sorted(groups.items()):
        n = len(items)
        valid_after = sum(r.final_valid for r in items) / n
        mean_total = sum(r.total_tokens for r in items) / n
        rows.append(
            {
                "model": model,
                "languages": langs,
                "scripts": n,
                "valid_first": sum(r.first_valid for r in items) / n,
                "valid_after_repair": valid_after,
                "tokens_first_answer": sum(r.first_tokens for r in items) / n,
                "tokens_with_repairs": mean_total,
                "repair_calls": sum(r.repair_calls for r in items),
                "dialogue_lines": sum(r.dialogue for r in items) / n,
                "statements": sum(r.statements for r in items) / n,
                "max_tokens_hit": sum(r.stop_reason == "max_tokens" for r in items),
                "meets_gate": valid_after >= GATE_VALID and mean_total < GATE_TOKENS,
            }
        )
    return rows


def report_markdown(runs: list[Run]) -> str:
    lines = [
        "| model | languages | scripts | valid first | valid after 1 repair | tokens first | tokens with repairs | repair calls | gate |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in summarise(runs):
        lines.append(
            f"| {r['model']} | {r['languages']} | {r['scripts']} | {r['valid_first']:.0%} |"
            f" {r['valid_after_repair']:.0%} | {r['tokens_first_answer']:.0f} | {r['tokens_with_repairs']:.0f} |"
            f" {r['repair_calls']} | {'PASS' if r['meets_gate'] else 'FAIL'} |"
        )
    lines.append("")
    lines.append(
        f"Gate: at least {GATE_VALID:.0%} valid after one repair and under {GATE_TOKENS} output tokens per chapter"
        " (repairs included), per model; plus a blind win in at least 4 of 6 pairs and no fact against the lesson."
    )
    return "\n".join(lines)


def fact_check_sheet(bundles: list[dict[str, Any]], runs: list[Run], model: str) -> str:
    """For a person: the lesson's facts and, beside them, the lines the chosen model wrote."""
    out = ["# Fact check", ""]
    by_id = {b["id"]: b for b in bundles}
    for r in runs:
        if r.model != model or r.run != 0 or len(r.languages) != 1:
            continue
        sheet = by_id[r.chapter].get("fact_sheet") or {}
        out += [f"## {r.chapter}", "", "Facts:"]
        out += [f"- {x}" for x in [*sheet.get("ideas", []), *sheet.get("key_facts", [])]]
        out += ["", "Script:", "", *["    " + ln for ln in r.script], ""]
    return "\n".join(out)


# -- commands ------------------------------------------------------------------------------------


def load_chapters(folder: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    bundles = [json.loads(p.read_text("utf-8")) for p in sorted(folder.glob("chapter-*.json"))]
    path = folder / "assignments.json"
    assignments = json.loads(path.read_text("utf-8")) if path.exists() else {}
    return bundles, assignments


def build_storyboards(
    bundles, runs: list[Run], model: str, assignments
) -> list[tuple[str, str, str]]:
    """``(chapter, stored board, new board)`` from run 0 of ``model`` (one language)."""
    pairs = []
    by_id = {b["id"]: b for b in bundles}
    for r in runs:
        if r.model != model or r.run != 0 or len(r.languages) != 1:
            continue
        bundle = by_id[r.chapter]
        header = build_header(bundle, assignments.get(r.chapter, {}), list(r.languages))
        result = validate_script(r.script, header)
        stored = board.storyboard_stored(bundle["stored"], bundle["language"])
        new = board.storyboard_script(result.statements, header, bundle["language"])
        pairs.append((r.chapter, stored, new))
    return pairs


async def cmd_run(args) -> int:
    bundles, assignments = load_chapters(Path(args.chapters))
    if not bundles:
        print("no chapter-*.json in", args.chapters, file=sys.stderr)
        return 1
    rows = plan_matrix([b["id"] for b in bundles])
    est = estimate(len(rows))
    print(
        f"{est['calls']} first calls (repairs on top), about {est['input_tokens']:,} input and {est['output_tokens']:,} output tokens"
    )
    if not args.spend:
        print(
            "dry run: nothing was sent. Pass --spend with the owner's go-ahead to call the models."
        )
        return 0
    by_id = {b["id"]: b for b in bundles}
    models: dict[str, Model] = {}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    results = out / "results.json"
    # Every finished run is written at once, and a second invocation resumes: a failure at call 40
    # of 54 (overload, rate limit) must not lose, or re-buy, the 39 runs already paid for.
    runs: list[Run] = _load_runs(results) if results.exists() else []
    done = {(r.chapter, r.model, tuple(r.languages), r.run) for r in runs}
    for chapter, model, langs, index in rows:
        if (chapter, model, tuple(langs), index) in done:
            continue
        bundle = by_id[chapter]
        header = build_header(bundle, assignments.get(chapter, {}), list(langs))
        client = models.setdefault(model, AnthropicModel(model))
        runs.append(await run_one(client, bundle, header, index))
        results.write_text(
            json.dumps([asdict(r) for r in runs], ensure_ascii=False, indent=1), "utf-8"
        )
        print(
            f"{chapter} {model} {'+'.join(langs)} #{index}: first={'ok' if runs[-1].first_valid else 'bad'}"
            f" final={'ok' if runs[-1].final_valid else 'bad'} tokens={runs[-1].total_tokens}"
        )
    print(report_markdown(runs))
    return 0


def cmd_prompts(args) -> int:
    bundles, assignments = load_chapters(Path(args.chapters))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for b in bundles:
        for langs in (["fr"], ["fr", "en"]):
            header = build_header(b, assignments.get(b["id"], {}), langs)
            name = f"{b['id']}-{'+'.join(langs)}"
            (out / f"{name}.system.txt").write_text(grammar_reference(header), "utf-8")
            (out / f"{name}.user.txt").write_text(build_user_message(b, header), "utf-8")
            (out / f"{name}.header.json").write_text(
                json.dumps(header.to_dict(), ensure_ascii=False, indent=1), "utf-8"
            )
    print(f"prompts for {len(bundles)} chapter(s) in {out}; no model was called")
    return 0


def _load_runs(path: Path) -> list[Run]:
    return [Run(**r) for r in json.loads(path.read_text("utf-8"))]


def cmd_report(args) -> int:
    runs = _load_runs(Path(args.results))
    print(report_markdown(runs))
    return 0


def cmd_blind(args) -> int:
    runs = _load_runs(Path(args.results))
    bundles, assignments = load_chapters(Path(args.chapters))
    pairs = build_storyboards(bundles, runs, args.model, assignments)
    sheet, key = board.blind_pairs(pairs, args.seed)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "blind-sheet.md").write_text(sheet, "utf-8")
    (out / "blind-key.json").write_text(board.dump_key(key), "utf-8")  # keep apart from the readers
    (out / "fact-check.md").write_text(fact_check_sheet(bundles, runs, args.model), "utf-8")
    print(f"{len(pairs)} pair(s): blind-sheet.md for the readers, blind-key.json for you only")
    return 0


def cmd_tally(args) -> int:
    key = json.loads(Path(args.key).read_text("utf-8"))
    votes = json.loads(Path(args.votes).read_text("utf-8"))
    print(json.dumps(board.tally(key, votes), indent=1))
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("prompts", "run"):
        p = sub.add_parser(name)
        p.add_argument(
            "--chapters", required=True, help="folder with chapter-*.json and assignments.json"
        )
        p.add_argument("--out", required=True)
        if name == "run":
            p.add_argument(
                "--spend", action="store_true", help="really call the models (owner's go-ahead)"
            )
    sub.add_parser("report").add_argument("--results", required=True)
    p = sub.add_parser("blind")
    p.add_argument("--results", required=True)
    p.add_argument("--chapters", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--model", default=PAIR_MODEL)
    p.add_argument("--seed", type=int, default=2737)
    p = sub.add_parser("tally")
    p.add_argument("--key", required=True)
    p.add_argument("--votes", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "run":
        return asyncio.run(cmd_run(args))
    return {"prompts": cmd_prompts, "report": cmd_report, "blind": cmd_blind, "tally": cmd_tally}[
        args.command
    ](args)


if __name__ == "__main__":
    sys.exit(main())
