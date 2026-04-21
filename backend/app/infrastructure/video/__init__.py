"""Video-generation provider abstraction.

A thin ``VideoProviderClient`` protocol lets us swap HeyGen for
another vendor (D-ID, Synthesia) later without touching service code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class CreateVideoResult:
    """Handle returned after dispatching a video generation request."""

    provider_video_id: str


@dataclass(frozen=True)
class VideoStatus:
    """Terminal status of a provider-side video generation job."""

    provider_video_id: str
    status: str  # "pending" | "processing" | "completed" | "failed"
    video_url: str | None = None
    error: str | None = None


class VideoProviderClient(Protocol):
    """Protocol every video vendor adapter must implement."""

    async def create_video(
        self,
        *,
        script: str,
        avatar_id: str,
        voice_id: str,
        callback_url: str,
        language: str,
    ) -> CreateVideoResult: ...

    async def get_video(self, video_id: str) -> VideoStatus: ...

    def verify_webhook_signature(self, *, signature: str, raw_body: bytes) -> bool: ...
