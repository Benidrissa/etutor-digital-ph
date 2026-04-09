"""Activation code endpoints — expert CRUD, learner redeem, QR, rate limiting."""

import base64
import io
import secrets
import string
import time
import uuid

import qrcode
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from structlog import get_logger

from app.api.deps import get_db as get_db_session
from app.api.deps_local_auth import AuthenticatedUser, get_current_user, require_role
from app.domain.models.activation_code import ActivationCode, ActivationCodeRedemption
from app.domain.models.course import Course, UserCourseEnrollment
from app.domain.models.module import Module
from app.domain.models.progress import UserModuleProgress
from app.domain.models.user import User, UserRole
from app.infrastructure.config.settings import settings

logger = get_logger(__name__)

router = APIRouter(tags=["Activation Codes"])

_ACTIVATION_RATE_STORE: dict[str, list[float]] = {}
_ACTIVATION_RATE_LIMIT = 5
_ACTIVATION_RATE_WINDOW = 60


def _check_activation_rate_limit(request: Request) -> None:
    headers = dict(request.scope.get("headers", []))
    forwarded = headers.get(b"x-forwarded-for", b"").decode()
    if forwarded:
        client_ip = forwarded.split(",")[-1].strip()
    else:
        real_ip = headers.get(b"x-real-ip", b"").decode()
        if real_ip:
            client_ip = real_ip.strip()
        else:
            client = request.scope.get("client")
            client_ip = client[0] if client else "unknown"

    now = time.time()
    window_start = now - _ACTIVATION_RATE_WINDOW
    hits = _ACTIVATION_RATE_STORE.get(client_ip, [])
    hits = [t for t in hits if t > window_start]

    if len(hits) >= _ACTIVATION_RATE_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests",
        )

    hits.append(now)
    _ACTIVATION_RATE_STORE[client_ip] = hits


def _generate_code(length: int = 12) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class GenerateCodesRequest(BaseModel):
    count: int = Field(1, ge=1, le=50)
    max_uses: int | None = Field(None, ge=1)


class ActivationCodeResponse(BaseModel):
    id: str
    code: str
    course_id: str
    max_uses: int | None
    times_used: int
    is_active: bool
    created_at: str


class CodePreviewResponse(BaseModel):
    course_title_fr: str
    course_title_en: str
    course_description_fr: str | None
    course_description_en: str | None
    cover_image_url: str | None
    expert_name: str
    valid: bool


class ManualActivateRequest(BaseModel):
    learner_email: str


class RedemptionResponse(BaseModel):
    learner_name: str
    learner_email: str
    redeemed_at: str
    method: str
    revenue_credits: int = 0


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _code_to_response(code: ActivationCode) -> ActivationCodeResponse:
    return ActivationCodeResponse(
        id=str(code.id),
        code=code.code,
        course_id=str(code.course_id),
        max_uses=code.max_uses,
        times_used=code.times_used,
        is_active=code.is_active,
        created_at=code.created_at.isoformat(),
    )


async def _get_course_for_expert(
    course_id: uuid.UUID,
    current_user: AuthenticatedUser,
    db,
) -> Course:
    result = await db.execute(select(Course).where(Course.id == course_id))
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")
    if current_user.role not in (UserRole.admin.value, UserRole.expert.value):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
        )
    if current_user.role == UserRole.expert.value and str(course.created_by) != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not own this course",
        )
    return course


