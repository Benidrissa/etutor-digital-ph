#!/usr/bin/env python3
"""Put English back in the ``en`` fields of stored module stories that carry French (#2710).

A question told from a French quiz row used to copy that row's French into the
``en`` side of its texts (« Que signifie faire une 'inférence'... » as the
English stem). The learner of the English story then read French.

For each stored module story, every text object of a question (``prompt``,
``stem``, ``original_stem``, ``explanation``, each ``choices``, ``hints`` and
``traps[].hint``) whose ``en`` looks French is given the English text of:

1. **the quiz row it was derived from** (``derived_from`` is the quiz unit and
   the question id): the English quiz question, its options and its
   explanation, when that row exists in English; else
2. **the English-language story of the same module**: the question with the
   same ``derived_from`` (or the same id) whose ``en`` is not French.

Nothing is translated and no model is called. A text with no English source is
left as it is and **listed**. Only the module story rows are written, never a
chapter row (a chapter row's ``updated_at`` is what the story's freshness
compares: touching one would make the story stale and regenerate it with paid
calls).

Dry-run by default: it prints what it would change and writes nothing. With
``--apply`` it updates the module story rows' ``content`` (one commit). It is
idempotent: a second run finds nothing to fix. Usage (inside the backend
container)::

    python scripts/repair_story_language.py            # report only
    python scripts/repair_story_language.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import re
import sys
import uuid
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.domain.services.story_metrics import french_in  # noqa: E402

_PREFIX_RE = re.compile(r"^\s*([a-h])\)\s*", re.IGNORECASE)
_WORD_RE = re.compile(r"[\w']+", re.UNICODE)
#: A text shorter than this is not judged (a name, a number).
_MIN_WORDS = 3

Path_ = tuple[Any, ...]


def _strip_prefix(text: str) -> str:
    return _PREFIX_RE.sub("", text, count=1).strip()


def looks_french(en: Any, fr: Any = None) -> bool:
    """Whether an ``en`` text is French: French stopwords, or the very text of the ``fr`` side."""
    if not isinstance(en, str):
        return False
    body = _strip_prefix(en)
    if french_in(body):
        return True
    other = _strip_prefix(fr) if isinstance(fr, str) else ""
    words = _WORD_RE.findall(body)
    return len(words) >= _MIN_WORDS and body.casefold() == other.casefold() and bool(other)


def _text_paths(question: Mapping[str, Any]) -> Iterator[Path_]:
    """The path of every ``{"en", "fr"}`` text object of a question."""
    for key in ("prompt", "stem", "original_stem", "explanation"):
        if isinstance(question.get(key), dict):
            yield (key,)
    for index, choice in enumerate(question.get("choices") or []):
        if isinstance(choice, dict):
            yield ("choices", index)
    for index, hint in enumerate(question.get("hints") or []):
        if isinstance(hint, dict):
            yield ("hints", index)
    for index, trap in enumerate(question.get("traps") or []):
        if isinstance(trap, dict) and isinstance(trap.get("hint"), dict):
            yield ("traps", index, "hint")


def _at(question: Any, path: Path_) -> Any:
    node = question
    for step in path:
        try:
            node = node[step]
        except (KeyError, IndexError, TypeError):
            return None
    return node if isinstance(node, dict) else None


def french_paths(question: Mapping[str, Any]) -> list[Path_]:
    """The text objects of ``question`` whose ``en`` is French."""
    out = []
    for path in _text_paths(question):
        node = _at(question, path)
        if node is not None and looks_french(node.get("en"), node.get("fr")):
            out.append(path)
    return out


def _label(path: Path_) -> str:
    return ".".join(str(p) for p in path)


@dataclass
class Sources:
    """Where English can come from.

    ``quiz``: ``(quiz unit number, question id)`` → the English quiz question as
    stored (``question``, ``options``, ``correct_answer``, ``explanation``).
    ``english``: the questions of the English story of the module (or any story
    with English), as story-document questions.
    """

    quiz: dict[tuple[str, str], Mapping[str, Any]] = field(default_factory=dict)
    english: list[Mapping[str, Any]] = field(default_factory=list)


def _derived_key(question: Mapping[str, Any]) -> tuple[str, str] | None:
    derived = question.get("derived_from")
    if isinstance(derived, dict) and derived.get("quiz_unit") and derived.get("question_id"):
        return str(derived["quiz_unit"]), str(derived["question_id"])
    return None


def _english_twin(question: Mapping[str, Any], sources: Sources) -> Mapping[str, Any] | None:
    """The same question in an English story: same quiz question, else same id."""
    key = _derived_key(question)
    for other in sources.english:
        if other is question:
            continue
        if key is not None and _derived_key(other) == key:
            return other
    for other in sources.english:
        if other is not question and other.get("id") == question.get("id"):
            return other
    return None


def _from_quiz(question: Mapping[str, Any], path: Path_, quiz: Mapping[str, Any]) -> str | None:
    """The English text the quiz row has for the text object at ``path``."""
    options = quiz.get("options")
    if path == ("explanation",):
        return str(quiz.get("explanation") or "") or None
    if path == ("original_stem",) or (path == ("prompt",) and "original_stem" not in question):
        return str(quiz.get("question") or "") or None
    if path[0] == "choices" and isinstance(options, list):
        choices = question.get("choices") or []
        index = path[1]
        answer = quiz.get("correct_answer")
        correct_id = (
            next((c.get("id") for c in choices if c.get("id") == chr(97 + answer)), None)
            if (isinstance(answer, int) and not isinstance(answer, bool))
            else None
        )
        # The options must be in the story's order: the right one is where it was.
        if (
            index < len(options)
            and len(options) == len(choices)
            and correct_id is not None
            and question.get("answer") == correct_id
        ):
            current = choices[index].get("en")
            prefix = _PREFIX_RE.match(current) if isinstance(current, str) else None
            label = f"{prefix.group(1)}) " if prefix else ""
            return f"{label}{options[index]}"
    return None


def _from_twin(question: Mapping[str, Any], path: Path_, twin: Mapping[str, Any]) -> str | None:
    """The twin's English text at the same place (choices and traps by their ids)."""
    if path[0] == "choices":
        mine = (question.get("choices") or [])[path[1]]
        node = next((c for c in twin.get("choices") or [] if c.get("id") == mine.get("id")), None)
    elif path[0] == "traps":
        mine = (question.get("traps") or [])[path[1]]
        other = next(
            (t for t in twin.get("traps") or [] if t.get("answer") == mine.get("answer")), None
        )
        node = other.get("hint") if isinstance(other, dict) else None
    else:
        node = _at(twin, path)
    text = node.get("en") if isinstance(node, dict) else None
    if isinstance(text, str) and text.strip() and not looks_french(text, node.get("fr")):
        return text
    return None


