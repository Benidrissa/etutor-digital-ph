"""Course Quality Agent service (#2215).

Orchestrates:
1. **Glossary extraction** — pre-pass that builds the canonical
   ``course_glossary_terms`` from all generated lessons in a course
   plus per-resource summaries. The glossary is the cross-unit truth
   for terminology consistency.
2. **Per-unit assessment** — calls Claude with the cached
   (rubric + syllabus + summaries + glossary) prefix and the per-unit
   tail (unit content + neighbor digest + RAG excerpts), returns a
   ``UnitQualityReport``, persists the score and flags onto the
   ``GeneratedContent`` row, and records a row in
   ``unit_quality_assessments`` with token + cost stats.
3. **Course sweep** — fan-out over every unit in a course; the caller
   (Celery) batches work to keep the prompt cache hot.
4. **Regeneration with constraints** — when a unit fails, derives the
   regeneration constraint list from the report's flags and calls the
   appropriate generator service (lesson / quiz / case study /
   flashcard) with ``quality_constraints=...``. Bounds the loop with
   max-attempts and the +3-monotonic-improvement guard.

The service is intentionally side-effect-heavy: it writes to
``unit_quality_assessments``, ``course_glossary_terms``,
``course_quality_runs``, ``generated_content_revisions`` and updates
``generated_content`` quality columns. All writes are within the
caller-supplied ``AsyncSession`` so the surrounding Celery task
controls the transaction boundary.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.ai.claude_service import ClaudeService
from app.ai.prompts.quality import (
    GLOSSARY_EXTRACTOR_SYSTEM_PROMPT,
    QUALITY_PROMPT_VERSION,
    build_auditor_user_message,
    build_cached_system_blocks,
    build_glossary_extractor_user_message,
    compute_weighted_score,
    constraints_block_from_report,
    has_critical_floor_violation,
)
from app.ai.rag.retriever import SemanticRetriever
from app.api.v1.schemas.quality import (
    CourseGlossaryDocument,
    GlossaryEntry,
    UnitQualityReport,
)
from app.domain.models.content import GeneratedContent
from app.domain.models.course import Course
from app.domain.models.course_quality import (
    CourseGlossaryTerm,
    CourseQualityRun,
    GeneratedContentRevision,
    UnitQualityAssessment,
)
from app.domain.models.course_resource import CourseResource
from app.domain.models.module import Module
from app.domain.models.module_unit import ModuleUnit

logger = structlog.get_logger()


# ---- Constants -----------------------------------------------------------

PASSING_SCORE_THRESHOLD = 90
MAX_REGEN_ATTEMPTS = 2
MIN_IMPROVEMENT_PER_ATTEMPT = 3  # +3 points minimum, else stop loop
COURSE_PASSING_RATIO = 0.92  # for early exit
DEFAULT_BUDGET_FULL = 200
DEFAULT_BUDGET_TARGETED = 50

# Approximate Claude Sonnet 4.6 pricing (cents per million tokens)
# Used for cost_cents accounting; refresh when pricing changes.
PRICING_INPUT_CENTS_PER_M = 300  # $3 / M
PRICING_OUTPUT_CENTS_PER_M = 1500  # $15 / M
PRICING_CACHE_WRITE_CENTS_PER_M = 375  # ~25% premium on writes
PRICING_CACHE_READ_CENTS_PER_M = 30  # ~10% of input


def normalize_term(text: str) -> str:
    """Lowercase + strip accents + collapse whitespace.

    Used as the dedup key in ``course_glossary_terms``. Two surface
    forms ("Écart-type" / "ecart-type" / " ecart  type ") collapse to
    the same row.
    """
    s = unicodedata.normalize("NFKD", text or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def calculate_cost_cents(usage: dict[str, Any]) -> int:
    """Compute the cost of one Claude call in integer cents.

    ``usage`` keys: ``input_tokens``, ``output_tokens``,
    ``cache_creation_input_tokens``, ``cache_read_input_tokens``.
    Anthropic reports cache reads + cache writes SEPARATELY from the
    main ``input_tokens`` field (which is then the *uncached* portion).
    """
    inp = int(usage.get("input_tokens") or 0)
    out = int(usage.get("output_tokens") or 0)
    cwrite = int(usage.get("cache_creation_input_tokens") or 0)
    cread = int(usage.get("cache_read_input_tokens") or 0)
    cents = (
        inp * PRICING_INPUT_CENTS_PER_M
        + out * PRICING_OUTPUT_CENTS_PER_M
        + cwrite * PRICING_CACHE_WRITE_CENTS_PER_M
        + cread * PRICING_CACHE_READ_CENTS_PER_M
    ) / 1_000_000
    return int(round(cents))


# ---- Service ------------------------------------------------------------


class CourseQualityService:
    """Quality agent orchestrator. See module docstring."""

    def __init__(
        self,
        claude_service: ClaudeService,
        semantic_retriever: SemanticRetriever | None = None,
    ):
        self.claude_service = claude_service
        self.semantic_retriever = semantic_retriever

    # ---- Context builder (cached prefix) ----------------------------

    async def build_quality_context(
        self,
        course_id: uuid.UUID,
        language: str,
        session: AsyncSession,
    ) -> dict[str, Any]:
        """Build the cached-prefix payload for a course quality run.

        Returns a dict with keys ``syllabus_block``,
        ``source_summaries_block``, ``glossary_block`` ready to feed
        into :func:`build_cached_system_blocks`.
        """
        course_result = await session.execute(select(Course).where(Course.id == course_id))
        course = course_result.scalar_one_or_none()
        if course is None:
            raise ValueError(f"Course {course_id} not found")

        # Syllabus + objectives
        syllabus_parts: list[str] = []
        if course.syllabus_context:
            syllabus_parts.append("### syllabus_context (prose)\n" + course.syllabus_context)
        if course.syllabus_json:
            syllabus_parts.append(
                "### syllabus_json\n" + json.dumps(course.syllabus_json, ensure_ascii=False, indent=2)
            )
        if course.objectives_json:
            syllabus_parts.append(
                "### module learning objectives\n"
                + json.dumps(course.objectives_json, ensure_ascii=False, indent=2)
            )
        syllabus_block = "\n\n".join(syllabus_parts) or "(no syllabus stored)"

        # Per-resource summaries
        res_result = await session.execute(
            select(CourseResource).where(CourseResource.course_id == course_id)
        )
        resources = list(res_result.scalars().all())
        summary_parts: list[str] = []
        for r in resources:
            if not r.summary_text:
                continue
            summary_parts.append(f"### {r.filename}\n{r.summary_text.strip()[:6000]}")
        source_summaries_block = "\n\n".join(summary_parts) or "(no source summaries available)"

        # Glossary
        gloss_result = await session.execute(
            select(CourseGlossaryTerm)
            .where(CourseGlossaryTerm.course_id == course_id)
            .where(CourseGlossaryTerm.language == language)
        )
        terms = list(gloss_result.scalars().all())
        glossary_parts: list[str] = []
        for t in terms:
            entry = {
                "term": t.term_display,
                "canonical_definition": t.canonical_definition,
                "first_appears_in_unit": (
                    t.first_unit.unit_number if t.first_unit else None
                ),
                "alt_phrasings": t.alt_phrasings or [],
                "source_citations": t.source_citations or [],
                "consistency_status": t.consistency_status,
                "drift_details": t.drift_details,
            }
            glossary_parts.append(json.dumps(entry, ensure_ascii=False))
        glossary_block = (
            "[\n  " + ",\n  ".join(glossary_parts) + "\n]"
            if glossary_parts
            else "(glossary not yet built)"
        )

        return {
            "syllabus_block": syllabus_block,
            "source_summaries_block": source_summaries_block,
            "glossary_block": glossary_block,
        }

    # ---- Glossary extraction ----------------------------------------

    async def extract_or_refresh_glossary(
        self,
        course_id: uuid.UUID,
        language: str,
        session: AsyncSession,
    ) -> list[CourseGlossaryTerm]:
        """Build (or rebuild) the canonical glossary for a course.

        Strategy: load every generated lesson's ``concepts`` array
        (already term/definition pairs from the lesson generator),
        plus per-resource summaries, and ask Claude to dedupe / pick
        canonical defs / detect drift in one structured-output call.

        For courses with > 12 lesson units this is done in chunks
        (per-module map step) plus a reduce step. For now we always
        do the single-call path; the map-reduce variant can be added
        when token counts demand it.
        """
        course_result = await session.execute(select(Course).where(Course.id == course_id))
        course = course_result.scalar_one_or_none()
        if course is None:
            raise ValueError(f"Course {course_id} not found")

        # Pull all lesson units' content + unit_number + title.
        lessons_result = await session.execute(
            select(GeneratedContent, ModuleUnit, Module)
            .join(Module, GeneratedContent.module_id == Module.id)
            .join(ModuleUnit, GeneratedContent.module_unit_id == ModuleUnit.id, isouter=True)
            .where(Module.course_id == course_id)
            .where(GeneratedContent.content_type == "lesson")
            .where(GeneratedContent.language == language)
        )
        rows = list(lessons_result.all())
        if not rows:
            logger.info(
                "Glossary extraction skipped — no lessons yet",
                course_id=str(course_id),
                language=language,
            )
            return []

        units_payload: list[dict[str, Any]] = []
        unit_number_to_uuid: dict[str, uuid.UUID] = {}
        for gc, mu, _mod in rows:
            unit_number = mu.unit_number if mu else None
            if not unit_number:
                continue
            unit_number_to_uuid[unit_number] = mu.id
            content = gc.content or {}
            units_payload.append(
                {
                    "unit_number": unit_number,
                    "title": (mu.title_fr if language == "fr" else mu.title_en) or "",
                    "concepts": content.get("concepts") or [],
                }
            )

        # Source summaries
        res_result = await session.execute(
            select(CourseResource).where(CourseResource.course_id == course_id)
        )
        source_summaries = [
            {"filename": r.filename, "summary": r.summary_text or ""}
            for r in res_result.scalars().all()
            if r.summary_text
        ]

        course_title = course.title_fr if language == "fr" else course.title_en
        user_message = build_glossary_extractor_user_message(
            course_title=course_title or "",
            language=language,
            units=units_payload,
            source_summaries=source_summaries,
        )

        # Single text block as system; no caching at this stage (one call total).
        parsed, usage = await self.claude_service.generate_structured_content_cached(
            system_blocks=[
                {"type": "text", "text": GLOSSARY_EXTRACTOR_SYSTEM_PROMPT},
            ],
            user_message=user_message,
            content_type="glossary_extraction",
        )
        if parsed.get("raw_response"):
            logger.error(
                "Glossary extraction returned unparseable JSON",
                course_id=str(course_id),
                language=language,
            )
            return []

        try:
            doc = CourseGlossaryDocument.model_validate(parsed)
        except Exception as e:
            logger.error(
                "Glossary extraction schema validation failed",
                course_id=str(course_id),
                error=str(e),
            )
            return []

        # Upsert each entry. Existing entries get their canonical
        # definition + drift flags refreshed; new entries are inserted.
        upserted: list[CourseGlossaryTerm] = []
        for entry in doc.entries:
            term_norm = normalize_term(entry.term)
            if not term_norm:
                continue
            existing_q = await session.execute(
                select(CourseGlossaryTerm).where(
                    and_(
                        CourseGlossaryTerm.course_id == course_id,
                        CourseGlossaryTerm.term_normalized == term_norm,
                        CourseGlossaryTerm.language == language,
                    )
                )
            )
            row = existing_q.scalar_one_or_none()
            first_uuid = unit_number_to_uuid.get(entry.first_appears_in_unit)
            if row is None:
                row = CourseGlossaryTerm(
                    course_id=course_id,
                    term_normalized=term_norm,
                    term_display=entry.term,
                    language=language,
                    canonical_definition=entry.canonical_definition,
                    first_unit_id=first_uuid,
                    alt_phrasings=entry.alt_phrasings,
                    source_citations=entry.source_citations,
                    consistency_status=entry.consistency_status,
                    drift_details=entry.drift_details,
                )
                session.add(row)
            else:
                row.term_display = entry.term
                row.canonical_definition = entry.canonical_definition
                row.first_unit_id = first_uuid or row.first_unit_id
                row.alt_phrasings = entry.alt_phrasings
                row.source_citations = entry.source_citations
                row.consistency_status = entry.consistency_status
                row.drift_details = entry.drift_details
            upserted.append(row)

        await session.flush()
        logger.info(
            "Glossary extraction complete",
            course_id=str(course_id),
            language=language,
            term_count=len(upserted),
            drift_count=sum(1 for t in upserted if t.consistency_status == "drift_detected"),
            usage=usage,
        )
        return upserted

    # ---- Per-unit assessment ----------------------------------------

    async def assess_unit(
        self,
        content_id: uuid.UUID,
        run_id: uuid.UUID | None,
        session: AsyncSession,
        attempt_number: int = 1,
        cached_blocks: list[dict[str, Any]] | None = None,
    ) -> tuple[UnitQualityReport, UnitQualityAssessment]:
        """Score a single unit and persist the result.

        ``cached_blocks`` lets the caller (a course-level sweep) build
        the system-prompt prefix once and reuse it across every unit
        — that's where the prompt-cache savings come from. When None,
        we build it inline (slower but correct for one-off targeted
        re-assessments).
        """
        gc = await session.get(GeneratedContent, content_id)
        if gc is None:
            raise ValueError(f"GeneratedContent {content_id} not found")

        # Hard guard: never assess (or regenerate) admin-locked content.
        if gc.is_manually_edited:
            gc.quality_status = "manual_override"
            await session.flush()
            raise PermissionError(
                f"GeneratedContent {content_id} is manually edited; cannot be assessed"
            )

        # Resolve module + course for context.
        module = await session.get(Module, gc.module_id)
        if module is None:
            raise ValueError(f"Module {gc.module_id} not found")
        course_id = module.course_id

        # Mark in-flight.
        gc.quality_status = "scoring"
        await session.flush()

        unit = (
            await session.get(ModuleUnit, gc.module_unit_id)
            if gc.module_unit_id
            else None
        )
        unit_number = unit.unit_number if unit else None
        unit_title = (
            (unit.title_fr if gc.language == "fr" else unit.title_en) if unit else ""
        )

        # Build cached prefix if not supplied.
        if cached_blocks is None:
            ctx = await self.build_quality_context(course_id, gc.language, session)
            cached_blocks = build_cached_system_blocks(**ctx)

        # Neighbor digest: every other unit's title + brief summary.
        neighbor_digest = await self._build_neighbor_digest(
            course_id=course_id,
            current_content_id=content_id,
            language=gc.language,
            session=session,
        )

        # RAG excerpts relevant to the unit's concepts.
        rag_excerpts = await self._build_rag_excerpts(gc=gc, module=module, session=session)

        user_message = build_auditor_user_message(
            unit_number=unit_number or "?",
            unit_title=unit_title or "",
            content_type=gc.content_type,
            language=gc.language,
            level=gc.level,
            unit_content=gc.content or {},
            sources_cited=gc.sources_cited,
            neighbor_digest=neighbor_digest,
            rag_excerpts=rag_excerpts,
        )

        parsed, usage = await self.claude_service.generate_structured_content_cached(
            system_blocks=cached_blocks,
            user_message=user_message,
            content_type=f"quality_audit_{gc.content_type}",
        )

        if parsed.get("raw_response"):
            logger.error(
                "Auditor returned unparseable JSON",
                content_id=str(content_id),
                run_id=str(run_id) if run_id else None,
            )
            gc.quality_status = "failed"
            await session.flush()
            raise ValueError("Auditor returned unparseable JSON")

        try:
            report = UnitQualityReport.model_validate(parsed)
        except Exception as e:
            gc.quality_status = "failed"
            await session.flush()
            raise ValueError(f"Auditor output failed schema validation: {e}") from e

        # Server-side score recomputation (don't trust the LLM number alone).
        recomputed = compute_weighted_score(report.dimension_scores.model_dump())
        floor_violation = has_critical_floor_violation(report.dimension_scores.model_dump())
        # Use the lower of (LLM-reported, recomputed) for safety.
        final_score = min(int(report.quality_score), recomputed)
        needs_regen = bool(report.needs_regeneration) or final_score < PASSING_SCORE_THRESHOLD or floor_violation

        # Persist into generated_content.
        gc.quality_score = Decimal(final_score)
        gc.quality_flags = [f.model_dump() for f in report.flags]
        gc.quality_assessed_at = datetime.utcnow()
        gc.last_quality_run_id = run_id
        gc.quality_status = (
            "passing" if not needs_regen else "needs_review"
        )

        # Persist the assessment row.
        cost = calculate_cost_cents(usage)
        assessment = UnitQualityAssessment(
            run_id=run_id,
            generated_content_id=content_id,
            attempt_number=attempt_number,
            score=Decimal(final_score),
            dimension_scores=report.dimension_scores.model_dump(),
            flags=[f.model_dump() for f in report.flags],
            model="claude-sonnet-4-6",
            tokens_in=usage.get("input_tokens"),
            tokens_out=usage.get("output_tokens"),
            cache_read_tokens=usage.get("cache_read_input_tokens"),
            cache_write_tokens=usage.get("cache_creation_input_tokens"),
            cost_cents=cost,
        )
        session.add(assessment)
        await session.flush()

        logger.info(
            "Unit assessed",
            content_id=str(content_id),
            run_id=str(run_id) if run_id else None,
            score=final_score,
            needs_regen=needs_regen,
            flag_count=len(report.flags),
            floor_violation=floor_violation,
            cost_cents=cost,
            usage=usage,
        )
        return report, assessment

    # ---- Course sweep -----------------------------------------------

    async def assess_course(
        self,
        course_id: uuid.UUID,
        triggered_by_user_id: uuid.UUID | None,
        session: AsyncSession,
        run_kind: str = "full",
        budget_credits: int | None = None,
        idempotency_key: str | None = None,
    ) -> CourseQualityRun:
        """Create the run row (idempotently). The Celery task picks it
        up and orchestrates the per-unit fan-out + glossary pre-pass.

        Two-step idempotency:
        1. ``(course_id, idempotency_key)`` unique — the same
           idempotency key (e.g. day-bucketed sha) within the same
           course returns the existing run.
        2. ``ux_one_active_run_per_course`` partial unique — even with
           a fresh idempotency key, a second run cannot be queued
           while another is queued/scoring/regenerating.
        """
        if budget_credits is None:
            budget_credits = (
                DEFAULT_BUDGET_FULL if run_kind == "full" else DEFAULT_BUDGET_TARGETED
            )

        # Default key: same course + same user + same UTC day collapses.
        if idempotency_key is None:
            day = datetime.utcnow().strftime("%Y-%m-%d")
            user_part = str(triggered_by_user_id) if triggered_by_user_id else "system"
            key_src = f"{course_id}:{user_part}:{day}:{run_kind}"
            idempotency_key = hashlib.sha256(key_src.encode()).hexdigest()[:64]

        # Try INSERT; on conflict, return the existing row.
        run = CourseQualityRun(
            course_id=course_id,
            run_kind=run_kind,
            status="queued",
            triggered_by_user_id=triggered_by_user_id,
            budget_credits=budget_credits,
            idempotency_key=idempotency_key,
        )
        session.add(run)
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            existing_q = await session.execute(
                select(CourseQualityRun).where(
                    and_(
                        CourseQualityRun.course_id == course_id,
                        CourseQualityRun.idempotency_key == idempotency_key,
                    )
                )
            )
            existing = existing_q.scalar_one_or_none()
            if existing is not None:
                logger.info(
                    "Idempotent run reuse",
                    course_id=str(course_id),
                    run_id=str(existing.id),
                    idempotency_key=idempotency_key,
                )
                return existing
            # Otherwise it must be the partial-unique blocking us.
            active_q = await session.execute(
                select(CourseQualityRun).where(
                    and_(
                        CourseQualityRun.course_id == course_id,
                        CourseQualityRun.status.in_(
                            ["queued", "scoring", "regenerating"]
                        ),
                    )
                )
            )
            active = active_q.scalar_one_or_none()
            if active is not None:
                logger.info(
                    "Active run already in flight",
                    course_id=str(course_id),
                    run_id=str(active.id),
                )
                return active
            raise

        return run

    async def finalize_run(
        self,
        run_id: uuid.UUID,
        session: AsyncSession,
    ) -> CourseQualityRun:
        """Roll up per-unit assessments into the run summary."""
        run = await session.get(CourseQualityRun, run_id)
        if run is None:
            raise ValueError(f"CourseQualityRun {run_id} not found")

        # Aggregate from generated_content for the units linked to this run.
        agg = await session.execute(
            select(
                func.count().label("total"),
                func.count()
                .filter(GeneratedContent.quality_status == "passing")
                .label("passing"),
                func.avg(GeneratedContent.quality_score).label("avg_score"),
            )
            .where(GeneratedContent.last_quality_run_id == run_id)
        )
        row = agg.one()
        total = int(row.total or 0)
        passing = int(row.passing or 0)
        avg = float(row.avg_score) if row.avg_score is not None else None

        run.units_total = total
        run.units_passing = passing
        run.overall_score = Decimal(round(avg, 2)) if avg is not None else None
        run.status = "completed"
        run.finished_at = datetime.utcnow()
        await session.flush()
        logger.info(
            "Run finalized",
            run_id=str(run_id),
            units_total=total,
            units_passing=passing,
            overall_score=avg,
        )
        return run

    # ---- Regeneration loop ------------------------------------------

    async def regenerate_with_constraints(
        self,
        content_id: uuid.UUID,
        constraints: list[str],
        session: AsyncSession,
        triggered_by_user_id: uuid.UUID | None = None,
        trigger: str = "quality_loop",
    ) -> GeneratedContent:
        """Regenerate the unit, threading constraints into the prompt.

        Bounds:
        - Refuses if ``is_manually_edited=True``.
        - Refuses if ``regeneration_attempts >= MAX_REGEN_ATTEMPTS``.
        - Writes a ``GeneratedContentRevision`` pre-image before the
          generator overwrites the row.

        Returns the refreshed ``GeneratedContent`` row.
        """
        gc = await session.get(GeneratedContent, content_id)
        if gc is None:
            raise ValueError(f"GeneratedContent {content_id} not found")

        if gc.is_manually_edited:
            raise PermissionError("Cannot regenerate manually-edited content")
        if gc.regeneration_attempts >= MAX_REGEN_ATTEMPTS:
            logger.info(
                "Skipping regeneration — max attempts reached",
                content_id=str(content_id),
                attempts=gc.regeneration_attempts,
            )
            gc.quality_status = "needs_review_final"
            await session.flush()
            return gc

        # Save pre-image.
        rev = GeneratedContentRevision(
            generated_content_id=gc.id,
            revision=gc.content_revision,
            content=gc.content,
            sources_cited=gc.sources_cited,
            quality_score_before=gc.quality_score,
            quality_flags_before=gc.quality_flags,
            trigger=trigger,
            triggered_by_user_id=triggered_by_user_id,
        )
        session.add(rev)

        gc.quality_status = "regenerating"
        gc.regeneration_attempts = (gc.regeneration_attempts or 0) + 1
        gc.content_revision = (gc.content_revision or 1) + 1
        await session.flush()

        # Resolve unit_id string for the generator API.
        unit = (
            await session.get(ModuleUnit, gc.module_unit_id)
            if gc.module_unit_id
            else None
        )
        unit_id_str = unit.unit_number if unit else gc.content.get("unit_id", "")

        # Dispatch to the right generator service.
        if self.semantic_retriever is None:
            raise RuntimeError(
                "CourseQualityService.regenerate_with_constraints requires a SemanticRetriever"
            )

        if gc.content_type == "lesson":
            from app.domain.services.lesson_service import LessonGenerationService

            svc = LessonGenerationService(self.claude_service, self.semantic_retriever)
            await svc.get_or_generate_lesson(
                module_id=gc.module_id,
                unit_id=unit_id_str,
                language=gc.language,
                country=gc.country_context or "CI",
                level=gc.level,
                session=session,
                force_regenerate=True,
                quality_constraints=constraints,
            )
        elif gc.content_type == "quiz":
            from app.domain.services.quiz_service import QuizService

            svc = QuizService(self.claude_service, self.semantic_retriever)
            await svc.get_or_generate_quiz(
                module_id=gc.module_id,
                unit_id=unit_id_str,
                language=gc.language,
                country=gc.country_context or "CI",
                level=gc.level,
                session=session,
                force_regenerate=True,
                quality_constraints=constraints,
            )
        elif gc.content_type in ("case", "case_study"):
            from app.domain.services.lesson_service import CaseStudyGenerationService

            svc = CaseStudyGenerationService(self.claude_service, self.semantic_retriever)
            await svc.get_or_generate_case_study(
                module_id=gc.module_id,
                unit_id=unit_id_str,
                language=gc.language,
                country=gc.country_context or "CI",
                level=gc.level,
                session=session,
                force_regenerate=True,
                quality_constraints=constraints,
            )
        elif gc.content_type == "flashcard":
            from app.domain.services.flashcard_service import FlashcardGenerationService

            svc = FlashcardGenerationService(self.claude_service, self.semantic_retriever)
            await svc.get_or_generate_flashcard_set(
                module_id=gc.module_id,
                language=gc.language,
                country=gc.country_context or "CI",
                level=gc.level,
                session=session,
                force_regenerate=True,
                quality_constraints=constraints,
            )
        else:
            raise ValueError(f"Unknown content_type for regeneration: {gc.content_type}")

        # Refresh the row from the DB after the generator overwrote it.
        await session.refresh(gc)
        return gc

    async def assess_and_regenerate_loop(
        self,
        content_id: uuid.UUID,
        run_id: uuid.UUID | None,
        session: AsyncSession,
        cached_blocks: list[dict[str, Any]] | None = None,
        triggered_by_user_id: uuid.UUID | None = None,
    ) -> UnitQualityAssessment:
        """Full assess → (regen → reassess)*N loop for a single unit.

        Returns the LAST assessment row. Stop conditions:
        1. Score >= PASSING_SCORE_THRESHOLD.
        2. ``regeneration_attempts >= MAX_REGEN_ATTEMPTS``.
        3. Improvement < MIN_IMPROVEMENT_PER_ATTEMPT (anti-oscillation).
        4. ``is_manually_edited=True`` at any point.
        """
        attempt = 1
        prev_score: int | None = None
        last_report, last_assessment = await self.assess_unit(
            content_id=content_id,
            run_id=run_id,
            session=session,
            attempt_number=attempt,
            cached_blocks=cached_blocks,
        )

        while True:
            current_score = int(last_report.quality_score)
            gc = await session.get(GeneratedContent, content_id)
            if gc is None:
                break
            if gc.is_manually_edited:
                gc.quality_status = "manual_override"
                await session.flush()
                break
            if not last_report.needs_regeneration and current_score >= PASSING_SCORE_THRESHOLD:
                # Pass — we're done.
                break
            if (gc.regeneration_attempts or 0) >= MAX_REGEN_ATTEMPTS:
                gc.quality_status = "needs_review_final"
                await session.flush()
                break
            if (
                prev_score is not None
                and current_score - prev_score < MIN_IMPROVEMENT_PER_ATTEMPT
            ):
                gc.quality_status = "needs_review_final"
                await session.flush()
                logger.info(
                    "Anti-oscillation guard tripped — stopping loop",
                    content_id=str(content_id),
                    prev_score=prev_score,
                    current_score=current_score,
                )
                break

            # Regenerate.
            try:
                await self.regenerate_with_constraints(
                    content_id=content_id,
                    constraints=last_report.regeneration_constraints,
                    session=session,
                    triggered_by_user_id=triggered_by_user_id,
                    trigger="quality_loop",
                )
            except (PermissionError, ValueError) as e:
                logger.warning(
                    "Regeneration aborted",
                    content_id=str(content_id),
                    error=str(e),
                )
                break

            prev_score = current_score
            attempt += 1
            last_report, last_assessment = await self.assess_unit(
                content_id=content_id,
                run_id=run_id,
                session=session,
                attempt_number=attempt,
                cached_blocks=cached_blocks,
            )

        return last_assessment

    # ---- Helpers ----------------------------------------------------

    async def _build_neighbor_digest(
        self,
        course_id: uuid.UUID,
        current_content_id: uuid.UUID,
        language: str,
        session: AsyncSession,
        max_units: int = 30,
    ) -> list[dict[str, str]]:
        """200-token-ish summary per other unit in the course.

        Cheaper than putting full unit texts in context — sufficient
        signal to spot most cross-unit factual contradictions when the
        glossary doesn't catch them already.
        """
        result = await session.execute(
            select(GeneratedContent, ModuleUnit, Module)
            .join(Module, GeneratedContent.module_id == Module.id)
            .join(ModuleUnit, GeneratedContent.module_unit_id == ModuleUnit.id, isouter=True)
            .where(Module.course_id == course_id)
            .where(GeneratedContent.language == language)
            .where(GeneratedContent.id != current_content_id)
            .where(GeneratedContent.content_type.in_(["lesson", "case", "case_study"]))
            .limit(max_units)
        )
        digest: list[dict[str, str]] = []
        for gc, mu, _mod in result.all():
            unit_number = mu.unit_number if mu else ""
            title = (mu.title_fr if language == "fr" else mu.title_en) if mu else ""
            content = gc.content or {}
            # Compose a ~200-token summary: introduction + key_points joined.
            intro = str(content.get("introduction") or "").strip()
            key_pts = content.get("key_points") or []
            kp_text = " | ".join(str(k) for k in key_pts) if isinstance(key_pts, list) else ""
            summary = (intro + " " + kp_text).strip()
            if len(summary) > 800:
                summary = summary[:800] + "…"
            digest.append(
                {
                    "unit_number": unit_number or "",
                    "title": title or "",
                    "summary": summary,
                }
            )
        return digest

    async def _build_rag_excerpts(
        self,
        gc: GeneratedContent,
        module: Module,
        session: AsyncSession,
    ) -> list[dict[str, str]]:
        """Top-k RAG chunks relevant to this unit's content.

        Optional: when no retriever is wired (e.g. unit tests) we
        return an empty list and the auditor flags UNGROUNDED_CLAIM
        for any claim it can't verify.
        """
        if self.semantic_retriever is None:
            return []
        # Build a query from the lesson's title + introduction.
        content = gc.content or {}
        title = content.get("unit_title") or content.get("title") or ""
        intro = str(content.get("introduction") or "")
        query = (str(title) + ". " + intro)[:2000]
        if not query.strip():
            return []
        try:
            results = await self.semantic_retriever.search_for_module(
                query=query,
                user_level=gc.level,
                user_language=gc.language,
                books_sources=getattr(module, "books_sources", None) or {},
                top_k=8,
                session=session,
            )
        except Exception as e:
            logger.warning(
                "RAG retrieval failed in quality auditor — proceeding without excerpts",
                content_id=str(gc.id),
                error=str(e),
            )
            return []
        excerpts: list[dict[str, str]] = []
        for r in results or []:
            chunk = getattr(r, "chunk", r)
            excerpts.append(
                {
                    "source": str(getattr(chunk, "source", "") or ""),
                    "chapter": str(getattr(chunk, "chapter", "") or ""),
                    "page": str(getattr(chunk, "page", "") or ""),
                    "content": str(getattr(chunk, "content", "") or "")[:1500],
                }
            )
        return excerpts


__all__ = [
    "CourseQualityService",
    "PASSING_SCORE_THRESHOLD",
    "MAX_REGEN_ATTEMPTS",
    "MIN_IMPROVEMENT_PER_ATTEMPT",
    "DEFAULT_BUDGET_FULL",
    "DEFAULT_BUDGET_TARGETED",
    "calculate_cost_cents",
    "normalize_term",
]
