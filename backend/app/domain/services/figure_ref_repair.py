"""Repoint lesson figure references whose ``source_images`` row was deleted (#2707).

A generated lesson stores the figures it shows twice: as a list in
``content["source_image_refs"]`` and as inline ``{{source_image:<uuid>}}``
markers in its text. Both name a ``source_images`` row by id.

Re-indexing a course deletes its ``source_images`` rows and creates them again
under new ids (``RAGPipeline.clear_source_images`` for an image re-index,
``clear_resource_images`` before a donor clone). Lessons generated before the
re-index then point at rows that no longer exist: the figure answers 404 in
the lesson, and the story generator drops it (``live_figures``), so a chapter
about a figure is told without it.

This module finds, for each dangling id, the row that replaced it **in the
same course** and rewrites the lesson to name it:

1. by picture: the deleted row's ``image_hash``, when the caller took a
   snapshot of the rows before deleting them (:func:`snapshot_figures`);
2. by caption and figure number, which a ref carries with it;
3. by figure number alone, only when it names one picture in the course.

A ref with no safe replacement is left as it is and reported.

Rewriting a lesson changes the digest a story chapter was pinned to
(``StoryCourseRecord.source_lesson_digest``), which would mark the chapter
stale and have it written again by the model on its next visit. The story was
told from the same lesson text, so by default the pin is moved to the new
digest and nothing is regenerated (``keep_stories``).
"""

from __future__ import annotations

import json
import re
import unicodedata
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import structlog
from sqlalchemy import String, cast, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.content import GeneratedContent
from app.domain.models.course import Course
from app.domain.models.module import Module
from app.domain.models.source_image import SourceImage
from app.domain.models.story_course import StoryCourseRecord

logger = structlog.get_logger(__name__)

#: ``{{source_image:<uuid>}}`` as lessons embed a figure in their text.
MARKER_RE = re.compile(
    r"\{\{source_image:([0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})\}\}"
)

#: ``figure_kind`` values that are never shown as a figure: mis-extracted
#: paragraphs of text (#2431) and page decoration.
EXCLUDED_KINDS = frozenset({"body_text", "decorative"})

#: How a replacement was found, most certain first.
BY_HASH = "hash"
BY_CAPTION = "caption"
BY_FIGURE_NUMBER = "figure_number"

#: Why a dangling ref was left alone.
NO_CANDIDATE = "no_candidate"
AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class Figure:
    """A ``source_images`` row as matching reads it (live, or a snapshot of a deleted one)."""

    id: str
    figure_number: str = ""
    captions: frozenset[str] = frozenset()
    image_type: str | None = None
    figure_kind: str | None = None
    page_number: int | None = None
    image_hash: str | None = None
    course_resource_id: str | None = None
    #: Creation order, so the choice between duplicates is stable.
    order: str = ""


@dataclass(frozen=True)
class Repoint:
    """One dangling id and the row that replaces it."""

    old: str
    new: str
    method: str


@dataclass
class RowRepair:
    """What one ``generated_content`` row needs."""

    content_id: str
    repoints: list[Repoint] = field(default_factory=list)
    #: ``(dangling id, reason)`` for refs with no safe replacement.
    unmatched: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class RepairReport:
    """The outcome for one course."""

    course_id: str
    rows: list[RowRepair] = field(default_factory=list)
    stories_repinned: int = 0
    applied: bool = False

    @property
    def repointed(self) -> int:
        return sum(len(row.repoints) for row in self.rows)

    @property
    def unmatched(self) -> int:
        return sum(len(row.unmatched) for row in self.rows)

    def as_dict(self) -> dict[str, Any]:
        return {
            "course_id": self.course_id,
            "applied": self.applied,
            "rows": len(self.rows),
            "repointed": self.repointed,
            "unmatched": self.unmatched,
            "stories_repinned": self.stories_repinned,
            "details": [
                {
                    "content_id": row.content_id,
                    "repoints": [[r.old, r.new, r.method] for r in row.repoints],
                    "unmatched": [list(u) for u in row.unmatched],
                }
                for row in self.rows
            ],
        }


# --------------------------------------------------------------------------
# Pure matching
# --------------------------------------------------------------------------


