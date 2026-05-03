"""Read-side rewriter for citation strings produced by the lesson generator.

The lesson/case-study generators store ``DocumentChunk.source =
rag_collection_id`` (a course UUID) for AI-generated courses, then format
``sources_cited`` as ``"<UUID>, p.43"`` strings via ``source.title()``. This
module rewrites those UUID-prefixed strings into a human-readable form
**after** generation, without touching the generation pipeline:

  ``"Bd2E9508-9B48-46F4-959C-14B682Cba886, p.43"``  →  ``"Triola Chapter 3, p.43"``

The mapping is purely a presentation-layer transform. It uses information
already on disk — ``CourseResource.filename`` and ``Course.title_*`` — so no
schema changes, no re-indexation, and no Claude API spend.

Multi-PDF resolution (#2178): when the course has more than one PDF, each
citation's ``(chapter, page)`` is matched against ``DocumentChunk`` rows for
that course; the chunk's content prefix is then substring-matched against
each ``CourseResource.raw_text`` to identify the originating PDF. Per-citation
fallback to the course title only when the lookup is genuinely ambiguous.
"""

from __future__ import annotations

import contextlib
import re
from typing import Any
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.course import Course
from app.domain.models.course_resource import CourseResource
from app.domain.models.document_chunk import DocumentChunk
from app.domain.models.module import Module
from app.domain.models.source_image import SourceImage, SourceImageChunk

# Match either the full UUID form (``8-4-4-4-12``) or a bare 8-char hex
# stem (#2174) — Claude sometimes echoes only the leading segment back.
# The lookahead pins the 8-char form to a separator (whitespace / comma /
# end-of-string) so a normal word that *happens* to start with hex letters
# (e.g. ``"Cafebabe Ch.1"``) is the only false positive we accept;
# ordinary names like ``"Donaldson"`` have non-hex chars and won't match.
_UUID_PREFIX_RE = re.compile(
    r"^\s*(?:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[0-9a-f]{8}(?=\s|,|$))",
    re.IGNORECASE,
)
_CHAPTER_RE = re.compile(r"\bCh\.([^,\s]+)", re.IGNORECASE)
_PAGE_RE = re.compile(r"\bp\.(\d+)", re.IGNORECASE)
# Match what TextChunker._clean_text strips so we can locate a chunk's
# (cleaned) content inside a resource's pre-clean raw_text.
_PAGE_NUMBER_NOISE = re.compile(r"\b(?:Page|page)\s*\d+\b")
_CHAPTER_HEADER_NOISE = re.compile(r"\b\d{1,3}\s*\|\s*Chapter\s*\d+")
_CASE_BREAK = re.compile(r"([a-z])([A-Z])")
_WHITESPACE = re.compile(r"\s+")
_FINGERPRINT_LEN = 200


def _starts_with_uuid(s: str) -> bool:
    return bool(_UUID_PREFIX_RE.match(s)) if isinstance(s, str) else False


def humanize_filename(filename: str | None) -> str:
    """``triola_chapter_3.pdf`` -> ``Triola Chapter 3``."""
    if not filename:
        return ""
    name = filename.strip()
    if "." in name:
        stem, _, ext = name.rpartition(".")
        if 1 <= len(ext) <= 5 and ext.isalnum():
            name = stem
    name = name.replace("_", " ").replace("-", " ")
    name = re.sub(r"\s+", " ", name).strip()
    return name.title() if name else ""


def _replace_uuid_prefix(s: str, display: str) -> str:
    """Swap a leading UUID with ``display``, preserving the trailing suffix."""
    m = _UUID_PREFIX_RE.match(s)
    if not m:
        return s
    return display + s[m.end() :]


def _course_title(course: Course | None, language: str) -> str | None:
    if course is None:
        return None
    if language == "en":
        return getattr(course, "title_en", None) or getattr(course, "title_fr", None)
    return getattr(course, "title_fr", None) or getattr(course, "title_en", None)


def _resource_label(resource: CourseResource | None) -> str | None:
    if resource is None:
        return None
    return humanize_filename(resource.parent_filename or resource.filename) or None


def _normalize_for_match(text: str | None) -> str:
    """Apply the same cleaning as ``TextChunker._clean_text`` plus lowercase.

    Chunks are stored post-clean, so to find a chunk inside a ``CourseResource.raw_text``
    we apply the same cleaning to ``raw_text`` once. Lowercasing additionally
    guards against any ``.title()``/case drift along the way.
    """
    if not text:
        return ""
    text = _WHITESPACE.sub(" ", text)
    text = _PAGE_NUMBER_NOISE.sub("", text)
    text = _CHAPTER_HEADER_NOISE.sub("", text)
    text = re.sub(r"\s*\n\s*", " ", text)
    text = _CASE_BREAK.sub(r"\1. \2", text)
    return text.lower()


