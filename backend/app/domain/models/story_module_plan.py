"""The episode plan of a module story (#2680): one per (module, language).

Story generator v4 plans a module as ONE episode before any chapter is
written — the premise, the props that come back, each chapter's beats and
hook, and the rally — then tells the chapters in order from it
(:mod:`app.domain.services.story_plan`).

``content`` holds ``{"plan", "inputs", "gaps", "pins"}``: the normalised plan,
the breakdown of what it was made from (to re-plan only a changed chapter),
what the code had to fix, and the lesson and quiz rows it was made from.
``inputs`` is the digest of that breakdown, ``digest`` the digest of the
plan, and ``global_digest`` the digest of the plan without its chapters,
which every chapter row records (``sira_chapter.plan``). ``model`` is the
model that wrote it, or ``DEFAULTED`` for a plan made in code because no
answer could be used.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import ForeignKey, SmallInteger, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.models.base import Base


class StoryModulePlan(Base):
    """A module story's episode plan in one language."""

    __tablename__ = "story_module_plans"
    __table_args__ = (
        UniqueConstraint("module_id", "language", name="uq_story_module_plans_module_language"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    module_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("modules.id", ondelete="CASCADE"), nullable=False
    )
    language: Mapped[str] = mapped_column(String(5), nullable=False)
    #: ``story_repair.PLAN_VERSION`` it was made by.
    version: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    inputs: Mapped[str] = mapped_column(String(64), nullable=False)
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    global_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[dict] = mapped_column(JSONB, nullable=False)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
