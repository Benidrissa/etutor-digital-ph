"""Helper to resolve a unit_number string to its ``module_units.id``.

Replaces the legacy JSON-string match (``content->>'unit_id' = '1.3'``)
that powered cache lookups before issue #2007 / migration 084. Centralizes
the resolution so every read site goes through the same code path and
the ``"summative"`` sentinel (module-scoped quizzes) is handled
consistently.
"""

from __future__ import annotations

import uuid

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.module_unit import ModuleUnit

SUMMATIVE_SENTINEL = "summative"


async def resolve_module_unit_id(
    session: AsyncSession,
    module_id: uuid.UUID,
    unit_number: str,
) -> uuid.UUID | None:
    """Return ``module_units.id`` for ``(module_id, unit_number)``.

    Returns ``None`` when ``unit_number`` is the summative sentinel (the
    caller must fall back to the module-scoped lookup) or when no row
    matches (unknown unit_number — caller should usually 404).
    """
    if unit_number == SUMMATIVE_SENTINEL or not unit_number:
        return None
    result = await session.execute(
        select(ModuleUnit.id).where(
            and_(
                ModuleUnit.module_id == module_id,
                ModuleUnit.unit_number == unit_number,
            )
        )
    )
    return result.scalar_one_or_none()