async def _enroll_learner(learner_id: uuid.UUID, course_id: uuid.UUID, db) -> None:
    existing = await db.execute(
        select(UserCourseEnrollment).where(
            UserCourseEnrollment.user_id == learner_id,
            UserCourseEnrollment.course_id == course_id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        return

    enrollment = UserCourseEnrollment(
        user_id=learner_id,
        course_id=course_id,
        status="active",
        completion_pct=0.0,
    )
    db.add(enrollment)

    modules_result = await db.execute(select(Module).where(Module.course_id == course_id))
    for mod in modules_result.scalars().all():
        prog = await db.execute(
            select(UserModuleProgress).where(
                UserModuleProgress.user_id == learner_id,
                UserModuleProgress.module_id == mod.id,
            )
        )
        if prog.scalar_one_or_none() is None:
            db.add(
                UserModuleProgress(
                    user_id=learner_id,
                    module_id=mod.id,
                    status="in_progress" if mod.module_number == 1 else "locked",
                    completion_pct=0.0,
                    time_spent_minutes=0,
                )
            )


# ---------------------------------------------------------------------------
# Expert endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/expert/courses/{course_id}/codes",
    response_model=list[ActivationCodeResponse],
    status_code=status.HTTP_201_CREATED,
)
async def generate_codes(
    course_id: uuid.UUID,
    body: GenerateCodesRequest,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.expert, UserRole.admin)),
    db=Depends(get_db_session),
) -> list[ActivationCodeResponse]:
    """Generate one or more activation codes for a course. Expert/Admin only."""
    await _get_course_for_expert(course_id, current_user, db)

    codes: list[ActivationCode] = []
    for _ in range(body.count):
        for _attempt in range(10):
            raw = _generate_code()
            dup = await db.execute(select(ActivationCode).where(ActivationCode.code == raw))
            if dup.scalar_one_or_none() is None:
                break
        ac = ActivationCode(
            id=uuid.uuid4(),
            code=raw,
            course_id=course_id,
            created_by=uuid.UUID(current_user.id),
            max_uses=body.max_uses,
        )
        db.add(ac)
        codes.append(ac)

    await db.commit()
    for ac in codes:
        await db.refresh(ac)

    logger.info("Activation codes generated", course_id=str(course_id), count=len(codes))
    return [_code_to_response(ac) for ac in codes]


@router.get(
    "/expert/courses/{course_id}/codes",
    response_model=list[ActivationCodeResponse],
)
async def list_codes(
    course_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.expert, UserRole.admin)),
    db=Depends(get_db_session),
) -> list[ActivationCodeResponse]:
    """List all activation codes for a course with usage stats. Expert/Admin only."""
    await _get_course_for_expert(course_id, current_user, db)

    result = await db.execute(
        select(ActivationCode)
        .where(ActivationCode.course_id == course_id)
        .order_by(ActivationCode.created_at.desc())
    )
    return [_code_to_response(ac) for ac in result.scalars().all()]


@router.get(
    "/expert/courses/{course_id}/codes/{code_id}/redemptions",
    response_model=list[RedemptionResponse],
)
async def list_redemptions(
    course_id: uuid.UUID,
    code_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.expert, UserRole.admin)),
    db=Depends(get_db_session),
) -> list[RedemptionResponse]:
    """List all redemptions for a code — who, when, method, revenue. Expert/Admin only."""
    await _get_course_for_expert(course_id, current_user, db)

    code_result = await db.execute(
        select(ActivationCode).where(
            ActivationCode.id == code_id,
            ActivationCode.course_id == course_id,
        )
    )
    ac = code_result.scalar_one_or_none()
    if not ac:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Code not found")

    redemptions_result = await db.execute(
        select(ActivationCodeRedemption)
        .where(ActivationCodeRedemption.code_id == code_id)
        .order_by(ActivationCodeRedemption.redeemed_at.desc())
    )
    redemptions = redemptions_result.scalars().all()

    responses: list[RedemptionResponse] = []
    for r in redemptions:
        user_result = await db.execute(select(User).where(User.id == r.user_id))
        learner = user_result.scalar_one_or_none()
        responses.append(
            RedemptionResponse(
                learner_name=learner.name if learner else "Unknown",
                learner_email=learner.email or "" if learner else "",
                redeemed_at=r.redeemed_at.isoformat(),
                method=r.method,
                revenue_credits=0,
            )
        )
    return responses


@router.post(
    "/expert/courses/{course_id}/codes/{code_id}/activate",
    status_code=status.HTTP_201_CREATED,
)
async def manual_activate(
    course_id: uuid.UUID,
    code_id: uuid.UUID,
    body: ManualActivateRequest,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.expert, UserRole.admin)),
    db=Depends(get_db_session),
) -> dict:
    """Manually activate a code for a learner by email. Expert/Admin only."""
    await _get_course_for_expert(course_id, current_user, db)

    code_result = await db.execute(
        select(ActivationCode).where(
            ActivationCode.id == code_id,
            ActivationCode.course_id == course_id,
        )
    )
    ac = code_result.scalar_one_or_none()
    if not ac:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Code not found")
    if not ac.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Code is inactive")
    if ac.max_uses is not None and ac.times_used >= ac.max_uses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Code usage limit reached"
        )

    learner_result = await db.execute(select(User).where(User.email == body.learner_email))
    learner = learner_result.scalar_one_or_none()
    if not learner:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No user found with email {body.learner_email}",
        )

    await _enroll_learner(learner.id, course_id, db)

    redemption = ActivationCodeRedemption(
        id=uuid.uuid4(),
        code_id=code_id,
        user_id=learner.id,
        method="manual",
    )
    db.add(redemption)
    ac.times_used += 1

    await db.commit()
    logger.info(
        "Manual activation",
        code_id=str(code_id),
        learner_email=body.learner_email,
        actor=current_user.id,
    )
    return {"status": "activated", "learner_email": body.learner_email}


