"""Organization CRUD + member management endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from app.api.deps import get_db_session
from app.api.deps_local_auth import AuthenticatedUser, get_current_user, require_role
from app.domain.models.organization import OrgMemberRole
from app.domain.models.user import User, UserRole
from app.domain.services.organization_service import OrganizationService

router = APIRouter(prefix="/organizations", tags=["Organizations"])

_svc = OrganizationService()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class CreateOrgRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    slug: str | None = None
    description: str | None = None
    contact_email: str | None = None
    logo_url: str | None = None


class UpdateOrgRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    contact_email: str | None = None
    logo_url: str | None = None


class AddMemberRequest(BaseModel):
    email: str
    role: OrgMemberRole = OrgMemberRole.viewer


class UpdateMemberRoleRequest(BaseModel):
    role: OrgMemberRole


class OrgResponse(BaseModel):
    id: str
    name: str
    slug: str
    description: str | None = None
    logo_url: str | None = None
    contact_email: str | None = None
    is_active: bool
    created_at: str


class OrgWithRoleResponse(BaseModel):
    organization: OrgResponse
    role: str
    joined_at: str


class MemberResponse(BaseModel):
    user_id: str
    name: str
    email: str | None
    role: str
    joined_at: str


class OrgCreditSummary(BaseModel):
    balance: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _org_to_response(org) -> OrgResponse:
    return OrgResponse(
        id=str(org.id),
        name=org.name,
        slug=org.slug,
        description=org.description,
        logo_url=org.logo_url,
        contact_email=org.contact_email,
        is_active=org.is_active,
        created_at=org.created_at.isoformat(),
    )


# ---------------------------------------------------------------------------
# Organization CRUD
# ---------------------------------------------------------------------------


@router.post("", status_code=status.HTTP_201_CREATED, response_model=OrgResponse)
async def create_organization(
    body: CreateOrgRequest,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin, UserRole.sub_admin)),
    db=Depends(get_db_session),
) -> OrgResponse:
    """Create a new organization. Admin/sub_admin only."""
    org = await _svc.create_organization(
        db,
        name=body.name,
        slug=body.slug,
        description=body.description,
        contact_email=body.contact_email,
        logo_url=body.logo_url,
        creator_id=uuid.UUID(current_user.id),
    )
    return _org_to_response(org)


@router.get("/me", response_model=list[OrgWithRoleResponse])
async def list_my_organizations(
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
) -> list[OrgWithRoleResponse]:
    """List all organizations where the current user is a member."""
    memberships = await _svc.list_user_organizations(db, uuid.UUID(current_user.id))
    return [
        OrgWithRoleResponse(
            organization=_org_to_response(m["organization"]),
            role=m["role"].value if hasattr(m["role"], "value") else m["role"],
            joined_at=m["joined_at"].isoformat() if m["joined_at"] else "",
        )
        for m in memberships
    ]


@router.get("/{org_id}", response_model=OrgResponse)
async def get_organization(
    org_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
) -> OrgResponse:
    """Get organization details. Requires membership."""
    await _svc.require_org_role(db, org_id, uuid.UUID(current_user.id))
    org = await _svc.get_organization(db, org_id)
    return _org_to_response(org)


@router.patch("/{org_id}", response_model=OrgResponse)
async def update_organization(
    org_id: uuid.UUID,
    body: UpdateOrgRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
) -> OrgResponse:
    """Update organization. Requires owner/admin role."""
    updates = body.model_dump(exclude_unset=True)
    org = await _svc.update_organization(db, org_id, uuid.UUID(current_user.id), **updates)
    return _org_to_response(org)


# ---------------------------------------------------------------------------
# Member management
# ---------------------------------------------------------------------------


@router.get("/{org_id}/members", response_model=list[MemberResponse])
async def list_members(
    org_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
) -> list[MemberResponse]:
    """List organization members. Requires membership."""
    await _svc.require_org_role(db, org_id, uuid.UUID(current_user.id))
    members = await _svc.list_members(db, org_id)
    return [
        MemberResponse(
            user_id=str(m.user_id),
            name=m.user.name if m.user else "",
            email=m.user.email if m.user else None,
            role=m.role.value,
            joined_at=m.joined_at.isoformat(),
        )
        for m in members
    ]


@router.post(
    "/{org_id}/members",
    status_code=status.HTTP_201_CREATED,
    response_model=MemberResponse,
)
async def add_member(
    org_id: uuid.UUID,
    body: AddMemberRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
) -> MemberResponse:
    """Add a member by email. Requires owner/admin role."""
    member = await _svc.add_member(
        db,
        org_id=org_id,
        user_email=body.email,
        role=body.role,
        invited_by=uuid.UUID(current_user.id),
    )
    user_result = await db.get(User, member.user_id)
    return MemberResponse(
        user_id=str(member.user_id),
        name=user_result.name if user_result else "",
        email=user_result.email if user_result else None,
        role=member.role.value,
        joined_at=member.joined_at.isoformat(),
    )


@router.patch("/{org_id}/members/{user_id}", response_model=MemberResponse)
async def update_member_role(
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    body: UpdateMemberRoleRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
) -> MemberResponse:
    """Update a member's role. Requires owner role."""
    member = await _svc.update_member_role(
        db, org_id, user_id, body.role, uuid.UUID(current_user.id)
    )
    user_result = await db.get(User, member.user_id)
    return MemberResponse(
        user_id=str(member.user_id),
        name=user_result.name if user_result else "",
        email=user_result.email if user_result else None,
        role=member.role.value,
        joined_at=member.joined_at.isoformat(),
    )


@router.delete(
    "/{org_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_member(
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
) -> None:
    """Remove a member. Requires owner/admin role."""
    await _svc.remove_member(db, org_id, user_id, uuid.UUID(current_user.id))


# ---------------------------------------------------------------------------
# Credits
# ---------------------------------------------------------------------------


@router.get("/{org_id}/credits", response_model=OrgCreditSummary)
async def get_org_credits(
    org_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
) -> OrgCreditSummary:
    """Get organization credit balance. Requires membership."""
    await _svc.require_org_role(db, org_id, uuid.UUID(current_user.id))
    balance = await _svc.get_org_credit_balance(db, org_id)
    return OrgCreditSummary(balance=balance)
