"""Dependencies for local JWT authentication."""

import uuid
from collections.abc import Callable

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer
from sqlalchemy import select
from structlog import get_logger

from ..domain.models.user import UserRole
from ..domain.services.jwt_auth_service import JWTAuthService

logger = get_logger(__name__)

# Security scheme for JWT Bearer tokens
security = HTTPBearer()


class AuthenticatedUser:
    """Represents an authenticated user from JWT claims."""

    def __init__(self, jwt_payload: dict):
        self.id = jwt_payload["sub"]
        self.email = jwt_payload["email"]
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


async def require_subscription_or_first_unit(
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
) -> AuthenticatedUser:
    """Allow free units of a module for free; require subscription for others.

    Reads `unit_id` from path params (e.g. 'M01-U02'). The number of free units
    is controlled by the 'subscription-free-units-count' platform setting (default: 2).
    Falls back to DB order_index check when unit_id format is unrecognised.
    """
    import re

    from ..domain.models.module_unit import ModuleUnit
    from ..domain.services.platform_settings_service import SettingsCache
    from ..domain.services.subscription_service import SubscriptionService
    from ..infrastructure.persistence.database import get_db_session

    if user.role == "admin":
        return user

    unit_id = request.path_params.get("unit_id") or request.path_params.get("unitId")

    free_count = SettingsCache.instance().get("subscription-free-units-count", 2)
    m = re.search(r"-U0*(\d+)$", unit_id.upper()) if unit_id else None
    if m and int(m.group(1)) <= free_count:
        return user

    # Check subscription
    async for session in get_db_session():
        sub = await SubscriptionService().get_active_subscription(uuid.UUID(user.id), session)
        if sub is not None:
            return user

        # No subscription — fall back to DB order_index check
        if unit_id:
            result = await session.execute(
                select(ModuleUnit.order_index).where(ModuleUnit.unit_number == unit_id)
            )
            order = result.scalar_one_or_none()
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

        if not enrollment and user.role != "admin":
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
