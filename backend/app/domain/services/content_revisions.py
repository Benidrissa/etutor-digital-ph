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

Writers in *different* sessions can race on one row (a course quality run and
the MCQ backfill, say). The revision an overwrite saves and bumps must be the
database's, not that of an object a long-lived session loaded earlier, or an
overwrite committed meanwhile is overwritten again under the same revision
number with no pre-image of it. So the row an overwrite starts from is re-read
under a row lock (:func:`locked_for_overwrite`), and a pre-image that already
exists for the revision but holds other content is a :class:`RevisionConflict`,
never a reason to skip.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.course_quality import GeneratedContentRevision

#: ``trigger`` recorded on pre-images written by a plain ``force_regenerate``.
REGENERATE_TRIGGER = "regenerate"
#: ``trigger`` recorded on pre-images written by an admin's edit of a quiz.
ADMIN_EDIT_TRIGGER = "admin_edit"


class RevisionConflict(RuntimeError):
    """A pre-image saved for this revision holds other content than the row.

    The row was changed under the same revision number, so which questions a
    learner served that revision saw is no longer known. Overwriting it again
    would only bury that; the writer aborts instead.
    """


def locked_for_overwrite(stmt: Select) -> Select:
    """``stmt`` (a select of ``GeneratedContent``) re-reading the row under a lock.

    ``populate_existing`` refreshes an object the session already holds, so the
    revision an overwrite saves and bumps is the database's; ``FOR NO KEY
    UPDATE`` (what an UPDATE takes) makes a concurrent writer wait until this
    transaction commits, without blocking inserts of pre-images, which only
    reference the row.
    """
    return stmt.with_for_update(key_share=True).execution_options(populate_existing=True)


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

    Call it before overwriting the row, on a row read with
    :func:`locked_for_overwrite`. A no-op (returns ``None``) when that
    pre-image already exists with the same content — the quality agent and
    the backfill write their own first, and inserting again would violate
    ``uq_genc_revision``. Raises :class:`RevisionConflict` when it exists with
    other content: the row changed without a new revision. Returns the new,
    pending pre-image otherwise; the caller's commit persists it together with
    the overwrite.
    """
    revision = current_revision(row)
    existing = await find_pre_image(session, row.id, revision)
    if existing is not None:
        if existing.content != row.content:
            raise RevisionConflict(
                f"generated_content {row.id}: the pre-image of revision {revision} "
                "holds other content than the row; refusing to overwrite it again"
            )
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


def as_utc(value: Any) -> datetime | None:
    """``value`` as an aware UTC datetime; naive values are UTC (``generated_at``)."""
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def superseded_at(row: Any, pre_image: Any) -> datetime | None:
    """When the revision saved in ``pre_image`` stopped being served.

    The pre-image is written just before its revision is overwritten; its
    ``created_at`` is the writing transaction's start, so it can be early by
    the length of that transaction (an AI call). When the overwrite produced
    the row's current content, the row's ``generated_at`` is stamped at the
    overwrite itself. The later of the two is the best estimate; ``None``
    when neither is known.
    """
    times = [as_utc(getattr(pre_image, "created_at", None))]
    if getattr(pre_image, "revision", None) == current_revision(row) - 1:
        times.append(as_utc(getattr(row, "generated_at", None)))
    known = [time for time in times if time is not None]
    return max(known) if known else None
