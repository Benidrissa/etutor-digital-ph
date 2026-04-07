"""Celery task for syllabus generation — generates course module structure via Claude API."""

import asyncio
import uuid

import structlog
from celery import Task
from sqlalchemy import delete, select, text

from app.tasks.celery_app import celery_app

_CONTEXT_BUDGET_CHARS = 200_000

logger = structlog.get_logger(__name__)


class SyllabusTask(Task):
    """Base task for syllabus generation with progress tracking."""

    def on_success(self, retval, task_id, args, kwargs):
        logger.info("Syllabus generation completed", task_id=task_id, result=retval)

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        logger.error("Syllabus generation failed", task_id=task_id, exception=str(exc))


@celery_app.task(
    bind=True,
    base=SyllabusTask,
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 1, "countdown": 30},
    time_limit=600,  # 10 min hard limit
    soft_time_limit=540,  # 9 min soft limit
)
def generate_course_syllabus(self, course_id: str, estimated_hours: int) -> dict:
    """Generate course module structure using Claude API and save to DB.

    Fix for SoftTimeLimitExceeded (issue #876):
    - Phase 1 (read course) and Phase 2 (Claude API) use asyncio.run() with a
      fresh async engine — this is safe because the engine is created inside
      the coroutine, after the fork, so no stale asyncpg pool is inherited.
    - Phase 3 (DB save) uses the sync SQLAlchemy engine obtained from
      engine.sync_engine to avoid any asyncio event loop conflict during commit.
    """
    from app.infrastructure.config.settings import settings

    logger.info(
        "Starting syllabus generation",
        task_id=self.request.id,
        course_id=course_id,
        estimated_hours=estimated_hours,
    )

    self.update_state(
        state="GENERATING",
        meta={"step": "generating", "progress": 10, "modules_count": 0},
    )

    # ── Phase 1: Read course metadata via async engine ─────────────────────
    from app.domain.models.course import Course

    async def _fetch_course():
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

        engine = create_async_engine(settings.database_url, echo=False, pool_size=2, max_overflow=0)
        try:
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as session:
                result = await session.execute(
                    select(Course).where(Course.id == uuid.UUID(course_id))
                )
                course = result.scalar_one_or_none()
                if not course:
                    return None
                cats = list(course.taxonomy_categories or [])
                return {
                    "title_fr": course.title_fr,
                    "title_en": course.title_en,
                    "course_hours": course.estimated_hours,
                    "rag_collection_id": course.rag_collection_id,
                    "domain_slugs": [tc.slug for tc in cats if tc.type == "domain"],
                    "level_slugs": [tc.slug for tc in cats if tc.type == "level"],
                    "audience_slugs": [tc.slug for tc in cats if tc.type == "audience"],
                }
        finally:
            await engine.dispose()

    course_data = asyncio.run(_fetch_course())
    if not course_data:
        return {
            "status": "failed",
            "error": f"Course not found: {course_id}",
            "modules_count": 0,
            "modules": [],
        }

    title_fr = course_data["title_fr"]
    title_en = course_data["title_en"]
    course_hours = course_data["course_hours"]
    rag_collection_id = course_data["rag_collection_id"]
    domain_slugs = course_data["domain_slugs"]
    level_slugs = course_data["level_slugs"]
    audience_slugs = course_data["audience_slugs"]

    # ── Phase 1.5: Extract text from uploaded PDFs ──────────────────────────
    self.update_state(
        state="GENERATING",
        meta={"step": "extracting_pdf_text", "progress": 15, "modules_count": 0},
    )

    resource_text = None
    from pathlib import Path

    course_dir = Path("uploads/course_resources") / course_id
    if course_dir.exists():
        import fitz  # PyMuPDF

        pdf_files = sorted(course_dir.glob("*.pdf"))

        pdf_full_texts = []
        for pdf_path in pdf_files:
            try:
                doc = fitz.open(str(pdf_path))
                book_name = pdf_path.stem.replace("_", " ")
                toc = doc.get_toc()
                pages_text = []
                for page in doc:
                    page_text = page.get_text().strip()
                    if page_text:
                        pages_text.append(page_text)
                doc.close()
                full_text = "\n\n".join(pages_text)
                if toc:
                    toc_lines = [f"{'  ' * (lvl - 1)}{title}" for lvl, title, _ in toc]
                    toc_str = "\n".join(toc_lines[:100])
                    full_text = f"TABLE OF CONTENTS:\n{toc_str}\n\nCONTENT:\n{full_text}"
                pdf_full_texts.append((book_name, full_text, toc))
                logger.info(
                    "Extracted PDF text",
                    pdf=book_name,
                    pages=len(pages_text),
                    chars=len(full_text),
                    has_toc=bool(toc),
                )
            except Exception as e:
                logger.warning(
                    "Failed to extract PDF text",
                    pdf=str(pdf_path),
                    error=str(e),
                )

        if pdf_full_texts:
            total_chars = sum(len(txt) for _, txt, _ in pdf_full_texts)

            if total_chars <= _CONTEXT_BUDGET_CHARS:
                logger.info(
                    "PDFs fit within context budget — using raw text",
                    course_id=course_id,
                    total_chars=total_chars,
                    budget=_CONTEXT_BUDGET_CHARS,
                )
                pdf_sections = [
                    f"### {name}\n{txt[:50000]}" for name, txt, _toc in pdf_full_texts
                ]
                resource_text = "\n\n---\n\n".join(pdf_sections)
            else:
                logger.info(
                    "PDFs exceed context budget — using multi-pass summarization",
                    course_id=course_id,
                    total_chars=total_chars,
                    budget=_CONTEXT_BUDGET_CHARS,
                )
                self.update_state(
                    state="GENERATING",
                    meta={"step": "summarizing_pdfs", "progress": 20, "modules_count": 0},
                )
                from app.ai.pdf_summarizer import summarize_pdfs_sync

                pdf_summaries = summarize_pdfs_sync(pdf_full_texts)
                pdf_sections = [
                    f"### {name}\n{summary}"
                    for (name, _text, _toc), summary in zip(
                        pdf_full_texts, pdf_summaries, strict=True
                    )
                ]
                resource_text = "\n\n---\n\n".join(pdf_sections)

            logger.info(
                "PDF text prepared for syllabus context",
                course_id=course_id,
                pdf_count=len(pdf_sections),
                total_chars=len(resource_text),
            )

    # ── Phase 2: Call Claude API (async, fresh event loop) ──────────────────
    self.update_state(
        state="GENERATING",
        meta={"step": "calling_claude", "progress": 25, "modules_count": 0},
    )

    async def _call_claude():
        from app.domain.services.course_agent_service import CourseAgentService

        agent = CourseAgentService()
        return await agent.generate_course_structure(
            title_fr=title_fr,
            title_en=title_en,
            course_domain=domain_slugs,
            course_level=level_slugs,
            audience_type=audience_slugs,
            estimated_hours=estimated_hours or course_hours,
            resource_text=resource_text,
        )

    module_dicts = asyncio.run(_call_claude())

    self.update_state(
        state="SAVING",
        meta={
            "step": "saving",
            "progress": 80,
            "modules_count": len(module_dicts),
        },
    )

    # ── Phase 3: Save modules + units using SYNC SQLAlchemy ────────────────
    # We avoid asyncio.run() here entirely to prevent fork-inherited asyncpg
    # connection pool conflicts that cause session.commit() to deadlock.
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.domain.models.module import Module
    from app.domain.models.module_unit import ModuleUnit

    books_sources: dict | None
    if course_dir.exists():
        pdf_names = [f.stem.replace("_", " ") for f in course_dir.glob("*.pdf")]
        books_sources = {name: [] for name in pdf_names}
    elif rag_collection_id:
        books_sources = {rag_collection_id: []}
    else:
        books_sources = None

    sync_engine = create_engine(
        settings.database_url_sync,
        pool_pre_ping=True,
        pool_size=2,
        max_overflow=0,
    )
    try:
        with Session(sync_engine) as session:
            session.execute(delete(Module).where(Module.course_id == uuid.UUID(course_id)))

            saved_modules = []
            for i, m in enumerate(module_dicts):
                module_id = uuid.uuid4()
                module = Module(
                    id=module_id,
                    module_number=i + 1,
                    level=1,
                    title_fr=m["title_fr"],
                    title_en=m["title_en"],
                    description_fr=m.get("description_fr"),
                    description_en=m.get("description_en"),
                    estimated_hours=m.get("estimated_hours", 20),
                    bloom_level=m.get("bloom_level"),
                    course_id=uuid.UUID(course_id),
                    books_sources=books_sources,
                )
                session.add(module)

                for j, u in enumerate(m.get("units", [])):
                    unit = ModuleUnit(
                        id=uuid.uuid4(),
                        module_id=module_id,
                        unit_number=f"{i + 1}.{j + 1}",
                        title_fr=u.get("title_fr", f"Unité {j + 1}"),
                        title_en=u.get("title_en", f"Unit {j + 1}"),
                        description_fr=u.get("description_fr"),
                        description_en=u.get("description_en"),
                        estimated_minutes=15,
                        order_index=j,
                    )
                    session.add(unit)

                saved_modules.append(
                    {
                        "id": str(module_id),
                        "module_number": i + 1,
                        "title_fr": m["title_fr"],
                        "title_en": m["title_en"],
                        "units_count": len(m.get("units", [])),
                    }
                )

            import json

            session.execute(
                text("UPDATE courses SET module_count = :mc, syllabus_json = :sj WHERE id = :cid"),
                {
                    "mc": len(module_dicts),
                    "sj": json.dumps(module_dicts),
                    "cid": course_id,
                },
            )

            session.commit()

            logger.info(
                "Syllabus generated and saved",
                course_id=course_id,
                module_count=len(saved_modules),
            )
    finally:
        sync_engine.dispose()

    self.update_state(
        state="COMPLETE",
        meta={
            "step": "complete",
            "progress": 100,
            "modules_count": len(saved_modules),
        },
    )

    return {
        "status": "complete",
        "modules_count": len(saved_modules),
        "modules": saved_modules,
    }
