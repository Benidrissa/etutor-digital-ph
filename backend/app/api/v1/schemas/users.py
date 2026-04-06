"""User profile management schemas."""

from pydantic import BaseModel, Field

from app.domain.models.user import UserRole


class OnboardingRequest(BaseModel):
    """User onboarding profile update request."""

    preferred_language: str = Field(
        ..., pattern="^(fr|en)$", description="User's preferred language"
    )
    country: str = Field(..., description="ECOWAS country code")
    professional_role: str = Field(..., description="Professional role")
    current_level: int = Field(..., ge=1, le=4, description="Self-assessed skill level (1-4)")


class UserProfileResponse(BaseModel):
    """User profile response."""

    id: str
    email: str | None
    name: str
    preferred_language: str
    country: str | None
    professional_role: str | None
    current_level: int
    streak_days: int
    avatar_url: str | None
    last_active: str
    created_at: str
    role: UserRole = UserRole.user
    is_active: bool = True
    phone_number: str | None = None
    analytics_opt_out: bool = False


class UpdateProfileRequest(BaseModel):
    """User profile update request."""

    name: str | None = Field(None, max_length=100)
    preferred_language: str | None = Field(None, pattern="^(fr|en)$")
    country: str | None = None
    professional_role: str | None = None
    analytics_opt_out: bool | None = None


class ProfileUpdateResponse(BaseModel):
    """Response after profile update with re-contextualization flag."""

    profile: UserProfileResponse
    content_recontextualization_required: bool = False
