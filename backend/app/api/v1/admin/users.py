"""Admin-only endpoints for user management."""

import csv
import io
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from structlog import get_logger

from app.api.deps import get_db as get_db_session
from app.api.deps_local_auth import AuthenticatedUser, require_role
from app.api.v1.schemas.admin import AuditLogResponse
from app.api.v1.schemas.users import UserProfileResponse
from app.domain.models.audit_log import AdminAction, AuditLog
from app.domain.models.module import Module
from app.domain.models.progress import UserModuleProgress
from app.domain.models.quiz import QuizAttempt
from app.domain.models.user import User, UserRole
from app.domain.repositories.implementations.user_repository import UserRepository

logger = get_logger(__name__)
router = APIRouter(prefix="/admin", tags=["Admin"])


class UpdateRoleRequest(BaseModel):
    role: UserRole


class UpdateUserStatusRequest(BaseModel):
    is_active: bool


def _user_to_response(u: User) -> UserProfileResponse:
    return UserProfileResponse(
        id=str(u.id),
        email=u.email,
        name=u.name,
        preferred_language=u.preferred_language,
        country=u.country,
        professional_role=u.professional_role,
        current_level=u.current_level,
        streak_days=u.streak_days,
        avatar_url=u.avatar_url,
        last_active=u.last_active.isoformat(),
        created_at=u.created_at.isoformat(),
        role=u.role,
        is_active=u.is_active,
        phone_number=u.phone_number,
        analytics_opt_out=u.analytics_opt_out,
    )


async def _write_audit_log(
    db,
    admin: AuthenticatedUser,
    target_user: User,
    action: AdminAction,
    details: str | None = None,
) -> None:
    log = AuditLog(
        admin_id=UUID(admin.id),
        admin_email=admin.email or f"phone:{getattr(admin, 'phone_number', 'unknown')}",
        target_user_id=target_user.id,
        target_user_email=target_user.email,
        action=action,
        details=details,
    )
    db.add(log)


@router.get("/users/export/csv")
async def export_users_csv(
    search: str | None = Query(None),
    country: str | None = Query(None),
    level: int | None = Query(None, ge=1, le=4),
    role: UserRole | None = Query(None),
    is_active: bool | None = Query(None),
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin)),
    db=Depends(get_db_session),
) -> StreamingResponse:
    """Export user list as CSV. Admin only."""
    try:
        stmt = select(User)

        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(or_(User.name.ilike(pattern), User.email.ilike(pattern)))
        if country:
            stmt = stmt.where(User.country == country)
        if level is not None:
            stmt = stmt.where(User.current_level == level)
        if role is not None:
            stmt = stmt.where(User.role == role.value)
        if is_active is not None:
            stmt = stmt.where(User.is_active == is_active)

        stmt = stmt.order_by(User.created_at.desc())
        result = await db.execute(stmt)
        users = result.scalars().all()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "id",
                "email",
                "phone_number",
                "name",
                "country",
                "professional_role",
                "current_level",
                "role",
                "is_active",
                "streak_days",
                "preferred_language",
                "last_active",
                "created_at",
            ]
        )
        for u in users:
            writer.writerow(
                [
                    str(u.id),
                    u.email or "",
                    u.phone_number or "",
                    u.name,
                    u.country or "",
                    u.professional_role or "",
                    u.current_level,
                    u.role.value,
                    u.is_active,
                    u.streak_days,
                    u.preferred_language,
                    u.last_active.isoformat(),
                    u.created_at.isoformat(),
                ]
            )

        output.seek(0)
        logger.info("Admin exported users CSV", admin_id=current_user.id, count=len(users))

        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=users_export.csv"},
        )
    except Exception as e:
        logger.error("Failed to export users CSV", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to export users",
        )


@router.get("/users/count")
async def count_users(
    search: str | None = Query(None),
    country: str | None = Query(None),
    level: int | None = Query(None, ge=1, le=4),
    role: UserRole | None = Query(None),
    is_active: bool | None = Query(None),
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin)),
    db=Depends(get_db_session),
) -> dict:
    """Count users matching filters. Admin only."""
    try:
        stmt = select(func.count()).select_from(User)

        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(or_(User.name.ilike(pattern), User.email.ilike(pattern)))
        if country:
            stmt = stmt.where(User.country == country)
        if level is not None:
            stmt = stmt.where(User.current_level == level)
        if role is not None:
            stmt = stmt.where(User.role == role.value)
        if is_active is not None:
            stmt = stmt.where(User.is_active == is_active)

        result = await db.execute(stmt)
        return {"count": result.scalar_one()}
    except Exception as e:
        logger.error("Failed to count users", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to count users",
        )


@router.get("/users", response_model=list[UserProfileResponse])
async def list_users(
    search: str | None = Query(None, description="Search by name or email"),
    country: str | None = Query(None),
    level: int | None = Query(None, ge=1, le=4),
    role: UserRole | None = Query(None),
    is_active: bool | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin)),
    db=Depends(get_db_session),
) -> list[UserProfileResponse]:
    """List users with search and filters. Admin only."""
    try:
        stmt = select(User)

        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(or_(User.name.ilike(pattern), User.email.ilike(pattern)))
        if country:
            stmt = stmt.where(User.country == country)
        if level is not None:
            stmt = stmt.where(User.current_level == level)
        if role is not None:
            stmt = stmt.where(User.role == role.value)
        if is_active is not None:
            stmt = stmt.where(User.is_active == is_active)

        stmt = stmt.order_by(User.created_at.desc()).offset(offset).limit(limit)
        result = await db.execute(stmt)
        users = result.scalars().all()

        return [_user_to_response(u) for u in users]
    except Exception as e:
        logger.error("Failed to list users", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve users",
        )


