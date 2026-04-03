"""Admin-only endpoints for user management."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from structlog import get_logger

from app.api.deps import get_db as get_db_session
from app.api.deps_local_auth import AuthenticatedUser, require_role
from app.domain.models.user import User, UserRole
from app.domain.repositories.implementations.user_repository import UserRepository

from ..schemas.users import UserProfileResponse

logger = get_logger(__name__)
router = APIRouter(prefix="/admin", tags=["Admin"])


class UpdateRoleRequest(BaseModel):
    role: UserRole


@router.get("/users", response_model=list[UserProfileResponse])
async def list_users(
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin)),
    db=Depends(get_db_session),
) -> list[UserProfileResponse]:
    """List all users. Admin only."""
    try:
        result = await db.execute(select(User).order_by(User.created_at.desc()))
        users = result.scalars().all()

        return [
            UserProfileResponse(
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
            )
            for u in users
        ]
    except Exception as e:
        logger.error("Failed to list users", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve users",
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

        user.role = request.role
        await db.commit()
        await db.refresh(user)

        logger.info(
            "User role updated",
            admin_id=current_user.id,
            target_user_id=str(user_id),
            new_role=request.role.value,
        )

        return UserProfileResponse(
            id=str(user.id),
            email=user.email,
            name=user.name,
            preferred_language=user.preferred_language,
            country=user.country,
            professional_role=user.professional_role,
            current_level=user.current_level,
            streak_days=user.streak_days,
            avatar_url=user.avatar_url,
            last_active=user.last_active.isoformat(),
            created_at=user.created_at.isoformat(),
            role=user.role,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to update user role", user_id=str(user_id), error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update user role",
        )
