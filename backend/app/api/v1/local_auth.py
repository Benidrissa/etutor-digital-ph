"""Local authentication endpoints with TOTP MFA."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from structlog import get_logger

from ...api.deps import get_db_session
from ...domain.services.local_auth_service import AuthenticationError, LocalAuthService
from ...domain.services.platform_settings_service import PlatformSettingsService

logger = get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["Authentication"])

_settings_svc = PlatformSettingsService()


async def _require_registration_enabled() -> None:
    enabled = await _settings_svc.get("auth-self-registration-enabled")
    if not enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Self-registration is disabled for this instance.",
        )


# =============================================================================
# REQUEST/RESPONSE SCHEMAS
# =============================================================================


class RegisterRequest(BaseModel):
    """User registration request."""

    email: EmailStr
    name: str = Field(..., min_length=2, max_length=100)
    preferred_language: str = Field(default="fr", pattern="^(fr|en)$")
    country: str | None = Field(None, description="ECOWAS country code")
    professional_role: str | None = Field(None, max_length=50)


class RegisterResponse(BaseModel):
    """User registration response with TOTP setup."""

    user_id: str
    email: str
    name: str
    qr_code: str  # Base64 encoded QR code image
    backup_codes: list[str]
    secret: str  # For manual entry
    provisioning_uri: str


class VerifyTOTPRequest(BaseModel):
    """TOTP verification request."""

    user_id: str
    totp_code: str = Field(..., min_length=6, max_length=6, pattern="^[0-9]{6}$")


class LoginRequest(BaseModel):
    """Login request."""

    email: EmailStr
    totp_code: str = Field(..., min_length=6, max_length=8, pattern="^[0-9]{6,8}$")


class TokenResponse(BaseModel):
    """Token response."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: dict[str, Any]


class RefreshTokenRequest(BaseModel):
    """Refresh token request."""

    refresh_token: str | None = None


