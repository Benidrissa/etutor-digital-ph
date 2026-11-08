"""Revision pinning for regenerated ``generated_content`` rows.

Regeneration overwrites a cached row *in place*: same row id, same question
ids (``q1``..``qN``), new questions and a new answer key, and
``content_revision`` bumped by one. Anything a learner holds that was built
from the old content — a quiz they are part-way through, answers queued
offline — would otherwise be graded against questions they never saw.

The rule that keeps every revision gradeable: before a row is overwritten, its
current content is saved as a ``generated_content_revisions`` pre-image keyed
``(generated_content_id, revision)`` (unique, ``uq_genc_revision``). Learner
payloads carry ``content_revision``; a submission that names an older revision
is graded against that revision's pre-image.

Several writers can reach the same overwrite in one session (the quality agent
and the backfill write their own pre-image, with their own ``trigger``, before
calling the generator), so :func:`ensure_pre_image` checks before it inserts.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.course_quality import GeneratedContentRevision

#: ``trigger`` recorded on pre-images written by a plain ``force_regenerate``.
REGENERATE_TRIGGER = "regenerate"


def current_revision(row: Any) -> int:
    """The row's ``content_revision``, defaulting to 1.

    ``content_revision`` is a server default, so a row INSERTed in this
    session reads ``None`` until it is refreshed; that row is revision 1.
    """
    value = getattr(row, "content_revision", None)
    if isinstance(value, int) and not isinstance(value, bool) and value >= 1:
        return value
    return 1


async def find_pre_image(
    session: AsyncSession, content_id: uuid.UUID, revision: int
) -> GeneratedContentRevision | None:
    """The saved pre-image of ``content_id`` at ``revision``, if any."""
    result = await session.execute(
        select(GeneratedContentRevision).where(
            GeneratedContentRevision.generated_content_id == content_id,
            GeneratedContentRevision.revision == revision,
        )
    )
    return result.scalars().first()


async def ensure_pre_image(
    session: AsyncSession,
    row: Any,
    *,
    trigger: str = REGENERATE_TRIGGER,
    triggered_by_user_id: uuid.UUID | None = None,
) -> GeneratedContentRevision | None:
    """Save ``row``'s current content as the pre-image of its current revision.

    Call it before overwriting the row. A no-op (returns ``None``) when that
    pre-image already exists — the quality agent and the backfill write their
    own first in the same session, and inserting again would violate
    ``uq_genc_revision``. Returns the new, pending pre-image otherwise; the
    caller's commit persists it together with the overwrite.
    """
    revision = current_revision(row)
    if await find_pre_image(session, row.id, revision) is not None:
        return None
    pre_image = GeneratedContentRevision(
        generated_content_id=row.id,
        revision=revision,
        content=row.content,
        sources_cited=row.sources_cited,
        quality_score_before=getattr(row, "quality_score", None),
        quality_flags_before=getattr(row, "quality_flags", None),
        trigger=trigger,
        triggered_by_user_id=triggered_by_user_id,
    )
    session.add(pre_image)
    return pre_image


async def content_at_revision(
    session: AsyncSession, row: Any, revision: int | None
) -> tuple[dict, int] | None:
    """``(content, revision)`` of ``row`` as it was at ``revision``.

    ``None`` (not given) or the row's current revision → the current content.
    An older revision → its pre-image's content. Returns ``None`` when that
    revision cannot be recovered (no pre-image), so the caller can refuse to
    grade instead of grading against the wrong questions.
    """
    current = current_revision(row)
    if revision is None or revision == current:
        return row.content, current
    pre_image = await find_pre_image(session, row.id, revision)
    if pre_image is None or not isinstance(pre_image.content, dict):
        return None
    return pre_image.content, revision
