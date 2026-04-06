"""Admin API endpoints for syllabus management with AI agent."""

from __future__ import annotations

import json
import uuid

import structlog
from anthropic import AsyncAnthropic
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.rag.embeddings import EmbeddingService
from app.ai.rag.retriever import SemanticRetriever
from app.api.deps import get_db_session
from app.api.deps_local_auth import AuthenticatedUser, require_role
from app.api.v1.schemas.admin_syllabus import (
    AuditLogEntry,
    ModuleExportResponse,
    ModuleListResponse,
    ModuleSaveRequest,
    ModuleSaveResponse,
    SyllabusAgentRequest,
)
from app.domain.models.module import Module
from app.domain.models.module_unit import ModuleUnit
from app.domain.models.user import UserRole
from app.domain.services.syllabus_agent_service import SyllabusAgentService
from app.infrastructure.config.settings import get_settings

logger = structlog.get_logger()

router = APIRouter(prefix="/admin/syllabus", tags=["admin"])


_require_admin = require_role(UserRole.admin)


async def get_syllabus_agent_service() -> SyllabusAgentService:
    """Dependency factory for the syllabus agent service."""
    settings = get_settings()
    anthropic_client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    embedding_service = EmbeddingService(api_key=settings.openai_api_key)
    semantic_retriever = SemanticRetriever(embedding_service)
    return SyllabusAgentService(
        anthropic_client=anthropic_client,
        semantic_retriever=semantic_retriever,
        embedding_service=embedding_service,
    )


@router.get("", response_model=ModuleListResponse)
async def list_modules(
    current_user: AuthenticatedUser = Depends(_require_admin),
    session: AsyncSession = Depends(get_db_session),
    agent_service: SyllabusAgentService = Depends(get_syllabus_agent_service),
) -> ModuleListResponse:
    """Return modules for the admin syllabus page, filtered by owner."""
    modules = await agent_service.get_modules_list(
        session,
        user_id=str(current_user.id),
    )
    return ModuleListResponse(modules=modules, total=len(modules))