def normalise(text: Any) -> str:
    """A caption or figure number as it is compared: folded, one-spaced, no end dot."""
    if not isinstance(text, str):
        return ""
    folded = unicodedata.normalize("NFKC", text).casefold()
    return " ".join(folded.split()).strip(" .:;,")


def _captions(*values: Any) -> frozenset[str]:
    return frozenset(c for c in (normalise(v) for v in values) if c)


def figure_of_ref(ref: Mapping[str, Any]) -> Figure:
    """What a stored ref still says about the row it named."""
    return Figure(
        id=str(ref.get("id") or ""),
        figure_number=normalise(ref.get("figure_number")),
        captions=_captions(ref.get("caption"), ref.get("caption_en"), ref.get("caption_fr")),
        image_type=ref.get("image_type") if isinstance(ref.get("image_type"), str) else None,
    )


def figure_of_row(row: Any) -> Figure:
    """A ``source_images`` row (or a ``Row`` of its columns) as a :class:`Figure`."""
    created = getattr(row, "created_at", None)
    resource = getattr(row, "course_resource_id", None)
    return Figure(
        id=str(row.id),
        figure_number=normalise(getattr(row, "figure_number", None)),
        captions=_captions(
            getattr(row, "caption", None),
            getattr(row, "caption_en", None),
            getattr(row, "caption_fr", None),
        ),
        image_type=getattr(row, "image_type", None),
        figure_kind=getattr(row, "figure_kind", None),
        page_number=getattr(row, "page_number", None),
        image_hash=getattr(row, "image_hash", None),
        course_resource_id=str(resource) if resource else None,
        order=f"{created.isoformat() if created else ''}|{row.id}",
    )


def _pick(candidates: Sequence[Figure], wanted: Figure, taken: set[str]) -> Figure:
    """The best of several equally valid candidates.

    A row no other ref of the lesson took yet comes first, so two refs that
    named two copies of a figure keep naming two rows. Then the same resource,
    page and image type as the row that was lost, then the oldest.
    """

    def rank(candidate: Figure) -> tuple:
        return (
            candidate.id in taken,
            bool(wanted.course_resource_id)
            and candidate.course_resource_id != wanted.course_resource_id,
            wanted.page_number is not None and candidate.page_number != wanted.page_number,
            bool(wanted.image_type) and candidate.image_type != wanted.image_type,
            candidate.order,
        )

    return min(candidates, key=rank)


def _one_picture(candidates: Sequence[Figure]) -> bool:
    """Whether the candidates are one picture: a single row, or copies with one hash."""
    if len(candidates) == 1:
        return True
    hashes = {c.image_hash for c in candidates}
    return len(hashes) == 1 and None not in hashes


def find_replacement(
    ref: Figure,
    live: Sequence[Figure],
    *,
    removed: Figure | None = None,
    taken: set[str] | None = None,
) -> tuple[Figure | None, str]:
    """The live row that replaces a dangling ref, and how it was found.

    ``live`` are the rows of the ref's own course. ``removed`` is the snapshot
    of the deleted row, when there is one. Returns ``(None, reason)`` when no
    row can be named safely.
    """
    taken = taken if taken is not None else set()
    shown = [c for c in live if c.figure_kind not in EXCLUDED_KINDS]
    wanted = Figure(
        id=ref.id,
        figure_number=ref.figure_number or (removed.figure_number if removed else ""),
        captions=ref.captions | (removed.captions if removed else frozenset()),
        image_type=ref.image_type or (removed.image_type if removed else None),
        page_number=removed.page_number if removed else None,
        image_hash=removed.image_hash if removed else None,
        course_resource_id=removed.course_resource_id if removed else None,
    )

    if wanted.image_hash:
        same_picture = [c for c in shown if c.image_hash == wanted.image_hash]
        if same_picture:
            return _pick(same_picture, wanted, taken), BY_HASH

    if wanted.captions:
        same_caption = [
            c
            for c in shown
            if c.captions & wanted.captions
            and (
                not c.figure_number
                or not wanted.figure_number
                or c.figure_number == wanted.figure_number
            )
        ]
        if same_caption:
            return _pick(same_caption, wanted, taken), BY_CAPTION
        return None, NO_CANDIDATE

    if wanted.figure_number:
        same_number = [c for c in shown if c.figure_number == wanted.figure_number]
        if wanted.page_number is not None:
            on_page = [c for c in same_number if c.page_number == wanted.page_number]
            same_number = on_page or same_number
        if not same_number:
            return None, NO_CANDIDATE
        if _one_picture(same_number):
            return _pick(same_number, wanted, taken), BY_FIGURE_NUMBER
        return None, AMBIGUOUS

    return None, NO_CANDIDATE


