"""Dependencies for local JWT authentication."""

from collections.abc import Callable

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer
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
        self.role: UserRole = UserRole(jwt_payload.get("role", UserRole.user.value))

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
    """Verify JWT access token from Authorization header.

    Args:
        request: FastAPI request object
        token: Bearer token from Authorization header
        jwt_service: JWT service for token validation

    Returns:
        AuthenticatedUser instance with user claims

    Raises:
        HTTPException: 401 if token is invalid or expired
    """
    try:
        # Extract token from HTTPBearer
        access_token = token.credentials

        # Verify and decode JWT
        payload = jwt_service.verify_access_token(access_token)

        # Create authenticated user
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
    """Get current authenticated user.

    This is an alias for verify_access_token for easier use in endpoints.

    Args:
        user: Authenticated user from token verification

    Returns:
        AuthenticatedUser instance
    """
    return user


def require_role(*allowed_roles: UserRole) -> Callable:
    """FastAPI dependency factory that enforces role-based access control.

    Args:
        *allowed_roles: Roles that are permitted to access the endpoint.

    Returns:
        FastAPI dependency function that validates the user's role.

    Raises:
        HTTPException: 403 if the authenticated user's role is not in allowed_roles.

    Example:
        @router.get("/admin/users", dependencies=[Depends(require_role(UserRole.admin))])
        @router.get("/validate", dependencies=[Depends(require_role(UserRole.expert, UserRole.admin))])
    """

    async def role_guard(
        user: AuthenticatedUser = Depends(get_current_user),
    ) -> AuthenticatedUser:
        if user.role not in allowed_roles:
            logger.warning(
                "Access denied: insufficient role",
                user_id=user.id,
                user_role=user.role,
                required_roles=[r.value for r in allowed_roles],
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return user

    return role_guard


async def get_optional_user(
    request: Request, jwt_service: JWTAuthService = Depends(get_jwt_service)
) -> AuthenticatedUser | None:
    """Get current user if authenticated, None otherwise.

    This dependency doesn't raise exceptions for missing/invalid tokens,
    allowing endpoints to work for both authenticated and anonymous users.

    Args:
        request: FastAPI request object
        jwt_service: JWT service for token validation

    Returns:
        AuthenticatedUser instance if token is valid, None otherwise
    """
    try:
        # Try to get Authorization header
        auth_header = request.headers.get("authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return None

        # Extract and verify token
        token = auth_header[7:]  # Remove "Bearer " prefix
        payload = jwt_service.verify_access_token(token)

        user = AuthenticatedUser(payload)
        logger.info("Optional user authenticated", user_id=user.id)
        return user

    except Exception as e:
        logger.debug("Optional authentication failed", error=str(e))
        return None