@router.get("/users/{user_id}", response_model=UserProfileResponse)
async def get_user(
    user_id: UUID,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin)),
    db=Depends(get_db_session),
) -> UserProfileResponse:
    """Get user detail. Admin only."""
    try:
        user_repo = UserRepository(db)
        user = await user_repo.get_by_id(user_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        return _user_to_response(user)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get user", user_id=str(user_id), error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve user",
        )


@router.patch("/users/{user_id}/role", response_model=UserProfileResponse)
async def update_user_role(
    user_id: UUID,
    request: UpdateRoleRequest,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin)),
    db=Depends(get_db_session),
) -> UserProfileResponse:
    """Update a user's role. Admin only."""
    if str(user_id) == str(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot change your own role"
        )

    try:
        user_repo = UserRepository(db)
        user = await user_repo.get_by_id(user_id)

        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        old_role = user.role
        user.role = request.role

        action_map = {
            UserRole.expert: AdminAction.promote_to_expert,
            UserRole.admin: AdminAction.promote_to_admin,
            UserRole.user: AdminAction.demote_to_user,
        }
        action = action_map.get(request.role, AdminAction.update_role)
        await _write_audit_log(
            db,
            current_user,
            user,
            action,
            details=f"role changed from {old_role.value} to {request.role.value}",
        )

        await db.commit()
        await db.refresh(user)

        logger.info(
            "User role updated",
            admin_id=current_user.id,
            target_user_id=str(user_id),
            new_role=request.role.value,
        )

        return _user_to_response(user)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to update user role", user_id=str(user_id), error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update user role",
        )


@router.patch("/users/{user_id}/status", response_model=UserProfileResponse)
async def update_user_status(
    user_id: UUID,
    request: UpdateUserStatusRequest,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin)),
    db=Depends(get_db_session),
) -> UserProfileResponse:
    """Deactivate or reactivate a user. Admin only."""
    if str(user_id) == str(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot change your own status",
        )

    try:
        user_repo = UserRepository(db)
        user = await user_repo.get_by_id(user_id)

        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        user.is_active = request.is_active
        action = AdminAction.reactivate_user if request.is_active else AdminAction.deactivate_user
        await _write_audit_log(db, current_user, user, action)

        await db.commit()
        await db.refresh(user)

        logger.info(
            "User status updated",
            admin_id=current_user.id,
            target_user_id=str(user_id),
            is_active=request.is_active,
        )

        return _user_to_response(user)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to update user status", user_id=str(user_id), error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update user status",
        )


@router.get("/audit-logs", response_model=list[AuditLogResponse])
async def list_audit_logs(
    target_user_id: UUID | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin)),
    db=Depends(get_db_session),
) -> list[AuditLogResponse]:
    """List admin audit logs. Admin only."""
    try:
        stmt = select(AuditLog)

        if target_user_id is not None:
            stmt = stmt.where(AuditLog.target_user_id == target_user_id)

        stmt = stmt.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit)
        result = await db.execute(stmt)
        logs = result.scalars().all()

        return [
            AuditLogResponse(
                id=str(log.id),
                admin_id=str(log.admin_id) if log.admin_id else None,
                admin_email=log.admin_email,
                target_user_id=str(log.target_user_id) if log.target_user_id else None,
                target_user_email=log.target_user_email,
                action=log.action,
                details=log.details,
                created_at=log.created_at.isoformat(),
            )
            for log in logs
        ]
    except Exception as e:
        logger.error("Failed to list audit logs", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve audit logs",
        )


@router.get("/users/{user_id}/progress")
async def get_user_progress(
    user_id: UUID,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin)),
    db=Depends(get_db_session),
) -> list[dict]:
    """Get module progress for a user. Admin only."""
    try:
        stmt = (
            select(UserModuleProgress, Module)
            .join(Module, UserModuleProgress.module_id == Module.id)
            .where(UserModuleProgress.user_id == user_id)
            .order_by(Module.module_number)
        )
        result = await db.execute(stmt)
        rows = result.all()

        return [
            {
                "module_id": str(p.module_id),
                "module_number": m.module_number,
                "title_fr": m.title_fr,
                "title_en": m.title_en,
                "status": p.status,
                "completion_pct": p.completion_pct,
                "quiz_score_avg": p.quiz_score_avg,
                "time_spent_minutes": p.time_spent_minutes,
                "last_accessed": p.last_accessed.isoformat() if p.last_accessed else None,
            }
            for p, m in rows
        ]
    except Exception as e:
        logger.error("Failed to get user progress", user_id=str(user_id), error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve user progress",
        )


@router.get("/users/{user_id}/quiz-history")
async def get_user_quiz_history(
    user_id: UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin)),
    db=Depends(get_db_session),
) -> list[dict]:
    """Get quiz attempt history for a user. Admin only."""
    try:
        stmt = (
            select(QuizAttempt)
            .where(QuizAttempt.user_id == user_id)
            .order_by(QuizAttempt.attempted_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await db.execute(stmt)
        attempts = result.scalars().all()

        return [
            {
                "id": str(a.id),
                "quiz_id": str(a.quiz_id),
                "score": a.score,
                "time_taken_sec": a.time_taken_sec,
                "attempted_at": a.attempted_at.isoformat(),
            }
            for a in attempts
        ]
    except Exception as e:
        logger.error("Failed to get user quiz history", user_id=str(user_id), error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve quiz history",
        )
