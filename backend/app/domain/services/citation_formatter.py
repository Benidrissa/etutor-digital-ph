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
"""

from __future__ import annotations

import contextlib
import re
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.course import Course
from app.domain.models.course_resource import CourseResource
from app.domain.models.module import Module

_UUID_PREFIX_RE = re.compile(
    r"^\s*([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
    re.IGNORECASE,
)


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


def _pick_display_name(
    course: Course | None,
    resources: list[CourseResource],
    language: str,
) -> str | None:
    """Pick the label that replaces a UUID prefix.

    - Single CourseResource: humanized filename of that PDF.
    - Multiple resources: course title (we can't disambiguate from a
      flat string alone).
    - No resources: course title.
    """
    if len(resources) == 1:
        only = resources[0]
        return humanize_filename(only.parent_filename or only.filename) or None
    if course is None:
        return None
    if language == "en":
        return getattr(course, "title_en", None) or getattr(course, "title_fr", None)
    return getattr(course, "title_fr", None) or getattr(course, "title_en", None)


def _replace_uuid_prefix(s: str, display: str) -> str:
    """Swap a leading UUID with ``display``, preserving the trailing suffix."""
    m = _UUID_PREFIX_RE.match(s)
    if not m:
        return s
    return display + s[m.end() :]


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

    display = _pick_display_name(course, resources, language)
    if not display:
        return list(str_sources)

    return [_replace_uuid_prefix(s, display) if _starts_with_uuid(s) else s for s in str_sources]


def rewrite_uuid_citations_with_context(
    sources: list | None,
    course: Course | None,
    resources: list[CourseResource],
    language: str = "fr",
) -> list[str]:
    """Synchronous variant for callers that already have ``course`` and resources loaded.

    Used by the tutor service, which resolves the active course up front
    and shouldn't hit the DB again per emitted source.
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
    human-readable label.
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
    display = _pick_display_name(course, resources, language)
    if not display:
        return list(sources)

    rewritten: list[dict] = []
    for entry in sources:
        if isinstance(entry, dict):
            src = entry.get("source", "")
            if _starts_with_uuid(src):
                entry = {**entry, "source": _replace_uuid_prefix(src, display)}
        rewritten.append(entry)
    return rewritten


async def rewrite_response_citations(response, session: AsyncSession):
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