def referenced_ids(content: Any) -> list[str]:
    """Every figure id a content document names, refs first, in order, once each."""
    found: list[str] = []
    if isinstance(content, Mapping):
        for ref in content.get("source_image_refs") or []:
            if isinstance(ref, Mapping) and isinstance(ref.get("id"), str):
                found.append(ref["id"].lower())
    text = json.dumps(content, ensure_ascii=False) if content is not None else ""
    found.extend(match.lower() for match in MARKER_RE.findall(text))
    return list(dict.fromkeys(found))


def plan_row(
    content_id: str,
    content: Any,
    dangling: Iterable[str],
    live: Sequence[Figure],
    *,
    removed: Mapping[str, Figure] | None = None,
    resolved: dict[str, Repoint] | None = None,
) -> RowRepair:
    """The repoints one row needs. ``resolved`` carries choices across a course's rows."""
    dangling = set(dangling)
    removed = removed or {}
    resolved = resolved if resolved is not None else {}
    refs = {}
    if isinstance(content, Mapping):
        for ref in content.get("source_image_refs") or []:
            if isinstance(ref, Mapping) and isinstance(ref.get("id"), str):
                refs.setdefault(ref["id"].lower(), ref)

    repair = RowRepair(content_id=content_id)
    taken: set[str] = set()
    for old in referenced_ids(content):
        if old not in dangling:
            continue
        known = resolved.get(old)
        if known is not None:
            repair.repoints.append(known)
            taken.add(known.new)
            continue
        ref = figure_of_ref(refs[old]) if old in refs else Figure(id=old)
        replacement, how = find_replacement(ref, live, removed=removed.get(old), taken=taken)
        if replacement is None:
            repair.unmatched.append((old, how))
            continue
        repoint = Repoint(old=old, new=replacement.id, method=how)
        resolved[old] = repoint
        repair.repoints.append(repoint)
        taken.add(replacement.id)
    return repair


def rewrite_content(content: Any, repoints: Sequence[Repoint]) -> Any:
    """``content`` with every old id replaced, in the ref list and in the text markers.

    Ids are replaced in the serialised document, so a marker inside any string
    follows its ref. Two refs that now name one row are merged into the first.
    """
    if not repoints:
        return content
    text = json.dumps(content, ensure_ascii=False)
    for repoint in repoints:
        text = re.sub(re.escape(repoint.old), repoint.new, text, flags=re.IGNORECASE)
    rewritten = json.loads(text)
    if isinstance(rewritten, dict) and isinstance(rewritten.get("source_image_refs"), list):
        seen: set[str] = set()
        merged = []
        for ref in rewritten["source_image_refs"]:
            ref_id = ref.get("id") if isinstance(ref, dict) else None
            if isinstance(ref_id, str):
                if ref_id in seen:
                    continue
                seen.add(ref_id)
            merged.append(ref)
        rewritten["source_image_refs"] = merged
    return rewritten


# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------

_FIGURE_COLUMNS = (
    SourceImage.id,
    SourceImage.figure_number,
    SourceImage.caption,
    SourceImage.caption_en,
    SourceImage.caption_fr,
    SourceImage.image_type,
    SourceImage.figure_kind,
    SourceImage.page_number,
    SourceImage.image_hash,
    SourceImage.course_resource_id,
    SourceImage.created_at,
)


async def snapshot_figures(
    session: AsyncSession, source: str, course_resource_id: uuid.UUID | None = None
) -> dict[str, Figure]:
    """The rows about to be deleted, by id: taken before a re-index clears them."""
    stmt = select(*_FIGURE_COLUMNS).where(SourceImage.source == source)
    if course_resource_id is not None:
        stmt = stmt.where(SourceImage.course_resource_id == course_resource_id)
    rows = (await session.execute(stmt)).all()
    return {str(row.id): figure_of_row(row) for row in rows}


