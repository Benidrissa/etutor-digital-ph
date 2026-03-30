"""Authentication endpoints for SantePublique AOF.

Handles user registration, login, profile management, and placement tests.
Auth flows: Frontend → Supabase Auth → Backend JWT validation.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from structlog import get_logger

from ...api.deps import get_auth_service, get_placement_service
from ...domain.services.auth_service import AuthService
from ...domain.services.placement_service import PlacementService
from ...integrations.supabase_auth import AuthenticatedUser, get_supabase_client, verify_auth_token

logger = get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["Authentication"])


# =============================================================================
# REQUEST/RESPONSE SCHEMAS
# =============================================================================


class UserProfileResponse(BaseModel):
    """Current user profile data."""

    id: UUID
    email: str
    name: str
    preferred_language: str = Field(..., pattern="^(fr|en)$")
    country: str | None = Field(None, description="ECOWAS country code")
    professional_role: str | None = None
    current_level: int = Field(..., ge=1, le=4)
    streak_days: int = Field(..., ge=0)
    created_at: str
    last_active: str


class UpdateProfileRequest(BaseModel):
    """Update user profile preferences."""

    name: str | None = Field(None, min_length=2, max_length=100)
    preferred_language: str | None = Field(None, pattern="^(fr|en)$")
    country: str | None = Field(None, description="ECOWAS country code")
    professional_role: str | None = Field(None, max_length=50)


class PlacementTestRequest(BaseModel):
    """Submit placement test answers."""

    answers: dict[str, Any] = Field(..., description="Question ID → selected answer mapping")
    time_taken_seconds: int = Field(..., ge=60, le=3600, description="Time taken (1-60 minutes)")


class PlacementTestResponse(BaseModel):
    """Placement test results."""

    assigned_level: int = Field(..., ge=1, le=4)
    score_percentage: float = Field(..., ge=0.0, le=100.0)
    competency_areas: list[str] = Field(..., description="Strong areas identified")
    recommendations: list[str] = Field(..., description="Learning path recommendations")


class WebhookUserEvent(BaseModel):
    """Supabase webhook payload for user events."""

    type: str  # "INSERT", "UPDATE", "DELETE"
    table: str
    schema: str
    record: dict | None = None
    old_record: dict | None = None


# =============================================================================
# AUTH ENDPOINTS
# =============================================================================


@router.get("/me", response_model=UserProfileResponse)
async def get_current_user(
    current_user: AuthenticatedUser = Depends(verify_auth_token),
    auth_service: AuthService = Depends(get_auth_service),
) -> UserProfileResponse:
    """Get current authenticated user profile.

    Returns:
        Current user profile with preferences and progress

    Raises:
        401: Invalid or expired JWT token
        404: User profile not found in database
    """
    try:
        # Fetch full user profile from database
        user_profile = await auth_service.get_user_profile(current_user.id)

        if not user_profile:
            # Create profile if missing (first-time OAuth users)
            await auth_service.create_user_profile(
                user_id=current_user.id,
                email=current_user.email,
                name=current_user.email.split("@")[0],  # Fallback name
                preferred_language=current_user.preferred_language,
                country=current_user.country,
                professional_role=current_user.professional_role,
            )
            user_profile = await auth_service.get_user_profile(current_user.id)

        logger.info("Fetched user profile", user_id=str(current_user.id))
        return user_profile

    except Exception as e:
        logger.error("Failed to fetch user profile", user_id=str(current_user.id), error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to fetch user profile"
        )


@router.patch("/me", response_model=UserProfileResponse)
async def update_current_user(
    updates: UpdateProfileRequest,
    current_user: AuthenticatedUser = Depends(verify_auth_token),
    auth_service: AuthService = Depends(get_auth_service),
) -> UserProfileResponse:
    """Update current user profile preferences.

    Args:
        updates: Profile fields to update (partial update)

    Returns:
        Updated user profile

    Raises:
        401: Invalid or expired JWT token
        400: Invalid update data
    """
    try:
        # Update profile in database
        updated_profile = await auth_service.update_user_profile(
            current_user.id, updates.model_dump(exclude_unset=True)
        )

        # Sync metadata to Supabase Auth for JWT claims
        if updates.preferred_language or updates.country:
            supabase_client = await get_supabase_client()
            metadata = {}
            if updates.preferred_language:
                metadata["preferred_language"] = updates.preferred_language
            if updates.country:
                metadata["country"] = updates.country

            await supabase_client.update_user_metadata(str(current_user.id), metadata)

        logger.info(
            "Updated user profile",
            user_id=str(current_user.id),
            updates=updates.model_dump(exclude_unset=True),
        )
        return updated_profile

    except ValueError as e:
        logger.warning("Invalid profile update", user_id=str(current_user.id), error=str(e))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error("Failed to update user profile", user_id=str(current_user.id), error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update profile"
        )


@router.post("/placement-test", response_model=PlacementTestResponse)
async def submit_placement_test(
    submission: PlacementTestRequest,
    current_user: AuthenticatedUser = Depends(verify_auth_token),
    placement_service: PlacementService = Depends(get_placement_service),
) -> PlacementTestResponse:
    """Submit placement test and assign user to appropriate level.

    The placement test determines the user's starting level (1-4) based on:
    - Public health knowledge (basic concepts, epidemiology)
    - Data analysis skills (statistics, interpretation)
    - Professional experience (role, years of experience)

    Args:
        submission: Test answers and completion time

    Returns:
        Assigned level and personalized recommendations

    Raises:
        401: Invalid or expired JWT token
        400: Invalid test submission
        409: Placement test already completed
    """
    try:
        # Check if user already completed placement test
        existing_result = await placement_service.get_placement_result(current_user.id)
        if existing_result:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Placement test already completed. Contact support to retake.",
            )

        # Score placement test and assign level
        result = await placement_service.score_placement_test(
            user_id=current_user.id,
            answers=submission.answers,
            time_taken=submission.time_taken_seconds,
            user_context={
                "professional_role": current_user.professional_role,
                "country": current_user.country,
                "preferred_language": current_user.preferred_language,
            },
        )

        logger.info(
            "Completed placement test",
            user_id=str(current_user.id),
            assigned_level=result.assigned_level,
            score=result.score_percentage,
        )

        return result

    except HTTPException:
        raise
    except ValueError as e:
        logger.warning(
            "Invalid placement test submission", user_id=str(current_user.id), error=str(e)
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error("Failed to process placement test", user_id=str(current_user.id), error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process placement test",
        )


# =============================================================================
# WEBHOOK ENDPOINTS (for Supabase Auth events)
# =============================================================================


@router.post("/webhook/user-created")
async def handle_user_created_webhook(
    event: WebhookUserEvent,
    auth_service: AuthService = Depends(get_auth_service),
):
    """Handle Supabase user creation webhook.

    Creates corresponding user profile in our database when a new user
    signs up through Supabase Auth (email/password or OAuth).

    Args:
        event: Supabase webhook payload

    Returns:
        Success confirmation

    Raises:
        400: Invalid webhook payload
        500: Database error
    """
    try:
        if event.type != "INSERT" or event.table != "users" or not event.record:
            logger.warning("Invalid webhook event", event_type=event.type, table=event.table)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook event"
            )

        user_data = event.record
        user_id = UUID(user_data["id"])

        # Extract profile data from Supabase user
        email = user_data["email"]
        user_metadata = user_data.get("user_metadata", {})

        # Create user profile in our database
        await auth_service.create_user_profile(
            user_id=user_id,
            email=email,
            name=user_metadata.get("name", email.split("@")[0]),
            preferred_language=user_metadata.get("preferred_language", "fr"),
            country=user_metadata.get("country"),
            professional_role=user_metadata.get("professional_role"),
        )

        logger.info("Created user profile from webhook", user_id=str(user_id), email=email)
        return {"status": "success", "message": "User profile created"}

    except ValueError as e:
        logger.warning("Invalid webhook data", error=str(e))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error("Webhook processing failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Webhook processing failed"
        )
