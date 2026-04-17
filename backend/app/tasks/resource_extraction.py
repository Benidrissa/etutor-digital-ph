"""Celery task for extracting text from uploaded course resource PDFs."""

import hashlib
import uuid
from pathlib import Path

import structlog

from app.domain.models.course_resource import (
    EXTRACTION_STATUS_DONE,
    EXTRACTION_STATUS_EXTRACTING,
    EXTRACTION_STATUS_FAILED,
)
from app.tasks.celery_app import celery_app

logger = structlog.get_logger(__name__)

UPLOAD_DIR = Path("uploads/course_resources")


@celery_app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 3, "countdown": 30},
    time_limit=600,
    soft_time_limit=540,
    ignore_result=True,
    acks_late=True,
)
def extract_course_resource(self, resource_id: str) -> dict:
    """Extract text from an uploaded course resource PDF and chain indexation.

    Reads the saved file from uploads/course_resources/{course_id}/{filename}.pdf,
    runs PyMuPDF extraction + optional chapter split, updates the CourseResource
    row(s) with the extracted text, then chains index_course_resources if the
    course is in AI-assisted mode and has a rag_collection_id.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.domain.models.course import Course
    from app.domain.models.course_resource import CourseResource
    from app.infrastructure.config.settings import settings

    engine = create_engine(
        settings.database_url_sync, pool_pre_ping=True, pool_size=2, max_overflow=0
    )

    try:
        with Session(engine) as session:
            resource = session.get(CourseResource, uuid.UUID(resource_id))
            if resource is None:
                logger.warning(
                    "extract_course_resource: resource not found",
                    resource_id=resource_id,
                )
                return {"status": "not_found"}

            course = session.get(Course, resource.course_id)
            if course is None:
                logger.warning("extract_course_resource: course not found", resource_id=resource_id)
                return {"status": "not_found"}

            course_id = str(resource.course_id)
            original_filename = resource.filename

            resource.extraction_status = EXTRACTION_STATUS_EXTRACTING
            session.commit()

        logger.info(
            "extract_course_resource: starting",
            resource_id=resource_id,
            course_id=course_id,
            filename=original_filename,
        )

        course_dir = UPLOAD_DIR / course_id
        pdf_path = course_dir / f"{original_filename}.pdf"

        if not pdf_path.exists():
            for candidate in course_dir.glob("*.pdf"):
                if candidate.stem == original_filename:
                    pdf_path = candidate
                    break

        if not pdf_path.exists():
            logger.error(
                "extract_course_resource: PDF file not found on disk",
                resource_id=resource_id,
                path=str(pdf_path),
            )
            with Session(engine) as session:
                res = session.get(CourseResource, uuid.UUID(resource_id))
                if res:
                    res.extraction_status = EXTRACTION_STATUS_FAILED
                    session.commit()
            return {"status": "file_not_found"}

        data = pdf_path.read_bytes()

        from app.domain.services.platform_settings_service import SettingsCache

        cache = SettingsCache.instance()
        max_pdf_chars = int(cache.get("upload-max-pdf-chars") or 2_500_000)

        import fitz

        doc = fitz.open(stream=data, filetype="pdf")
        toc = doc.get_toc()
        pages_text = []
        for page in doc:
            page_text = page.get_text().strip()
            if page_text:
                pages_text.append(page_text)
        doc.close()
        full_text = "\n\n".join(pages_text)
        total_chars = len(full_text)

        new_resource_ids: list[str] = []

        with Session(engine) as session:
            resource = session.get(CourseResource, uuid.UUID(resource_id))
            if resource is None:
                return {"status": "not_found"}

            if total_chars <= max_pdf_chars:
                toc_str = ""
                if toc:
                    toc_lines = [f"{'  ' * (lvl - 1)}{title}" for lvl, title, _ in toc]
                    toc_str = "\n".join(toc_lines[:100])
                    full_text = f"TABLE OF CONTENTS:\n{toc_str}\n\nCONTENT:\n{full_text}"

                resource.raw_text = full_text
                resource.toc_json = toc or None
                resource.char_count = len(full_text)
                resource.content_hash = hashlib.sha256(full_text.encode("utf-8")).hexdigest()
                resource.extraction_status = EXTRACTION_STATUS_DONE
                session.commit()
                new_resource_ids.append(resource_id)

                logger.info(
                    "extract_course_resource: done (single part)",
                    resource_id=resource_id,
                    chars=len(full_text),
                )
            else:
                from app.ai.pdf_summarizer import split_pdf_by_chapters

                parts = split_pdf_by_chapters(full_text, toc, max_pdf_chars)
                parent_stem = resource.filename

                resource.raw_text = parts[0][1] if parts else full_text
                resource.toc_json = toc or None
                resource.char_count = len(resource.raw_text or "")
                resource.content_hash = hashlib.sha256(
                    (resource.raw_text or "").encode("utf-8")
                ).hexdigest()
                resource.filename = f"{parent_stem}_part1"
                resource.parent_filename = parent_stem
                resource.extraction_status = EXTRACTION_STATUS_DONE
                session.commit()
                new_resource_ids.append(resource_id)

                for idx, (_part_title, part_text) in enumerate(parts[1:], start=2):
                    part_filename = f"{parent_stem}_part{idx}"
                    new_res = CourseResource(
                        course_id=resource.course_id,
                        filename=part_filename,
                        parent_filename=parent_stem,
                        raw_text=part_text,
                        toc_json=toc or None,
                        char_count=len(part_text),
                        content_hash=hashlib.sha256(part_text.encode("utf-8")).hexdigest(),
                        extraction_status=EXTRACTION_STATUS_DONE,
                    )
                    session.add(new_res)
                    session.commit()
                    new_resource_ids.append(str(new_res.id))

                logger.info(
                    "extract_course_resource: done (split)",
                    resource_id=resource_id,
                    parts=len(parts),
                    total_chars=total_chars,
                )

        with Session(engine) as session:
            course = session.get(Course, uuid.UUID(course_id))
            if course and course.creation_mode == "ai_assisted" and course.rag_collection_id:
                from celery.result import AsyncResult

                should_index = not course.indexation_task_id or AsyncResult(
                    course.indexation_task_id
                ).state in ("SUCCESS", "FAILURE", "REVOKED")

                if should_index:
                    from app.tasks.rag_indexation import index_course_resources

                    task = index_course_resources.delay(course_id, course.rag_collection_id)
                    course.indexation_task_id = task.id
                    session.commit()
                    logger.info(
                        "extract_course_resource: chained indexation",
                        course_id=course_id,
                        task_id=task.id,
                    )

        return {
            "status": "done",
            "resource_ids": new_resource_ids,
            "course_id": course_id,
        }

    except Exception as exc:
        logger.error(
            "extract_course_resource: failed",
            resource_id=resource_id,
            error=str(exc),
        )
        try:
            with Session(engine) as session:
                res = session.get(CourseResource, uuid.UUID(resource_id))
                if res:
                    res.extraction_status = EXTRACTION_STATUS_FAILED
                    session.commit()
        except Exception as mark_exc:
            logger.warning(
                "extract_course_resource: could not mark failed",
                resource_id=resource_id,
                error=str(mark_exc),
            )
        raise
    finally:
        engine.dispose()
