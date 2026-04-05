"""Celery task for syllabus generation — generates course module structure via Claude API."""

import asyncio
import uuid

import structlog
from celery import Task
from sqlalchemy import delete, select

from app.tasks.celery_app import celery_app

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

    This runs synchronously in a Celery worker. We use asyncio.run()
    to call the async service and DB operations from the sync Celery context.
    """
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

    async def _run_generation():
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

        from app.domain.models.course import Course
        from app.domain.models.module import Module
        from app.domain.models.module_unit import ModuleUnit
        from app.domain.services.course_agent_service import CourseAgentService
        from app.infrastructure.config.settings import settings

        engine = create_async_engine(
            settings.database_url, echo=False, pool_size=5, max_overflow=2
        )
        async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        # Phase 1: Read course metadata in its own session
        async with async_session() as session:
            result = await session.execute(select(Course).where(Course.id == uuid.UUID(course_id)))
            course = result.scalar_one_or_none()
            if not course:
                return {
                    "status": "failed",
                    "error": f"Course not found: {course_id}",
                    "modules_count": 0,
                    "modules": [],
                }

            # Cache values before closing session
            title_fr = course.title_fr
            title_en = course.title_en
            course_hours = course.estimated_hours
            rag_collection_id = course.rag_collection_id
            cats = list(course.taxonomy_categories or [])
            domain_slugs = [tc.slug for tc in cats if tc.type == "domain"]
            level_slugs = [tc.slug for tc in cats if tc.type == "level"]
            audience_slugs = [tc.slug for tc in cats if tc.type == "audience"]

        # Phase 2: Call Claude API (no DB session needed)
        self.update_state(
            state="GENERATING",
            meta={"step": "calling_claude", "progress": 20, "modules_count": 0},
        )

        agent = CourseAgentService()
        module_dicts = await agent.generate_course_structure(
            title_fr=title_fr,
            title_en=title_en,
            course_domain=domain_slugs,
            course_level=level_slugs,
            audience_type=audience_slugs,
            estimated_hours=estimated_hours or course_hours,
        )

        self.update_state(
            state="SAVING",
            meta={
                "step": "saving",
                "progress": 80,
                "modules_count": len(module_dicts),
            },
        )

        # Build books_sources from uploaded PDF filenames
        from pathlib import Path

        course_dir = Path("uploads/course_resources") / course_id
        if course_dir.exists():
            pdf_names = [f.stem.replace("_", " ") for f in course_dir.glob("*.pdf")]
            books_sources = {name: [] for name in pdf_names}
        elif rag_collection_id:
            books_sources = {rag_collection_id: []}
        else:
            books_sources = None

        # Phase 3: Save modules + units in a clean session
        async with async_session() as session:
            await session.execute(delete(Module).where(Module.course_id == uuid.UUID(course_id)))

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

                # Save units from AI response
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

            # Update course metadata via raw SQL to avoid selectin loading
            import json

            from sqlalchemy import text

            await session.execute(
                text("UPDATE courses SET module_count = :mc, syllabus_json = :sj WHERE id = :cid"),
                {
                    "mc": len(module_dicts),
                    "sj": json.dumps(module_dicts),
                    "cid": course_id,
                },
            )

            await session.commit()

            logger.info(
                "Syllabus generated and saved",
                course_id=course_id,
                module_count=len(saved_modules),
            )

        await engine.dispose()

        return {
            "status": "complete",
            "modules_count": len(saved_modules),
            "modules": saved_modules,
        }

    try:
        result = asyncio.run(_run_generation())

        self.update_state(
            state="COMPLETE",
            meta={
                "step": "complete",
                "progress": 100,
                "modules_count": result.get("modules_count", 0),
            },
        )

        return result

    except Exception as exc:
        logger.error(
            "Syllabus generation failed",
            course_id=course_id,
            error=str(exc),
        )
        raise
