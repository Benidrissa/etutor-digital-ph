"""Admin endpoints for the course quality agent (#2215, review UI #2249).

The agent runs **autonomously** after each lesson generation; these
endpoints exist for human review and override of what the agent
already flagged. Endpoints:

Per-course (router prefix ``/admin/courses``):

- ``POST /admin/courses/{course_id}/quality/runs`` — enqueue a sweep
  (idempotent via day-bucketed key + partial unique on active runs)
- ``GET  /admin/courses/{course_id}/quality/runs`` — list runs
- ``GET  /admin/courses/{course_id}/quality/runs/{run_id}`` — one run
  with per-unit summary
- ``GET  /admin/courses/{course_id}/quality/summary`` — dashboard tile
- ``GET  /admin/courses/{course_id}/quality/glossary`` — read glossary
- ``GET  /admin/courses/{course_id}/units/{content_id}/quality`` —
  per-unit drill-in with dimension scores + flags
- ``POST /admin/courses/{course_id}/units/{content_id}/quality/regenerate``
  — targeted retry; respects ``is_manually_edited`` and the max-attempt cap
- ``POST /admin/courses/{course_id}/units/{content_id}/quality/resolve``
  — admin marks the unit resolved (sets ``quality_status='passing'``
  and ``validated=true``)
- ``POST /admin/courses/{course_id}/units/{content_id}/quality/unlock``
  — clears ``is_manually_edited`` so a future run can re-evaluate

Cross-course (router prefix ``/admin/quality``):

- ``GET  /admin/quality/review-queue`` — courses sorted by
  attention-needed for the top-level review surface

Roles: ``admin``, ``sub_admin`` see any course; ``expert`` is gated
to courses they own (``Course.created_by == user.id``).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import case, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from structlog import get_logger

from app.api.deps import get_db as get_db_session
from app.api.deps_local_auth import AuthenticatedUser, require_role
from app.api.v1.schemas.quality import (
    CourseQualityRunDetail,
    CourseQualityRunSummary,
    DimensionScores,
    GlossaryEntryResponse,
    QualityFlag,
    RegenerateUnitRequest,
    ResolveUnitRequest,
    ReviewQueueEntry,
    RunQualityCheckRequest,
    UnitQualityDetail,
    UnitQualitySummary,
    to_decimal_safe,
)
from app.domain.models.content import GeneratedContent
from app.domain.models.course import Course
from app.domain.models.course_quality import (
    CourseGlossaryTerm,
    CourseQualityRun,
    UnitQualityAssessment,
)
from app.domain.models.module import Module
from app.domain.models.module_unit import ModuleUnit
from app.domain.models.user import UserRole

logger = get_logger(__name__)
router = APIRouter(prefix="/admin/courses", tags=["Admin - Quality"])
review_router = APIRouter(prefix="/admin/quality", tags=["Admin - Quality"])

_QUALITY_ROLES = (UserRole.admin, UserRole.sub_admin, UserRole.expert)


async def _assert_course_access(
    session: AsyncSession,
    course_id: uuid.UUID,
    user: AuthenticatedUser,
) -> uuid.UUID | None:
    """Verify the course exists and the caller may access it.

    Returns the course's ``created_by`` value (or ``None``). Raises
    404 when the course is missing, 403 when an ``expert`` caller is
    not the course owner. ``admin`` and ``sub_admin`` bypass the
    ownership check.
    """
    row = await session.execute(select(Course.created_by).where(Course.id == course_id))
    result = row.first()
    if result is None:
        raise HTTPException(status_code=404, detail="Course not found")
    created_by: uuid.UUID | None = result[0]
    if user.role == UserRole.expert.value and (
        created_by is None or str(created_by) != str(user.id)
    ):
        raise HTTPException(
            status_code=403,
            detail="You do not have access to this course's quality data.",
        )
    return created_by


@router.post(
    "/{course_id}/quality/runs",
    response_model=CourseQualityRunSummary,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_quality_run(
    course_id: uuid.UUID,
    payload: RunQualityCheckRequest,
    current_user: AuthenticatedUser = Depends(require_role(*_QUALITY_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> CourseQualityRunSummary:
    """Queue a course quality sweep.

    Returns the in-flight run if one already exists for the same
    (course, day-bucketed user). Pass ``force=true`` to bypass that
    collapse and always start a fresh run; the partial unique on
    ``ux_one_active_run_per_course`` will still reject if any run is
    active for this course (avoids double sweeps).
    """
    from app.ai.claude_service import ClaudeService
    from app.domain.services.quality_agent_service import CourseQualityService
    from app.tasks.quality_assessment import assess_course_task

    await _assert_course_access(session, course_id, current_user)

    service = CourseQualityService(ClaudeService(), semantic_retriever=None)
    idempotency_key = None if payload.force else None  # default: service derives day-bucketed
    if payload.force:
        # Random idempotency key so we always insert a new row.
        idempotency_key = uuid.uuid4().hex[:32]

    try:
        run = await service.assess_course(
            course_id=course_id,
            triggered_by_user_id=uuid.UUID(str(current_user.id)),
            session=session,
            run_kind=payload.run_kind,
            budget_credits=payload.budget_credits,
            idempotency_key=idempotency_key,
        )
        await session.commit()
    except Exception as e:
        await session.rollback()
        logger.error(
            "Failed to enqueue quality run",
            course_id=str(course_id),
            error=str(e),
        )
        raise HTTPException(status_code=500, detail=f"Failed to enqueue run: {e}") from e

    # Dispatch the Celery task — fire-and-forget. If a duplicate run
    # was returned (idempotency hit), still dispatch; the task is
    # idempotent on its own state machine.
    if run.status in ("queued",):
        try:
            assess_course_task.apply_async(
                kwargs={
                    "run_id": str(run.id),
                    "triggered_by_user_id": str(current_user.id),
                },
                priority=5,
            )
        except Exception as exc:
            logger.warning(
                "Failed to dispatch assess_course_task (run row exists, will need retry)",
                run_id=str(run.id),
                error=str(exc),
            )

    return CourseQualityRunSummary.model_validate(
        {
            **run.__dict__,
            "id": run.id,
            "course_id": run.course_id,
            "overall_score": to_decimal_safe(run.overall_score),
        }
    )


@router.get(
    "/{course_id}/quality/runs",
    response_model=list[CourseQualityRunSummary],
)
async def list_quality_runs(
    course_id: uuid.UUID,
    limit: int = 20,
    current_user: AuthenticatedUser = Depends(require_role(*_QUALITY_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> list[CourseQualityRunSummary]:
    """Most recent runs first."""
    await _assert_course_access(session, course_id, current_user)
    rows = await session.execute(
        select(CourseQualityRun)
        .where(CourseQualityRun.course_id == course_id)
        .order_by(desc(CourseQualityRun.created_at))
        .limit(max(1, min(limit, 100)))
    )
    return [
        CourseQualityRunSummary.model_validate(
            {
                **r.__dict__,
                "id": r.id,
                "course_id": r.course_id,
                "overall_score": to_decimal_safe(r.overall_score),
            }
        )
        for r in rows.scalars().all()
    ]


@router.get(
    "/{course_id}/quality/runs/{run_id}",
    response_model=CourseQualityRunDetail,
)
async def get_quality_run(
    course_id: uuid.UUID,
    run_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_role(*_QUALITY_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> CourseQualityRunDetail:
    """Run detail + per-unit roll-up.

    Pulls the per-unit data from ``generated_content.last_quality_run_id``
    so the response stays a single hop and we don't have to walk
    ``unit_quality_assessments`` history (latest score lives on the
    GC row already).
    """
    await _assert_course_access(session, course_id, current_user)
    run = await session.get(CourseQualityRun, run_id)
    if run is None or run.course_id != course_id:
        raise HTTPException(status_code=404, detail="Run not found")

    unit_rows = await session.execute(
        select(GeneratedContent, ModuleUnit)
        .join(Module, GeneratedContent.module_id == Module.id)
        .join(ModuleUnit, GeneratedContent.module_unit_id == ModuleUnit.id, isouter=True)
        .where(GeneratedContent.last_quality_run_id == run_id)
        .where(Module.course_id == course_id)
    )
    units: list[UnitQualitySummary] = []
    for gc, mu in unit_rows.all():
        units.append(
            UnitQualitySummary(
                generated_content_id=gc.id,
                unit_number=(mu.unit_number if mu else None),
                content_type=gc.content_type,
                language=gc.language,
                quality_score=to_decimal_safe(gc.quality_score),
                quality_status=gc.quality_status,  # type: ignore[arg-type]
                flag_count=len(gc.quality_flags or []),
                regeneration_attempts=gc.regeneration_attempts or 0,
                is_manually_edited=bool(gc.is_manually_edited),
                last_assessed_at=gc.quality_assessed_at,
            )
        )

    return CourseQualityRunDetail.model_validate(
        {
            **run.__dict__,
            "id": run.id,
            "course_id": run.course_id,
            "overall_score": to_decimal_safe(run.overall_score),
            "units": units,
        }
    )


@router.get(
    "/{course_id}/quality/glossary",
    response_model=list[GlossaryEntryResponse],
)
async def get_course_glossary(
    course_id: uuid.UUID,
    language: str | None = None,
    current_user: AuthenticatedUser = Depends(require_role(*_QUALITY_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> list[GlossaryEntryResponse]:
    """Read the canonical glossary for a course.

    The ``consistency_status`` field surfaces drift the agent flagged
    during its pre-pass; admins can use the ``drift_details`` text to
    decide whether to manually edit the canonical definition or
    trigger a regenerate of the affected units.
    """
    await _assert_course_access(session, course_id, current_user)
    q = (
        select(CourseGlossaryTerm, ModuleUnit)
        .join(
            ModuleUnit,
            CourseGlossaryTerm.first_unit_id == ModuleUnit.id,
            isouter=True,
        )
        .where(CourseGlossaryTerm.course_id == course_id)
    )
    if language:
        q = q.where(CourseGlossaryTerm.language == language)
    q = q.order_by(CourseGlossaryTerm.term_normalized)
    rows = await session.execute(q)
    out: list[GlossaryEntryResponse] = []
    for term, first_unit in rows.all():
        out.append(
            GlossaryEntryResponse(
                id=term.id,
                term_display=term.term_display,
                language=term.language,
                canonical_definition=term.canonical_definition,
                first_unit_number=(first_unit.unit_number if first_unit else None),
                consistency_status=term.consistency_status,
                drift_details=term.drift_details,
                occurrences_count=len(term.occurrences or []),
                status=term.status,
            )
        )
    return out


@router.post(
    "/{course_id}/units/{content_id}/quality/regenerate",
    response_model=dict,
    status_code=status.HTTP_202_ACCEPTED,
)
async def regenerate_unit_with_constraints(
    course_id: uuid.UUID,
    content_id: uuid.UUID,
    payload: RegenerateUnitRequest,
    current_user: AuthenticatedUser = Depends(require_role(*_QUALITY_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Targeted regenerate for a flagged unit.

    Hands off to ``assess_and_regenerate_unit_task`` so the work runs
    on a Celery worker (Anthropic calls take seconds; we don't want to
    block an admin HTTP request). When ``payload.constraints`` is
    empty we let the task pull the latest auditor-emitted constraints
    from ``generated_content.quality_flags``.
    """
    from app.tasks.quality_assessment import assess_and_regenerate_unit_task

    await _assert_course_access(session, course_id, current_user)

    gc = await session.get(GeneratedContent, content_id)
    if gc is None:
        raise HTTPException(status_code=404, detail="Content not found")

    # Validate the GC actually belongs to this course.
    module = await session.get(Module, gc.module_id)
    if module is None or module.course_id != course_id:
        raise HTTPException(status_code=404, detail="Content does not belong to this course")

    if gc.is_manually_edited:
        raise HTTPException(
            status_code=409,
            detail="Content is manually edited (locked). Use POST .../quality/unlock first.",
        )

    try:
        task = assess_and_regenerate_unit_task.apply_async(
            kwargs={
                "content_id": str(content_id),
                "triggered_by_user_id": str(current_user.id),
            },
            priority=5,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to dispatch task: {e}") from e
    return {"task_id": task.id, "content_id": str(content_id)}


@router.post(
    "/{course_id}/units/{content_id}/quality/resolve",
    response_model=dict,
)
async def resolve_unit_quality(
    course_id: uuid.UUID,
    content_id: uuid.UUID,
    payload: ResolveUnitRequest,
    current_user: AuthenticatedUser = Depends(require_role(*_QUALITY_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Mark a flagged unit as resolved without regenerating.

    Sets ``quality_status='passing'`` AND ``validated=true``. The
    admin is asserting human review supersedes the agent's score.
    Future quality runs will still re-score the row, but this one is
    cleared from the current run's ``needs_review`` queue.
    """
    await _assert_course_access(session, course_id, current_user)
    gc = await session.get(GeneratedContent, content_id)
    if gc is None:
        raise HTTPException(status_code=404, detail="Content not found")
    module = await session.get(Module, gc.module_id)
    if module is None or module.course_id != course_id:
        raise HTTPException(status_code=404, detail="Content does not belong to this course")

    gc.quality_status = "passing"
    gc.validated = True
    gc.quality_assessed_at = datetime.utcnow()
    await session.commit()
    return {
        "content_id": str(content_id),
        "quality_status": gc.quality_status,
        "note": payload.note,
    }


@router.post(
    "/{course_id}/units/{content_id}/quality/unlock",
    response_model=dict,
)
async def unlock_unit_for_quality(
    course_id: uuid.UUID,
    content_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_role(*_QUALITY_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Clear ``is_manually_edited`` so the agent can re-evaluate.

    Required before a quality run will touch a row the admin
    previously locked via the ``PUT .../content/{id}`` editor.
    """
    await _assert_course_access(session, course_id, current_user)
    gc = await session.get(GeneratedContent, content_id)
    if gc is None:
        raise HTTPException(status_code=404, detail="Content not found")
    module = await session.get(Module, gc.module_id)
    if module is None or module.course_id != course_id:
        raise HTTPException(status_code=404, detail="Content does not belong to this course")

    gc.is_manually_edited = False
    gc.quality_status = "pending"
    await session.commit()
    return {"content_id": str(content_id), "is_manually_edited": False}


@router.get(
    "/{course_id}/quality/summary",
    response_model=dict,
)
async def get_quality_summary(
    course_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_role(*_QUALITY_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Course-level quality dashboard tile.

    Returns: total units, units passing/failing/locked, latest run
    summary, glossary drift count.
    """
    await _assert_course_access(session, course_id, current_user)

    counts_q = await session.execute(
        select(
            GeneratedContent.quality_status,
            func.count().label("n"),
        )
        .join(Module, GeneratedContent.module_id == Module.id)
        .where(Module.course_id == course_id)
        .group_by(GeneratedContent.quality_status)
    )
    by_status: dict[str, int] = {row.quality_status: int(row.n) for row in counts_q.all()}
    total = sum(by_status.values())

    last_run_q = await session.execute(
        select(CourseQualityRun)
        .where(CourseQualityRun.course_id == course_id)
        .order_by(desc(CourseQualityRun.created_at))
        .limit(1)
    )
    last_run = last_run_q.scalar_one_or_none()

    drift_q = await session.execute(
        select(func.count())
        .select_from(CourseGlossaryTerm)
        .where(CourseGlossaryTerm.course_id == course_id)
        .where(CourseGlossaryTerm.consistency_status == "drift_detected")
    )
    drift_count = int(drift_q.scalar_one() or 0)

    return {
        "course_id": str(course_id),
        "units_total": total,
        "units_by_status": by_status,
        "glossary_drift_count": drift_count,
        "last_run": (
            CourseQualityRunSummary.model_validate(
                {
                    **last_run.__dict__,
                    "id": last_run.id,
                    "course_id": last_run.course_id,
                    "overall_score": to_decimal_safe(last_run.overall_score),
                }
            ).model_dump(mode="json")
            if last_run is not None
            else None
        ),
    }


@router.get(
    "/{course_id}/units/{content_id}/quality",
    response_model=UnitQualityDetail,
)
async def get_unit_quality_detail(
    course_id: uuid.UUID,
    content_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_role(*_QUALITY_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> UnitQualityDetail:
    """Per-unit drill-in for the review UI.

    Returns the hot fields from ``generated_content`` plus the latest
    ``unit_quality_assessments`` row's ``dimension_scores`` so the UI
    can render the dimension bars without a second round-trip.
    """
    await _assert_course_access(session, course_id, current_user)

    gc = await session.get(GeneratedContent, content_id)
    if gc is None:
        raise HTTPException(status_code=404, detail="Content not found")

    module = await session.get(Module, gc.module_id)
    if module is None or module.course_id != course_id:
        raise HTTPException(status_code=404, detail="Content does not belong to this course")

    unit_number: str | None = None
    if gc.module_unit_id is not None:
        mu = await session.get(ModuleUnit, gc.module_unit_id)
        if mu is not None:
            unit_number = mu.unit_number

    latest_q = await session.execute(
        select(UnitQualityAssessment)
        .where(UnitQualityAssessment.generated_content_id == content_id)
        .order_by(desc(UnitQualityAssessment.attempt_number))
        .limit(1)
    )
    latest = latest_q.scalar_one_or_none()

    dimensions: DimensionScores | None = None
    if latest is not None and latest.dimension_scores:
        try:
            dimensions = DimensionScores.model_validate(latest.dimension_scores)
        except Exception:
            # Tolerate legacy rows where the JSONB shape differs from
            # the current schema; the UI degrades to "no chart" rather
            # than 500-ing on the read path.
            dimensions = None

    flags = [QualityFlag.model_validate(f) for f in (gc.quality_flags or [])]

    return UnitQualityDetail(
        generated_content_id=gc.id,
        unit_number=unit_number,
        content_type=gc.content_type,
        language=gc.language,
        quality_score=to_decimal_safe(gc.quality_score),
        quality_status=gc.quality_status,  # type: ignore[arg-type]
        flag_count=len(flags),
        regeneration_attempts=gc.regeneration_attempts or 0,
        is_manually_edited=bool(gc.is_manually_edited),
        validated=bool(gc.validated),
        quality_assessed_at=gc.quality_assessed_at,
        last_quality_run_id=gc.last_quality_run_id,
        quality_flags=flags,
        dimension_scores=dimensions,
        latest_attempt_id=(latest.id if latest else None),
        latest_attempt_number=(latest.attempt_number if latest else None),
        latest_attempt_score=to_decimal_safe(latest.score) if latest else None,
    )


# ---- cross-course review queue ----


@review_router.get("/review-queue", response_model=list[ReviewQueueEntry])
async def list_review_queue(
    limit: int = 100,
    has_issues: bool = True,
    current_user: AuthenticatedUser = Depends(require_role(*_QUALITY_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> list[ReviewQueueEntry]:
    """Cross-course review queue, sorted by attention-needed.

    Owner-scoped for ``expert`` callers (only courses where
    ``Course.created_by == user.id``). When ``has_issues`` is true
    (default), courses with no flagged units and no glossary drift are
    omitted — the surface is a triage queue, not a directory.
    """
    needs_review_count = func.coalesce(
        func.sum(case((GeneratedContent.quality_status == "needs_review", 1), else_=0)),
        0,
    ).label("units_needs_review")
    needs_review_final_count = func.coalesce(
        func.sum(case((GeneratedContent.quality_status == "needs_review_final", 1), else_=0)),
        0,
    ).label("units_needs_review_final")
    failed_count = func.coalesce(
        func.sum(case((GeneratedContent.quality_status == "failed", 1), else_=0)),
        0,
    ).label("units_failed")
    passing_count = func.coalesce(
        func.sum(case((GeneratedContent.quality_status == "passing", 1), else_=0)),
        0,
    ).label("units_passing")
    total_count = func.coalesce(func.count(GeneratedContent.id), 0).label("units_total")
    last_assessed_at = func.max(GeneratedContent.quality_assessed_at).label("last_assessed_at")

    base_q = (
        select(
            Course.id.label("course_id"),
            Course.title_fr.label("course_title_fr"),
            Course.title_en.label("course_title_en"),
            Course.created_by.label("owner_id"),
            total_count,
            passing_count,
            needs_review_count,
            needs_review_final_count,
            failed_count,
            last_assessed_at,
        )
        .select_from(Course)
        .join(Module, Module.course_id == Course.id, isouter=True)
        .join(GeneratedContent, GeneratedContent.module_id == Module.id, isouter=True)
        .group_by(Course.id, Course.title_fr, Course.title_en, Course.created_by)
    )
    if current_user.role == UserRole.expert.value:
        base_q = base_q.where(Course.created_by == uuid.UUID(str(current_user.id)))

    base_q = base_q.order_by(
        desc(needs_review_final_count + failed_count),
        desc(needs_review_count),
        desc(Course.created_at),
    ).limit(max(1, min(limit, 500)))

    course_rows = (await session.execute(base_q)).all()

    if not course_rows:
        return []

    course_ids = [row.course_id for row in course_rows]

    drift_q = await session.execute(
        select(
            CourseGlossaryTerm.course_id,
            func.count().label("drift_count"),
        )
        .where(CourseGlossaryTerm.course_id.in_(course_ids))
        .where(CourseGlossaryTerm.consistency_status == "drift_detected")
        .group_by(CourseGlossaryTerm.course_id)
    )
    drift_by_course: dict[uuid.UUID, int] = {
        row.course_id: int(row.drift_count) for row in drift_q.all()
    }

    # Latest run per course (one round-trip via correlated subquery would
    # be tighter; iterate for clarity since N is bounded by ``limit``).
    last_run_q = await session.execute(
        select(CourseQualityRun)
        .where(CourseQualityRun.course_id.in_(course_ids))
        .order_by(CourseQualityRun.course_id, desc(CourseQualityRun.created_at))
    )
    last_run_by_course: dict[uuid.UUID, CourseQualityRun] = {}
    for run in last_run_q.scalars().all():
        last_run_by_course.setdefault(run.course_id, run)

    out: list[ReviewQueueEntry] = []
    for row in course_rows:
        drift = drift_by_course.get(row.course_id, 0)
        nrf = int(row.units_needs_review_final or 0)
        nr = int(row.units_needs_review or 0)
        failed = int(row.units_failed or 0)
        if has_issues and (nrf + nr + failed + drift) == 0:
            continue
        last_run = last_run_by_course.get(row.course_id)
        last_run_dto: CourseQualityRunSummary | None = None
        if last_run is not None:
            last_run_dto = CourseQualityRunSummary.model_validate(
                {
                    **last_run.__dict__,
                    "id": last_run.id,
                    "course_id": last_run.course_id,
                    "overall_score": to_decimal_safe(last_run.overall_score),
                }
            )
        out.append(
            ReviewQueueEntry(
                course_id=row.course_id,
                course_title_fr=row.course_title_fr,
                course_title_en=row.course_title_en,
                owner_id=row.owner_id,
                units_total=int(row.units_total or 0),
                units_passing=int(row.units_passing or 0),
                units_needs_review=nr,
                units_needs_review_final=nrf,
                units_failed=failed,
                glossary_drift_count=drift,
                last_assessed_at=row.last_assessed_at,
                last_run=last_run_dto,
            )
        )
    return out
