"""JWT Authentication service for TOTP MFA system."""

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Any

import jwt
from structlog import get_logger

from app.domain.services.platform_settings_service import SettingsCache
from app.infrastructure.config.settings import settings

logger = get_logger(__name__)


class JWTAuthService:
    """Service for managing JWT tokens and refresh tokens."""

    def __init__(self):
        self.jwt_secret = settings.jwt_secret
        self.jwt_algorithm = "HS256"
        _cache = SettingsCache.instance()
        self.access_token_expire_minutes = _cache.get("auth.access_token_expiry_minutes", 15)
        self.refresh_token_expire_days = _cache.get("auth.refresh_token_expiry_days", 90)

    def create_access_token(self, user_id: str, email: str, **extra_claims: Any) -> str:
        """Create a JWT access token.

        Args:
            user_id: User UUID
            email: User email
            **extra_claims: Additional claims to include

        Returns:
            JWT access token
        """
        now = datetime.utcnow()
        expire = now + timedelta(minutes=self.access_token_expire_minutes)

        payload = {
            "sub": user_id,
            "email": email,
            "exp": expire,
            "iat": now,
            "iss": "santepublique-aof",
            "aud": "santepublique-aof-frontend",
            "type": "access",
            **extra_claims,
        }

        token = jwt.encode(payload, self.jwt_secret, algorithm=self.jwt_algorithm)
        logger.info("Created access token", user_id=user_id, expires_at=expire.isoformat())
        return token

    def create_refresh_token(self) -> str:
        """Create a random refresh token.

        Returns:
            Cryptographically secure random token
        """
        return secrets.token_urlsafe(64)

    def hash_token(self, token: str) -> str:
        """Hash a token for secure storage.

        Args:
            token: Raw token to hash

        Returns:
            SHA-256 hash of the token
        """
        return hashlib.sha256(token.encode()).hexdigest()

    def verify_access_token(self, token: str) -> dict[str, Any]:
        """Verify and decode an access token.

        Args:
            token: JWT access token

        Returns:
            Decoded token payload

        Raises:
            jwt.InvalidTokenError: If token is invalid or expired
        """
        try:
            payload = jwt.decode(
                token,
                self.jwt_secret,
                algorithms=[self.jwt_algorithm],
                audience="santepublique-aof-frontend",
                issuer="santepublique-aof",
            )

            # Verify token type
            if payload.get("type") != "access":
                raise jwt.InvalidTokenError("Invalid token type")

            return payload

        except jwt.ExpiredSignatureError:
            logger.warning("Access token expired")
            raise
        except jwt.InvalidTokenError as e:
            logger.warning("Invalid access token", error=str(e))
            raise

    def get_token_expiry(self, token_type: str = "refresh") -> datetime:
        """Get expiration datetime for a token type.

        Args:
            token_type: "access" or "refresh"

        Returns:
            Expiration datetime
        """
        now = datetime.utcnow()
        if token_type == "access":
            return now + timedelta(minutes=self.access_token_expire_minutes)
        else:  # refresh
            return now + timedelta(days=self.refresh_token_expire_days)

    def generate_magic_link_token(self) -> str:
        """Generate a secure token for magic links.

        Returns:
            Cryptographically secure random token
        """
        return secrets.token_urlsafe(32)

    def create_password_reset_token(self, user_id: str, email: str) -> str:
        """Create a JWT token for password reset (magic link).

        Args:
            user_id: User UUID
            email: User email

        Returns:
            JWT token for password reset
        """
        now = datetime.utcnow()
        expire = now + timedelta(hours=SettingsCache.instance().get("auth.magic_link_expiry_hours", 1))

        payload = {
            "sub": user_id,
            "email": email,
            "exp": expire,
            "iat": now,
            "iss": "santepublique-aof",
            "aud": "santepublique-aof-magic-link",
            "type": "magic_link",
        }

        token = jwt.encode(payload, self.jwt_secret, algorithm=self.jwt_algorithm)
        logger.info("Created magic link token", user_id=user_id, expires_at=expire.isoformat())
        return token

    def verify_magic_link_token(self, token: str) -> dict[str, Any]:
        """Verify a magic link JWT token.

        Args:
            token: JWT magic link token

        Returns:
            Decoded token payload

        Raises:
            jwt.InvalidTokenError: If token is invalid or expired
        """
        try:
            payload = jwt.decode(
                token,
                self.jwt_secret,
                algorithms=[self.jwt_algorithm],
                audience="santepublique-aof-magic-link",
                issuer="santepublique-aof",
            )

            # Verify token type
            if payload.get("type") != "magic_link":
                raise jwt.InvalidTokenError("Invalid token type")

            return payload

        except jwt.ExpiredSignatureError:
            logger.warning("Magic link token expired")
            raise
        except jwt.InvalidTokenError as e:
            logger.warning("Invalid magic link token", error=str(e))
            raise
