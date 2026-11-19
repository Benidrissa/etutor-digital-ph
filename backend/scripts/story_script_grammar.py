"""Grammar v0 of the director script: parser, validator, error format (#2737).

A SPIKE, not production code. Nothing under ``app/`` imports it; the production
parser is #2746. It exists so the paper test can parse and check what a model
writes. The document that defines the grammar is ``docs/story-director-script.md``;
the macro table below is its data.

One line is one statement::

    macro  positional...  key=value...  "text"            (one language)
    macro  positional...  key=value...  "texte" | "text"   (the pair form)

Blank lines and lines starting with ``#`` are ignored. Errors carry the line
number, a stable code and a message that can be sent back to the model; a
``warning`` never makes a script invalid.

No model call, no database, no network: pure functions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

LANGS = ("fr", "en")

#: Roles only. First names are put in at display time; the hero stays the learner.
ROLES = ("hero", "friend", "family", "mentor", "tutor")
#: ``app/api/v1/schemas/story_course.py`` MOODS, minus the two that are not poses of a line.
MOODS = ("talk", "happy", "think", "surprised", "sad")
#: Named positions on a backdrop (a mark of the library; the player's own slots apply otherwise).
MARKS = ("left", "centre", "right", "off")
REVEALS = ("groups", "columns", "steps", "all")

#: Limits of v0, in characters, applied to each language of a pair.
DIALOGUE_LIMIT = 60
NARRATE_LIMIT = 90
QUESTION_LIMIT = 90
TEASER_LIMIT = 90
#: "About 70 lines": more than ``MAX_LINES`` statements is an error, more than ``TARGET_LINES`` a warning.
TARGET_LINES = 70
MAX_LINES = 80
#: "About 40 of them dialogue lines": outside this range is a warning.
DIALOGUE_RANGE = (25, 50)
#: Exact check 3 of the epic: at most this many lines in a row without a visible change.
MAX_SILENT_RUN = 3

# -- the macro table -----------------------------------------------------------

#: What an argument is. Every kind is checked by ``_check_value``.
KINDS = (
    "role", "rolelist", "place", "object", "machine", "qref", "quiz", "card",
    "mood", "mark", "reveal", "target", "number",
)  # fmt: skip


@dataclass(frozen=True)
class Arg:
    name: str
    kind: str
    required: bool = True


@dataclass(frozen=True)
class Macro:
    name: str
    positional: tuple[Arg, ...] = ()
    named: tuple[Arg, ...] = ()
    #: ``"none"`` (no text) or ``"one"`` (one text, in the pair form a pair).
    text: str = "none"
    limit: int = 0
    #: A variadic last positional (``ask Q1 Q2``): one or more of the last kind.
    variadic: bool = False
    #: Only in open-loop mode; v0 parses them and refuses them in linear mode.
    loop_only: bool = False
    #: A line that makes the picture change on screen (exact check 3).
    visible: bool = False
    #: Counts as a dialogue line.
    dialogue: bool = False


_MACHINE_DATA = ("n", "a", "b", "from", "to", "mark")

MACROS: dict[str, Macro] = {
    m.name: m
    for m in (
        Macro("scene", (Arg("place", "place"),), (Arg("cast", "rolelist"),), visible=True),
        Macro(
            "say",
            (Arg("who", "role"),),
            (Arg("mood", "mood", False),),
            text="one",
            limit=DIALOGUE_LIMIT,
            dialogue=True,
        ),
        Macro("narrate", text="one", limit=NARRATE_LIMIT),
        Macro(
            "mistake",
            (Arg("who", "role"),),
            (Arg("mood", "mood", False),),
            text="one",
            limit=DIALOGUE_LIMIT,
            dialogue=True,
        ),
        Macro("show", (Arg("object", "object"),), (Arg("at", "mark", False),), visible=True),
        Macro(
            "machine",
            (Arg("machine", "machine"),),
            tuple(Arg(k, "number", False) for k in _MACHINE_DATA)
            + (Arg("reveal", "reveal", False),),
            visible=True,
        ),
        Macro("point", (Arg("who", "role"),), (Arg("target", "target"),), visible=True),
        Macro("card", (Arg("card", "card"),), visible=True),
        Macro("bet", (Arg("question", "qref"),), visible=True),
        Macro("ask", (Arg("questions", "quiz"),), variadic=True, visible=True),
        Macro("game", visible=True),
        Macro("reward"),
        Macro("open", (Arg("question", "qref"),), text="one", limit=QUESTION_LIMIT, dialogue=True),
        Macro("close", (Arg("question", "qref"),)),
        Macro("recap", (Arg("question", "qref"),), loop_only=True),
        Macro("cliff", (Arg("question", "qref"),), loop_only=True),
        Macro("teaser", text="one", limit=TEASER_LIMIT),
    )
}

# -- the Hero's Journey table (#2749), as far as the grammar needs it -------------

STAGE_NAMES = {
    1: "ordinary world", 2: "call", 3: "refusal", 4: "mentor", 5: "threshold",
    6: "tests, allies, enemies", 7: "approach", 8: "ordeal", 9: "reward",
    10: "road back", 11: "resurrection", 12: "elixir",
}  # fmt: skip
#: Blocks a stage requires (#2749). ``ask`` is also required whenever the header lists quiz questions.
STAGE_BLOCKS: dict[int, tuple[str, ...]] = {
    3: ("bet", "mistake"),
    5: ("machine",),
    6: ("ask",),
    8: ("bet", "mistake"),
    9: ("card",),
    11: ("ask",),
    12: ("teaser",),
}


def distribute_stages(index: int, count: int, *, mentor: bool = True) -> list[int]:
    """Stages of chapter ``index`` (1-based) of ``count`` chapters, the rally counted (#2749).

    1 chapter plays all twelve; 2: Start, then the rest; 3: Start, Trials with
    Summit, Return; 4: one moment each; beyond 4 the extra chapters are Trials.
    Stage 4 is left out without a mentor.
    """
    start, trials, summit, back = [1, 2, 3, 4, 5], [6], [7, 8, 9], [10, 11, 12]
    if count <= 1:
        stages = start + trials + summit + back
    elif count == 2:
        stages = start if index == 1 else trials + summit + back
    elif count == 3:
        stages = [start, trials + summit, back][index - 1]
    else:
        if index == 1:
            stages = start
        elif index == count:
            stages = back
        elif index == count - 1:
            stages = summit
        else:
            stages = trials
    return [s for s in stages if mentor or s != 4]


def required_blocks(stages: list[int]) -> list[str]:
    seen: list[str] = []
    for stage in stages:
        for block in STAGE_BLOCKS.get(stage, ()):
            if block not in seen:
                seen.append(block)
    return seen


# -- the header that code imposes ------------------------------------------------


@dataclass
class Header:
    """What code decides for a chapter; the script may not deviate from it."""

    chapter: str = ""
    #: Languages of the script's text, in the order of a pair (``"fr" | "en"``). One entry: one text.
    languages: list[str] = field(default_factory=lambda: ["fr"])
    mode: str = "linear"
    stages: list[int] = field(default_factory=list)
    #: Questions the script raises (``L1``...) with a hint on their wording, and those it answers.
    opens: dict[str, str] = field(default_factory=dict)
    closes: list[str] = field(default_factory=list)
    #: Quiz questions to place (``Q1``...), each once; the value is the question's stem, for the model.
    quiz: dict[str, str] = field(default_factory=dict)
    #: Cards to place: id -> the card's title.
    cards: dict[str, str] = field(default_factory=dict)
    cast: list[str] = field(default_factory=lambda: ["hero", "friend"])
    places: list[str] = field(default_factory=list)
    objects: dict[str, str] = field(default_factory=dict)
    machines: list[str] = field(default_factory=list)
    #: Numbers the lesson's facts and quiz contain (digits only); a machine's numbers should be among them.
    numbers: list[str] = field(default_factory=list)
    #: ``bet`` choices: question -> {"right", "wrong"}; the third choice is always "I don't know".
    bets: dict[str, dict[str, str]] = field(default_factory=dict)

    @property
    def pair(self) -> bool:
        return len(self.languages) > 1

    @property
    def required(self) -> list[str]:
        blocks = required_blocks(self.stages)
        if self.quiz and "ask" not in blocks:
            blocks.append("ask")
        return blocks

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Header:
        known = {f for f in cls.__dataclass_fields__}  # noqa: C416
        return cls(**{k: v for k, v in raw.items() if k in known})

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


# -- errors ----------------------------------------------------------------------


@dataclass(frozen=True)
class ScriptError:
    """``line`` is 1-based; 0 means the script as a whole (something is missing)."""

    line: int
    code: str
    message: str
    warning: bool = False


def format_errors(errors: list[ScriptError], lines: list[str] | None = None) -> str:
    """The error format sent back to the model: line number, code, message, the line itself."""
    out = []
    for error in errors:
        kind = "warning" if error.warning else "error"
        where = f"line {error.line}" if error.line else "script"
        out.append(f"{where} [{error.code}] {kind}: {error.message}")
        if lines and 1 <= error.line <= len(lines):
            out.append(f"  > {lines[error.line - 1]}")
    return "\n".join(out)


# -- parsing ---------------------------------------------------------------------

_TOKEN = re.compile(r'\s*(?:("(?:[^"\\]|\\.)*")|(\|)|([^\s"|]+))')
_TARGET = re.compile(r"^(machine\.[a-z][a-z0-9_]*|[a-z][a-z0-9_]*)$")
_NUMBER = re.compile(r"^-?\d+(?:[.,]\d+)?(?:[;/]-?\d+(?:[.,]\d+)?)*$")
_QREF = re.compile(r"^L\d+$")
_QUIZ = re.compile(r"^Q\d+$")
_IDENT = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass
class Statement:
    line: int
    macro: str
    args: list[str] = field(default_factory=list)
    named: dict[str, str] = field(default_factory=dict)
    texts: list[str] = field(default_factory=list)
    raw: str = ""


def _unquote(token: str) -> str:
    return token[1:-1].replace('\\"', '"').replace("\\\\", "\\")


def parse_line(number: int, raw: str) -> tuple[Statement | None, list[ScriptError]]:
    """One line to one statement, or the syntax errors that stop it."""
    text = raw.strip()
    tokens: list[tuple[str, str]] = []
    pos = 0
    while pos < len(text):
        match = _TOKEN.match(text, pos)
        if match is None or match.end() == pos:
            reason = "an unclosed quote" if '"' in text[pos:] else "a character that is not allowed"
            return None, [ScriptError(number, "bad_syntax", f"cannot read the line: {reason}")]
        if match.group(1) is not None:
            tokens.append(("text", _unquote(match.group(1))))
        elif match.group(2) is not None:
            tokens.append(("bar", "|"))
        else:
            tokens.append(("word", match.group(3)))
        pos = match.end()
    if not tokens or tokens[0][0] != "word":
        return None, [ScriptError(number, "bad_syntax", "a line starts with a macro name")]
    stmt = Statement(number, tokens[0][1].lower(), raw=raw.rstrip())
    errors: list[ScriptError] = []
    previous = "word"
    for kind, value in tokens[1:]:
        if kind == "word":
            if "=" in value:
                key, _, val = value.partition("=")
                if not key or not val:
                    errors.append(ScriptError(number, "bad_syntax", f"'{value}': write key=value"))
                elif key in stmt.named:
                    errors.append(ScriptError(number, "duplicate_arg", f"'{key}' is given twice"))
                else:
                    stmt.named[key] = val
            else:
                stmt.args.append(value)
        elif kind == "text":
            if previous == "text":
                errors.append(
                    ScriptError(number, "bad_syntax", 'two texts need a "|" between them')
                )
            stmt.texts.append(value)
        elif previous != "text":
            errors.append(ScriptError(number, "bad_syntax", 'a "|" goes after a text'))
        previous = kind
    if previous == "bar":
        errors.append(ScriptError(number, "bad_syntax", 'a "|" must be followed by a text'))
    return stmt, errors


def extract_lines(answer: str) -> list[str]:
    """The script's lines out of a model answer: code fences dropped, nothing else touched."""
    lines = [ln.rstrip() for ln in (answer or "").splitlines()]
    return [ln for ln in lines if not ln.strip().startswith("```")]


def parse_script(lines: list[str]) -> tuple[list[Statement], list[ScriptError]]:
    statements: list[Statement] = []
    errors: list[ScriptError] = []
    for number, raw in enumerate(lines, start=1):
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        stmt, found = parse_line(number, raw)
        errors.extend(found)
        if stmt is not None and not found:
            statements.append(stmt)
    return statements, errors


# -- validation of one statement ---------------------------------------------------


def _check_value(kind: str, value: str, header: Header) -> str | None:
    """None when ``value`` fits ``kind``, else the reason (and a code prefix ``code|text``)."""
    if kind == "role":
        if value not in ROLES:
            return f"unknown_role|'{value}' is not a role; use {', '.join(ROLES)}"
        if value not in header.cast:
            return f"role_not_in_cast|'{value}' is not in this chapter's cast ({', '.join(header.cast)})"
    elif kind == "rolelist":
        roles = value.split(",")
        for role in roles:
            if role not in ROLES:
                return f"unknown_role|'{role}' is not a role; use {', '.join(ROLES)}"
            if role not in header.cast:
                return f"role_not_in_cast|'{role}' is not in this chapter's cast ({', '.join(header.cast)})"
        if not 2 <= len(set(roles)) <= 3 or len(set(roles)) != len(roles):
            return "cast_size|a scene has 2 or 3 different roles on stage"
    elif kind == "place":
        if value not in header.places:
            return (
                f"unknown_place|'{value}' is not a place of the menu ({', '.join(header.places)})"
            )
    elif kind == "object":
        if value not in header.objects:
            return f"unknown_object|'{value}' is not an object of the menu ({', '.join(header.objects)})"
    elif kind == "machine":
        if value not in header.machines:
            return f"unknown_machine|'{value}' is not a machine of the menu ({', '.join(header.machines)})"
    elif kind == "qref":
        if not _QREF.match(value):
            return f"bad_value|'{value}' is not a question id like L1"
    elif kind == "quiz":
        if not _QUIZ.match(value):
            return f"bad_value|'{value}' is not a quiz question id like Q1"
        if value not in header.quiz:
            return f"unknown_question|'{value}' is not a quiz question of this chapter ({', '.join(header.quiz)})"
    elif kind == "card":
        if value not in header.cards:
            return (
                f"unknown_card|'{value}' is not a card of this chapter ({', '.join(header.cards)})"
            )
    elif kind == "mood":
        if value not in MOODS:
            return f"bad_value|mood '{value}' is not one of {', '.join(MOODS)}"
    elif kind == "mark":
        if value not in MARKS:
            return f"bad_value|mark '{value}' is not one of {', '.join(MARKS)}"
    elif kind == "reveal":
        if value not in REVEALS:
            return f"bad_value|reveal '{value}' is not one of {', '.join(REVEALS)}"
    elif kind == "target":
        if not _TARGET.match(value):
            return f"bad_value|target '{value}' is machine.<part> or an object id"
    elif kind == "number":
        if not _NUMBER.match(value):
            return f"bad_value|'{value}' is not a number (digits, or a;b;c for a list)"
    return None


def _split(reason: str) -> tuple[str, str]:
    code, _, message = reason.partition("|")
    return code, message


def check_statement(stmt: Statement, header: Header) -> list[ScriptError]:
    """Everything that can be checked on one line alone, against the header's menu."""
    macro = MACROS.get(stmt.macro)
    if macro is None:
        return [
            ScriptError(
                stmt.line,
                "unknown_macro",
                f"'{stmt.macro}' is not a macro; the macros are {', '.join(MACROS)}",
            )
        ]
    errors: list[ScriptError] = []

    def add(code: str, message: str) -> None:
        errors.append(ScriptError(stmt.line, code, f"{stmt.macro}: {message}"))

    expected = len(macro.positional)
    if len(stmt.args) < expected or (not macro.variadic and len(stmt.args) > expected):
        names = " ".join(a.name for a in macro.positional) or "nothing"
        add("bad_arity", f"takes {names}, got {len(stmt.args)} argument(s)")
    for arg, value in zip(macro.positional, stmt.args, strict=False):
        values = (
            stmt.args[len(macro.positional) - 1 :]
            if macro.variadic and arg is macro.positional[-1]
            else [value]
        )
        for item in values:
            reason = _check_value(arg.kind, item, header)
            if reason:
                add(*_split(reason))
    allowed = {a.name: a for a in macro.named}
    for key, value in stmt.named.items():
        arg = allowed.get(key)
        if arg is None:
            add(
                "unknown_arg",
                f"'{key}' is not an argument; it takes {', '.join(allowed) or 'none'}",
            )
            continue
        reason = _check_value(arg.kind, value, header)
        if reason:
            add(*_split(reason))
    for arg in macro.named:
        if arg.required and arg.name not in stmt.named:
            add("missing_arg", f"needs {arg.name}=...")
    if stmt.macro == "machine" and not any(k in stmt.named for k in _MACHINE_DATA):
        add("missing_arg", f"needs its data: one of {', '.join(k + '=' for k in _MACHINE_DATA)}")
    # text
    want = (len(header.languages) if header.pair else 1) if macro.text == "one" else 0
    if len(stmt.texts) != want:
        if want == 0:
            add("text_unexpected", "takes no text")
        elif want == 1:
            add("text_count", "takes one text in quotes")
        else:
            add("text_count", 'takes two texts: "' + '" | "'.join(header.languages) + '"')
    else:
        for lang, text in zip(header.languages, stmt.texts, strict=False):
            if not text.strip():
                add("text_empty", f"the {lang} text is empty")
            elif len(text) > macro.limit:
                add(
                    "too_long",
                    f"the {lang} text has {len(text)} characters, the limit is {macro.limit}",
                )
    return errors


# -- validation of the script ------------------------------------------------------

_DEIXIS = re.compile(
    r"\b(ce|cet|cette|ces|ceci|cela|voici|voilà|regarde[zr]?|this|these|look|here)\b", re.I
)


@dataclass
class ValidationResult:
    statements: list[Statement]
    errors: list[ScriptError]
    warnings: list[ScriptError]
    stats: dict[str, Any]

    @property
    def valid(self) -> bool:
        return not self.errors

    @property
    def faulty_lines(self) -> list[int]:
        return sorted({e.line for e in self.errors if e.line})

    @property
    def script_errors(self) -> list[ScriptError]:
        """Errors about the script as a whole (something missing): line 0."""
        return [e for e in self.errors if not e.line]


def validate_script(lines: list[str], header: Header) -> ValidationResult:
    """Parse and check a whole script against its header."""
    statements, errors = parse_script(lines)
    warnings: list[ScriptError] = []
    for stmt in statements:
        errors.extend(check_statement(stmt, header))
    errors.extend(_check_flow(statements, header, warnings))
    errors.sort(key=lambda e: (e.line == 0, e.line))
    stats = {
        "statements": len(statements),
        "dialogue": sum(1 for s in statements if MACROS.get(s.macro, Macro("")).dialogue),
        "macros": sorted({s.macro for s in statements}),
    }
    return ValidationResult(statements, errors, warnings, stats)


def _check_flow(
    statements: list[Statement], header: Header, warnings: list[ScriptError]
) -> list[ScriptError]:
    errors: list[ScriptError] = []
    known = [s for s in statements if s.macro in MACROS]
    if not known:
        return [ScriptError(0, "empty", "the script has no statement")]

    def err(stmt: Statement, code: str, message: str) -> None:
        errors.append(ScriptError(stmt.line, code, f"{stmt.macro}: {message}"))

    def warn(stmt: Statement | None, code: str, message: str) -> None:
        warnings.append(ScriptError(stmt.line if stmt else 0, code, message, warning=True))

    if len(known) > MAX_LINES:
        errors.append(
            ScriptError(
                known[MAX_LINES].line,
                "too_many_lines",
                f"the script has {len(known)} statements, the limit is {MAX_LINES}: delete this line",
            )
        )
    elif len(known) > TARGET_LINES:
        warn(None, "lines_over_target", f"{len(known)} statements; aim at about {TARGET_LINES}")
    dialogue = sum(1 for s in known if MACROS[s.macro].dialogue)
    if not DIALOGUE_RANGE[0] <= dialogue <= DIALOGUE_RANGE[1]:
        warn(None, "dialogue_count", f"{dialogue} dialogue lines; aim at about 40")

    if known[0].macro != "scene":
        err(known[0], "scene_first", "the script starts with a scene")

    cast: list[str] = []
    opened: set[str] = set()
    closed: set[str] = set()
    bet: set[str] = set()
    asked: set[str] = set()
    cards: set[str] = set()
    machines: list[str] = []
    shown: set[str] = set()
    picture_since_scene = False
    first_at: dict[str, int] = {}
    silent = 0
    for index, stmt in enumerate(known):
        macro = MACROS[stmt.macro]
        first_at.setdefault(stmt.macro, index)
        name = stmt.macro
        a0 = stmt.args[0] if stmt.args else ""
        if macro.loop_only and header.mode == "linear":
            err(stmt, "mode_refused", "is not allowed in linear mode")
        if name == "scene":
            cast = stmt.named.get("cast", "").split(",") if stmt.named.get("cast") else []
            picture_since_scene = False
        elif name in ("say", "mistake", "point") and a0 in ROLES and cast and a0 not in cast:
            err(
                stmt,
                "speaker_off_stage",
                f"'{a0}' is not on stage in this scene ({', '.join(cast)})",
            )
        if name == "mistake" and a0 == "hero":
            err(
                stmt,
                "mistake_by_hero",
                "the misconception is said by a character, never by the hero",
            )
        if name == "open":
            if a0 not in header.opens:
                err(
                    stmt,
                    "unknown_question",
                    f"'{a0}' is not a question to open ({', '.join(header.opens) or 'none'})",
                )
            elif a0 in opened:
                err(stmt, "open_twice", f"'{a0}' is opened twice")
            opened.add(a0)
        elif name == "close":
            if a0 not in opened:
                err(stmt, "close_before_open", f"'{a0}' is closed before it is opened")
            elif a0 not in header.closes:
                err(stmt, "unknown_question", f"'{a0}' is not a question to close here")
            elif a0 in closed:
                err(stmt, "close_twice", f"'{a0}' is closed twice")
            closed.add(a0)
        elif name == "bet":
            if a0 not in opened:
                err(stmt, "bet_without_open", f"'{a0}' must be opened before it is bet on")
            elif a0 in bet:
                err(stmt, "bet_twice", f"'{a0}' is bet on twice")
            bet.add(a0)
        elif name in ("cliff", "recap") and header.mode != "linear":
            if a0 not in opened or a0 in closed:
                err(stmt, "loop_state", f"'{a0}' must be open to use {name}")
        elif name == "ask":
            for ref in stmt.args:
                if ref in asked:
                    err(stmt, "question_twice", f"{ref} is asked twice")
                asked.add(ref)
        elif name == "card":
            if a0 in cards:
                err(stmt, "card_twice", f"card '{a0}' is placed twice")
            cards.add(a0)
            if not picture_since_scene and not machines and not shown:
                warn(
                    stmt, "card_before_picture", "a card should come after the picture of its idea"
                )
        elif name == "show" and a0 in header.objects:
            shown.add(a0)
            picture_since_scene = True
        elif name == "machine" and a0 in header.machines:
            machines.append(a0)
            picture_since_scene = True
            for key in _MACHINE_DATA:
                digits = re.sub(r"\D", "", stmt.named.get(key, "")) if key in stmt.named else ""
                if digits and header.numbers and digits not in header.numbers:
                    warn(
                        stmt,
                        "number_not_in_facts",
                        f"{key}={stmt.named[key]} is in no fact or question",
                    )
        elif name == "point":
            target = stmt.named.get("target", "")
            if target.startswith("machine."):
                if not machines:
                    err(stmt, "target_unknown", f"'{target}': no machine is on the board yet")
            elif target and target not in header.objects and target not in shown:
                err(stmt, "target_unknown", f"'{target}' is not an object of the menu")
        elif name == "teaser":
            if any(t.rstrip().endswith("?") for t in stmt.texts):
                err(
                    stmt,
                    "teaser_is_question",
                    "a teaser states the next topic; it is not a question",
                )
            if stmt is not known[-1]:
                err(stmt, "teaser_not_last", "the teaser is the last statement")
        if name == "say" and any(_DEIXIS.search(t) for t in stmt.texts):
            recent = known[max(0, index - 2) : index]
            if not any(r.macro in ("point", "show", "machine") for r in recent):
                warn(
                    stmt,
                    "deictic_without_target",
                    "the line points at something ('this', 'look') with nothing pointed at",
                )
        if macro.visible:
            silent = 0
        else:
            silent += 1
            if silent == MAX_SILENT_RUN + 1:
                warn(
                    stmt, "silent_run", f"more than {MAX_SILENT_RUN} lines without a visible change"
                )

    for ref in header.opens:
        if ref not in opened:
            errors.append(
                ScriptError(0, "open_missing", f'question {ref} is never opened (open {ref} "...")')
            )
    for ref in header.closes:
        if ref not in closed:
            errors.append(
                ScriptError(0, "close_missing", f"question {ref} is never closed (close {ref})")
            )
    for ref in header.quiz:
        if ref not in asked:
            errors.append(
                ScriptError(
                    0, "question_missing", f"quiz question {ref} is never asked (ask {ref})"
                )
            )
    for card in header.cards:
        if card not in cards:
            errors.append(
                ScriptError(0, "card_missing", f"card '{card}' is never placed (card {card})")
            )
    for block in header.required:
        if block not in first_at:
            errors.append(
                ScriptError(0, "block_missing", f"this chapter's stage needs a '{block}' line")
            )
    if {"bet", "machine", "card"} <= set(first_at) and not (
        first_at["bet"] < first_at["machine"] < first_at["card"]
    ):
        warn(None, "order_bet_machine_card", "the order should be bet, then machine, then card")
    return errors


# -- repair ------------------------------------------------------------------------


def apply_repair(lines: list[str], line: int, answer: str) -> list[str]:
    """Replace line ``line`` (1-based) by the model's one-line answer; ``DELETE`` drops it."""
    fixed = [ln for ln in extract_lines(answer) if ln.strip()]
    out = list(lines)
    if not 1 <= line <= len(out):
        return out
    if not fixed or fixed[0].strip().upper() == "DELETE":
        del out[line - 1]
    else:
        out[line - 1 : line] = fixed[:1]
    return out


def insert_missing(lines: list[str], answer: str) -> list[str]:
    """Add the lines a model wrote for what is missing, before a final ``teaser`` if there is one."""
    extra = [ln for ln in extract_lines(answer) if ln.strip() and not ln.strip().startswith("#")]
    out = [ln for ln in lines]
    at = len(out)
    while at > 0 and not out[at - 1].strip():
        at -= 1
    if at and out[at - 1].strip().startswith("teaser"):
        at -= 1
    out[at:at] = extra
    return out
