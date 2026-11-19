"""Anonymised story events (#2711): what the learner bet, answered and finished.

The only way a story's teaching can be measured: story progress lives in the
browser, so without these events nobody can tell whether betting before the
explanation helps. They go to the existing ``usage_events`` table
(:class:`AnalyticsService`'s), with three rules:

* **Nothing that identifies the learner.** The row has no user and no session:
  the request is authenticated (to stop strangers filling the table, and to read
  the opt-out), then the user is forgotten. Nothing links two events of a
  learner, so what can be measured is rates (how often a bet matches, how often
  the first answer is right), not one child's path.
* **No free text.** Every field is a boolean, a small number, a language code
  or an identifier of the story (a slug), the chapter or the question; a value
  that is not shaped like one is refused. The learner's name and answers never
  appear.
* **The learner's opt-out is honoured** (``users.analytics_opt_out``): an event
  from a user who opted out is dropped, and the client does not send it either.

There is no automatic expiry on ``usage_events`` today; :func:`purge_story_events`
deletes them by age and is what a retention schedule would call (see
``docs/story-events-consent.md``).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.usage_event import UsageEvent

EVENT_NAMES = ("story_prediction", "story_first_try", "story_chapter_complete")
ID_RE = re.compile(r"^[A-Za-z0-9._:\-]{1,100}$")


class StoryEvent(BaseModel):
    """One event. Extra keys are refused (``extra="forbid"``): nothing free-form gets in."""

    model_config = ConfigDict(extra="forbid")

    event: Literal["story_prediction", "story_first_try", "story_chapter_complete"]
    #: The story document's id (a slug), the chapter's id and the question's id.
    story: str = Field(..., pattern=ID_RE.pattern)
    chapter: str | None = Field(None, pattern=ID_RE.pattern)
    question: str | None = Field(None, pattern=ID_RE.pattern)
    lang: Literal["fr", "en"] | None = None
    #: ``story_prediction``: the bet matched what the demo showed.
    matched: bool | None = None
    #: ``story_first_try``: the first answer was right.
    correct: bool | None = None
    #: ``story_first_try``: 1 or 2, the try that settled the question.
    attempts: int | None = Field(None, ge=1, le=2)
    #: ``story_chapter_complete``: the stars won, 0 to 3.
    stars: int | None = Field(None, ge=0, le=3)


class StoryEventsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: list[StoryEvent] = Field(..., min_length=1, max_length=50)


def properties_of(event: StoryEvent) -> dict[str, Any]:
    """What is stored: the event's fields that are set, and a marker that it is anonymous."""
    data = event.model_dump(exclude={"event"}, exclude_none=True)
    data["anonymised"] = True
    return data


async def ingest_story_events(
    db: AsyncSession, events: list[StoryEvent], *, opted_out: bool
) -> int:
    """Store ``events`` with no user and no session; ``0`` for a learner who opted out."""
    if opted_out or not events:
        return 0
    db.add_all(
        [
            UsageEvent(
                user_id=None, session_id=None, event_name=e.event, properties=properties_of(e)
            )
            for e in events
        ]
    )
    await db.commit()
    return len(events)


async def purge_story_events(db: AsyncSession, *, older_than_days: int) -> int:
    """Delete story events older than ``older_than_days`` days; returns how many."""
    since = datetime.now(tz=UTC) - timedelta(days=older_than_days)
    result = await db.execute(
        delete(UsageEvent).where(
            UsageEvent.event_name.in_(EVENT_NAMES), UsageEvent.created_at < since
        )
    )
    await db.commit()
    return int(getattr(result, "rowcount", 0) or 0)
