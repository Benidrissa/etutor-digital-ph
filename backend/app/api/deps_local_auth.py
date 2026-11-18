"""Dependencies for local JWT authentication."""

import re
import uuid
from collections.abc import Callable

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from structlog import get_logger

from ..ai.usage_context import set_ai_context_user
from ..domain.models.user import UserRole
from ..domain.services.jwt_auth_service import JWTAuthService
from .deps import get_db

logger = get_logger(__name__)

#: Roles that read every unit without a subscription.
_STAFF_ROLES = frozenset({UserRole.admin.value, UserRole.sub_admin.value})

#: A canonical unit number ("1.2"); its minor part is the unit's place in the module.
_UNIT_NUMBER_RE = re.compile(r"^\d+\.(\d+)$")

# Security scheme for JWT Bearer tokens
security = HTTPBearer()


class AuthenticatedUser:
    """Represents an authenticated user from JWT claims."""

    def __init__(self, jwt_payload: dict):
        self.id = jwt_payload["sub"]
        self.email = jwt_payload.get("email")
        self.phone_number = jwt_payload.get("phone_number")
        self.preferred_language = jwt_payload.get("preferred_language", "fr")
        self.country = jwt_payload.get("country")
        self.current_level = jwt_payload.get("current_level", 1)
        self.professional_role = jwt_payload.get("professional_role")
        self.role: str = jwt_payload.get("role", UserRole.user.value)

        # JWT metadata
        self.exp = jwt_payload.get("exp", 0)
        self.iat = jwt_payload.get("iat", 0)
        self.iss = jwt_payload.get("iss")


def get_jwt_service() -> JWTAuthService:
    """Get JWT service instance."""
    return JWTAuthService()


async def verify_access_token(
    request: Request,
    token: str = Depends(security),
    jwt_service: JWTAuthService = Depends(get_jwt_service),
) -> AuthenticatedUser:
    """Verify JWT access token from Authorization header."""
    try:
        access_token = token.credentials
        payload = jwt_service.verify_access_token(access_token)
        user = AuthenticatedUser(payload)
        set_ai_context_user(user.id)  # attribute downstream AI usage to this user (#2629)
        logger.info("User authenticated via JWT", user_id=user.id, email=user.email)
        return user
    except jwt.ExpiredSignatureError:
        logger.warning("Expired JWT token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError as e:
        logger.warning("Invalid JWT token", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception as e:
        logger.error("Token verification failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(
    user: AuthenticatedUser = Depends(verify_access_token),
) -> AuthenticatedUser:
    """Get current authenticated user."""
    return user


def require_role(*roles: UserRole) -> Callable:
    """Factory for role-based access control dependency."""
    allowed = {r.value for r in roles}

    async def _check_role(
        user: AuthenticatedUser = Depends(get_current_user),
    ) -> AuthenticatedUser:
        if user.role not in allowed:
            logger.warning(
                "Access denied - insufficient role",
                user_id=user.id,
                user_role=user.role,
                required_roles=list(allowed),
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return user

    return _check_role


async def get_optional_user(
    request: Request, jwt_service: JWTAuthService = Depends(get_jwt_service)
) -> AuthenticatedUser | None:
    """Get current user if authenticated, None otherwise."""
    try:
        auth_header = request.headers.get("authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return None
        token = auth_header[7:]
        payload = jwt_service.verify_access_token(token)
        user = AuthenticatedUser(payload)
        set_ai_context_user(user.id)  # attribute downstream AI usage to this user (#2629)
        logger.info("Optional user authenticated", user_id=user.id)
        return user
    except Exception as e:
        logger.debug("Optional authentication failed", error=str(e))
        return None


async def require_active_subscription(
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
) -> AuthenticatedUser:
    """Require an active subscription to access content.

    Admin users bypass this check (they have auto-provisioned subscriptions).
    First unit of each module is free — caller must check separately if needed.

    Raises:
        HTTPException: 403 if no active subscription.
    """
    from ..domain.services.subscription_service import SubscriptionService
    from ..infrastructure.persistence.database import get_db_session

    async for session in get_db_session():
        sub = await SubscriptionService().get_active_subscription(uuid.UUID(user.id), session)
        if sub is not None:
            return user
        break

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": "subscription_required",
            "message": "An active subscription is required to access this content.",
        },
    )


async def _resolve_module_uuid(module_id: str | None, session) -> uuid.UUID | None:
    """Best-effort resolution of a path ``module_id`` to its UUID.

    Accepts a UUID string or a module code (``M01``). Returns ``None`` when the
    value is absent or unresolvable — callers treat that as "couldn't scope".
    """
    if not module_id:
        return None
    try:
        return uuid.UUID(module_id)
    except (ValueError, AttributeError):
        pass

    from ..domain.models.module import Module

    code = re.match(r"^M(\d{2})$", module_id.upper())
    if not code:
        return None
    result = await session.execute(
        select(Module.id).where(Module.module_number == int(code.group(1)))
    )
    return result.scalars().first()


async def require_subscription_or_first_unit(
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
) -> AuthenticatedUser:
    """Allow free units of a module for free; require subscription for others.

    Reads `unit_id` from path params (canonical `unit_number` form, e.g. '1.2').
    The number of free units is controlled by the 'subscription-free-units-count'
    platform setting (default: 2). Falls back to DB order_index check when
    unit_id format is unrecognised.
    """
    from ..domain.models.module_unit import ModuleUnit
    from ..domain.services.platform_settings_service import SettingsCache
    from ..domain.services.subscription_service import SubscriptionService
    from ..infrastructure.persistence.database import get_db_session

    if user.role in ("admin", "sub_admin"):
        return user

    unit_id = request.path_params.get("unit_id") or request.path_params.get("unitId")
    module_id = request.path_params.get("module_id") or request.path_params.get("moduleId")

    free_count = SettingsCache.instance().get("subscription-free-units-count", 2)
    if unit_number_is_free(unit_id, free_count):
        return user

    # Check subscription
    async for session in get_db_session():
        sub = await SubscriptionService().get_active_subscription(uuid.UUID(user.id), session)
        if sub is not None:
            return user

        # No subscription — fall back to DB order_index check.
        # Scope by module: a unit number like "1.3" is shared across many modules,
        # so an unscoped lookup matches multiple rows and used to crash the request
        # with MultipleResultsFound → unhandled 500 for learners (#2459). We resolve
        # the module from the path and use .first() so the gate degrades to a clean
        # 403 even if the module can't be resolved.
        if unit_id:
            unit_query = select(ModuleUnit.order_index).where(ModuleUnit.unit_number == unit_id)
            module_uuid = await _resolve_module_uuid(module_id, session)
            if module_uuid is not None:
                unit_query = unit_query.where(ModuleUnit.module_id == module_uuid)
            result = await session.execute(unit_query.limit(1))
            order = result.scalars().first()
            if order is not None and order < free_count:
                return user
        break

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": "subscription_required",
            "message": "An active subscription is required to access this content. The first lesson of each module is free.",
        },
    )


