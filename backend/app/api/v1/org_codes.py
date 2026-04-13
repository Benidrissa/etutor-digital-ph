"""Organization activation code endpoints."""

from __future__ import annotations

import base64
import io
import uuid

import qrcode
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.api.deps_local_auth import AuthenticatedUser, get_current_user
from app.infrastructure.config.settings import settings
from app.domain.services.activation_code_service import ActivationCodeService
from app.domain.services.organization_service import OrganizationService

router = APIRouter(
    prefix="/organizations/{org_id}/codes",
    tags=["Organization Codes"],
)

_code_svc = ActivationCodeService()
_org_svc = OrganizationService()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class GenerateOrgCodesRequest(BaseModel):
    curriculum_id: str | None = None
    course_id: str | None = None
    count: int = Field(1, ge=1, le=500)
    max_uses: int | None = Field(None, ge=1)


class OrgCodeResponse(BaseModel):
    id: str
    code: str
    course_id: str | None
    curriculum_id: str | None
    max_uses: int | None
    times_used: int
    is_active: bool
    created_at: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("", status_code=status.HTTP_201_CREATED, response_model=list[OrgCodeResponse])
async def generate_org_codes(
    org_id: uuid.UUID,
    body: GenerateOrgCodesRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> list[OrgCodeResponse]:
    """Generate activation codes for an organization (with credit escrow)."""
    codes = await _code_svc.generate_org_codes(
        db,
        org_id=org_id,
        actor_id=uuid.UUID(current_user.id),
        curriculum_id=uuid.UUID(body.curriculum_id) if body.curriculum_id else None,
        course_id=uuid.UUID(body.course_id) if body.course_id else None,
        count=body.count,
        max_uses=body.max_uses,
    )
    return [
        OrgCodeResponse(
            id=str(c.id),
            code=c.code,
            course_id=str(c.course_id) if c.course_id else None,
            curriculum_id=str(c.curriculum_id) if c.curriculum_id else None,
            max_uses=c.max_uses,
            times_used=c.times_used,
            is_active=c.is_active,
            created_at=c.created_at.isoformat(),
        )
        for c in codes
    ]


@router.get("", response_model=list[OrgCodeResponse])
async def list_org_codes(
    org_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
    curriculum_id: uuid.UUID | None = Query(None),
    is_active: bool | None = Query(None),
) -> list[OrgCodeResponse]:
    """List activation codes for an organization."""
    await _org_svc.require_org_role(db, org_id, uuid.UUID(current_user.id))
    codes = await _code_svc.list_org_codes(
        db,
        org_id=org_id,
        curriculum_id=curriculum_id,
        is_active=is_active,
    )
    return [
        OrgCodeResponse(
            id=str(c.id),
            code=c.code,
            course_id=str(c.course_id) if c.course_id else None,
            curriculum_id=str(c.curriculum_id) if c.curriculum_id else None,
            max_uses=c.max_uses,
            times_used=c.times_used,
            is_active=c.is_active,
            created_at=c.created_at.isoformat(),
        )
        for c in codes
    ]


@router.get("/{code_id}", response_model=OrgCodeResponse)
async def get_org_code(
    org_id: uuid.UUID,
    code_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> OrgCodeResponse:
    """Get a single org code with details."""
    from sqlalchemy import select

    from app.domain.models.activation_code import ActivationCode

    await _org_svc.require_org_role(db, org_id, uuid.UUID(current_user.id))

    result = await db.execute(
        select(ActivationCode).where(
            ActivationCode.id == code_id,
            ActivationCode.organization_id == org_id,
        )
    )
    ac = result.scalar_one_or_none()
    if ac is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Code not found.")

    return OrgCodeResponse(
        id=str(ac.id),
        code=ac.code,
        course_id=str(ac.course_id) if ac.course_id else None,
        curriculum_id=str(ac.curriculum_id) if ac.curriculum_id else None,
        max_uses=ac.max_uses,
        times_used=ac.times_used,
        is_active=ac.is_active,
        created_at=ac.created_at.isoformat(),
    )


@router.post("/{code_id}/revoke", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_org_code(
    org_id: uuid.UUID,
    code_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """Revoke an unused org code and refund escrowed credits."""
    await _code_svc.revoke_org_code(
        db,
        org_id=org_id,
        code_id=code_id,
        actor_id=uuid.UUID(current_user.id),
    )


@router.get("/{code_id}/qr")
async def get_org_code_qr(
    org_id: uuid.UUID,
    code_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Generate QR code for an org activation code."""
    from sqlalchemy import select

    from app.domain.models.activation_code import ActivationCode

    await _org_svc.require_org_role(db, org_id, uuid.UUID(current_user.id))

    result = await db.execute(
        select(ActivationCode).where(
            ActivationCode.id == code_id,
            ActivationCode.organization_id == org_id,
        )
    )
    ac = result.scalar_one_or_none()
    if ac is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Code not found.")

    activation_url = f"{settings.frontend_url}/fr/activate?code={ac.code}"
    img = qrcode.make(activation_url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode()
    return {"qr_base64": f"data:image/png;base64,{b64}"}