class RefreshTokenResponse(BaseModel):
    """Refresh token response."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int


class MagicLinkRequest(BaseModel):
    """Magic link request."""

    email: EmailStr


class MagicLinkResponse(BaseModel):
    """Magic link response."""

    message: str


class VerifyMagicLinkRequest(BaseModel):
    """Magic link verification request."""

    token: str


class LogoutRequest(BaseModel):
    """Logout request."""

    refresh_token: str


class RegisterPasswordRequest(BaseModel):
    """Password registration request."""

    identifier: str = Field(..., min_length=3, description="Email or phone number")
    password: str = Field(..., min_length=6, max_length=128)
    name: str = Field(..., min_length=2, max_length=100)
    preferred_language: str = Field(default="fr", pattern="^(fr|en)$")
    country: str | None = None
    professional_role: str | None = None


class LoginPasswordRequest(BaseModel):
    """Password login request."""

    identifier: str = Field(..., min_length=3)
    password: str = Field(..., min_length=1)


class RequestPasswordResetRequest(BaseModel):
    """Request password reset."""

    identifier: str = Field(..., min_length=3)


class ResetPasswordRequest(BaseModel):
    """Reset password with token."""

    token: str
    new_password: str = Field(..., min_length=6, max_length=128)


class RegisterEmailOTPRequest(BaseModel):
    """Email OTP registration request."""

    email: EmailStr
    name: str = Field(..., min_length=2, max_length=100)
    preferred_language: str = Field(default="fr", pattern="^(fr|en)$")
    country: str | None = Field(None, description="ECOWAS country code")
    professional_role: str | None = Field(None, max_length=50)


class RegisterEmailOTPResponse(BaseModel):
    """Email OTP registration response."""

    user_id: str
    email: str
    name: str
    verification_method: str = "email_otp"
    otp_id: str
    expires_at: str
    expires_in_seconds: int


class VerifyEmailOTPRequest(BaseModel):
    """Email OTP verification request."""

    otp_id: str
    otp_code: str = Field(..., min_length=6, max_length=6, pattern="^[0-9]{6}$")


class SendLoginOTPRequest(BaseModel):
    """Send login OTP request."""

    email: EmailStr


class SendLoginOTPResponse(BaseModel):
    """Send login OTP response."""

    otp_id: str
    expires_at: str
    expires_in_seconds: int
    message: str


class VerifyLoginOTPRequest(BaseModel):
    """Verify login OTP request."""

    otp_id: str
    otp_code: str = Field(..., min_length=6, max_length=6, pattern="^[0-9]{6}$")


# ---- Phone OTP (WhatsApp) ----------------------------------------------------


_PHONE_PATTERN = r"^\+?[1-9]\d{6,14}$"


class RegisterPhoneOTPRequest(BaseModel):
    """Phone OTP registration request (WhatsApp delivery)."""

    phone_number: str = Field(..., min_length=7, max_length=20, pattern=_PHONE_PATTERN)
    name: str = Field(..., min_length=2, max_length=100)
    preferred_language: str = Field(default="fr", pattern="^(fr|en)$")
    country: str | None = Field(None, description="ECOWAS country code")
    professional_role: str | None = Field(None, max_length=50)


class RegisterPhoneOTPResponse(BaseModel):
    """Phone OTP registration response."""

    user_id: str
    phone_number: str
    name: str
    verification_method: str = "phone_otp"
    channel: str = "whatsapp"
    otp_id: str
    expires_at: str
    expires_in_seconds: int


class VerifyPhoneOTPRequest(BaseModel):
    """Phone OTP verification request."""

    otp_id: str
    otp_code: str = Field(..., min_length=6, max_length=6, pattern="^[0-9]{6}$")


class SendLoginPhoneOTPRequest(BaseModel):
    """Send login phone OTP request."""

    phone_number: str = Field(..., min_length=7, max_length=20, pattern=_PHONE_PATTERN)


class SendLoginPhoneOTPResponse(BaseModel):
    """Send login phone OTP response."""

    otp_id: str
    phone_number: str
    expires_at: str
    expires_in_seconds: int
    message: str


class VerifyLoginPhoneOTPRequest(BaseModel):
    """Verify login phone OTP request."""

    otp_id: str
    otp_code: str = Field(..., min_length=6, max_length=6, pattern="^[0-9]{6}$")


# =============================================================================
# AUTH ENDPOINTS
# =============================================================================


@router.post("/register", response_model=RegisterResponse)
async def register(
    request: RegisterRequest,
    db=Depends(get_db_session),
    _guard=Depends(_require_registration_enabled),
) -> RegisterResponse:
    """Register a new user with TOTP MFA setup.

    Flow:
    1. User provides email + profile info
    2. System generates TOTP secret + QR code
    3. User scans QR code with authenticator app
    4. User calls /verify-totp to complete setup

    Returns:
        Registration response with QR code for MFA setup

    Raises:
        400: User already exists or invalid data
        500: Registration failed
    """
    try:
        auth_service = LocalAuthService(db)
        result = await auth_service.register_user(
            email=request.email,
            name=request.name,
            preferred_language=request.preferred_language,
            country=request.country,
            professional_role=request.professional_role,
        )

        logger.info("User registration initiated", email=request.email)
        return RegisterResponse(**result)

    except AuthenticationError as e:
        logger.warning("Registration failed", email=request.email, error=str(e))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error("Registration error", email=request.email, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Registration failed"
        )


@router.post("/verify-totp", response_model=TokenResponse)
async def verify_totp(
    request: VerifyTOTPRequest, response: Response, db=Depends(get_db_session)
) -> TokenResponse:
    """Verify TOTP code and complete registration.

    Args:
        request: User ID and 6-digit TOTP code

    Returns:
        Access token and refresh token

    Raises:
        400: Invalid TOTP code or user not found
        500: Verification failed
    """
    try:
        auth_service = LocalAuthService(db)
        result = await auth_service.verify_totp_setup(
            user_id=request.user_id, totp_code=request.totp_code
        )

        # Set refresh token as httpOnly cookie
        response.set_cookie(
            key="refresh_token",
            value=result["refresh_token"],
            httponly=True,
            secure=True,
            samesite="lax",
            max_age=auth_service.jwt_service.refresh_token_expire_days * 24 * 60 * 60,
        )

        logger.info("TOTP verification successful", user_id=request.user_id)
        return TokenResponse(**result)

    except AuthenticationError as e:
        logger.warning("TOTP verification failed", user_id=request.user_id, error=str(e))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error("TOTP verification error", user_id=request.user_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Verification failed"
        )


@router.post("/login", response_model=TokenResponse)
async def login(
    request: LoginRequest, response: Response, db=Depends(get_db_session)
) -> TokenResponse:
    """Login with email and TOTP/backup code.

    Args:
        request: Email and 6-digit TOTP code (or 8-digit backup code)

    Returns:
        Access token and refresh token

    Raises:
        400: Invalid credentials
        500: Login failed
    """
    try:
        auth_service = LocalAuthService(db)
        result = await auth_service.login_with_totp(
            email=request.email, totp_code=request.totp_code
        )

        # Set refresh token as httpOnly cookie
        response.set_cookie(
            key="refresh_token",
            value=result["refresh_token"],
            httponly=True,
            secure=True,
            samesite="lax",
            max_age=auth_service.jwt_service.refresh_token_expire_days * 24 * 60 * 60,
        )

        logger.info("Login successful", email=request.email)
        return TokenResponse(**result)

    except AuthenticationError as e:
        logger.warning("Login failed", email=request.email, error=str(e))
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))
    except Exception as e:
        logger.error("Login error", email=request.email, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Login failed"
        )


@router.post("/refresh", response_model=RefreshTokenResponse)
async def refresh_token(
    http_request: Request,
    payload: RefreshTokenRequest | None = None,
    db=Depends(get_db_session),
) -> RefreshTokenResponse:
    """Refresh access token using refresh token.

    Reads the token from the request body, falling back to the `refresh_token`
    HttpOnly cookie. The cookie fallback lets the long-lived session survive
    WebView localStorage eviction.

    Returns:
        New access token

    Raises:
        401: Invalid or expired refresh token
        500: Refresh failed
    """
    token = (payload.refresh_token if payload else None) or http_request.cookies.get(
        "refresh_token"
    )
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token required",
        )

    try:
        auth_service = LocalAuthService(db)
        result = await auth_service.refresh_access_token(token)

        logger.info("Token refreshed successfully")
        return RefreshTokenResponse(**result)

    except AuthenticationError as e:
        logger.warning("Token refresh failed", error=str(e))
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))
    except Exception as e:
        logger.error("Token refresh error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Token refresh failed"
        )


@router.post("/magic-link", response_model=MagicLinkResponse)
async def send_magic_link(
    request: MagicLinkRequest, db=Depends(get_db_session)
) -> MagicLinkResponse:
    """Send magic link for account recovery.

    Args:
        request: User email

    Returns:
        Confirmation message

    Raises:
        500: Failed to send magic link
    """
    try:
        auth_service = LocalAuthService(db)
        success = await auth_service.send_magic_link(request.email)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to send recovery email",
            )

        logger.info("Magic link sent", email=request.email)
        return MagicLinkResponse(
            message="If an account exists with this email, a recovery link has been sent."
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Magic link error", email=request.email, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send recovery email",
        )


@router.post("/verify-magic-link", response_model=RegisterResponse)
async def verify_magic_link(
    request: VerifyMagicLinkRequest, db=Depends(get_db_session)
) -> RegisterResponse:
    """Verify magic link and reset MFA.

    Args:
        request: Magic link token

    Returns:
        New TOTP setup (QR code, backup codes)

    Raises:
        400: Invalid or expired magic link
        500: Verification failed
    """
    try:
        auth_service = LocalAuthService(db)
        result = await auth_service.verify_magic_link(request.token)

        logger.info("Magic link verified, MFA reset")
        return RegisterResponse(**result)

    except AuthenticationError as e:
        logger.warning("Magic link verification failed", error=str(e))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error("Magic link verification error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Magic link verification failed",
        )


@router.post("/logout")
async def logout(
    request: LogoutRequest, response: Response, db=Depends(get_db_session)
) -> dict[str, str]:
    """Logout user by invalidating refresh token.

    Args:
        request: Refresh token to invalidate

    Returns:
        Logout confirmation
    """
    try:
        auth_service = LocalAuthService(db)
        success = await auth_service.logout(request.refresh_token)

        # Clear refresh token cookie
        response.delete_cookie(key="refresh_token", httponly=True, secure=True, samesite="lax")

        if success:
            logger.info("User logged out successfully")
            return {"message": "Logged out successfully"}
        else:
            logger.warning("Logout failed")
            return {"message": "Logout failed"}

    except Exception as e:
        logger.error("Logout error", error=str(e))
        # Don't raise error for logout, just clear cookie
        response.delete_cookie(key="refresh_token", httponly=True, secure=True, samesite="lax")
        return {"message": "Logged out"}


# =============================================================================
# PASSWORD AUTH ENDPOINTS
# =============================================================================


@router.post("/register-password", response_model=TokenResponse)
async def register_with_password(
    request: RegisterPasswordRequest,
    request_obj: Request,
    db=Depends(get_db_session),
    _guard=Depends(_require_registration_enabled),
) -> TokenResponse:
    """Register a new user with email or phone + password.

    Returns:
        Access token and refresh token

    Raises:
        400: User already exists or invalid data
        500: Registration failed
    """
    try:
        ip_address = getattr(request_obj.client, "host", None) if request_obj.client else None

        auth_service = LocalAuthService(db)
        result = await auth_service.register_user_with_password(
            identifier=request.identifier,
            password=request.password,
            name=request.name,
            preferred_language=request.preferred_language,
            country=request.country,
            professional_role=request.professional_role,
            ip_address=ip_address,
        )

        logger.info("Password registration successful", identifier=request.identifier)
        return TokenResponse(**result)

    except AuthenticationError as e:
        logger.warning("Password registration failed", identifier=request.identifier, error=str(e))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error("Password registration error", identifier=request.identifier, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Registration failed"
        )


@router.post("/login-password", response_model=TokenResponse)
async def login_with_password(
    request: LoginPasswordRequest,
    response: Response,
    request_obj: Request,
    db=Depends(get_db_session),
) -> TokenResponse:
    """Login with email or phone + password.

    Returns:
        Access token and refresh token

    Raises:
        401: Invalid credentials
        500: Login failed
    """
    try:
        ip_address = getattr(request_obj.client, "host", None) if request_obj.client else None

        auth_service = LocalAuthService(db)
        result = await auth_service.login_with_password(
            identifier=request.identifier,
            password=request.password,
            ip_address=ip_address,
        )

        response.set_cookie(
            key="refresh_token",
            value=result["refresh_token"],
            httponly=True,
            secure=True,
            samesite="lax",
            max_age=auth_service.jwt_service.refresh_token_expire_days * 24 * 60 * 60,
        )

        logger.info("Password login successful", identifier=request.identifier)
        return TokenResponse(**result)

    except AuthenticationError as e:
        logger.warning("Password login failed", identifier=request.identifier, error=str(e))
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))
    except Exception as e:
        logger.error("Password login error", identifier=request.identifier, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Login failed"
        )


@router.post("/request-password-reset")
async def request_password_reset(
    request: RequestPasswordResetRequest, request_obj: Request, db=Depends(get_db_session)
) -> dict[str, str]:
    """Request a password reset link.

    Always returns 200 to avoid user enumeration.

    Returns:
        Confirmation message
    """
    try:
        ip_address = getattr(request_obj.client, "host", None) if request_obj.client else None

        auth_service = LocalAuthService(db)
        await auth_service.request_password_reset(
            identifier=request.identifier, ip_address=ip_address
        )

        logger.info("Password reset requested", identifier=request.identifier)
    except Exception as e:
        logger.error("Password reset request error", identifier=request.identifier, error=str(e))

    return {"message": "If an account exists, a reset link has been sent."}


@router.post("/reset-password")
async def reset_password(
    request: ResetPasswordRequest, db=Depends(get_db_session)
) -> dict[str, str]:
    """Complete a password reset using a reset token.

    Returns:
        Confirmation message

    Raises:
        400: Invalid or expired token
        500: Reset failed
    """
    try:
        auth_service = LocalAuthService(db)
        await auth_service.complete_password_reset(
            token=request.token, new_password=request.new_password
        )

        logger.info("Password reset completed")
        return {"message": "Password reset successful."}

    except AuthenticationError as e:
        logger.warning("Password reset failed", error=str(e))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error("Password reset error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Password reset failed"
        )


# =============================================================================
# EMAIL OTP ENDPOINTS
# =============================================================================


@router.post("/register-email-otp", response_model=RegisterEmailOTPResponse)
async def register_email_otp(
    request: RegisterEmailOTPRequest,
    request_obj: Request,
    db=Depends(get_db_session),
    _guard=Depends(_require_registration_enabled),
) -> RegisterEmailOTPResponse:
    """Register a new user with email OTP verification.

    Flow:
    1. User provides email + profile info
    2. System sends 6-digit OTP to email
    3. User calls /verify-email-otp to complete setup

    Returns:
        Registration response with OTP details

    Raises:
        400: User already exists, rate limit exceeded, or invalid data
        500: Registration failed
    """
    try:
        ip_address = getattr(request_obj.client, "host", None) if request_obj.client else None

        auth_service = LocalAuthService(db)
        result = await auth_service.register_user_with_email_otp(
            email=request.email,
            name=request.name,
            preferred_language=request.preferred_language,
            country=request.country,
            professional_role=request.professional_role,
            ip_address=ip_address,
        )

        logger.info("User email OTP registration initiated", email=request.email)
        return RegisterEmailOTPResponse(**result)

    except AuthenticationError as e:
        logger.warning("Email OTP registration failed", email=request.email, error=str(e))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error("Email OTP registration error", email=request.email, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Registration failed"
        )


@router.post("/verify-email-otp", response_model=TokenResponse)
async def verify_email_otp(
    request: VerifyEmailOTPRequest,
    response: Response,
    request_obj: Request,
    db=Depends(get_db_session),
) -> TokenResponse:
    """Verify email OTP code and complete registration.

    Args:
        request: OTP ID and 6-digit OTP code

    Returns:
        Access token and refresh token

    Raises:
        400: Invalid OTP code, expired, or max attempts exceeded
        500: Verification failed
    """
    try:
        ip_address = getattr(request_obj.client, "host", None) if request_obj.client else None

        auth_service = LocalAuthService(db)
        result = await auth_service.verify_email_otp_registration(
            otp_id=request.otp_id, otp_code=request.otp_code, ip_address=ip_address
        )

        # Set refresh token as httpOnly cookie
        response.set_cookie(
            key="refresh_token",
            value=result["refresh_token"],
            httponly=True,
            secure=True,
            samesite="lax",
            max_age=auth_service.jwt_service.refresh_token_expire_days * 24 * 60 * 60,
        )

        logger.info("Email OTP verification successful", otp_id=request.otp_id)
        return TokenResponse(**result)

    except AuthenticationError as e:
        logger.warning("Email OTP verification failed", otp_id=request.otp_id, error=str(e))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error("Email OTP verification error", otp_id=request.otp_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Verification failed"
        )


@router.post("/send-login-otp", response_model=SendLoginOTPResponse)
async def send_login_otp(
    request: SendLoginOTPRequest, request_obj: Request, db=Depends(get_db_session)
) -> SendLoginOTPResponse:
    """Send OTP for email-based login.

    Args:
        request: User email

    Returns:
        OTP details

    Raises:
        400: Invalid credentials or rate limit exceeded
        500: Failed to send OTP
    """
    try:
        ip_address = getattr(request_obj.client, "host", None) if request_obj.client else None

        auth_service = LocalAuthService(db)
        result = await auth_service.send_login_otp(email=request.email, ip_address=ip_address)

        logger.info("Login OTP sent", email=request.email)
        return SendLoginOTPResponse(**result)

    except AuthenticationError as e:
        logger.warning("Send login OTP failed", email=request.email, error=str(e))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error("Send login OTP error", email=request.email, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to send login code"
        )


@router.post("/verify-login-otp", response_model=TokenResponse)
async def verify_login_otp(
    request: VerifyLoginOTPRequest,
    response: Response,
    request_obj: Request,
    db=Depends(get_db_session),
) -> TokenResponse:
    """Verify login OTP code and authenticate user.

    Args:
        request: OTP ID and 6-digit OTP code

    Returns:
        Access token and refresh token

    Raises:
        401: Invalid OTP code or authentication failed
        500: Login failed
    """
    try:
        ip_address = getattr(request_obj.client, "host", None) if request_obj.client else None

        auth_service = LocalAuthService(db)
        result = await auth_service.verify_login_otp(
            otp_id=request.otp_id, otp_code=request.otp_code, ip_address=ip_address
        )

        # Set refresh token as httpOnly cookie
        response.set_cookie(
            key="refresh_token",
            value=result["refresh_token"],
            httponly=True,
            secure=True,
            samesite="lax",
            max_age=auth_service.jwt_service.refresh_token_expire_days * 24 * 60 * 60,
        )

        logger.info("Login OTP verification successful", otp_id=request.otp_id)
        return TokenResponse(**result)

    except AuthenticationError as e:
        logger.warning("Login OTP verification failed", otp_id=request.otp_id, error=str(e))
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))
    except Exception as e:
        logger.error("Login OTP verification error", otp_id=request.otp_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Login verification failed"
        )


# =============================================================================
# PHONE OTP (WhatsApp) ENDPOINTS
# =============================================================================


@router.post("/register-phone-otp", response_model=RegisterPhoneOTPResponse)
async def register_phone_otp(
    request: RegisterPhoneOTPRequest,
    request_obj: Request,
    db=Depends(get_db_session),
    _guard=Depends(_require_registration_enabled),
) -> RegisterPhoneOTPResponse:
    """Register a new user with phone number + WhatsApp OTP verification.

    Flow:
    1. User provides phone number + profile info
    2. System sends 6-digit OTP via WhatsApp
    3. User calls /verify-phone-otp to complete setup
    """
    try:
        ip_address = getattr(request_obj.client, "host", None) if request_obj.client else None

        auth_service = LocalAuthService(db)
        result = await auth_service.register_user_with_phone_otp(
            phone_number=request.phone_number,
            name=request.name,
            preferred_language=request.preferred_language,
            country=request.country,
            professional_role=request.professional_role,
            ip_address=ip_address,
        )

        logger.info("User phone OTP registration initiated", phone=request.phone_number)
        return RegisterPhoneOTPResponse(**result)

    except AuthenticationError as e:
        logger.warning("Phone OTP registration failed", phone=request.phone_number, error=str(e))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error("Phone OTP registration error", phone=request.phone_number, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Registration failed"
        )


@router.post("/verify-phone-otp", response_model=TokenResponse)
async def verify_phone_otp(
    request: VerifyPhoneOTPRequest,
    response: Response,
    request_obj: Request,
    db=Depends(get_db_session),
) -> TokenResponse:
    """Verify phone OTP code and complete registration."""
    try:
        ip_address = getattr(request_obj.client, "host", None) if request_obj.client else None

        auth_service = LocalAuthService(db)
        result = await auth_service.verify_phone_otp_registration(
            otp_id=request.otp_id, otp_code=request.otp_code, ip_address=ip_address
        )

        response.set_cookie(
            key="refresh_token",
            value=result["refresh_token"],
            httponly=True,
            secure=True,
            samesite="lax",
            max_age=auth_service.jwt_service.refresh_token_expire_days * 24 * 60 * 60,
        )

        logger.info("Phone OTP verification successful", otp_id=request.otp_id)
        return TokenResponse(**result)

    except AuthenticationError as e:
        logger.warning("Phone OTP verification failed", otp_id=request.otp_id, error=str(e))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error("Phone OTP verification error", otp_id=request.otp_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Verification failed"
        )


@router.post("/send-login-phone-otp", response_model=SendLoginPhoneOTPResponse)
async def send_login_phone_otp(
    request: SendLoginPhoneOTPRequest,
    request_obj: Request,
    db=Depends(get_db_session),
) -> SendLoginPhoneOTPResponse:
    """Send a login OTP via WhatsApp."""
    try:
        ip_address = getattr(request_obj.client, "host", None) if request_obj.client else None

        auth_service = LocalAuthService(db)
        result = await auth_service.send_login_phone_otp(
            phone_number=request.phone_number, ip_address=ip_address
        )

        logger.info("Login phone OTP sent", phone=request.phone_number)
        return SendLoginPhoneOTPResponse(**result)

    except AuthenticationError as e:
        logger.warning("Send login phone OTP failed", phone=request.phone_number, error=str(e))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error("Send login phone OTP error", phone=request.phone_number, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to send login code"
        )


@router.post("/verify-login-phone-otp", response_model=TokenResponse)
async def verify_login_phone_otp(
    request: VerifyLoginPhoneOTPRequest,
    response: Response,
    request_obj: Request,
    db=Depends(get_db_session),
) -> TokenResponse:
    """Verify a login phone OTP and authenticate the user."""
    try:
        ip_address = getattr(request_obj.client, "host", None) if request_obj.client else None

        auth_service = LocalAuthService(db)
        result = await auth_service.verify_login_phone_otp(
            otp_id=request.otp_id, otp_code=request.otp_code, ip_address=ip_address
        )

        response.set_cookie(
            key="refresh_token",
            value=result["refresh_token"],
            httponly=True,
            secure=True,
            samesite="lax",
            max_age=auth_service.jwt_service.refresh_token_expire_days * 24 * 60 * 60,
        )

        logger.info("Login phone OTP verification successful", otp_id=request.otp_id)
        return TokenResponse(**result)

    except AuthenticationError as e:
        logger.warning("Login phone OTP verification failed", otp_id=request.otp_id, error=str(e))
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))
    except Exception as e:
        logger.error("Login phone OTP verification error", otp_id=request.otp_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Login verification failed"
        )


# =============================================================================
# HEALTH CHECK
# =============================================================================


@router.get("/health")
async def auth_health() -> dict[str, str]:
    """Auth service health check."""
    return {"status": "healthy", "service": "local-auth"}
