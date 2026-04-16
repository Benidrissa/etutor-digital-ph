"""Certificate endpoints — expert template management, learner certificates, public verification."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from structlog import get_logger

from app.api.deps import get_db as get_db_session
from app.api.deps_local_auth import AuthenticatedUser, get_current_user, require_role
from app.api.v1.schemas.certificate import (
    CertificateDetail,
    CertificateListItem,
    CertificateTemplateCreate,
    CertificateTemplateResponse,
    CertificateTemplateUpdate,
    CertificateVerifyResponse,
)
from app.domain.models.user import User, UserRole
from app.domain.services.certificate_service import CertificateService

logger = get_logger(__name__)
router = APIRouter(tags=["Certificates"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _template_to_response(t) -> CertificateTemplateResponse:
    return CertificateTemplateResponse(
        id=str(t.id),
        course_id=str(t.course_id),
        title_fr=t.title_fr,
        title_en=t.title_en,
        organization_name=t.organization_name,
        signatory_name=t.signatory_name,
        signatory_title=t.signatory_title,
        logo_url=t.logo_url,
        additional_text_fr=t.additional_text_fr,
        additional_text_en=t.additional_text_en,
        is_active=t.is_active,
        created_at=t.created_at,
        updated_at=t.updated_at,
    )


# ---------------------------------------------------------------------------
# Expert template endpoints (#767)
# ---------------------------------------------------------------------------


@router.post(
    "/expert/courses/{course_id}/certificate-template",
    response_model=CertificateTemplateResponse,
    status_code=status.HTTP_200_OK,
)
async def upsert_certificate_template(
    course_id: uuid.UUID,
    body: CertificateTemplateCreate,
    db: AsyncSession = Depends(get_db_session),
    current_user: AuthenticatedUser = Depends(
        require_role(UserRole.admin, UserRole.sub_admin, UserRole.expert)
    ),
):
    """Create or update the certificate template for a course."""
    svc = CertificateService(db)
    try:
        template = await svc.create_or_update_template(
            course_id=course_id,
            expert_id=uuid.UUID(current_user.id),
            data=body.model_dump(exclude_unset=True),
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    return _template_to_response(template)


@router.get(
    "/expert/courses/{course_id}/certificate-template",
    response_model=CertificateTemplateResponse,
)
async def get_certificate_template(
    course_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
    current_user: AuthenticatedUser = Depends(
        require_role(UserRole.admin, UserRole.sub_admin, UserRole.expert)
    ),
):
    """Get the certificate template for a course."""
    svc = CertificateService(db)
    template = await svc.get_template(course_id)
    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No certificate template for this course",
        )
    return _template_to_response(template)


# ---------------------------------------------------------------------------
# Learner certificate endpoints (#768)
# ---------------------------------------------------------------------------


@router.get("/certificates", response_model=list[CertificateListItem])
async def list_my_certificates(
    db: AsyncSession = Depends(get_db_session),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """List all certificates earned by the current user."""
    svc = CertificateService(db)
    certs = await svc.get_user_certificates(uuid.UUID(current_user.id))
    return [
        CertificateListItem(
            id=str(c.id),
            course_id=str(c.course_id),
            course_title_fr=c.course.title_fr if c.course else "",
            course_title_en=c.course.title_en if c.course else "",
            verification_code=c.verification_code,
            average_score=c.average_score,
            completed_at=c.completed_at,
            issued_at=c.issued_at,
            status=c.status,
        )
        for c in certs
    ]


@router.get("/certificates/{certificate_id}", response_model=CertificateDetail)
async def get_certificate_detail(
    certificate_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Get certificate detail (owner only)."""
    svc = CertificateService(db)
    cert = await svc.get_certificate(certificate_id)
    if not cert or str(cert.user_id) != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Certificate not found")

    tmpl_resp = _template_to_response(cert.template) if cert.template else None
    return CertificateDetail(
        id=str(cert.id),
        course_id=str(cert.course_id),
        course_title_fr=cert.course.title_fr if cert.course else "",
        course_title_en=cert.course.title_en if cert.course else "",
        verification_code=cert.verification_code,
        average_score=cert.average_score,
        completed_at=cert.completed_at,
        issued_at=cert.issued_at,
        status=cert.status,
        pdf_url=cert.pdf_url,
        metadata_json=cert.metadata_json,
        template=tmpl_resp,
    )


@router.get("/certificates/{certificate_id}/download")
async def download_certificate_pdf(
    certificate_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Download certificate PDF (owner only)."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.domain.models.certificate import Certificate
    from app.domain.services.certificate_pdf_service import CertificatePDFService

    svc = CertificateService(db)
    cert = await svc.get_certificate(certificate_id)
    if not cert or str(cert.user_id) != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Certificate not found")

    # If PDF already exists in MinIO, stream it
    if cert.pdf_url:
        try:
            from app.infrastructure.storage.s3 import S3StorageService

            storage = S3StorageService()
            key = f"certificates/{cert.id}.pdf"
            pdf_bytes = await storage.download_bytes(key)
            return StreamingResponse(
                iter([pdf_bytes]),
                media_type="application/pdf",
                headers={
                    "Content-Disposition": f'attachment; filename="certificate-{cert.verification_code}.pdf"'
                },
            )
        except Exception:
            logger.warning("PDF download from storage failed, regenerating", cert_id=str(cert.id))

    # Generate on-demand if not stored yet
    if not cert.template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Certificate template not available for PDF generation",
        )

    # Load user record for PDF
    user = await db.get(User, cert.user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="User not found")

    pdf_svc = CertificatePDFService()
    language = current_user.preferred_language or "fr"
    url = await pdf_svc.generate_and_store(cert, cert.template, cert.course, user, db, language)

    # Now download the freshly generated PDF
    from app.infrastructure.storage.s3 import S3StorageService

    storage = S3StorageService()
    key = f"certificates/{cert.id}.pdf"
    pdf_bytes = await storage.download_bytes(key)
    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="certificate-{cert.verification_code}.pdf"'
        },
    )


# ---------------------------------------------------------------------------
# Public verification endpoint (#768)
# ---------------------------------------------------------------------------


@router.get("/verify/{verification_code}", response_model=CertificateVerifyResponse)
async def verify_certificate(
    verification_code: str,
    db: AsyncSession = Depends(get_db_session),
):
    """Public certificate verification — no authentication required."""
    from sqlalchemy.orm import selectinload

    svc = CertificateService(db)
    cert = await svc.verify_certificate(verification_code)
    if not cert:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=CertificateVerifyResponse(valid=False).model_dump(),
        )

    # Load user name
    user = await db.get(User, cert.user_id)
    learner_name = user.name if user else None

    return CertificateVerifyResponse(
        valid=True,
        learner_name=learner_name,
        course_title_fr=cert.course.title_fr if cert.course else None,
        course_title_en=cert.course.title_en if cert.course else None,
        completion_date=cert.completed_at,
        average_score=cert.average_score,
        organization_name=cert.template.organization_name if cert.template else None,
        signatory_name=cert.template.signatory_name if cert.template else None,
        status=cert.status,
    )
