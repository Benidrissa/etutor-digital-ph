"""Shared course management logic for admin and expert contexts.

Admin context: no ownership checks, no credit deduction.
Expert context: adds ownership validation and optional credit deduction via CostTracker.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from structlog import get_logger

from app.domain.models.course import Course
from app.domain.models.document_chunk import DocumentChunk
from app.domain.models.module import Module
from app.domain.services.course_agent_service import CourseAgentService
from app.tasks.rag_indexation import UPLOAD_DIR, index_course_resources

logger = get_logger(__name__)

ALLOWED_RESOURCE_TYPES = {"application/pdf"}
MAX_RESOURCE_SIZE = 100 * 1024 * 1024  # 100 MB


@runtime_checkable
class CostTracker(Protocol):
    """Protocol for credit deduction — implemented by CreditService (issue #612)."""

    async def deduct(self, user_id: uuid.UUID, amount: int, reason: str) -> None: ...

    async def check_balance(self, user_id: uuid.UUID, required: int) -> bool: ...


def _slugify(text: str) -> str:
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_-]+", "-", slug)
    slug = re.sub(r"^-+|-+$", "", slug)
    return slug


class CourseManagementService:
    """Shared business logic for course CRUD, AI structure generation, and RAG indexation.

    Both the admin router and the expert router delegate to this service.
    Pass `check_ownership=True` and a `cost_tracker` from the expert context.
    """

    # ------------------------------------------------------------------
    # Course creation
    # ------------------------------------------------------------------

    async def create_course(
        self,
        db: AsyncSession,
        actor_id: uuid.UUID,
        data: dict[str, Any],
        is_marketplace: bool = False,
    ) -> Course:
        """Create a course (draft). Generates a unique slug from the English title.

        Args:
            db: async DB session.
            actor_id: UUID of the user creating the course (admin or expert).
            data: dict with course fields (title_fr, title_en, etc.).
            is_marketplace: reserved for marketplace context (#610); stored for future use.
        """
        base_slug = _slugify(data.get("title_en") or data.get("title_fr", "course"))
        slug = base_slug
        suffix = 1
        while True:
            existing = await db.execute(select(Course).where(Course.slug == slug))
            if existing.scalar_one_or_none() is None:
                break
            slug = f"{base_slug}-{suffix}"
            suffix += 1

        course = Course(
            id=uuid.uuid4(),
            slug=slug,
            title_fr=data["title_fr"],
            title_en=data["title_en"],
            description_fr=data.get("description_fr"),
            description_en=data.get("description_en"),
            course_domain=data.get("course_domain", []),
            course_level=data.get("course_level", []),
            audience_type=data.get("audience_type", []),
            languages=data.get("languages", "fr,en"),
            estimated_hours=data.get("estimated_hours", 20),
            cover_image_url=data.get("cover_image_url"),
            rag_collection_id=data.get("rag_collection_id") or str(uuid.uuid4()),
            created_by=actor_id,
            status="draft",
        )
        db.add(course)
        await db.commit()
        await db.refresh(course)

        logger.info(
            "course.created",
            course_id=str(course.id),
            actor_id=str(actor_id),
            is_marketplace=is_marketplace,
        )
        return course

    # ------------------------------------------------------------------
    # Course update
    # ------------------------------------------------------------------

    async def update_course(
        self,
        db: AsyncSession,
        course_id: uuid.UUID,
        data: dict[str, Any],
        actor_id: uuid.UUID,
        check_ownership: bool = False,
    ) -> Course:
        """Update course metadata.

        Args:
            db: async DB session.
            course_id: UUID of the course to update.
            data: fields to update (from Pydantic model_dump(exclude_unset=True)).
            actor_id: UUID of the requesting user.
            check_ownership: if True, raises 403 when actor is not the course creator.
        """
        course = await self._get_course_or_404(db, course_id)

        if check_ownership:
            self._assert_ownership(course, actor_id)

        for field, value in data.items():
            setattr(course, field, value)

        await db.commit()
        await db.refresh(course)

        logger.info("course.updated", course_id=str(course_id), actor_id=str(actor_id))
        return course

    # ------------------------------------------------------------------
    # Structure generation (AI)
    # ------------------------------------------------------------------

    async def generate_structure(
        self,
        db: AsyncSession,
        course_id: uuid.UUID,
        actor_id: uuid.UUID,
        estimated_hours: int = 20,
        deduct_credits: bool = False,
        cost_tracker: CostTracker | None = None,
        credit_cost: int = 10,
    ) -> dict[str, Any]:
        """Generate module outline via CourseAgentService (wraps Claude API).

        Args:
            db: async DB session.
            course_id: UUID of the target course.
            actor_id: UUID of the requesting user.
            estimated_hours: total hours to plan for.
            deduct_credits: if True, deduct `credit_cost` credits via `cost_tracker`.
            cost_tracker: CostTracker implementation; required when deduct_credits=True.
            credit_cost: number of credits to deduct per generation.
        """
        course = await self._get_course_or_404(db, course_id)

        if deduct_credits:
            if cost_tracker is None:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="cost_tracker required when deduct_credits=True",
                )
            has_balance = await cost_tracker.check_balance(actor_id, credit_cost)
            if not has_balance:
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail="Insufficient credits for structure generation",
                )

        max_number_result = await db.execute(
            select(func.max(Module.module_number)).where(Module.course_id == course_id)
        )
        max_number = max_number_result.scalar_one() or 0

        agent = CourseAgentService()
        module_dicts = await agent.generate_course_structure(
            title_fr=course.title_fr,
            title_en=course.title_en,
            course_domain=list(course.course_domain or []),
            course_level=list(course.course_level or []),
            audience_type=list(course.audience_type or []),
            estimated_hours=estimated_hours or course.estimated_hours,
        )

        saved_modules: list[dict[str, Any]] = []
        for i, m in enumerate(module_dicts):
            module = Module(
                id=uuid.uuid4(),
                module_number=max_number + i + 1,
                level=1,
                title_fr=m["title_fr"],
                title_en=m["title_en"],
                description_fr=m.get("description_fr"),
                description_en=m.get("description_en"),
                estimated_hours=m.get("estimated_hours", 20),
                bloom_level=m.get("bloom_level"),
                course_id=course_id,
            )
            db.add(module)
            saved_modules.append(
                {
                    "id": str(module.id),
                    "module_number": module.module_number,
                    "title_fr": module.title_fr,
                    "title_en": module.title_en,
                }
            )

        course.module_count = (
            await db.execute(
                select(func.count()).select_from(Module).where(Module.course_id == course_id)
            )
        ).scalar_one() + len(module_dicts)

        await db.commit()

        if deduct_credits and cost_tracker is not None:
            await cost_tracker.deduct(actor_id, credit_cost, f"generate_structure:{course_id}")

        logger.info(
            "course.structure_generated",
            course_id=str(course_id),
            actor_id=str(actor_id),
            module_count=len(saved_modules),
            credits_deducted=credit_cost if deduct_credits else 0,
        )
        return {"modules": saved_modules, "count": len(saved_modules)}

    # ------------------------------------------------------------------
    # Publish
    # ------------------------------------------------------------------

    async def publish_course(
        self,
        db: AsyncSession,
        course_id: uuid.UUID,
        actor_id: uuid.UUID,
        check_ownership: bool = False,
    ) -> Course:
        """Publish a draft course after validating RAG indexation is complete.

        Args:
            db: async DB session.
            course_id: UUID of the course to publish.
            actor_id: UUID of the requesting user.
            check_ownership: if True, raises 403 when actor is not the course creator.
        """
        course = await self._get_course_or_404(db, course_id)

        if check_ownership:
            self._assert_ownership(course, actor_id)

        chunk_count = await db.execute(
            select(func.count())
            .select_from(DocumentChunk)
            .where(DocumentChunk.source == course.rag_collection_id)
        )
        if chunk_count.scalar_one() == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot publish: RAG indexation not complete. "
                "Upload resources and run indexation first.",
            )

        course.status = "published"
        course.published_at = datetime.now(UTC)

        module_count_result = await db.execute(
            select(func.count()).select_from(Module).where(Module.course_id == course_id)
        )
        course.module_count = module_count_result.scalar_one()

        await db.commit()
        await db.refresh(course)

        logger.info("course.published", course_id=str(course_id), actor_id=str(actor_id))
        return course

    # ------------------------------------------------------------------
    # Resource upload
    # ------------------------------------------------------------------

    async def upload_resource(
        self,
        db: AsyncSession,
        course_id: uuid.UUID,
        file: UploadFile,
        actor_id: uuid.UUID,
        check_ownership: bool = False,
    ) -> dict[str, Any]:
        """Validate and store a PDF resource for a course.

        Args:
            db: async DB session.
            course_id: UUID of the course.
            file: uploaded file (PDF only, ≤100 MB).
            actor_id: UUID of the requesting user.
            check_ownership: if True, raises 403 when actor is not the course creator.
        """
        course = await self._get_course_or_404(db, course_id)

        if check_ownership:
            self._assert_ownership(course, actor_id)

        content_type = file.content_type or ""
        if content_type not in ALLOWED_RESOURCE_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Only PDF files are accepted. Got: {content_type}",
            )

        data = await file.read()
        if len(data) > MAX_RESOURCE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="File exceeds maximum size of 100MB",
            )

        if not data.startswith(b"%PDF"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File does not appear to be a valid PDF",
            )

        safe_name = re.sub(r"[^\w.\-]", "_", Path(file.filename or "resource.pdf").name)
        if not safe_name.lower().endswith(".pdf"):
            safe_name += ".pdf"

        course_dir = UPLOAD_DIR / str(course_id)
        course_dir.mkdir(parents=True, exist_ok=True)
        dest = course_dir / safe_name
        dest.write_bytes(data)

        logger.info(
            "course.resource_uploaded",
            course_id=str(course_id),
            filename=safe_name,
            size_bytes=len(data),
            actor_id=str(actor_id),
        )
        return {"course_id": str(course_id), "name": safe_name, "size_bytes": len(data)}

    # ------------------------------------------------------------------
    # RAG indexation
    # ------------------------------------------------------------------

    async def index_resources(
        self,
        db: AsyncSession,
        course_id: uuid.UUID,
        actor_id: uuid.UUID,
        check_ownership: bool = False,
        deduct_credits: bool = False,
        cost_tracker: CostTracker | None = None,
        credit_cost: int = 5,
    ) -> dict[str, Any]:
        """Trigger Celery RAG indexation task for course resources.

        Args:
            db: async DB session.
            course_id: UUID of the course.
            actor_id: UUID of the requesting user.
            check_ownership: if True, raises 403 when actor is not the course creator.
            deduct_credits: if True, deduct `credit_cost` credits via `cost_tracker`.
            cost_tracker: CostTracker implementation; required when deduct_credits=True.
            credit_cost: number of credits to deduct per indexation trigger.
        """
        course = await self._get_course_or_404(db, course_id)

        if check_ownership:
            self._assert_ownership(course, actor_id)

        if not course.rag_collection_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Course has no rag_collection_id",
            )

        if deduct_credits:
            if cost_tracker is None:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="cost_tracker required when deduct_credits=True",
                )
            has_balance = await cost_tracker.check_balance(actor_id, credit_cost)
            if not has_balance:
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail="Insufficient credits for RAG indexation",
                )

        task = index_course_resources.delay(str(course_id), course.rag_collection_id)

        if deduct_credits and cost_tracker is not None:
            await cost_tracker.deduct(actor_id, credit_cost, f"index_resources:{course_id}")

        logger.info(
            "course.rag_indexation_triggered",
            course_id=str(course_id),
            task_id=task.id,
            actor_id=str(actor_id),
            credits_deducted=credit_cost if deduct_credits else 0,
        )
        return {"task_id": task.id, "status": "started"}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_course_or_404(self, db: AsyncSession, course_id: uuid.UUID) -> Course:
        result = await db.execute(select(Course).where(Course.id == course_id))
        course = result.scalar_one_or_none()
        if not course:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")
        return course

    def _assert_ownership(self, course: Course, actor_id: uuid.UUID) -> None:
        if course.created_by != actor_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to modify this course",
            )
