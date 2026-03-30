"""Local authentication endpoints with TOTP MFA."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, EmailStr, Field
from structlog import get_logger

from ...api.deps import get_db_session
from ...domain.services.local_auth_service import AuthenticationError, LocalAuthService

logger = get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["Authentication"])


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

    refresh_token: str


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


# =============================================================================
# AUTH ENDPOINTS
# =============================================================================


@router.post("/register", response_model=RegisterResponse)
async def register(request: RegisterRequest, db=Depends(get_db_session)) -> RegisterResponse:
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
            samesite="strict",
            max_age=30 * 24 * 60 * 60,  # 30 days
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
            samesite="strict",
            max_age=30 * 24 * 60 * 60,  # 30 days
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
    request: RefreshTokenRequest, db=Depends(get_db_session)
) -> RefreshTokenResponse:
    """Refresh access token using refresh token.

    Args:
        request: Refresh token

    Returns:
        New access token

    Raises:
        401: Invalid or expired refresh token
        500: Refresh failed
    """
    try:
        auth_service = LocalAuthService(db)
        result = await auth_service.refresh_access_token(request.refresh_token)

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
        response.delete_cookie(key="refresh_token", httponly=True, secure=True, samesite="strict")

        if success:
            logger.info("User logged out successfully")
            return {"message": "Logged out successfully"}
        else:
            logger.warning("Logout failed")
            return {"message": "Logout failed"}

    except Exception as e:
        logger.error("Logout error", error=str(e))
        # Don't raise error for logout, just clear cookie
        response.delete_cookie(key="refresh_token", httponly=True, secure=True, samesite="strict")
        return {"message": "Logged out"}


# =============================================================================
# HEALTH CHECK
# =============================================================================


@router.get("/health")
async def auth_health() -> dict[str, str]:
    """Auth service health check."""
    return {"status": "healthy", "service": "local-auth"}