@dataclass
class Report:
    fixed: list[tuple[str, str, str]] = field(default_factory=list)  # (question, path, source)
    unfixed: list[tuple[str, str]] = field(default_factory=list)  # (question, path)

    def extend(self, other: Report) -> None:
        self.fixed += other.fixed
        self.unfixed += other.unfixed


def repair_question(question: dict[str, Any], sources: Sources) -> Report:
    """Fix the French ``en`` texts of one question in place; report what was done."""
    report = Report()
    qid = str(question.get("id"))
    quiz_key = _derived_key(question)
    quiz = sources.quiz.get(quiz_key) if quiz_key else None
    twin = _english_twin(question, sources)
    for path in french_paths(question):
        node = _at(question, path)
        found: tuple[str, str] | None = None
        if quiz is not None:
            text = _from_quiz(question, path, quiz)
            if text and not looks_french(text, node.get("fr")):
                found = (text, "quiz row")
        if found is None and twin is not None:
            text = _from_twin(question, path, twin)
            if text:
                found = (text, f"English story ({twin.get('id')})")
        if found is None:
            report.unfixed.append((qid, _label(path)))
            continue
        node["en"] = found[0]
        report.fixed.append((qid, _label(path), found[1]))
    return report


def repair_document(doc: dict[str, Any], sources: Sources) -> tuple[dict[str, Any], Report]:
    """A copy of the story document with its French ``en`` texts repaired, and the report."""
    out = copy.deepcopy(doc)
    report = Report()
    for question in out.get("questions") or []:
        if isinstance(question, dict):
            report.extend(repair_question(question, sources))
    return out, report


