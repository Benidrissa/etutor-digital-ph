"""Celery task for syllabus generation — generates course module structure via Claude API."""

import asyncio
import hashlib
import uuid

import structlog
from celery import Task
from sqlalchemy import delete, select, text

from app.tasks.celery_app import celery_app

logger = structlog.get_logger(__name__)


class SyllabusTask(Task):
    """Base task for syllabus generation with progress tracking."""

    def on_success(self, retval, task_id, args, kwargs):
        logger.info("Syllabus generation completed", task_id=task_id, result=retval)

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        logger.error("Syllabus generation failed", task_id=task_id, exception=str(exc))
        # Reset creation_step so the user can retry
        try:
            course_id = args[0] if args else kwargs.get("course_id")
            if course_id:
                from sqlalchemy import create_engine, text
                from sqlalchemy.orm import Session

                from app.infrastructure.config.settings import settings

                engine = create_engine(settings.database_url_sync, pool_pre_ping=True)
                with Session(engine) as session:
                    session.execute(
                        text(
                            "UPDATE courses SET creation_step = 'info'"
                            " WHERE id = :cid AND creation_step = 'generating'"
                        ),
                        {"cid": course_id},
                    )
                    session.commit()
                engine.dispose()
        except Exception as reset_exc:
            logger.warning("Failed to reset creation_step", error=str(reset_exc))