@router.get("/expert/courses/{course_id}/codes/{code_id}/qr")
async def get_qr_code(
    course_id: uuid.UUID,
    code_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.expert, UserRole.admin)),
    db=Depends(get_db_session),
) -> dict:
    """Return QR code as base64 PNG for an activation code. Expert/Admin only."""
    await _get_course_for_expert(course_id, current_user, db)

    code_result = await db.execute(
        select(ActivationCode).where(
            ActivationCode.id == code_id,
            ActivationCode.course_id == course_id,
        )
    )
    ac = code_result.scalar_one_or_none()
    if not ac:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Code not found")

    activation_url = f"{settings.frontend_url}/fr/activate?code={ac.code}"
    img = qrcode.make(activation_url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode()
    return {"qr_base64": f"data:image/png;base64,{b64}"}


# ---------------------------------------------------------------------------
# Learner endpoints (public preview + authenticated redeem)
# ---------------------------------------------------------------------------


@router.get("/activate/{code}/preview", response_model=CodePreviewResponse)
async def preview_code(
    code: str,
    request: Request,
    db=Depends(get_db_session),
) -> CodePreviewResponse:
    """Preview course info for an activation code. Public, rate-limited 5/min/IP."""
    _check_activation_rate_limit(request)

    code_result = await db.execute(
        select(ActivationCode).where(ActivationCode.code == code.upper())
    )
    ac = code_result.scalar_one_or_none()

    if not ac or not ac.is_active:
        return CodePreviewResponse(
            course_title_fr="",
            course_title_en="",
            course_description_fr=None,
            course_description_en=None,
            cover_image_url=None,
            expert_name="",
            valid=False,
        )

    if ac.max_uses is not None and ac.times_used >= ac.max_uses:
        return CodePreviewResponse(
            course_title_fr="",
            course_title_en="",
            course_description_fr=None,
            course_description_en=None,
            cover_image_url=None,
            expert_name="",
            valid=False,
        )

    course_result = await db.execute(select(Course).where(Course.id == ac.course_id))
    course = course_result.scalar_one_or_none()
    if not course:
        return CodePreviewResponse(
            course_title_fr="",
            course_title_en="",
            course_description_fr=None,
            course_description_en=None,
            cover_image_url=None,
            expert_name="",
            valid=False,
        )

    expert_name = ""
    if course.created_by:
        expert_result = await db.execute(select(User).where(User.id == course.created_by))
        expert = expert_result.scalar_one_or_none()
        if expert:
            expert_name = expert.name

    return CodePreviewResponse(
        course_title_fr=course.title_fr,
        course_title_en=course.title_en,
        course_description_fr=course.description_fr,
        course_description_en=course.description_en,
        cover_image_url=course.cover_image_url,
        expert_name=expert_name,
        valid=True,
    )


@router.post("/activate/{code}/redeem", status_code=status.HTTP_201_CREATED)
async def redeem_code(
    code: str,
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
) -> dict:
    """Redeem an activation code to enroll in a course. Authenticated, rate-limited 5/min/IP."""
    _check_activation_rate_limit(request)

    code_result = await db.execute(
        select(ActivationCode).where(ActivationCode.code == code.upper())
    )
    ac = code_result.scalar_one_or_none()
    if not ac:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid activation code")
    if not ac.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Activation code is inactive"
        )
    if ac.max_uses is not None and ac.times_used >= ac.max_uses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Activation code usage limit reached"
        )

    learner_id = uuid.UUID(current_user.id)

    dup = await db.execute(
        select(ActivationCodeRedemption).where(
            ActivationCodeRedemption.code_id == ac.id,
            ActivationCodeRedemption.user_id == learner_id,
        )
    )
    if dup.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You have already redeemed this code",
        )

    await _enroll_learner(learner_id, ac.course_id, db)

    redemption = ActivationCodeRedemption(
        id=uuid.uuid4(),
        code_id=ac.id,
        user_id=learner_id,
        method="code",
    )
    db.add(redemption)
    ac.times_used += 1

    await db.commit()
    logger.info(
        "Activation code redeemed",
        code=code.upper(),
        user_id=current_user.id,
        course_id=str(ac.course_id),
    )
    return {"status": "enrolled", "course_id": str(ac.course_id)}
