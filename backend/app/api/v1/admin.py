"""Admin-only endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from structlog import get_logger

from app.api.deps import get_db as get_db_session
from app.api.deps_local_auth import AuthenticatedUser, require_role
from app.domain.models.user import User, UserRole

logger = get_logger(__name__)

router = APIRouter(
    prefix="/admin",
    tags=["Admin"],
    dependencies=[Depends(require_role(UserRole.admin))],
)


@router.get("/users")
async def list_users(
    db=Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_role(UserRole.admin)),
) -> list[dict]:
    """List all users (admin only).

    Returns:
        List of user records with basic info and roles.
    """
    result = await db.execute(
        select(
            User.id,
            User.email,
            User.name,
            User.role,
            User.preferred_language,
            User.country,
            User.current_level,
            User.streak_days,
            User.last_active,
            User.created_at,
        ).order_by(User.created_at.desc())
    )
    rows = result.fetchall()

    return [
        {
            "id": str(row.id),
            "email": row.email,
            "name": row.name,
            "role": row.role.value if row.role else UserRole.user.value,
            "preferred_language": row.preferred_language,
            "country": row.country,
            "current_level": row.current_level,
            "streak_days": row.streak_days,
            "last_active": row.last_active.isoformat() if row.last_active else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]


@router.patch("/users/{user_id}/role")
async def update_user_role(
    user_id: UUID,
    role: UserRole,
    db=Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_role(UserRole.admin)),
) -> dict:
    """Update a user's role (admin only).

    Args:
        user_id: Target user UUID.
        role: New role to assign.

    Returns:
        Updated user id and role.
    """
    user = await db.scalar(select(User).where(User.id == user_id))
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.role = role
    await db.commit()

    logger.info("User role updated", target_user_id=str(user_id), new_role=role.value)

    return {"id": str(user.id), "email": user.email, "role": user.role.value}
