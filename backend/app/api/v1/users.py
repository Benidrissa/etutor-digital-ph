"""User profile management endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from structlog import get_logger

from app.api.deps import get_db as get_db_session
from app.api.deps_local_auth import get_current_user

from ...domain.models.user import User
from ...domain.repositories.implementations.user_repository import UserRepository
from ...domain.services.auth_service import AuthService
from .schemas.users import (
    OnboardingRequest,
    ProfileUpdateResponse,
    UpdateProfileRequest,
    UserProfileResponse,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/users", tags=["Users"])


def _to_uuid(raw_id: str | UUID) -> UUID:
    """Convert a string or UUID to UUID."""
    return UUID(raw_id) if isinstance(raw_id, str) else raw_id


def _build_profile_response(user: User) -> UserProfileResponse:
    """Build UserProfileResponse from a User model instance."""
    return UserProfileResponse(
        id=str(user.id),
        email=user.email,
        name=user.name,
        preferred_language=user.preferred_language,
        country=user.country,
        professional_role=user.professional_role,
        current_level=user.current_level,
        streak_days=user.streak_days,
        avatar_url=user.avatar_url,
        last_active=user.last_active.isoformat(),
        created_at=user.created_at.isoformat(),
        role=user.role,
        phone_number=user.phone_number,
        analytics_opt_out=user.analytics_opt_out,
    )


@router.get("/me", response_model=UserProfileResponse)
async def get_current_user_profile(
    current_user=Depends(get_current_user),
    db=Depends(get_db_session),
) -> UserProfileResponse:
    """Get current user profile.

    Returns:
        Current user's profile information
    """
    try:
        user_repo = UserRepository(db)
        user_id = _to_uuid(current_user.id)
        user = await user_repo.get_by_id(user_id)

        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        return _build_profile_response(user)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get user profile", user_id=str(current_user.id), error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to get user profile"
        )


@router.patch("/me", response_model=ProfileUpdateResponse)
async def update_user_profile(
    request: UpdateProfileRequest,
    current_user: User = Depends(get_current_user),
    db=Depends(get_db_session),
) -> ProfileUpdateResponse:
    """Update user profile.

    Args:
        request: Updated profile fields
        current_user: Current authenticated user
        db: Database session

    Returns:
        Updated user profile

    Raises:
        400: Invalid update data
        500: Update failed
    """
    try:
        user_repo = UserRepository(db)
        auth_service = AuthService(user_repo)

        # Check if country is changing for re-contextualization flag
        country_changed = request.country is not None and request.country != current_user.country

        updates = {}
        if request.name is not None:
            updates["name"] = request.name
        if request.preferred_language is not None:
            updates["preferred_language"] = request.preferred_language
        if request.country is not None:
            updates["country"] = request.country
        if request.professional_role is not None:
            updates["professional_role"] = request.professional_role
        if request.analytics_opt_out is not None:
            updates["analytics_opt_out"] = request.analytics_opt_out

        user_id = _to_uuid(current_user.id)
        await auth_service.update_user_profile(user_id, updates)
        updated_user = await user_repo.get_by_id(user_id)

        if not updated_user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        logger.info("User profile updated", user_id=str(current_user.id))

        return ProfileUpdateResponse(
            profile=_build_profile_response(updated_user),
            content_recontextualization_required=country_changed,
        )

    except Exception as e:
        logger.error("Profile update failed", user_id=str(current_user.id), error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Profile update failed"
        )


@router.post("/me/onboarding", response_model=UserProfileResponse)
async def complete_onboarding(
    request: OnboardingRequest,
    current_user: User = Depends(get_current_user),
    db=Depends(get_db_session),
) -> UserProfileResponse:
    """Complete user onboarding flow.

    Updates user profile with onboarding data including language preference,
    country, professional role, and skill level.

    Args:
        request: Onboarding data (language, country, role, level)
        current_user: Current authenticated user
        db: Database session

    Returns:
        Updated user profile

    Raises:
        400: Invalid onboarding data
        500: Update failed
    """
    try:
        user_repo = UserRepository(db)
        auth_service = AuthService(user_repo)
        user_id = _to_uuid(current_user.id)

        updates = {
            "preferred_language": request.preferred_language,
            "country": request.country,
            "professional_role": request.professional_role,
            "current_level": request.current_level,
        }

        await auth_service.update_user_profile(user_id, updates)
        updated_user = await user_repo.get_by_id(user_id)

        if not updated_user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        logger.info(
            "User onboarding completed",
            user_id=str(current_user.id),
            country=request.country,
            role=request.professional_role,
            level=request.current_level,
        )

        return _build_profile_response(updated_user)

    except Exception as e:
        logger.error("Onboarding completion failed", user_id=str(current_user.id), error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Onboarding completion failed"
        )


@router.post("/me/avatar", response_model=UserProfileResponse)
async def upload_avatar(
    current_user: User = Depends(get_current_user),
    db=Depends(get_db_session),
    file: UploadFile = File(...),
) -> UserProfileResponse:
    """Upload user avatar.

    Args:
        current_user: Current authenticated user
        db: Database session
        file: Avatar image file (max 2MB)

    Returns:
        Updated user profile with avatar URL

    Raises:
        400: Invalid file type/size or upload failed
        500: Upload failed
    """
    # Validate file
    if file.size and file.size > 2 * 1024 * 1024:  # 2MB limit
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="File size exceeds 2MB limit"
        )

    if file.content_type not in ["image/jpeg", "image/jpg", "image/png", "image/webp"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file type. Supported formats: JPEG, PNG, WebP",
        )

    try:
        user_repo = UserRepository(db)
        auth_service = AuthService(user_repo)

        # Generate unique filename

        # For MVP, we'll store avatars as base64 data URLs
        # In production, you'd upload to cloud storage (S3, Cloudinary, etc.)
        contents = await file.read()
        if len(contents) > 2 * 1024 * 1024:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="File size exceeds 2MB limit"
            )

        # Create data URL for MVP
        import base64

        encoded_content = base64.b64encode(contents).decode("utf-8")
        avatar_url = f"data:{file.content_type};base64,{encoded_content}"

        # Update user profile with avatar URL
        user_id = _to_uuid(current_user.id)
        await auth_service.update_user_profile(user_id, {"avatar_url": avatar_url})
        updated_user = await user_repo.get_by_id(user_id)

        if not updated_user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        logger.info("Avatar uploaded successfully", user_id=str(current_user.id))
        return _build_profile_response(updated_user)

    except Exception as e:
        logger.error("Avatar upload failed", user_id=str(current_user.id), error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Avatar upload failed"
        )