def _parse_chapter_page(citation: str) -> tuple[str | None, int | None]:
    """Pull ``(chapter, page)`` out of a citation string suffix."""
    chapter: str | None = None
    page: int | None = None
    if not isinstance(citation, str):
        return None, None
    m = _CHAPTER_RE.search(citation)
    if m:
        chapter = m.group(1).strip().rstrip(",")
    m = _PAGE_RE.search(citation)
    if m:
        try:
            page = int(m.group(1))
        except ValueError:
            page = None
    return chapter, page


def _pick_display_name(
    course: Course | None,
    resources: list[CourseResource],
    language: str,
) -> str | None:
    """Pick the label that replaces a UUID prefix when no per-citation map exists.

    - Single CourseResource: humanized filename of that PDF.
    - Multiple resources: course title (used as the per-citation fallback).
    - No resources: course title.
    """
    if len(resources) == 1:
        return _resource_label(resources[0])
    return _course_title(course, language)


async def _resolve_per_citation_map(
    course: Course,
    resources: list[CourseResource],
    pairs: set[tuple[str | None, int | None]],
    session: AsyncSession,
) -> dict[tuple[str | None, int | None], str]:
    """Return ``{(chapter, page): humanized_filename}`` for resolvable citations.

    Resolution order:

    1. **Direct FK** (#2186): if a chunk row has ``course_resource_id`` set
       (populated by ingest from migration 089 onward), use it directly.
    2. **Content fingerprint vote** (#2178): substring-match chunk content
       against each ``CourseResource.raw_text``.
    3. **SourceImage.surrounding_text tiebreaker** (#2181): for chunks where
       step 2 matched multiple resources, look up linked figures and use
       the surrounding paragraph as a second fingerprint.

    Pairs that don't yield a unique resource are simply omitted from the map.
    """
    rag_id = getattr(course, "rag_collection_id", None)
    if not rag_id or not pairs or not resources:
        return {}

    # Build OR-of-AND filter: (chapter=:c, page=:p) for each pair (skip Nones).
    filterable = [(c, p) for (c, p) in pairs if c is not None or p is not None]
    if not filterable:
        return {}
    conditions = []
    for c, p in filterable:
        clauses = [DocumentChunk.source == rag_id]
        if c is not None:
            clauses.append(DocumentChunk.chapter == str(c))
        if p is not None:
            clauses.append(DocumentChunk.page == p)
        conditions.append(and_(*clauses))
    stmt = (
        select(
            DocumentChunk.id,
            DocumentChunk.chapter,
            DocumentChunk.page,
            DocumentChunk.content,
            DocumentChunk.course_resource_id,
        )
        .where(or_(*conditions))
        .limit(200)
    )
    rows = (await session.execute(stmt)).all()
    if not rows:
        return {}

    normalized_resources: list[tuple[CourseResource, str]] = [
        (r, _normalize_for_match(r.raw_text or "")) for r in resources if r.raw_text
    ]
    if not normalized_resources:
        return {}

    AMBIGUOUS: object = object()
    seen: dict[tuple[str | None, int | None], CourseResource | object] = {}
    # Chunks whose content matched 2+ resources — defer to the image-text
    # tiebreaker pass below.
    deferred: list[tuple[Any, str | None, int | None, list[CourseResource]]] = []

    # Build resource-by-id lookup once for the FK fast path.
    resource_by_id = {r.id: r for r in resources}

    def _record(key: tuple[str | None, int | None], winner: CourseResource) -> None:
        prior = seen.get(key)
        if prior is None:
            seen[key] = winner
        elif prior is AMBIGUOUS:
            return
        elif getattr(prior, "id", None) != winner.id:
            seen[key] = AMBIGUOUS

    for row in rows:
        chunk_id = row[0]
        chunk_chapter = row[1]
        chunk_page = row[2]
        chunk_content = row[3] or ""
        chunk_resource_id = row[4]

        # Fast path (#2186): chunks ingested after migration 089 carry a
        # direct FK to their originating CourseResource. Skip all the
        # fingerprint dance for those.
        if chunk_resource_id is not None:
            direct = resource_by_id.get(chunk_resource_id)
            if direct is not None:
                _record((chunk_chapter, chunk_page), direct)
                continue

        normalized = _normalize_for_match(chunk_content)
        fingerprint = normalized[:_FINGERPRINT_LEN]
        if len(fingerprint) < 40:
            continue
        matches: list[CourseResource] = []
        for resource, normalized_text in normalized_resources:
            if fingerprint in normalized_text:
                matches.append(resource)
        if len(matches) == 1:
            _record((chunk_chapter, chunk_page), matches[0])
        elif len(matches) > 1:
            deferred.append((chunk_id, chunk_chapter, chunk_page, matches))

    if deferred:
        chunk_ids = list({d[0] for d in deferred if d[0] is not None})
        if chunk_ids:
            img_stmt = (
                select(SourceImageChunk.document_chunk_id, SourceImage.surrounding_text)
                .join(SourceImage, SourceImage.id == SourceImageChunk.source_image_id)
                .where(SourceImageChunk.document_chunk_id.in_(chunk_ids))
            )
            img_rows = (await session.execute(img_stmt)).all()
            surrounding_by_chunk: dict[Any, list[str]] = {}
            for cid, st in img_rows:
                if not st:
                    continue
                surrounding_by_chunk.setdefault(cid, []).append(st)

            for chunk_id, chunk_chapter, chunk_page, candidates in deferred:
                sts = surrounding_by_chunk.get(chunk_id, [])
                if not sts:
                    continue
                # Vote: which candidate uniquely contains a surrounding_text?
                # Pre-compute candidate normalized_text lookup.
                candidate_texts = {
                    r.id: t for (r, t) in normalized_resources for c in candidates if c.id == r.id
                }
                tiebreaker_winner: CourseResource | None = None
                for st in sts:
                    fp = _normalize_for_match(st)[:_FINGERPRINT_LEN]
                    if len(fp) < 40:
                        continue
                    sub_matches = [r for r in candidates if fp in candidate_texts.get(r.id, "")]
                    if len(sub_matches) == 1:
                        tiebreaker_winner = sub_matches[0]
                        break
                if tiebreaker_winner is not None:
                    _record((chunk_chapter, chunk_page), tiebreaker_winner)

    out: dict[tuple[str | None, int | None], str] = {}
    for key, winner in seen.items():
        if winner is None or winner is AMBIGUOUS:
            continue
        label = _resource_label(winner)  # type: ignore[arg-type]
        if label:
            out[key] = label
    return out