@router.post("/agent", response_model=None)
async def chat_with_agent(
    request: SyllabusAgentRequest,
    current_user: AuthenticatedUser = Depends(_require_admin),
    session: AsyncSession = Depends(get_db_session),
    agent_service: SyllabusAgentService = Depends(get_syllabus_agent_service),
) -> StreamingResponse:
    """Stream agent responses via SSE for syllabus creation/editing."""

    logger.info(
        "Syllabus agent request",
        admin_id=str(current_user.id),
        message_length=len(request.message),
        module_id=str(request.module_id) if request.module_id else None,
    )

    async def stream_response():
        async for chunk in agent_service.stream_agent_response(
            admin_id=str(current_user.id),
            admin_email=current_user.email,
            message=request.message,
            session=session,
            module_id=request.module_id,
            conversation_history=request.conversation_history,
        ):
            yield chunk

    return StreamingResponse(
        stream_response(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{module_id}", response_model=None)
async def get_module(
    module_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(_require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Get a single module's full data for editing, including units."""
    result = await session.execute(select(Module).where(Module.id == module_id))
    module = result.scalar_one_or_none()
    if not module:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Module not found",
        )

    # Fetch units for this module
    units_result = await session.execute(
        select(ModuleUnit).where(ModuleUnit.module_id == module_id).order_by(ModuleUnit.order_index)
    )
    units = units_result.scalars().all()

    books = module.books_sources or {}
    return {
        "id": str(module.id),
        "module_number": module.module_number,
        "level": module.level,
        "title_fr": module.title_fr,
        "title_en": module.title_en,
        "description_fr": module.description_fr,
        "description_en": module.description_en,
        "estimated_hours": module.estimated_hours,
        "bloom_level": module.bloom_level,
        "prereq_modules": [str(p) for p in (module.prereq_modules or [])],
        "objectives_fr": books.get("objectives_fr", []),
        "objectives_en": books.get("objectives_en", []),
        "key_contents_fr": books.get("key_contents_fr", []),
        "key_contents_en": books.get("key_contents_en", []),
        "aof_context_fr": books.get("aof_context_fr", ""),
        "aof_context_en": books.get("aof_context_en", ""),
        "activities": books.get("activities", {}),
        "source_references": books.get("source_references", []),
        "units": [
            {
                "id": str(u.id),
                "unit_number": u.unit_number,
                "title_fr": u.title_fr,
                "title_en": u.title_en,
                "description_fr": u.description_fr,
                "description_en": u.description_en,
                "order_index": u.order_index,
            }
            for u in units
        ],
    }


@router.put("/{module_id}", response_model=ModuleSaveResponse)
async def update_module(
    module_id: uuid.UUID,
    request: ModuleSaveRequest,
    current_user: AuthenticatedUser = Depends(_require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> ModuleSaveResponse:
    """Update a module directly (inline edit from preview panel).

    NOTE: This updates the module record in-place. Already-generated
    lessons/quizzes are NOT automatically regenerated. To apply
    syllabus changes to learner-facing content, re-trigger content
    generation for the affected module units.
    """
    result = await session.execute(select(Module).where(Module.id == module_id))
    module = result.scalar_one_or_none()
    if not module:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Module not found")

    draft = request.draft
    if draft.level:
        module.level = draft.level
    if draft.title_fr:
        module.title_fr = draft.title_fr
    if draft.title_en:
        module.title_en = draft.title_en
    module.description_fr = draft.description_fr
    module.description_en = draft.description_en
    if draft.estimated_hours:
        module.estimated_hours = draft.estimated_hours
    module.bloom_level = draft.bloom_level

    books = dict(module.books_sources or {})
    books.update(
        {
            "objectives_fr": draft.objectives_fr,
            "objectives_en": draft.objectives_en,
            "key_contents_fr": draft.key_contents_fr,
            "key_contents_en": draft.key_contents_en,
            "aof_context_fr": draft.aof_context_fr or "",
            "aof_context_en": draft.aof_context_en or "",
            "activities": draft.activities.model_dump(),
            "source_references": draft.source_references,
        }
    )
    module.books_sources = books

    try:
        await session.execute(
            text(
                """
                INSERT INTO admin_syllabus_audit_log
                    (id, admin_id, admin_email, action, module_id, module_number, changes, created_at)
                VALUES
                    (:id, :admin_id, :admin_email, :action, :module_id, :module_number, :changes::jsonb, NOW())
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "admin_id": str(current_user.id),
                "admin_email": current_user.email,
                "action": "inline_update",
                "module_id": str(module_id),
                "module_number": module.module_number,
                "changes": json.dumps(draft.model_dump()),
            },
        )
    except Exception as e:
        logger.warning("Audit log write failed", error=str(e))

    await session.commit()

    return ModuleSaveResponse(
        id=module.id,
        module_number=module.module_number,
        created=False,
        message=f"Module M{module.module_number:02d} updated successfully",
    )


@router.get("/{module_id}/export", response_model=ModuleExportResponse)
async def export_module(
    module_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(_require_admin),
    session: AsyncSession = Depends(get_db_session),
    agent_service: SyllabusAgentService = Depends(get_syllabus_agent_service),
) -> ModuleExportResponse:
    """Export a module as Markdown in canonical syllabus format."""
    result = await session.execute(select(Module).where(Module.id == module_id))
    module = result.scalar_one_or_none()
    if not module:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Module not found")

    markdown = await agent_service.export_module_as_markdown(module_id, session)
    return ModuleExportResponse(module_number=module.module_number, markdown=markdown)


@router.get("/{module_id}/audit", response_model=list[AuditLogEntry])
async def get_audit_log(
    module_id: uuid.UUID,
    limit: int = 20,
    current_user: AuthenticatedUser = Depends(_require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> list[AuditLogEntry]:
    """Return modification history for a module."""
    try:
        result = await session.execute(
            text(
                """
                SELECT id, admin_id, admin_email, action, module_id, module_number, changes, created_at
                FROM admin_syllabus_audit_log
                WHERE module_id = :module_id
                ORDER BY created_at DESC
                LIMIT :limit
                """
            ),
            {"module_id": str(module_id), "limit": limit},
        )
        rows = result.fetchall()
        return [
            AuditLogEntry(
                id=row.id,
                admin_id=row.admin_id,
                admin_email=row.admin_email,
                action=row.action,
                module_id=row.module_id,
                module_number=row.module_number,
                changes=row.changes if isinstance(row.changes, dict) else {},
                created_at=row.created_at,
            )
            for row in rows
        ]
    except Exception as e:
        logger.warning("Audit log fetch failed", error=str(e))
        return []
