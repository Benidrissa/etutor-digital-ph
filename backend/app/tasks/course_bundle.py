"""Celery task: generate a flat ZIP bundle of self-contained HTML."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import structlog
from celery import Task

from app.tasks.celery_app import celery_app

logger = structlog.get_logger(__name__)

BUNDLE_SOFT_LIMIT = 1800  # 30 min
BUNDLE_HARD_LIMIT = 1860  # 31 min


class BundleCallbackTask(Task):
    def on_success(self, retval, task_id, args, kwargs):
        logger.info("bundle_task.completed", task_id=task_id, result=retval)

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        logger.error(
            "bundle_task.failed",
            task_id=task_id,
            exception=str(exc),
            traceback=einfo.traceback if einfo else None,
        )


def _make_session_factory(settings):
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    engine = create_async_engine(settings.database_url, echo=False, pool_size=3, max_overflow=1)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, factory


async def _mark_bundle_failed(bundle_id: str, error_msg: str, settings) -> None:
    """Best-effort status update on unhandled task failure."""
    from app.domain.models.course_bundle import CourseBundle

    engine, sf = _make_session_factory(settings)
    try:
        async with sf() as s:
            b = await s.get(CourseBundle, uuid.UUID(bundle_id))
            if b and b.status not in ("ready",):
                b.status = "failed"
                b.error_message = error_msg[:500]
                await s.commit()
    finally:
        await engine.dispose()


@celery_app.task(
    bind=True,
    base=BundleCallbackTask,
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 2, "countdown": 30},
    soft_time_limit=BUNDLE_SOFT_LIMIT,
    time_limit=BUNDLE_HARD_LIMIT,
    rate_limit="3/m",
)
def generate_course_bundle_task(self, bundle_id: str) -> dict:
    """Generate a flat ZIP of self-contained HTML for every course unit.

    Triggered by POST /admin/courses/{course_id}/bundle.  Updates the
    CourseBundle row with progress, uploads ZIP to MinIO, marks ready.
    """

    async def _run() -> dict:
        from sqlalchemy import select as sa_select
        from sqlalchemy.orm import selectinload

        from app.ai.claude_service import ClaudeService
        from app.ai.rag.retriever import SemanticRetriever
        from app.domain.models.course import Course
        from app.domain.models.course_bundle import CourseBundle
        from app.domain.models.module import Module
        from app.domain.services.bundle_service import BundleService
        from app.domain.services.flashcard_service import (
            FlashcardGenerationService,
        )
        from app.domain.services.lesson_service import (
            CaseStudyGenerationService,
            LessonGenerationService,
        )
        from app.domain.services.quiz_service import QuizService
        from app.infrastructure.config.settings import settings
        from app.infrastructure.storage.s3 import S3StorageService

        engine, session_factory = _make_session_factory(settings)
        try:
            async with session_factory() as session:
                bundle = await session.get(CourseBundle, uuid.UUID(bundle_id))
                if bundle is None:
                    logger.error(
                        "bundle_task.bundle_not_found",
                        bundle_id=bundle_id,
                    )
                    return {"status": "failed", "error": "bundle not found"}

                bundle.status = "generating"
                await session.commit()

                result = await session.execute(
                    sa_select(Course)
                    .where(Course.id == bundle.course_id)
                    .options(selectinload(Course.modules).selectinload(Module.units))
                )
                course = result.scalar_one_or_none()
                if course is None:
                    bundle.status = "failed"
                    bundle.error_message = "Course not found"
                    await session.commit()
                    return {
                        "status": "failed",
                        "error": "course not found",
                    }

                claude = ClaudeService()
                retriever = SemanticRetriever()
                lesson_svc = LessonGenerationService(claude, retriever)
                case_svc = CaseStudyGenerationService(claude, retriever)
                quiz_svc = QuizService(claude, retriever)
                flashcard_svc = FlashcardGenerationService(claude, retriever)
                bundle_svc = BundleService()
                storage = S3StorageService()  # noqa: F841 — used by svc

                lang = bundle.language
                level = bundle.level
                country = bundle.country
                course_title = course.title_fr if lang == "fr" else course.title_en

                sorted_modules = sorted(course.modules, key=lambda m: m.module_number)
                zip_files: list[tuple[str, bytes]] = []
                errors: list[str] = []
                total_units = sum(len(m.units) for m in sorted_modules)
                done = 0

                for mod in sorted_modules:
                    mod_title = mod.title_fr if lang == "fr" else mod.title_en
                    mn = mod.module_number

                    # Module-level flashcards
                    try:
                        fc_resp = await flashcard_svc.get_or_generate_flashcard_set(
                            module_id=mod.id,
                            language=lang,
                            country=country,
                            level=level,
                            session=session,
                        )
                        fc_html = await bundle_svc.render_flashcards(
                            module_title=mod_title,
                            course_title=course_title,
                            lang=lang,
                            level=level,
                            flashcards=fc_resp.flashcards,
                        )
                        zip_files.append(
                            (
                                f"{mn:03d}_00_flashcards_{lang}.html",
                                fc_html.encode(),
                            )
                        )
                    except Exception as exc:
                        err = f"Module {mn} flashcards: {exc}"
                        errors.append(err)
                        logger.warning("bundle_task.flashcard_failed", error=err)

                    sorted_units = sorted(mod.units, key=lambda u: u.order_index)
                    for unit in sorted_units:
                        un = unit.unit_number
                        unit_title = unit.title_fr if lang == "fr" else unit.title_en
                        unit_type = (unit.unit_type or "lesson").lower()

                        done += 1
                        self.update_state(
                            state="PROGRESS",
                            meta={
                                "progress": int(done * 100 / max(total_units, 1)),
                                "current_file": f"{mn}.{un}",
                            },
                        )

                        # Lesson — generated for all units
                        try:
                            lesson_resp = await lesson_svc.get_or_generate_lesson(
                                module_id=mod.id,
                                unit_id=un,
                                language=lang,
                                country=country,
                                level=level,
                                session=session,
                            )
                            lesson_html = await bundle_svc.render_lesson(
                                resp=lesson_resp,
                                module_title=mod_title,
                                unit_title=unit_title,
                                course_title=course_title,
                                session=session,
                            )
                            zip_files.append(
                                (
                                    f"{mn:03d}_{un}_lesson_{lang}.html",
                                    lesson_html.encode(),
                                )
                            )
                        except Exception as exc:
                            err = f"Module {mn} unit {un} lesson: {exc}"
                            errors.append(err)
                            logger.warning("bundle_task.lesson_failed", error=err)

                        # Quiz — only for quiz-typed units
                        if unit_type == "quiz":
                            try:
                                quiz_resp = await quiz_svc.get_or_generate_quiz(
                                    module_id=mod.id,
                                    unit_id=un,
                                    language=lang,
                                    country=country,
                                    level=level,
                                    num_questions=10,
                                    session=session,
                                )
                                quiz_html = await bundle_svc.render_quiz(
                                    resp=quiz_resp,
                                    module_title=mod_title,
                                    unit_title=unit_title,
                                    course_title=course_title,
                                    session=session,
                                )
                                zip_files.append(
                                    (
                                        f"{mn:03d}_{un}_quiz_{lang}.html",
                                        quiz_html.encode(),
                                    )
                                )
                            except Exception as exc:
                                err = f"Module {mn} unit {un} quiz: {exc}"
                                errors.append(err)
                                logger.warning("bundle_task.quiz_failed", error=err)

                        # Case study — only for case-typed units
                        if unit_type in ("case", "case_study"):
                            try:
                                case_resp = await case_svc.get_or_generate_case_study(
                                    module_id=mod.id,
                                    unit_id=un,
                                    language=lang,
                                    country=country,
                                    level=level,
                                    session=session,
                                )
                                case_html = await bundle_svc.render_case_study(
                                    resp=case_resp,
                                    module_title=mod_title,
                                    unit_title=unit_title,
                                    course_title=course_title,
                                    session=session,
                                )
                                zip_files.append(
                                    (
                                        f"{mn:03d}_{un}_case_{lang}.html",
                                        case_html.encode(),
                                    )
                                )
                            except Exception as exc:
                                err = f"Module {mn} unit {un} case: {exc}"
                                errors.append(err)
                                logger.warning("bundle_task.case_failed", error=err)

                if not zip_files:
                    bundle.status = "failed"
                    bundle.error_message = "No content could be generated"
                    await session.commit()
                    return {
                        "status": "failed",
                        "error": "no content generated",
                    }

                self.update_state(
                    state="PROGRESS",
                    meta={"progress": 99, "current_file": "zipping"},
                )
                zip_bytes = bundle_svc.build_zip(zip_files)
                key = f"bundles/{bundle.course_id}/{bundle_id}/{lang}.zip"
                url = await storage.upload_bytes(key, zip_bytes, "application/zip")

                bundle.status = "ready"
                bundle.storage_key = key
                bundle.storage_url = url
                bundle.file_size_bytes = len(zip_bytes)
                bundle.file_count = len(zip_files)
                bundle.completed_at = datetime.now(UTC)
                if errors:
                    bundle.error_message = f"{len(errors)} unit(s) failed: " + "; ".join(errors[:3])
                await session.commit()

                logger.info(
                    "bundle_task.done",
                    bundle_id=bundle_id,
                    files=len(zip_files),
                    size_bytes=len(zip_bytes),
                    errors=len(errors),
                )
                return {
                    "status": "ready",
                    "bundle_id": bundle_id,
                    "file_count": len(zip_files),
                    "size_bytes": len(zip_bytes),
                }
        finally:
            await engine.dispose()

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.error(
            "bundle_task.exception",
            bundle_id=bundle_id,
            error=str(exc),
        )
        import contextlib

        from app.infrastructure.config.settings import settings

        with contextlib.suppress(Exception):
            asyncio.run(_mark_bundle_failed(bundle_id, str(exc), settings))
        raise