def _apply_per_citation(
    str_sources: list[str],
    per_citation_map: dict[tuple[str | None, int | None], str],
    fallback_label: str | None,
) -> list[str]:
    """Rewrite each UUID-prefixed citation using the per-citation map first."""
    out: list[str] = []
    for s in str_sources:
        if not _starts_with_uuid(s):
            out.append(s)
            continue
        key = _parse_chapter_page(s)
        label = per_citation_map.get(key) or fallback_label
        out.append(_replace_uuid_prefix(s, label) if label else s)
    return out


async def rewrite_uuid_citations_for_module(
    sources: list | None,
    module_id: UUID | None,
    session: AsyncSession,
    language: str = "fr",
) -> list[str]:
    """Rewrite UUID-prefixed citation strings to human-readable form.

    Returns a new list. Strings that don't start with a UUID are passed
    through unchanged. If the module/course can't be resolved or there's
    no readable label available, the input is returned as-is.
    """
    if not sources:
        return [] if sources is None else list(sources)
    str_sources = [s for s in sources if isinstance(s, str)]
    if not any(_starts_with_uuid(s) for s in str_sources):
        return list(str_sources)
    if module_id is None:
        return list(str_sources)

    module = await session.get(Module, module_id)
    if module is None or module.course_id is None:
        return list(str_sources)

    course = await session.get(Course, module.course_id)
    res_result = await session.execute(
        select(CourseResource).where(CourseResource.course_id == module.course_id)
    )
    resources = list(res_result.scalars().all())

    fallback_label = _pick_display_name(course, resources, language)

    if len(resources) <= 1 or course is None:
        if not fallback_label:
            return list(str_sources)
        return [
            _replace_uuid_prefix(s, fallback_label) if _starts_with_uuid(s) else s
            for s in str_sources
        ]

    pairs = {_parse_chapter_page(s) for s in str_sources if _starts_with_uuid(s)}
    per_citation_map = await _resolve_per_citation_map(course, resources, pairs, session)
    return _apply_per_citation(str_sources, per_citation_map, fallback_label)