@celery_app.task(
    bind=True,
    base=SyllabusTask,
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 1, "countdown": 30},
    time_limit=3600,  # 60 min hard limit
    soft_time_limit=2700,  # 45 min soft limit
    ignore_result=True,
)
def generate_course_syllabus(
    self, course_id: str, estimated_hours: int, cached_resource_text: str | None = None
) -> dict:
    """Generate course module structure using Claude API and save to DB.

    Fix for SoftTimeLimitExceeded (issue #876):
    - Phase 1 (read course) and Phase 2 (Claude API) use asyncio.run() with a
      fresh async engine — this is safe because the engine is created inside
      the coroutine, after the fork, so no stale asyncpg pool is inherited.
    - Phase 3 (DB save) uses the sync SQLAlchemy engine obtained from
      engine.sync_engine to avoid any asyncio event loop conflict during commit.
    """
    from app.domain.services.platform_settings_service import SettingsCache
    from app.infrastructure.config.settings import settings

    cache = SettingsCache.instance()
    context_budget = cache.get("syllabus-context-budget-chars", 3_500_000)
    summarizer_model = cache.get("syllabus-summarizer-model", "claude-sonnet-4-6")
    summary_max_tokens = cache.get("syllabus-summary-max-output-tokens", 30_000)

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

    # ── Phase 1.5: Load resources from DB (pre-extracted at upload time) ──────
    from pathlib import Path

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    course_dir = Path("uploads/course_resources") / course_id
    pdf_full_texts: list[tuple[str, str, list]] = []

    if cached_resource_text is not None:
        resource_text = cached_resource_text
        logger.info(
            "Using cached syllabus_context — skipping PDF extraction",
            course_id=course_id,
            chars=len(resource_text),
        )
    else:
        self.update_state(
            state="GENERATING",
            meta={"step": "loading_resources", "progress": 15, "modules_count": 0},
        )
        resource_text = None

    if cached_resource_text is None:
        from app.domain.models.course_resource import CourseResource
        from app.infrastructure.config.settings import settings as _settings

        _resources_for_summarization: list[CourseResource] = []
        _sync_engine = create_engine(
            _settings.database_url_sync,
            pool_pre_ping=True,
            pool_size=2,
            max_overflow=0,
        )
        try:
            with Session(_sync_engine) as _session:
                existing_resources = (
                    _session.execute(
                        select(CourseResource).where(
                            CourseResource.course_id == uuid.UUID(course_id)
                        )
                    )
                    .scalars()
                    .all()
                )
        finally:
            _sync_engine.dispose()

        if existing_resources:
            logger.info(
                "Loading pre-extracted text from DB",
                course_id=course_id,
                resource_count=len(existing_resources),
            )
            for res in existing_resources:
                if res.raw_text:
                    pdf_full_texts.append(
                        (res.filename.replace("_", " "), res.raw_text, res.toc_json or [])
                    )
            _resources_for_summarization = list(existing_resources)

        elif course_dir.exists():
            import fitz  # PyMuPDF

            _new_resources: list[CourseResource] = []
            pdf_files = sorted(course_dir.glob("*.pdf"))
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
                    _new_resources.append(
                        CourseResource(
                            course_id=uuid.UUID(course_id),
                            filename=pdf_path.stem,
                            raw_text=full_text,
                            toc_json=toc or None,
                            char_count=len(full_text),
                            content_hash=hashlib.sha256(full_text.encode("utf-8")).hexdigest(),
                        )
                    )
                    logger.info(
                        "Extracted PDF text (fallback)",
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

            if _new_resources:
                _save_engine = create_engine(
                    _settings.database_url_sync,
                    pool_pre_ping=True,
                    pool_size=2,
                    max_overflow=0,
                )
                try:
                    with Session(_save_engine) as _save_session:
                        for res in _new_resources:
                            _save_session.add(res)
                        _save_session.commit()
                    logger.info(
                        "Saved fallback-extracted PDF text to DB",
                        course_id=course_id,
                        count=len(_new_resources),
                    )
                except Exception as save_exc:
                    logger.warning(
                        "Failed to persist extracted PDF text to DB (non-blocking)",
                        course_id=course_id,
                        error=str(save_exc),
                    )
                finally:
                    _save_engine.dispose()
                _resources_for_summarization = _new_resources
            else:
                _resources_for_summarization = []

        if pdf_full_texts:
            total_chars = sum(len(txt) for _, txt, _ in pdf_full_texts)

            if total_chars <= context_budget:
                logger.info(
                    "Resources fit within context budget — using raw text directly",
                    course_id=course_id,
                    total_chars=total_chars,
                    budget=context_budget,
                    resource_count=len(pdf_full_texts),
                )
                pdf_sections = [f"### {name}\n{txt}" for name, txt, _toc in pdf_full_texts]
                resource_text = "\n\n---\n\n".join(pdf_sections)
            else:
                logger.info(
                    "Resources exceed context budget — 1-call-per-resource summarization",
                    course_id=course_id,
                    total_chars=total_chars,
                    budget=context_budget,
                    resource_count=len(pdf_full_texts),
                )
                self.update_state(
                    state="GENERATING",
                    meta={"step": "summarizing_pdfs", "progress": 20, "modules_count": 0},
                )
                from app.ai.pdf_summarizer import summarize_pdfs_sync

                _needs_summarization: list[tuple[int, tuple[str, str, list]]] = []
                _cached_summaries: dict[int, str] = {}

                _lookup_engine = create_engine(
                    _settings.database_url_sync,
                    pool_pre_ping=True,
                    pool_size=2,
                    max_overflow=0,
                )
                try:
                    with Session(_lookup_engine) as _lookup_session:
                        for idx, (resource, pdf_entry) in enumerate(
                            zip(_resources_for_summarization, pdf_full_texts, strict=False)
                        ):
                            if resource.summary_text:
                                _cached_summaries[idx] = resource.summary_text
                                logger.info(
                                    "Reused existing summary for resource",
                                    filename=resource.filename,
                                )
                                continue
                            if resource.content_hash:
                                existing = _lookup_session.execute(
                                    select(CourseResource)
                                    .where(
                                        CourseResource.content_hash == resource.content_hash,
                                        CourseResource.summary_text.isnot(None),
                                        CourseResource.id != resource.id,
                                    )
                                    .limit(1)
                                ).scalar_one_or_none()
                                if existing:
                                    resource.summary_text = existing.summary_text
                                    resource.summary_model = existing.summary_model
                                    _cached_summaries[idx] = existing.summary_text
                                    logger.info(
                                        "Reused summary from another course",
                                        filename=resource.filename,
                                        source_course_id=str(existing.course_id),
                                    )
                                    continue
                            _needs_summarization.append((idx, pdf_entry))
                finally:
                    _lookup_engine.dispose()

                if _needs_summarization:
                    _new_summaries = summarize_pdfs_sync(
                        [entry for _, entry in _needs_summarization],
                        model=summarizer_model,
                        summary_max_output_tokens=summary_max_tokens,
                    )
                    _persist_engine = create_engine(
                        _settings.database_url_sync,
                        pool_pre_ping=True,
                        pool_size=2,
                        max_overflow=0,
                    )
                    try:
                        with Session(_persist_engine) as _persist_session:
                            for (orig_idx, _pdf_entry), summary in zip(
                                _needs_summarization, _new_summaries, strict=True
                            ):
                                _cached_summaries[orig_idx] = summary
                                if orig_idx < len(_resources_for_summarization):
                                    res = _resources_for_summarization[orig_idx]
                                    res.summary_text = summary
                                    res.summary_model = summarizer_model
                                    _persist_session.merge(res)
                            _persist_session.commit()
                    except Exception as persist_exc:
                        logger.warning(
                            "Failed to persist summaries to DB (non-blocking)",
                            course_id=course_id,
                            error=str(persist_exc),
                        )
                    finally:
                        _persist_engine.dispose()

                pdf_summaries = [_cached_summaries.get(i, "") for i in range(len(pdf_full_texts))]
                pdf_sections = [
                    f"### {name}\n{summary}"
                    for (name, _text, _toc), summary in zip(
                        pdf_full_texts, pdf_summaries, strict=True
                    )
                ]
                resource_text = "\n\n---\n\n".join(pdf_sections)

            logger.info(
                "Resource text prepared for syllabus context",
                course_id=course_id,
                resource_count=len(pdf_full_texts),
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
    elif pdf_full_texts:
        books_sources = {name: [] for name, _txt, _toc in pdf_full_texts}
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
            session.execute(
                delete(ModuleUnit).where(
                    ModuleUnit.module_id.in_(
                        select(Module.id).where(Module.course_id == uuid.UUID(course_id))
                    )
                )
            )
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

            update_sql = (
                "UPDATE courses SET module_count = :mc, syllabus_json = :sj,"
                " creation_step = 'generated'"
            )
            params: dict = {
                "mc": len(module_dicts),
                "sj": json.dumps(module_dicts),
                "cid": course_id,
            }
            if cached_resource_text is None and resource_text is not None:
                update_sql += ", syllabus_context = :ctx"
                params["ctx"] = resource_text
            update_sql += " WHERE id = :cid"
            session.execute(text(update_sql), params)

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
