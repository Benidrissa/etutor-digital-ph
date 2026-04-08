"""Admin endpoints for user group management (CRUD + member management)."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from structlog import get_logger

from app.api.deps import get_db as get_db_session
from app.api.deps_local_auth import AuthenticatedUser, require_role
from app.domain.models.user import User, UserRole
from app.domain.models.user_group import UserGroup, UserGroupMember

logger = get_logger(__name__)
router = APIRouter(prefix="/admin/groups", tags=["Admin - Groups"])


class CreateGroupRequest(BaseModel):
    name: str
    description: str | None = None


class UpdateGroupRequest(BaseModel):
    name: str | None = None
    description: str | None = None


class AddMemberRequest(BaseModel):
    user_id: str


class GroupMemberResponse(BaseModel):
    user_id: str
    user_email: str | None
    user_name: str
    added_at: str


class GroupResponse(BaseModel):
    id: str
    name: str
    description: str | None
    created_by: str | None
    created_at: str
    member_count: int


class GroupDetailResponse(GroupResponse):
    members: list[GroupMemberResponse]


def _group_to_response(group: UserGroup) -> GroupResponse:
    return GroupResponse(
        id=str(group.id),
        name=group.name,
        description=group.description,
        created_by=str(group.created_by) if group.created_by else None,
        created_at=group.created_at.isoformat(),
        member_count=len(group.members) if group.members else 0,
    )


def _group_to_detail_response(group: UserGroup) -> GroupDetailResponse:
    base = _group_to_response(group)
    members = []
    for m in group.members or []:
        user = m.user
        members.append(
            GroupMemberResponse(
                user_id=str(m.user_id),
                user_email=user.email if user else None,
                user_name=user.name if user else "",
                added_at=m.added_at.isoformat(),
            )
        )
    return GroupDetailResponse(**base.model_dump(), members=members)


@router.get("", response_model=list[GroupResponse])
async def list_groups(
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin)),
    db=Depends(get_db_session),
) -> list[GroupResponse]:
    """List all user groups. Admin only."""
    result = await db.execute(select(UserGroup).order_by(UserGroup.created_at.desc()))
    groups = result.scalars().all()
    return [_group_to_response(g) for g in groups]


@router.post("", response_model=GroupDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_group(
    request: CreateGroupRequest,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin)),
    db=Depends(get_db_session),
) -> GroupDetailResponse:
    """Create a user group. Admin only."""
    existing = await db.execute(select(UserGroup).where(UserGroup.name == request.name))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A group with this name already exists",
        )

    group = UserGroup(
        id=uuid.uuid4(),
        name=request.name,
        description=request.description,
        created_by=uuid.UUID(current_user.id),
    )
    db.add(group)
    await db.commit()
    await db.refresh(group)
    logger.info("User group created", group_id=str(group.id), admin_id=current_user.id)
    return _group_to_detail_response(group)


@router.get("/{group_id}", response_model=GroupDetailResponse)
async def get_group(
    group_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin)),
    db=Depends(get_db_session),
) -> GroupDetailResponse:
    """Get group detail with members. Admin only."""
    result = await db.execute(select(UserGroup).where(UserGroup.id == group_id))
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    return _group_to_detail_response(group)


@router.patch("/{group_id}", response_model=GroupDetailResponse)
async def update_group(
    group_id: uuid.UUID,
    request: UpdateGroupRequest,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin)),
    db=Depends(get_db_session),
) -> GroupDetailResponse:
    """Update group name or description. Admin only."""
    result = await db.execute(select(UserGroup).where(UserGroup.id == group_id))
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")

    if request.name and request.name != group.name:
        existing = await db.execute(select(UserGroup).where(UserGroup.name == request.name))
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A group with this name already exists",
            )

    for field, value in request.model_dump(exclude_unset=True).items():
        setattr(group, field, value)

    await db.commit()
    await db.refresh(group)
    logger.info("User group updated", group_id=str(group_id), admin_id=current_user.id)
    return _group_to_detail_response(group)


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(
    group_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin)),
    db=Depends(get_db_session),
) -> None:
    """Delete a user group. Admin only."""
    result = await db.execute(select(UserGroup).where(UserGroup.id == group_id))
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")

    await db.delete(group)
    await db.commit()
    logger.info("User group deleted", group_id=str(group_id), admin_id=current_user.id)


@router.post(
    "/{group_id}/members",
    response_model=GroupDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_member(
    group_id: uuid.UUID,
    request: AddMemberRequest,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin)),
    db=Depends(get_db_session),
) -> GroupDetailResponse:
    """Add a user to a group. Admin only."""
    group_result = await db.execute(select(UserGroup).where(UserGroup.id == group_id))
    group = group_result.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")

    try:
        user_id = uuid.UUID(request.user_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid user_id")

    user_result = await db.execute(select(User).where(User.id == user_id))
    if not user_result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    existing = await db.execute(
        select(UserGroupMember).where(
            UserGroupMember.group_id == group_id,
            UserGroupMember.user_id == user_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="User is already a member of this group"
        )

    db.add(UserGroupMember(group_id=group_id, user_id=user_id))
    await db.commit()
    await db.refresh(group)
    logger.info(
        "Member added to group",
        group_id=str(group_id),
        user_id=str(user_id),
        admin_id=current_user.id,
    )
    return _group_to_detail_response(group)


@router.delete("/{group_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    group_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin)),
    db=Depends(get_db_session),
) -> None:
    """Remove a user from a group. Admin only."""
    result = await db.execute(
        select(UserGroupMember).where(
            UserGroupMember.group_id == group_id,
            UserGroupMember.user_id == user_id,
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Member not found in group"
        )

    await db.delete(member)
    await db.commit()
    logger.info(
        "Member removed from group",
        group_id=str(group_id),
        user_id=str(user_id),
        admin_id=current_user.id,
    )