def rewrite_uuid_citations_with_context(
    sources: list | None,
    course: Course | None,
    resources: list[CourseResource],
    language: str = "fr",
) -> list[str]:
    """Synchronous variant for callers that already have ``course`` and resources loaded.

    Used by the tutor service's in-memory paths. Multi-PDF per-citation
    resolution requires a DB query, which is async-only — sync callers stick
    with the single-display fallback (course title for multi-resource).
    """
    if not sources:
        return [] if sources is None else list(sources)
    str_sources = [s for s in sources if isinstance(s, str)]
    if not any(_starts_with_uuid(s) for s in str_sources):
        return list(str_sources)

    display = _pick_display_name(course, resources, language)
    if not display:
        return list(str_sources)

    return [_replace_uuid_prefix(s, display) if _starts_with_uuid(s) else s for s in str_sources]


def rewrite_uuid_in_string(
    source: str | None,
    course: Course | None,
    resources: list[CourseResource],
    language: str = "fr",
) -> str:
    """Single-string variant for use in dict construction sites (tutor)."""
    if not source or not isinstance(source, str):
        return source or ""
    if not _starts_with_uuid(source):
        return source
    display = _pick_display_name(course, resources, language)
    if not display:
        return source
    return _replace_uuid_prefix(source, display)


async def rewrite_uuid_in_source_dicts(
    sources: list[dict] | None,
    course: Course | None,
    session: AsyncSession,
    language: str = "fr",
) -> list[dict]:
    """Tutor-side variant that rewrites the ``source`` field in each dict.

    Tutor citations are emitted as ``{"source": <str>, "chapter": ..., "page": ...}``
    dicts. Walks the list, swapping any UUID-prefixed ``source`` for a
    human-readable label. Multi-PDF courses get per-dict resolution using the
    dict's own ``chapter``/``page`` fields.
    """
    if not sources:
        return list(sources or [])
    needs_rewrite = any(
        _starts_with_uuid(s.get("source", "")) for s in sources if isinstance(s, dict)
    )
    if not needs_rewrite:
        return list(sources)
    if course is None or getattr(course, "id", None) is None:
        return list(sources)

    res_result = await session.execute(
        select(CourseResource).where(CourseResource.course_id == course.id)
    )
    resources = list(res_result.scalars().all())
    fallback_label = _pick_display_name(course, resources, language)

    if len(resources) <= 1:
        if not fallback_label:
            return list(sources)
        rewritten: list[dict] = []
        for entry in sources:
            if isinstance(entry, dict):
                src = entry.get("source", "")
                if _starts_with_uuid(src):
                    entry = {**entry, "source": _replace_uuid_prefix(src, fallback_label)}
            rewritten.append(entry)
        return rewritten

    pairs: set[tuple[str | None, int | None]] = set()
    for entry in sources:
        if not isinstance(entry, dict):
            continue
        if not _starts_with_uuid(entry.get("source", "")):
            continue
        chapter_raw = entry.get("chapter")
        chapter = str(chapter_raw) if chapter_raw is not None else None
        page_raw = entry.get("page")
        page: int | None
        try:
            page = int(page_raw) if page_raw is not None else None
        except (TypeError, ValueError):
            page = None
        pairs.add((chapter, page))
    per_citation_map = await _resolve_per_citation_map(course, resources, pairs, session)

    rewritten: list[dict] = []
    for entry in sources:
        if not isinstance(entry, dict):
            rewritten.append(entry)
            continue
        src = entry.get("source", "")
        if not _starts_with_uuid(src):
            rewritten.append(entry)
            continue
        chapter_raw = entry.get("chapter")
        chapter = str(chapter_raw) if chapter_raw is not None else None
        page_raw = entry.get("page")
        try:
            page = int(page_raw) if page_raw is not None else None
        except (TypeError, ValueError):
            page = None
        label = per_citation_map.get((chapter, page)) or fallback_label
        if label:
            entry = {**entry, "source": _replace_uuid_prefix(src, label)}
        rewritten.append(entry)
    return rewritten


async def rewrite_response_citations(response: Any, session: AsyncSession):
    """Rewrite ``response.content.sources_cited`` in place.

    Convenience wrapper for endpoint handlers that return a
    ``LessonResponse``/``CaseStudyResponse`` straight from a service call,
    so they can apply the citation rewrite without restructuring the
    response.
    """
    content = getattr(response, "content", None)
    if content is None:
        return response
    sources = getattr(content, "sources_cited", None)
    module_id = getattr(response, "module_id", None)
    if not sources or module_id is None:
        return response
    language = getattr(response, "language", "fr") or "fr"
    rewritten = await rewrite_uuid_citations_for_module(
        sources, module_id, session, language=language
    )
    # Frozen pydantic models reject attribute assignment; in that case the
    # endpoint reconstructs the content dict before instantiating, so this
    # silent fallthrough is intentional.
    with contextlib.suppress(AttributeError, ValueError):
        content.sources_cited = rewritten
    return response