def _content_digest(content: Any) -> str:
    # Imported here: the story service imports half the story stack.
    from app.domain.services.story_from_lesson_service import content_digest

    return content_digest(content)


async def repoint_course_figure_refs(
    session: AsyncSession,
    course_id: uuid.UUID,
    *,
    removed: Mapping[str, Figure] | None = None,
    dry_run: bool = False,
    keep_stories: bool = True,
) -> RepairReport:
    """Repoint every dangling figure ref in the course's generated content.

    Candidates are the course's own figures only (``source_images.source`` is
    the course's ``rag_collection_id``), so a ref never ends up naming another
    course's picture. Nothing is committed: the caller owns the transaction.
    """
    report = RepairReport(course_id=str(course_id))
    collection = (
        await session.execute(select(Course.rag_collection_id).where(Course.id == course_id))
    ).scalar_one_or_none()
    if not collection:
        return report

    rows = (
        (
            await session.execute(
                select(GeneratedContent)
                .join(Module, Module.id == GeneratedContent.module_id)
                .where(
                    Module.course_id == course_id,
                    cast(GeneratedContent.content, String).like("%source_image%"),
                )
                .order_by(GeneratedContent.id)
            )
        )
        .scalars()
        .all()
    )
    named: dict[uuid.UUID, list[str]] = {row.id: referenced_ids(row.content) for row in rows}
    all_ids = {ref_id for ids in named.values() for ref_id in ids}
    if not all_ids:
        return report
    existing = {
        str(found)
        for found in (
            await session.execute(
                select(SourceImage.id).where(SourceImage.id.in_([uuid.UUID(i) for i in all_ids]))
            )
        ).scalars()
    }
    dangling = all_ids - existing
    if not dangling:
        return report

    live = [
        figure_of_row(row)
        for row in (
            await session.execute(select(*_FIGURE_COLUMNS).where(SourceImage.source == collection))
        ).all()
    ]
    resolved: dict[str, Repoint] = {}
    for row in rows:
        if not dangling.intersection(named[row.id]):
            continue
        repair = plan_row(
            str(row.id), row.content, dangling, live, removed=removed, resolved=resolved
        )
        report.rows.append(repair)
        if dry_run or not repair.repoints:
            continue
        old_digest = _content_digest(row.content)
        row.content = rewrite_content(row.content, repair.repoints)
        if keep_stories:
            # ``updated_at`` is restated so the chapter row does not look
            # rewritten, which would have the module story assembled again.
            result = await session.execute(
                update(StoryCourseRecord)
                .where(
                    StoryCourseRecord.source_lesson_content_id == row.id,
                    StoryCourseRecord.source_lesson_digest == old_digest,
                )
                .values(
                    source_lesson_digest=_content_digest(row.content),
                    updated_at=StoryCourseRecord.updated_at,
                )
            )
            report.stories_repinned += result.rowcount or 0
    if not dry_run:
        await session.flush()
        report.applied = True
    logger.info(
        "Figure refs checked",
        course_id=str(course_id),
        rows=len(report.rows),
        repointed=report.repointed,
        unmatched=report.unmatched,
        stories_repinned=report.stories_repinned,
        dry_run=dry_run,
    )
    return report


async def heal_after_reindex(
    course_id: str | uuid.UUID, removed: Mapping[str, Figure] | None = None
) -> RepairReport | None:
    """Repoint a course's refs once a re-index has re-created its figures.

    Called by the indexation tasks in their own session. It never raises: a
    failed repair must not fail an indexation that succeeded, and the repair
    script can be run afterwards.
    """
    from app.infrastructure.persistence.database import async_session_factory

    try:
        async with async_session_factory() as session:
            report = await repoint_course_figure_refs(
                session, uuid.UUID(str(course_id)), removed=removed
            )
            await session.commit()
            return report
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Figure ref repair after re-index failed",
            course_id=str(course_id),
            error=str(exc),
        )
        return None
