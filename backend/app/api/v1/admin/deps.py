"""Admin-specific dependencies for role-based access control."""

from fastapi import Depends, HTTPException, status

from app.api.deps_local_auth import AuthenticatedUser, get_current_user


class AdminUser(AuthenticatedUser):
    """Represents an authenticated admin user."""


async def require_admin(
    user: AuthenticatedUser = Depends(get_current_user),
) -> AuthenticatedUser:
    """Require the current user to have the 'admin' role.

    Raises:
        HTTPException: 403 if user is not an admin
    """
    role = getattr(user, "role", None)
    if role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user
