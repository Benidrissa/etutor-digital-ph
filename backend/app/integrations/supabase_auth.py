"""Supabase Auth integration for SantePublique AOF.

Handles JWT validation, user profile sync, and OAuth flows.
All auth flows go through Supabase → Frontend → Backend API validation.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
import jwt
from fastapi import HTTPException, status
from structlog import get_logger

from ..infrastructure.config.settings import settings

logger = get_logger(__name__)


class SupabaseAuthError(Exception):
    """Supabase authentication error."""

    pass


class SupabaseAuthClient:
    """Client for Supabase Auth API operations."""

    def __init__(self):
        self.base_url = settings.supabase_url
        self.service_key = settings.supabase_service_role_key
        self.jwt_secret = settings.supabase_jwt_secret

        self._client = httpx.AsyncClient(
            base_url=f"{self.base_url}/auth/v1",
            headers={
                "Authorization": f"Bearer {self.service_key}",
                "apikey": self.service_key,
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(10.0),
        )

    async def verify_jwt(self, token: str) -> dict[str, Any]:
        """Verify and decode Supabase JWT token.

        Args:
            token: JWT access token from Authorization header

        Returns:
            Decoded JWT payload with user claims

        Raises:
            SupabaseAuthError: If token is invalid or expired
        """
        try:
            # Verify JWT signature and decode payload
            payload = jwt.decode(
                token,
                self.jwt_secret,
                algorithms=["HS256"],
                audience="authenticated",
                issuer=self.base_url,
            )

            # Validate required claims
            required_claims = ["sub", "email", "exp"]
            for claim in required_claims:
                if claim not in payload:
                    raise SupabaseAuthError(f"Missing required claim: {claim}")

            # Check expiration
            exp = payload.get("exp", 0)
            if datetime.fromtimestamp(exp, tz=UTC) <= datetime.now(UTC):
                raise SupabaseAuthError("Token has expired")

            return payload

        except jwt.InvalidTokenError as e:
            logger.warning("Invalid JWT token", error=str(e))
            raise SupabaseAuthError(f"Invalid token: {e}")
        except Exception as e:
            logger.error("JWT verification failed", error=str(e))
            raise SupabaseAuthError(f"Token verification failed: {e}")

    async def get_user_profile(self, user_id: str) -> dict[str, Any] | None:
        """Fetch user profile from Supabase Auth.

        Args:
            user_id: Supabase user UUID

        Returns:
            User profile data or None if not found
        """
        try:
            response = await self._client.get(f"/admin/users/{user_id}")

            if response.status_code == 404:
                return None
            elif response.status_code != 200:
                raise SupabaseAuthError(f"Failed to fetch user profile: {response.text}")

            return response.json()

        except httpx.RequestError as e:
            logger.error("Failed to fetch user profile", user_id=user_id, error=str(e))
            raise SupabaseAuthError(f"Network error: {e}")

    async def update_user_metadata(self, user_id: str, metadata: dict[str, Any]) -> None:
        """Update user metadata in Supabase Auth.

        Args:
            user_id: Supabase user UUID
            metadata: Custom metadata to store (preferred_language, country, etc.)
        """
        try:
            response = await self._client.put(
                f"/admin/users/{user_id}", json={"user_metadata": metadata}
            )

            if response.status_code != 200:
                raise SupabaseAuthError(f"Failed to update user metadata: {response.text}")

            logger.info("Updated user metadata", user_id=user_id, metadata=metadata)

        except httpx.RequestError as e:
            logger.error("Failed to update user metadata", user_id=user_id, error=str(e))
            raise SupabaseAuthError(f"Network error: {e}")

    async def list_users(self, page: int = 1, per_page: int = 20) -> dict[str, Any]:
        """List all users (admin operation).

        Args:
            page: Page number (1-based)
            per_page: Users per page (max 1000)

        Returns:
            List of users with pagination info
        """
        try:
            params = {"page": page, "per_page": per_page}
            response = await self._client.get("/admin/users", params=params)

            if response.status_code != 200:
                raise SupabaseAuthError(f"Failed to list users: {response.text}")

            return response.json()

        except httpx.RequestError as e:
            logger.error("Failed to list users", error=str(e))
            raise SupabaseAuthError(f"Network error: {e}")

    async def delete_user(self, user_id: str) -> None:
        """Delete user account (GDPR compliance).

        Args:
            user_id: Supabase user UUID to delete
        """
        try:
            response = await self._client.delete(f"/admin/users/{user_id}")

            if response.status_code == 404:
                logger.warning("User not found for deletion", user_id=user_id)
                return
            elif response.status_code != 200:
                raise SupabaseAuthError(f"Failed to delete user: {response.text}")

            logger.info("Deleted user account", user_id=user_id)

        except httpx.RequestError as e:
            logger.error("Failed to delete user", user_id=user_id, error=str(e))
            raise SupabaseAuthError(f"Network error: {e}")

    async def close(self):
        """Close HTTP client."""
        await self._client.aclose()


class AuthenticatedUser:
    """Represents an authenticated user from JWT claims."""

    def __init__(self, jwt_payload: dict[str, Any]):
        self.id: UUID = UUID(jwt_payload["sub"])
        self.email: str = jwt_payload["email"]

        # Extract custom claims from user_metadata
        user_metadata = jwt_payload.get("user_metadata", {})
        self.preferred_language: str = user_metadata.get("preferred_language", "fr")
        self.country: str | None = user_metadata.get("country")
        self.current_level: int = user_metadata.get("current_level", 1)
        self.professional_role: str | None = user_metadata.get("professional_role")

        # Standard claims
        self.role: str = jwt_payload.get("role", "authenticated")
        self.aud: str = jwt_payload.get("aud", "authenticated")
        self.exp: int = jwt_payload.get("exp", 0)

    @property
    def is_expired(self) -> bool:
        """Check if JWT token is expired."""
        return datetime.fromtimestamp(self.exp, tz=UTC) <= datetime.now(UTC)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        return {
            "id": str(self.id),
            "email": self.email,
            "preferred_language": self.preferred_language,
            "country": self.country,
            "current_level": self.current_level,
            "professional_role": self.professional_role,
            "role": self.role,
        }


# Global client instance
_supabase_client: SupabaseAuthClient | None = None


async def get_supabase_client() -> SupabaseAuthClient:
    """Get singleton Supabase client instance."""
    global _supabase_client
    if _supabase_client is None:
        _supabase_client = SupabaseAuthClient()
    return _supabase_client


async def verify_auth_token(authorization: str) -> AuthenticatedUser:
    """Verify Authorization header and return authenticated user.

    Args:
        authorization: "Bearer <jwt-token>" from request header

    Returns:
        AuthenticatedUser instance with claims

    Raises:
        HTTPException: 401 if authentication fails
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        # Extract token from "Bearer <token>"
        if not authorization.startswith("Bearer "):
            raise SupabaseAuthError("Invalid Authorization header format")

        token = authorization[7:]  # Remove "Bearer " prefix

        # Verify JWT with Supabase
        client = await get_supabase_client()
        payload = await client.verify_jwt(token)

        # Create authenticated user
        user = AuthenticatedUser(payload)

        logger.info("User authenticated", user_id=str(user.id), email=user.email)
        return user

    except SupabaseAuthError as e:
        logger.warning("Authentication failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Authentication failed: {e}",
            headers={"WWW-Authenticate": "Bearer"},
        )
