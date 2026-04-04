"""Email OTP service for registration and login verification."""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from structlog import get_logger

from app.domain.models.auth import EmailOTP
from app.domain.models.user import User
from app.domain.services.email_service import EmailService
from app.domain.services.platform_settings_service import SettingsCache

logger = get_logger(__name__)


class OTPError(Exception):
    """OTP related errors."""

    pass


class EmailOTPService:
    """Service for email OTP generation and verification."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.email_service = EmailService()
        _cache = SettingsCache.instance()
        self.otp_expiry_minutes = _cache.get("auth__otp_expiry_minutes", 10)
        self.max_attempts = _cache.get("auth__otp_max_attempts", 5)
        self.rate_limit_window = _cache.get("auth__otp_rate_limit_window_seconds", 600)
        self.max_otps_per_window = _cache.get("auth__otp_max_requests_per_window", 5)

    def generate_otp_code(self) -> str:
        """Generate a 6-digit OTP code.

        Returns:
            6-digit string OTP code
        """
        return f"{secrets.randbelow(1000000):06d}"

    def hash_otp_code(self, otp_code: str) -> str:
        """Hash an OTP code for secure storage.

        Args:
            otp_code: Plaintext OTP code

        Returns:
            SHA-256 hash of the OTP code
        """
        return hashlib.sha256(otp_code.encode()).hexdigest()

    async def send_registration_otp(
        self,
        email: str,
        user_id: UUID | None = None,
        language: str = "fr",
        ip_address: str | None = None,
    ) -> dict[str, Any]:
        """Send an OTP for registration verification.

        Args:
            email: User's email address
            user_id: User ID if user exists (nullable for registration flow)
            language: User's preferred language
            ip_address: Client IP address for rate limiting

        Returns:
            Dict with OTP ID and expiry info

        Raises:
            OTPError: If rate limit exceeded or email failed
        """
        try:
            # Check rate limiting
            await self._check_rate_limit(email, ip_address)

            # Clean up expired OTPs for this email
            await self._cleanup_expired_otps(email)

            # Generate new OTP
            otp_code = self.generate_otp_code()
            expires_at = datetime.utcnow() + timedelta(minutes=self.otp_expiry_minutes)

            # Store OTP (hashed)
            otp_record = EmailOTP(
                id=uuid4(),
                user_id=user_id,
                email=email,
                code=self.hash_otp_code(otp_code),
                purpose="registration",
                attempts=0,
                expires_at=expires_at,
                created_at=datetime.utcnow(),
                ip_address=ip_address,
            )
            self.db.add(otp_record)

            # Send email
            email_sent = await self.email_service.send_otp_email(
                email, otp_code, "registration", language
            )

            if not email_sent:
                await self.db.rollback()
                raise OTPError("Failed to send OTP email")

            await self.db.commit()

            logger.info("Registration OTP sent", email=email, otp_id=str(otp_record.id))

            return {
                "otp_id": str(otp_record.id),
                "expires_at": expires_at.isoformat(),
                "expires_in_seconds": self.otp_expiry_minutes * 60,
            }

        except OTPError:
            await self.db.rollback()
            raise
        except Exception as e:
            await self.db.rollback()
            logger.error("Failed to send registration OTP", email=email, error=str(e))
            raise OTPError(f"Failed to send OTP: {e}")

    async def send_login_otp(
        self,
        email: str,
        language: str = "fr",
        ip_address: str | None = None,
    ) -> dict[str, Any]:
        """Send an OTP for login verification.

        Args:
            email: User's email address
            language: User's preferred language
            ip_address: Client IP address for rate limiting

        Returns:
            Dict with OTP ID and expiry info

        Raises:
            OTPError: If user not found, rate limit exceeded, or email failed
        """
        try:
            # Check if user exists
            user = await self.db.scalar(select(User).where(User.email == email))
            if not user:
                raise OTPError("User not found")

            # Check rate limiting
            await self._check_rate_limit(email, ip_address)

            # Clean up expired OTPs for this email
            await self._cleanup_expired_otps(email)

            # Generate new OTP
            otp_code = self.generate_otp_code()
            expires_at = datetime.utcnow() + timedelta(minutes=self.otp_expiry_minutes)

            # Store OTP (hashed)
            otp_record = EmailOTP(
                id=uuid4(),
                user_id=user.id,
                email=email,
                code=self.hash_otp_code(otp_code),
                purpose="login",
                attempts=0,
                expires_at=expires_at,
                created_at=datetime.utcnow(),
                ip_address=ip_address,
            )
            self.db.add(otp_record)

            # Send email
            email_sent = await self.email_service.send_otp_email(email, otp_code, "login", language)

            if not email_sent:
                await self.db.rollback()
                raise OTPError("Failed to send OTP email")

            await self.db.commit()

            logger.info("Login OTP sent", email=email, otp_id=str(otp_record.id))

            return {
                "otp_id": str(otp_record.id),
                "expires_at": expires_at.isoformat(),
                "expires_in_seconds": self.otp_expiry_minutes * 60,
            }

        except OTPError:
            await self.db.rollback()
            raise
        except Exception as e:
            await self.db.rollback()
            logger.error("Failed to send login OTP", email=email, error=str(e))
            raise OTPError(f"Failed to send OTP: {e}")

    async def verify_otp(
        self,
        otp_id: str,
        otp_code: str,
        ip_address: str | None = None,
    ) -> dict[str, Any]:
        """Verify an OTP code.

        Args:
            otp_id: OTP record ID
            otp_code: 6-digit OTP code to verify
            ip_address: Client IP address

        Returns:
            Dict with verification result and user info

        Raises:
            OTPError: If OTP invalid, expired, or max attempts exceeded
        """
        try:
            # Get OTP record
            otp_record = await self.db.scalar(
                select(EmailOTP).where(
                    and_(EmailOTP.id == UUID(otp_id), EmailOTP.verified_at.is_(None))
                )
            )

            if not otp_record:
                raise OTPError("OTP not found or already verified")

            # Check if expired
            if otp_record.expires_at < datetime.utcnow():
                raise OTPError("OTP has expired")

            # Check attempts
            if otp_record.attempts >= self.max_attempts:
                raise OTPError("Maximum verification attempts exceeded")

            # Increment attempts
            otp_record.attempts += 1

            # Verify code (constant-time comparison against hash)
            if not hmac.compare_digest(otp_record.code, self.hash_otp_code(otp_code)):
                await self.db.commit()  # Save attempt increment
                attempts_left = self.max_attempts - otp_record.attempts
                raise OTPError(f"Invalid OTP code. {attempts_left} attempts remaining.")

            # Mark as verified
            otp_record.verified_at = datetime.utcnow()

            # Get user info if available
            user_info = None
            if otp_record.user_id:
                user = await self.db.scalar(select(User).where(User.id == otp_record.user_id))
                if user:
                    user_info = {
                        "id": str(user.id),
                        "email": user.email,
                        "name": user.name,
                        "preferred_language": user.preferred_language,
                        "country": user.country,
                        "current_level": user.current_level,
                    }

            await self.db.commit()

            logger.info(
                "OTP verified successfully",
                otp_id=otp_id,
                email=otp_record.email,
                purpose=otp_record.purpose,
            )

            return {
                "verified": True,
                "email": otp_record.email,
                "purpose": otp_record.purpose,
                "user": user_info,
                "verified_at": otp_record.verified_at.isoformat(),
            }

        except OTPError:
            await self.db.rollback()
            raise
        except Exception as e:
            await self.db.rollback()
            logger.error("OTP verification failed", otp_id=otp_id, error=str(e))
            raise OTPError(f"Verification failed: {e}")

    async def _check_rate_limit(self, email: str, ip_address: str | None = None) -> None:
        """Check if rate limit is exceeded for OTP requests.

        Args:
            email: User's email
            ip_address: Client IP address

        Raises:
            OTPError: If rate limit exceeded
        """
        try:
            # Check rate limit by email
            window_start = datetime.utcnow() - timedelta(seconds=self.rate_limit_window)

            email_count = await self.db.scalar(
                select(func.count(EmailOTP.id)).where(
                    and_(EmailOTP.email == email, EmailOTP.created_at >= window_start)
                )
            )

            if email_count and email_count >= self.max_otps_per_window:
                raise OTPError(
                    f"Too many OTP requests. Please wait {self.rate_limit_window // 60} minutes."
                )

            # Check rate limit by IP if provided
            if ip_address:
                ip_count = await self.db.scalar(
                    select(func.count(EmailOTP.id)).where(
                        and_(EmailOTP.ip_address == ip_address, EmailOTP.created_at >= window_start)
                    )
                )

                if ip_count and ip_count >= self.max_otps_per_window:
                    raise OTPError(
                        f"Too many OTP requests from this IP. Please wait {self.rate_limit_window // 60} minutes."
                    )

        except OTPError:
            raise
        except Exception as e:
            logger.error(
                "Rate limit check failed", email=email, ip_address=ip_address, error=str(e)
            )
            # Don't block on rate limit check errors

    async def _cleanup_expired_otps(self, email: str) -> None:
        """Clean up expired OTP records for an email.

        Args:
            email: Email address to clean up OTPs for
        """
        try:
            await self.db.execute(
                delete(EmailOTP).where(
                    and_(EmailOTP.email == email, EmailOTP.expires_at < datetime.utcnow())
                )
            )
            await self.db.commit()
        except Exception as e:
            logger.warning("Failed to cleanup expired OTPs", email=email, error=str(e))
            await self.db.rollback()
