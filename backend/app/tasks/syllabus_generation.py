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
        from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
        from sqlalchemy.orm import sessionmaker

        from app.domain.models.course import Course
        from app.domain.models.module import Module
        from app.domain.services.course_agent_service import CourseAgentService
        from app.infrastructure.config.settings import settings

        engine = create_async_engine(settings.database_url, echo=False)
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

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

            cats = course.taxonomy_categories or []

            self.update_state(
                state="GENERATING",
                meta={"step": "calling_claude", "progress": 20, "modules_count": 0},
            )

            agent = CourseAgentService()
            module_dicts = await agent.generate_course_structure(
                title_fr=course.title_fr,
                title_en=course.title_en,
                course_domain=[tc.slug for tc in cats if tc.type == "domain"],
                course_level=[tc.slug for tc in cats if tc.type == "level"],
                audience_type=[tc.slug for tc in cats if tc.type == "audience"],
                estimated_hours=estimated_hours or course.estimated_hours,
            )

            self.update_state(
                state="SAVING",
                meta={
                    "step": "saving",
                    "progress": 80,
                    "modules_count": len(module_dicts),
                },
            )

            await session.execute(delete(Module).where(Module.course_id == uuid.UUID(course_id)))
            await session.flush()

            saved_modules = []
            for i, m in enumerate(module_dicts):
                module = Module(
                    id=uuid.uuid4(),
                    module_number=i + 1,
                    level=1,
                    title_fr=m["title_fr"],
                    title_en=m["title_en"],
                    description_fr=m.get("description_fr"),
                    description_en=m.get("description_en"),
                    estimated_hours=m.get("estimated_hours", 20),
                    bloom_level=m.get("bloom_level"),
                    course_id=uuid.UUID(course_id),
                )
                session.add(module)
                saved_modules.append(
                    {
                        "id": str(module.id),
                        "module_number": module.module_number,
                        "title_fr": module.title_fr,
                        "title_en": module.title_en,
                    }
                )

            course.module_count = len(module_dicts)
            await session.commit()

            logger.info(
                "Syllabus generated and saved",
                course_id=course_id,
                module_count=len(saved_modules),
            )

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