def format_report(slug: str, report: Report) -> str:
    lines = [f"{slug}: {len(report.fixed)} to fix, {len(report.unfixed)} cannot be fixed"]
    lines += [f"  fix    {q} {p}  <- {src}" for q, p, src in report.fixed]
    lines += [f"  CANNOT {q} {p}  (no English source)" for q, p in report.unfixed]
    return "\n".join(lines)


# -- The database (not covered by the unit tests: SELECTs, and one write with --apply) ------------


async def _quiz_sources(session, module_id: uuid.UUID, wanted: set[str]) -> dict:
    """``(quiz unit number, question id)`` → English quiz question, for the units in ``wanted``."""
    from sqlalchemy import select

    from app.domain.models.content import GeneratedContent
    from app.domain.models.module_unit import ModuleUnit

    out: dict[tuple[str, str], Mapping[str, Any]] = {}
    units = (
        await session.execute(
            select(ModuleUnit.id, ModuleUnit.unit_number).where(
                ModuleUnit.module_id == module_id, ModuleUnit.unit_number.in_(wanted)
            )
        )
    ).all()
    for unit_id, number in units:
        row = (
            (
                await session.execute(
                    select(GeneratedContent)
                    .where(
                        GeneratedContent.module_unit_id == unit_id,
                        GeneratedContent.content_type == "quiz",
                        GeneratedContent.language == "en",
                    )
                    .order_by(GeneratedContent.generated_at.desc())
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )
        questions = (row.content or {}).get("questions") if row is not None else None
        for index, raw in enumerate(questions if isinstance(questions, list) else [], start=1):
            if isinstance(raw, dict):
                out[(str(number), str(raw.get("id") or f"#{index}"))] = raw
    return out


async def run(session, *, apply: bool) -> tuple[str, int]:
    """Every module story of the database; returns the printed report and the number fixed."""
    from sqlalchemy import select

    from app.domain.models.story_course import StoryCourseRecord

    rows = (
        (
            await session.execute(
                select(StoryCourseRecord).where(
                    StoryCourseRecord.module_id.is_not(None),
                    StoryCourseRecord.module_unit_id.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    english_by_module: dict[uuid.UUID, list[Mapping[str, Any]]] = {}
    for row in rows:
        if row.language == "en":
            english_by_module.setdefault(row.module_id, []).extend(
                (row.content or {}).get("questions") or []
            )
    out: list[str] = []
    total = 0
    for row in rows:
        content = row.content or {}
        flagged = [q for q in content.get("questions") or [] if french_paths(q)]
        if not flagged:
            continue
        wanted = {k[0] for q in flagged if (k := _derived_key(q))}
        sources = Sources(
            quiz=await _quiz_sources(session, row.module_id, wanted) if wanted else {},
            english=english_by_module.get(row.module_id, []) if row.language != "en" else [],
        )
        # An English story with French in it can still be mended from its own other questions.
        if row.language == "en":
            sources.english = [q for q in content.get("questions") or [] if q not in flagged]
        fixed, report = repair_document(content, sources)
        out.append(format_report(row.slug, report))
        total += len(report.fixed)
        if apply and report.fixed:
            row.content = fixed
    if apply and total:
        await session.commit()
    out.append(f"\n{total} text(s) {'fixed' if apply else 'to fix (dry run: nothing written)'}")
    return "\n".join(out), total


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--apply", action="store_true", help="write the fixes (default: dry run)")
    return parser.parse_args(argv)


async def main(argv: list[str] | None = None, session_factory=None) -> int:
    args = parse_args(argv)
    if session_factory is None:
        from app.infrastructure.persistence.database import async_session_factory

        session_factory = async_session_factory
    async with session_factory() as session:
        text, _total = await run(session, apply=args.apply)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