def unit_number_is_free(unit_number: str | None, free_count: int) -> bool:
    """A canonical unit number ("1.2") whose place in its module is within the free count."""
    match = _UNIT_NUMBER_RE.match(unit_number) if unit_number else None
    return match is not None and int(match.group(1)) <= free_count


def unit_is_free(unit_number: str | None, order_index: int | None, free_count: int) -> bool:
    """The free-unit rule of :func:`require_subscription_or_first_unit`, for one unit.

    A unit is free when its number places it within the first ``free_count``
    units of its module ("1.1", "1.2" with the default of 2), or else when its
    ``order_index`` (0-based) does.
    """
    if unit_number_is_free(unit_number, free_count):
        return True
    return order_index is not None and order_index < free_count


async def module_story_access(
    session: AsyncSession, user: AuthenticatedUser, module_id: uuid.UUID
) -> bool:
    """Whether ``user`` may read the story of the module ``module_id``.

    A module story tells every unit of its module, the paid ones included. So
    it is open to admins and sub-admins, to a learner with an active
    subscription, and otherwise only when every unit of the module is free
    under the lessons' own rule (:func:`unit_is_free`). A module with no unit
    has nothing paid to protect: the story routes answer 404 for it anyway.
    """
    from ..domain.models.module_unit import ModuleUnit
    from ..domain.services.platform_settings_service import SettingsCache
    from ..domain.services.subscription_service import SubscriptionService

    if user.role in _STAFF_ROLES:
        return True
    try:
        user_uuid: uuid.UUID | None = uuid.UUID(str(user.id))
    except (TypeError, ValueError):
        user_uuid = None
    if (
        user_uuid is not None
        and await SubscriptionService().get_active_subscription(user_uuid, session) is not None
    ):
        return True

    free_count = SettingsCache.instance().get("subscription-free-units-count", 2)
    units = (
        await session.execute(
            select(ModuleUnit.unit_number, ModuleUnit.order_index).where(
                ModuleUnit.module_id == module_id
            )
        )
    ).all()
    return all(unit_is_free(u.unit_number, u.order_index, free_count) for u in units)


async def require_subscription_or_free_module(
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> AuthenticatedUser:
    """Gate of a module story: staff, a subscriber, or a module whose units are all free.

    Reads ``module_id`` from the path. A value that is not a UUID passes: the
    route answers 404 ``module_not_found`` for it, as it does for an unknown
    module, so a learner and a subscriber see the same answer. The session is
    the request's own (``get_db``), shared with the route.

    Raises:
        HTTPException: 403 ``{"code": "subscription_required"}``.
    """
    if user.role in _STAFF_ROLES:
        return user
    try:
        module_id = uuid.UUID(str(request.path_params.get("module_id")))
    except (TypeError, ValueError):
        return user
    if await module_story_access(session, user, module_id):
        return user
    logger.info("Module story refused: subscription required", user_id=user.id)
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": "subscription_required",
            "message": "An active subscription is required for the story of this module.",
        },
    )


def require_enrollment(course_id_param: str = "course_id") -> Callable:
    """Factory for enrollment-based access control dependency.

    Verifies that the authenticated user is actively enrolled in the course
    identified by `course_id_param` in the path parameters.

    Raises:
        HTTPException: 401 if not authenticated, 403 if not enrolled.
    """

    async def _check_enrollment(
        request: Request,
        user: AuthenticatedUser = Depends(get_current_user),
    ) -> AuthenticatedUser:
        from ..domain.models.course import UserCourseEnrollment
        from ..infrastructure.persistence.database import get_db_session

        raw_id = request.path_params.get(course_id_param)
        if not raw_id:
            return user

        try:
            course_uuid = uuid.UUID(str(raw_id))
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid course identifier",
            )

        enrollment = None
        async for session in get_db_session():
            result = await session.execute(
                select(UserCourseEnrollment).where(
                    UserCourseEnrollment.user_id == uuid.UUID(user.id),
                    UserCourseEnrollment.course_id == course_uuid,
                    UserCourseEnrollment.status == "active",
                )
            )
            enrollment = result.scalar_one_or_none()
            break

        if not enrollment and user.role not in ("admin", "sub_admin"):
            logger.warning(
                "Access denied - not enrolled in course",
                user_id=user.id,
                course_id=str(course_uuid),
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You must be enrolled in this course to access this content",
            )

        return user

    return _check_enrollment
