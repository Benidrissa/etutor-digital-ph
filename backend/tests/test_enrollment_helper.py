"""Regression tests for enroll_user_in_course (enrollment_helper).

Verifies that non-first modules are seeded as 'not_started' (not 'locked')
after issue #2218 / #2125 removed sequential module gating.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.models.module import Module
from app.domain.models.progress import UserModuleProgress
from app.domain.services.enrollment_helper import enroll_user_in_course


def _make_module(module_number: int) -> Module:
    m = MagicMock(spec=Module)
    m.id = uuid.uuid4()
    m.module_number = module_number
    m.course_id = uuid.uuid4()
    return m


@pytest.mark.asyncio
async def test_first_module_gets_in_progress() -> None:
    """First module must be seeded as in_progress so learner can start immediately."""
    user_id = uuid.uuid4()
    course_id = uuid.uuid4()
    modules = [_make_module(1), _make_module(2), _make_module(3)]
    # Sort so module 1 is first
    modules.sort(key=lambda m: m.module_number)

    db = AsyncMock()
    # session.add() is synchronous — use MagicMock so side_effect fires immediately
    db.add = MagicMock()
    db.execute.side_effect = _make_execute_side_effect(
        existing_enrollment=None,
        modules=modules,
        existing_progress={},
    )

    await enroll_user_in_course(db, user_id, course_id)

    added = [
        call.args[0]
        for call in db.add.call_args_list
        if isinstance(call.args[0], UserModuleProgress)
    ]
    first_prog = next((p for p in added if p.module_id == modules[0].id), None)
    assert first_prog is not None
    assert first_prog.status == "in_progress", (
        "First module must be in_progress so learner can start immediately"
    )


@pytest.mark.asyncio
async def test_non_first_modules_get_not_started_not_locked() -> None:
    """Regression for #2218: non-first modules must NOT be seeded as 'locked'."""
    user_id = uuid.uuid4()
    course_id = uuid.uuid4()
    modules = [_make_module(1), _make_module(2), _make_module(3)]
    modules.sort(key=lambda m: m.module_number)

    db = AsyncMock()
    db.add = MagicMock()
    db.execute.side_effect = _make_execute_side_effect(
        existing_enrollment=None,
        modules=modules,
        existing_progress={},
    )

    await enroll_user_in_course(db, user_id, course_id)

    added = [
        c.args[0]
        for c in db.add.call_args_list
        if isinstance(c.args[0], UserModuleProgress)
    ]
    non_first = [p for p in added if p.module_id != modules[0].id]
    assert len(non_first) == 2, "Should have progress rows for modules 2 and 3"
    for prog in non_first:
        assert prog.status == "not_started", (
            f"Non-first module {prog.module_id} must be 'not_started', got '{prog.status}'. "
            "Regression: #2218 — enrollment_helper must not write 'locked' after #2125."
        )


@pytest.mark.asyncio
async def test_existing_enrollment_not_duplicated() -> None:
    """Re-enrolling an already-active learner must not create duplicate progress rows."""
    user_id = uuid.uuid4()
    course_id = uuid.uuid4()

    existing_enrollment = MagicMock()
    existing_enrollment.status = "active"

    db = AsyncMock()
    db.execute.side_effect = _make_execute_side_effect(
        existing_enrollment=existing_enrollment,
        modules=[],
        existing_progress={},
    )

    added: list = []
    db.add.side_effect = added.append

    result = await enroll_user_in_course(db, user_id, course_id)

    progress_rows = [obj for obj in added if isinstance(obj, UserModuleProgress)]
    assert len(progress_rows) == 0, "Must not add new progress rows for an active re-enrollment"
    assert result is existing_enrollment


@pytest.mark.asyncio
async def test_reactivates_inactive_enrollment() -> None:
    """An inactive (dropped) enrollment is reactivated, not duplicated."""
    user_id = uuid.uuid4()
    course_id = uuid.uuid4()

    existing_enrollment = MagicMock()
    existing_enrollment.status = "inactive"

    db = AsyncMock()
    db.execute.side_effect = _make_execute_side_effect(
        existing_enrollment=existing_enrollment,
        modules=[],
        existing_progress={},
    )
    db.add.side_effect = lambda _: None

    await enroll_user_in_course(db, user_id, course_id)

    assert existing_enrollment.status == "active"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_execute_side_effect(
    existing_enrollment,
    modules: list[Module],
    existing_progress: dict[uuid.UUID, UserModuleProgress],
):
    """Build a side_effect list for db.execute() calls in enroll_user_in_course.

    Call order:
      1. select(UserCourseEnrollment) — existing enrollment check
      2. select(Module) — fetch course modules
      3+. select(UserModuleProgress) — one per module
    """
    call_count = 0

    async def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1

        result = MagicMock()
        if call_count == 1:
            # Enrollment lookup
            result.scalar_one_or_none.return_value = existing_enrollment
        elif call_count == 2:
            # Module list
            scalars = MagicMock()
            scalars.all.return_value = modules
            result.scalars.return_value = scalars
        else:
            # Progress lookup per module — index into modules list
            module_idx = call_count - 3
            module = modules[module_idx] if module_idx < len(modules) else None
            existing = existing_progress.get(module.id) if module else None
            result.scalar_one_or_none.return_value = existing

        return result

    return side_effect
