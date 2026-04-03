"""Local authentication service with TOTP MFA."""

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from structlog import get_logger

from app.domain.models.auth import MagicLink, RefreshToken, TOTPSecret
from app.domain.models.user import User, UserRole
from app.domain.services.email_otp_service import EmailOTPService
from app.domain.services.email_service import EmailService
from app.domain.services.jwt_auth_service import JWTAuthService
from app.domain.services.platform_settings_service import SettingsCache
from app.domain.services.totp_service import TOTPService
from app.infrastructure.config.settings import settings

logger = get_logger(__name__)


class AuthenticationError(Exception):
    """Authentication related errors."""

    pass


class LocalAuthService:
    """Local authentication service with TOTP MFA support."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.jwt_service = JWTAuthService()
        self.totp_service = TOTPService()
        self.email_service = EmailService()
        self.email_otp_service = EmailOTPService(db)

    async def register_user(
        self,
        email: str,
        name: str,
        preferred_language: str = "fr",
        country: str | None = None,
        professional_role: str | None = None,
    ) -> dict[str, Any]:
        """Register a new user and setup TOTP.

        Args:
            email: User email
            name: User full name
            preferred_language: User preferred language (fr/en)
            country: User's country (ECOWAS code)
            professional_role: Professional role

        Returns:
            Dict with user info, QR code, and backup codes

        Raises:
            AuthenticationError: If user already exists
        """
        try:
            # Check if user already exists
            existing_user = await self.db.scalar(select(User).where(User.email == email))
            if existing_user:
                raise AuthenticationError("User already exists")

            # Assign admin role if email matches ADMIN_EMAIL setting
            initial_role = (
                UserRole.admin
                if settings.admin_email and email.lower() == settings.admin_email.lower()
                else UserRole.user
            )

            # Create user
            user = User(
                id=uuid4(),
                email=email,
                name=name,
                preferred_language=preferred_language,
                country=country,
                professional_role=professional_role,
                current_level=1,  # Will be set after placement test
                streak_days=0,
                role=initial_role,
                last_active=datetime.utcnow(),
                created_at=datetime.utcnow(),
            )
            self.db.add(user)

            # Generate TOTP secret
            totp_secret = self.totp_service.generate_secret()
            backup_codes = self.totp_service.generate_backup_codes()

            # Create TOTP record
            totp_record = TOTPSecret(
                id=uuid4(),
                user_id=user.id,
                secret=totp_secret,
                backup_codes=self.totp_service.hash_backup_codes(backup_codes),
                is_verified=False,
                created_at=datetime.utcnow(),
            )
            self.db.add(totp_record)

            # Generate QR code
            qr_code = self.totp_service.generate_qr_code(totp_secret, email)

            await self.db.commit()

            logger.info("User registered successfully", user_id=str(user.id), email=email)

            return {
                "user_id": str(user.id),
                "email": email,
                "name": name,
                "qr_code": qr_code,
                "backup_codes": backup_codes,
                "secret": totp_secret,  # For manual entry
                "provisioning_uri": self.totp_service.get_provisioning_uri(totp_secret, email),
            }

        except Exception as e:
            await self.db.rollback()
            logger.error("Registration failed", email=email, error=str(e))
            if isinstance(e, AuthenticationError):
                raise
            raise AuthenticationError(f"Registration failed: {e}")

    async def verify_totp_setup(self, user_id: str, totp_code: str) -> dict[str, Any]:
        """Verify TOTP setup and complete registration.

        Args:
            user_id: User UUID
            totp_code: 6-digit TOTP code from authenticator

        Returns:
            Dict with access token and user info

        Raises:
            AuthenticationError: If verification fails
        """
        try:
            # Get user and TOTP secret
            user = await self.db.scalar(select(User).where(User.id == UUID(user_id)))
            if not user:
                raise AuthenticationError("User not found")

            totp_record = await self.db.scalar(
                select(TOTPSecret).where(
                    and_(TOTPSecret.user_id == UUID(user_id), TOTPSecret.is_verified == False)
                )
            )
            if not totp_record:
                raise AuthenticationError("TOTP setup not found or already verified")

            # Verify TOTP code
            is_valid = self.totp_service.verify_token(totp_record.secret, totp_code)
            if not is_valid:
                raise AuthenticationError("Invalid TOTP code")

            # Mark as verified
            totp_record.is_verified = True
            totp_record.verified_at = datetime.utcnow()

            # Create tokens
            access_token = self.jwt_service.create_access_token(
                user_id=str(user.id),
                email=user.email,
                preferred_language=user.preferred_language,
                country=user.country,
                current_level=user.current_level,
                role=user.role.value,
            )

            refresh_token = self.jwt_service.create_refresh_token()
            refresh_record = RefreshToken(
                id=uuid4(),
                user_id=user.id,
                token_hash=self.jwt_service.hash_token(refresh_token),
                expires_at=self.jwt_service.get_token_expiry("refresh"),
                created_at=datetime.utcnow(),
            )
            self.db.add(refresh_record)

            await self.db.commit()

            # Send welcome email
            await self.email_service.send_welcome_email(
                user.email, user.name, user.preferred_language
            )

            logger.info("TOTP setup verified", user_id=user_id, email=user.email)

            return {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "token_type": "bearer",
                "expires_in": self.jwt_service.access_token_expire_minutes * 60,
                "user": {
                    "id": str(user.id),
                    "email": user.email,
                    "name": user.name,
                    "preferred_language": user.preferred_language,
                    "country": user.country,
                    "current_level": user.current_level,
                },
            }

        except Exception as e:
            await self.db.rollback()
            logger.error("TOTP verification failed", user_id=user_id, error=str(e))
            if isinstance(e, AuthenticationError):
                raise
            raise AuthenticationError(f"Verification failed: {e}")

    async def login_with_totp(self, email: str, totp_code: str) -> dict[str, Any]:
        """Login with email and TOTP code.

        Args:
            email: User email
            totp_code: 6-digit TOTP code from authenticator

        Returns:
            Dict with access token and user info

        Raises:
            AuthenticationError: If login fails
        """
        try:
            # Get user
            user = await self.db.scalar(select(User).where(User.email == email))
            if not user:
                raise AuthenticationError("Invalid credentials")

            # Get TOTP secret
            totp_record = await self.db.scalar(
                select(TOTPSecret).where(
                    and_(TOTPSecret.user_id == user.id, TOTPSecret.is_verified == True)
                )
            )
            if not totp_record:
                raise AuthenticationError("MFA not set up for this account")

            _cache = SettingsCache.instance()
            _MAX_FAILED = _cache.get("auth.max_failed_totp_attempts", 10)
            _LOCKOUT_MINUTES = _cache.get("auth.totp_lockout_minutes", 15)

            # Check account lockout
            if (
                totp_record.locked_until is not None
                and totp_record.locked_until > datetime.utcnow()
            ):
                remaining = int((totp_record.locked_until - datetime.utcnow()).total_seconds() / 60)
                raise AuthenticationError(
                    f"Account temporarily locked due to too many failed attempts. "
                    f"Try again in {remaining} minute(s)."
                )

            # Try backup code first, then TOTP
            is_valid = False
            if len(totp_code) == 8:  # Backup code
                is_valid, updated_codes = self.totp_service.verify_backup_code(
                    totp_record.backup_codes or "[]", totp_code
                )
                if is_valid:
                    totp_record.backup_codes = updated_codes
            else:  # Regular TOTP
                is_valid = self.totp_service.verify_token(totp_record.secret, totp_code)

            if not is_valid:
                totp_record.failed_attempts = (totp_record.failed_attempts or 0) + 1
                if totp_record.failed_attempts >= _MAX_FAILED:
                    totp_record.locked_until = datetime.utcnow() + timedelta(
                        minutes=_LOCKOUT_MINUTES
                    )
                    totp_record.failed_attempts = 0
                    await self.db.commit()
                    raise AuthenticationError(
                        f"Account locked for {_LOCKOUT_MINUTES} minutes after too many failed attempts."
                    )
                await self.db.commit()
                raise AuthenticationError("Invalid authentication code")

            # Reset failure counter on success
            totp_record.failed_attempts = 0
            totp_record.locked_until = None

            # Update user activity
            user.last_active = datetime.utcnow()

            # Create tokens
            access_token = self.jwt_service.create_access_token(
                user_id=str(user.id),
                email=user.email,
                preferred_language=user.preferred_language,
                country=user.country,
                current_level=user.current_level,
                role=user.role.value,
            )

            refresh_token = self.jwt_service.create_refresh_token()
            refresh_record = RefreshToken(
                id=uuid4(),
                user_id=user.id,
                token_hash=self.jwt_service.hash_token(refresh_token),
                expires_at=self.jwt_service.get_token_expiry("refresh"),
                created_at=datetime.utcnow(),
                last_used_at=datetime.utcnow(),
            )
            self.db.add(refresh_record)

            await self.db.commit()

            logger.info("User logged in successfully", user_id=str(user.id), email=email)

            return {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "token_type": "bearer",
                "expires_in": self.jwt_service.access_token_expire_minutes * 60,
                "user": {
                    "id": str(user.id),
                    "email": user.email,
                    "name": user.name,
                    "preferred_language": user.preferred_language,
                    "country": user.country,
                    "current_level": user.current_level,
                },
            }

        except Exception as e:
            await self.db.rollback()
            logger.error("Login failed", email=email, error=str(e))
            if isinstance(e, AuthenticationError):
                raise
            raise AuthenticationError(f"Login failed: {e}")

    async def send_magic_link(self, email: str) -> bool:
        """Send magic link for account recovery.

        Args:
            email: User email

        Returns:
            True if magic link was sent

        Raises:
            AuthenticationError: If user not found
        """
        try:
            # Get user
            user = await self.db.scalar(select(User).where(User.email == email))
            if not user:
                # Don't reveal if email exists or not
                logger.warning("Magic link requested for non-existent email", email=email)
                return True

            # Generate magic link token
            magic_token = self.jwt_service.generate_magic_link_token()

            # Store magic link
            magic_link = MagicLink(
                id=uuid4(),
                user_id=user.id,
                token_hash=self.jwt_service.hash_token(magic_token),
                expires_at=datetime.utcnow() + timedelta(hours=1),
                created_at=datetime.utcnow(),
            )
            self.db.add(magic_link)

            # Clean up old magic links for this user
            await self.db.execute(
                delete(MagicLink).where(
                    and_(MagicLink.user_id == user.id, MagicLink.expires_at < datetime.utcnow())
                )
            )

            await self.db.commit()

            # Send email
            success = await self.email_service.send_magic_link(
                email, magic_token, user.preferred_language
            )

            logger.info("Magic link sent", email=email, success=success)
            return success

        except Exception as e:
            await self.db.rollback()
            logger.error("Failed to send magic link", email=email, error=str(e))
            raise AuthenticationError("Failed to send recovery email")

    async def verify_magic_link(self, token: str) -> dict[str, Any]:
        """Verify magic link and allow user to reset MFA.

        Args:
            token: Magic link token

        Returns:
            Temporary access token for MFA setup

        Raises:
            AuthenticationError: If token is invalid
        """
        try:
            # Find magic link
            token_hash = self.jwt_service.hash_token(token)
            magic_link = await self.db.scalar(
                select(MagicLink).where(
                    and_(
                        MagicLink.token_hash == token_hash,
                        MagicLink.expires_at > datetime.utcnow(),
                        MagicLink.used_at.is_(None),
                    )
                )
            )

            if not magic_link:
                raise AuthenticationError("Invalid or expired magic link")

            # Get user
            user = await self.db.scalar(select(User).where(User.id == magic_link.user_id))
            if not user:
                raise AuthenticationError("User not found")

            # Mark magic link as used
            magic_link.used_at = datetime.utcnow()

            # Remove existing TOTP setup
            await self.db.execute(delete(TOTPSecret).where(TOTPSecret.user_id == user.id))

            # Generate new TOTP setup
            totp_secret = self.totp_service.generate_secret()
            backup_codes = self.totp_service.generate_backup_codes()

            totp_record = TOTPSecret(
                id=uuid4(),
                user_id=user.id,
                secret=totp_secret,
                backup_codes=self.totp_service.hash_backup_codes(backup_codes),
                is_verified=False,
                created_at=datetime.utcnow(),
            )
            self.db.add(totp_record)

            # Generate QR code
            qr_code = self.totp_service.generate_qr_code(totp_secret, user.email)

            await self.db.commit()

            logger.info("Magic link verified, MFA reset", user_id=str(user.id), email=user.email)

            return {
                "user_id": str(user.id),
                "email": user.email,
                "name": user.name,
                "qr_code": qr_code,
                "backup_codes": backup_codes,
                "secret": totp_secret,
                "provisioning_uri": self.totp_service.get_provisioning_uri(totp_secret, user.email),
            }

        except Exception as e:
            await self.db.rollback()
            logger.error("Magic link verification failed", error=str(e))
            if isinstance(e, AuthenticationError):
                raise
            raise AuthenticationError("Magic link verification failed")

    async def refresh_access_token(self, refresh_token: str) -> dict[str, Any]:
        """Refresh access token using refresh token.

        Args:
            refresh_token: Refresh token

        Returns:
            New access token

        Raises:
            AuthenticationError: If refresh token is invalid
        """
        try:
            token_hash = self.jwt_service.hash_token(refresh_token)

            # Find refresh token
            refresh_record = await self.db.scalar(
                select(RefreshToken).where(
                    and_(
                        RefreshToken.token_hash == token_hash,
                        RefreshToken.expires_at > datetime.utcnow(),
                    )
                )
            )

            if not refresh_record:
                raise AuthenticationError("Invalid or expired refresh token")

            # Get user
            user = await self.db.scalar(select(User).where(User.id == refresh_record.user_id))
            if not user:
                raise AuthenticationError("User not found")

            # Update refresh token usage
            refresh_record.last_used_at = datetime.utcnow()
            user.last_active = datetime.utcnow()

            # Create new access token
            access_token = self.jwt_service.create_access_token(
                user_id=str(user.id),
                email=user.email,
                preferred_language=user.preferred_language,
                country=user.country,
                current_level=user.current_level,
                role=user.role.value,
            )

            await self.db.commit()

            logger.info("Access token refreshed", user_id=str(user.id))

            return {
                "access_token": access_token,
                "token_type": "bearer",
                "expires_in": self.jwt_service.access_token_expire_minutes * 60,
            }

        except Exception as e:
            await self.db.rollback()
            logger.error("Token refresh failed", error=str(e))
            if isinstance(e, AuthenticationError):
                raise
            raise AuthenticationError("Token refresh failed")

    async def logout(self, refresh_token: str) -> bool:
        """Logout user by invalidating refresh token.

        Args:
            refresh_token: Refresh token to invalidate

        Returns:
            True if logout successful
        """
        try:
            token_hash = self.jwt_service.hash_token(refresh_token)

            # Delete refresh token
            await self.db.execute(delete(RefreshToken).where(RefreshToken.token_hash == token_hash))

            await self.db.commit()

            logger.info("User logged out")
            return True

        except Exception as e:
            await self.db.rollback()
            logger.error("Logout failed", error=str(e))
            return False

    async def register_user_with_email_otp(
        self,
        email: str,
        name: str,
        preferred_language: str = "fr",
        country: str | None = None,
        professional_role: str | None = None,
        ip_address: str | None = None,
    ) -> dict[str, Any]:
        """Register a new user and send email OTP for verification.

        Args:
            email: User email
            name: User full name
            preferred_language: User preferred language (fr/en)
            country: User's country (ECOWAS code)
            professional_role: Professional role
            ip_address: Client IP address for rate limiting

        Returns:
            Dict with user info and OTP details

        Raises:
            AuthenticationError: If user already exists or OTP sending fails
        """
        try:
            # Check if user already exists
            existing_user = await self.db.scalar(select(User).where(User.email == email))
            if existing_user:
                raise AuthenticationError("User already exists")

            # Assign admin role if email matches ADMIN_EMAIL setting
            initial_role = (
                UserRole.admin
                if settings.admin_email and email.lower() == settings.admin_email.lower()
                else UserRole.user
            )

            # Create user (without TOTP setup)
            user = User(
                id=uuid4(),
                email=email,
                name=name,
                preferred_language=preferred_language,
                country=country,
                professional_role=professional_role,
                current_level=1,  # Will be set after placement test
                streak_days=0,
                role=initial_role,
                last_active=datetime.utcnow(),
                created_at=datetime.utcnow(),
            )
            self.db.add(user)
            await self.db.commit()

            # Send email OTP
            otp_result = await self.email_otp_service.send_registration_otp(
                email, user.id, preferred_language, ip_address
            )

            logger.info(
                "User registration with email OTP initiated", user_id=str(user.id), email=email
            )

            return {
                "user_id": str(user.id),
                "email": email,
                "name": name,
                "verification_method": "email_otp",
                "otp_id": otp_result["otp_id"],
                "expires_at": otp_result["expires_at"],
                "expires_in_seconds": otp_result["expires_in_seconds"],
            }

        except AuthenticationError:
            await self.db.rollback()
            raise
        except Exception as e:
            await self.db.rollback()
            logger.error("Email OTP registration failed", email=email, error=str(e))
            raise AuthenticationError(f"Registration failed: {e}")

    async def verify_email_otp_registration(
        self, otp_id: str, otp_code: str, ip_address: str | None = None
    ) -> dict[str, Any]:
        """Verify email OTP and complete registration.

        Args:
            otp_id: OTP record ID
            otp_code: 6-digit OTP code
            ip_address: Client IP address

        Returns:
            Dict with access token and user info

        Raises:
            AuthenticationError: If verification fails
        """
        try:
            # Verify OTP
            otp_result = await self.email_otp_service.verify_otp(otp_id, otp_code, ip_address)

            if not otp_result["verified"] or otp_result["purpose"] != "registration":
                raise AuthenticationError("Invalid OTP verification")

            # Get user
            user = otp_result.get("user")
            if not user:
                raise AuthenticationError("User not found after OTP verification")

            user_obj = await self.db.scalar(select(User).where(User.id == UUID(user["id"])))
            if not user_obj:
                raise AuthenticationError("User not found")

            # Create tokens
            access_token = self.jwt_service.create_access_token(
                user_id=user["id"],
                email=user["email"],
                preferred_language=user["preferred_language"],
                country=user["country"],
                current_level=user["current_level"],
                role=user_obj.role.value,
            )

            refresh_token = self.jwt_service.create_refresh_token()
            refresh_record = RefreshToken(
                id=uuid4(),
                user_id=user_obj.id,
                token_hash=self.jwt_service.hash_token(refresh_token),
                expires_at=self.jwt_service.get_token_expiry("refresh"),
                created_at=datetime.utcnow(),
            )
            self.db.add(refresh_record)

            await self.db.commit()

            # Send welcome email
            await self.email_service.send_welcome_email(
                user["email"], user["name"], user["preferred_language"]
            )

            logger.info("Email OTP registration completed", user_id=user["id"], email=user["email"])

            return {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "token_type": "bearer",
                "expires_in": self.jwt_service.access_token_expire_minutes * 60,
                "user": user,
            }

        except AuthenticationError:
            await self.db.rollback()
            raise
        except Exception as e:
            await self.db.rollback()
            logger.error("Email OTP registration verification failed", otp_id=otp_id, error=str(e))
            raise AuthenticationError(f"Verification failed: {e}")

    async def send_login_otp(self, email: str, ip_address: str | None = None) -> dict[str, Any]:
        """Send OTP for login verification.

        Args:
            email: User email
            ip_address: Client IP address for rate limiting

        Returns:
            Dict with OTP details

        Raises:
            AuthenticationError: If user not found or OTP sending fails
        """
        try:
            # Get user to check language preference
            user = await self.db.scalar(select(User).where(User.email == email))
            if not user:
                # Don't reveal if email exists or not
                raise AuthenticationError("Invalid credentials")

            # Send login OTP
            otp_result = await self.email_otp_service.send_login_otp(
                email, user.preferred_language, ip_address
            )

            logger.info("Login OTP sent", email=email)

            return {
                "otp_id": otp_result["otp_id"],
                "expires_at": otp_result["expires_at"],
                "expires_in_seconds": otp_result["expires_in_seconds"],
                "message": "Login verification code sent to your email",
            }

        except AuthenticationError:
            raise
        except Exception as e:
            logger.error("Failed to send login OTP", email=email, error=str(e))
            raise AuthenticationError("Failed to send login verification code")

    async def verify_login_otp(
        self, otp_id: str, otp_code: str, ip_address: str | None = None
    ) -> dict[str, Any]:
        """Verify login OTP and authenticate user.

        Args:
            otp_id: OTP record ID
            otp_code: 6-digit OTP code
            ip_address: Client IP address

        Returns:
            Dict with access token and user info

        Raises:
            AuthenticationError: If verification fails
        """
        try:
            # Verify OTP
            otp_result = await self.email_otp_service.verify_otp(otp_id, otp_code, ip_address)

            if not otp_result["verified"] or otp_result["purpose"] != "login":
                raise AuthenticationError("Invalid OTP verification")

            # Get user
            user = otp_result.get("user")
            if not user:
                raise AuthenticationError("User not found after OTP verification")

            user_obj = await self.db.scalar(select(User).where(User.id == UUID(user["id"])))
            if not user_obj:
                raise AuthenticationError("User not found")

            # Update user activity
            user_obj.last_active = datetime.utcnow()

            # Create tokens
            access_token = self.jwt_service.create_access_token(
                user_id=user["id"],
                email=user["email"],
                preferred_language=user["preferred_language"],
                country=user["country"],
                current_level=user["current_level"],
                role=user_obj.role.value,
            )

            refresh_token = self.jwt_service.create_refresh_token()
            refresh_record = RefreshToken(
                id=uuid4(),
                user_id=user_obj.id,
                token_hash=self.jwt_service.hash_token(refresh_token),
                expires_at=self.jwt_service.get_token_expiry("refresh"),
                created_at=datetime.utcnow(),
                last_used_at=datetime.utcnow(),
            )
            self.db.add(refresh_record)

            await self.db.commit()

            logger.info("Login OTP verification successful", email=user["email"])

            return {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "token_type": "bearer",
                "expires_in": self.jwt_service.access_token_expire_minutes * 60,
                "user": user,
            }

        except AuthenticationError:
            await self.db.rollback()
            raise
        except Exception as e:
            await self.db.rollback()
            logger.error("Login OTP verification failed", otp_id=otp_id, error=str(e))
            raise AuthenticationError(f"Login verification failed: {e}")
