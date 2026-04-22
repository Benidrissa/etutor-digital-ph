"""Per-lesson HeyGen video summary generation.

Mirrors ``lesson_audio_service.py`` but produces a rendered MP4 via
HeyGen instead of an Opus audio file via OpenAI TTS. Writes to the
shared ``generated_audio`` table with ``media_type='video'``.

Flow:

1. Check the cache (``(module_id, unit_id, language, media_type='video')``
   already ``ready``) — return it.
2. Insert a ``pending`` row, flush, flip to ``generating``.
3. Build a taxonomy-aware Claude script (kids-register variant when
   ``detect_audience(course).is_kids``), honouring the admin
   ``video-summary-max-chars`` cap. Re-prompt once on overshoot;
   fall back to sentence-boundary truncation.
4. Dispatch to HeyGen: Direct Video (v2) when both avatar and voice
   IDs are seeded, Agent mode (v3) when either is empty. Record the
   ``provider_video_id`` and the ``api_version`` in
   ``media_metadata``. Leave status as ``generating`` — the
   ``heygen_poll`` Celery-beat task finalises the row when HeyGen
   finishes rendering.

The ready state is therefore written by the poller (via
``finalize_lesson_video``), not by this method.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.ai.claude_service import ClaudeService
from app.ai.prompts.audience import detect_audience
from app.domain.models.generated_audio import GeneratedAudio
from app.domain.models.module import Module
from app.domain.services.platform_settings_service import SettingsCache
from app.infrastructure.config.settings import settings
from app.infrastructure.storage.s3 import S3StorageService
from app.infrastructure.video.heygen_client import HeyGenClient, HeyGenError

logger = structlog.get_logger(__name__)


# ── Claude tool schema ────────────────────────────────────────────────

VIDEO_SCRIPT_TOOL = {
    "name": "save_video_script",
    "description": (
        "Save the 3-minute lesson summary narration. Call this exactly once with the full script."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "language": {"type": "string", "enum": ["fr", "en"]},
            "voice_tone": {
                "type": "string",
                "enum": [
                    "warm-educator",
                    "authoritative-professional",
                    "peer-casual",
                ],
                "description": "Pick the tone that matches the target audience.",
            },
            "scenes": {
                "type": "array",
                "minItems": 3,
                "maxItems": 6,
                "items": {
                    "type": "object",
                    "properties": {
                        "narration": {"type": "string"},
                        "duration_s": {
                            "type": "integer",
                            "minimum": 10,
                            "maximum": 90,
                        },
                    },
                    "required": ["narration", "duration_s"],
                },
            },
        },
        "required": ["language", "voice_tone", "scenes"],
    },
}


# ── Prompt templates ──────────────────────────────────────────────────


def _build_video_system_prompt(
    *,
    language: str,
    course_title: str | None,
    max_chars: int,
    is_kids: bool = False,
    age_range: str = "",
    level: int = 1,
) -> str:
    """Build the system prompt. Kids-register branch when is_kids."""
    lang_label = "French" if language == "fr" else "English"
    domain = course_title or "the subject area"

    if is_kids:
        age_hint = age_range or "6-12"
        return (
            f"You write 3-minute narrated video summaries for young "
            f"learners aged {age_hint} in West Africa.\n\n"
            f"Output language: {lang_label}.\n"
            f"Course field / domain: {domain}.\n"
            f"Target audience: children aged {age_hint}.\n\n"
            f"HARD CONSTRAINTS — your script MUST:\n"
            f"1. Use short, simple sentences children of {age_hint} "
            f"can follow out loud.\n"
            f"2. Open with a concrete, child-friendly hook — a "
            f"question, a fun fact, a tiny story — grounded in the "
            f"domain ({domain}).\n"
            f"3. Prefer comparisons and stories from daily life in "
            f"West Africa (family, village, school, market, nature) "
            f"over abstract definitions.\n"
            f"4. Replace jargon with plain language. If a technical "
            f"term is unavoidable, define it in the same sentence "
            f"using a familiar comparison.\n"
            f"5. End with a warm, encouraging 'Let's remember' "
            f"sentence and one simple 'Try this at home' idea.\n"
            f"6. Keep the concatenated narration under {max_chars} "
            f"characters — this is a hard cap, not a target.\n"
            f"7. Cover 3–6 scenes of self-contained spoken prose. "
            f"No markdown, no bullet points, no headers, no stage "
            f"directions, no source citations inside the narration.\n\n"
            f"Call the `save_video_script` tool exactly once. The "
            f"`voice_tone` should be `warm-educator` for this audience."
        )

    level_label = f"level {level}/4" if level else "the assigned course level"

    return (
        f"You write 3-minute narrated video summaries for a learning "
        f"platform.\n\n"
        f"Output language: {lang_label}.\n"
        f"Course field / domain: {domain}.\n"
        f"Learner level: {level_label}.\n\n"
        f"HARD CONSTRAINTS — your script MUST:\n"
        f"1. Cite examples specific to the domain ({domain}). "
        f"Ignoring the domain is a failure.\n"
        f"2. Use register and framing appropriate for the learner "
        f"level. Writing a student script for a professional "
        f"audience (or vice-versa) is a failure.\n"
        f"3. Keep the concatenated narration under {max_chars} "
        f"characters — this is a hard cap, not a target.\n"
        f"4. Cover 3–6 scenes with natural pacing; each scene is a "
        f"self-contained paragraph of spoken prose.\n"
        f"5. Write plain spoken prose. No markdown, no bullet "
        f"points, no headers, no stage directions, no source "
        f"citations inside the narration.\n"
        f"6. Do not repeat the title at the start; open with a "
        f"concrete hook grounded in the domain.\n\n"
        f"Call the `save_video_script` tool exactly once. Choose "
        f"`voice_tone` to match the audience."
    )


LESSON_VIDEO_USER_TEMPLATE = (
    "Module: {module_title}\n"
    "Unit: {unit_id}\n"
    "Learner level (1=beginner, 4=expert): {level}\n\n"
    "Lesson content to summarize (use this as the source of truth):\n\n"
    "{lesson_content}\n\n"
    "Write the 3-minute narration script now."
)


def _truncate_at_sentence(text: str, max_chars: int) -> str:
    """Truncate ``text`` to ≤ ``max_chars`` at a sentence boundary.

    Falls back to a hard slice with an ellipsis when no terminator
    sits in the allowed window.
    """
    if len(text) <= max_chars:
        return text
    window = text[:max_chars]
    for terminator in (".", "!", "?"):
        idx = window.rfind(terminator)
        if idx >= int(max_chars * 0.6):
            return window[: idx + 1].rstrip()
    return window.rstrip() + "…"


def is_web_ready_mp4(data: bytes) -> bool:
    """Sniff the ISO-BMFF ``ftyp`` box — HeyGen v2 always returns MP4."""
    if len(data) < 12:
        return False
    return data[4:8] == b"ftyp"


# ── Finalizer (called by the poller) ─────────────────────────────────


async def finalize_lesson_video(
    record: GeneratedAudio,
    *,
    video_url: str,
    session: AsyncSession,
    duration_hint: int | None = None,
    storage: S3StorageService | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> str:
    """Download the rendered MP4 and commit the ``ready`` row.

    On any failure the row is flipped to ``failed`` with an error
    message. Called by ``app.tasks.heygen_poll.poll_pending_heygen_videos``.
    """
    store = storage or S3StorageService()
    try:
        if http_client is None:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.get(video_url)
                resp.raise_for_status()
                video_bytes = resp.content
        else:
            resp = await http_client.get(video_url)
            resp.raise_for_status()
            video_bytes = resp.content
    except Exception as exc:
        record.status = "failed"
        record.error_message = f"download failed: {exc}"
        await session.commit()
        logger.error(
            "heygen.finalize.download_failed",
            media_id=str(record.id),
            provider_video_id=record.provider_video_id,
            error=str(exc),
        )
        return "failed"

    if not is_web_ready_mp4(video_bytes):
        record.status = "failed"
        record.error_message = "downloaded bytes are not a recognisable MP4 container"
        await session.commit()
        logger.error(
            "heygen.finalize.unsupported_container",
            media_id=str(record.id),
            provider_video_id=record.provider_video_id,
            first_bytes=video_bytes[:16].hex(),
        )
        return "failed"

    storage_key = f"video/{record.module_id}/{record.unit_id}/{record.language}/summary.mp4"
    try:
        storage_url = await store.upload_bytes(
            key=storage_key,
            data=video_bytes,
            content_type="video/mp4",
        )
    except Exception as exc:
        record.status = "failed"
        record.error_message = f"upload failed: {exc}"
        await session.commit()
        logger.error(
            "heygen.finalize.upload_failed",
            media_id=str(record.id),
            provider_video_id=record.provider_video_id,
            error=str(exc),
        )
        return "failed"

    record.status = "ready"
    record.storage_key = storage_key
    record.storage_url = storage_url
    record.file_size_bytes = len(video_bytes)
    if isinstance(duration_hint, (int, float)):
        record.duration_seconds = int(duration_hint)
    record.generated_at = datetime.utcnow()
    await session.commit()

    logger.info(
        "heygen.finalize.ready",
        media_id=str(record.id),
        provider_video_id=record.provider_video_id,
        bytes=len(video_bytes),
    )
    return "ready"


# ── Service ──────────────────────────────────────────────────────────


class LessonVideoService:
    """Pipeline: cache check → Claude script → HeyGen dispatch → row."""

    def __init__(
        self,
        claude_service: ClaudeService | None = None,
    ) -> None:
        self._claude = claude_service or ClaudeService()

    async def generate_for_lesson(
        self,
        lesson_id: uuid.UUID,
        module_id: uuid.UUID,
        unit_id: str,
        language: str,
        lesson_content: str,
        session: AsyncSession,
        *,
        heygen_client: HeyGenClient | None = None,
    ) -> GeneratedAudio:
        """Generate or return cached video summary row for a lesson.

        Returns the ``GeneratedAudio`` row with status either
        ``ready`` (cache hit) or ``generating`` (newly dispatched —
        the poller will complete the lifecycle).
        """
        cached = await self._find_cached(module_id, unit_id, language, session)
        if cached is not None:
            logger.info(
                "Returning cached lesson video",
                lesson_id=str(lesson_id),
                media_id=str(cached.id),
            )
            return cached

        # Gate on the feature flag AFTER the cache check so a flag-
        # off tenant can still serve previously-generated rows.
        cache = SettingsCache.instance()
        if not bool(cache.get("video-summary-feature-enabled", False)):
            raise RuntimeError("video_summary feature is disabled")

        existing = await self._find_existing(module_id, unit_id, language, session)
        if existing is not None:
            # Another worker is mid-generation for this (module, unit, lang).
            return existing

        record = GeneratedAudio(
            id=uuid.uuid4(),
            lesson_id=lesson_id,
            module_id=module_id,
            unit_id=unit_id,
            media_type="video",
            language=language,
            status="pending",
        )
        session.add(record)
        try:
            await session.flush()
        except Exception:
            await session.rollback()
            existing = await self._find_existing(module_id, unit_id, language, session)
            if existing is not None:
                return existing
            raise

        try:
            record.status = "generating"
            await session.flush()

            # Fetch module + course context for the prompt.
            module = await self._fetch_module(module_id, session)
            module_title = ""
            course_title = None
            is_kids = False
            age_range = ""
            level = 1
            if module:
                level = module.level or 1
                module_title = (
                    module.title_fr if language == "fr" else module.title_en
                ) or f"Module {module.module_number}"
                course = module.course
                if course:
                    course_title = course.title_fr if language == "fr" else course.title_en
                audience_ctx = detect_audience(course)
                is_kids = audience_ctx.is_kids
                if is_kids:
                    age_range = f"{audience_ctx.age_min}-{audience_ctx.age_max}"

            max_chars = int(cache.get("video-summary-max-chars", 2000))
            script = await self._generate_script(
                lesson_content=lesson_content,
                language=language,
                module_title=module_title,
                unit_id=unit_id,
                course_title=course_title,
                is_kids=is_kids,
                age_range=age_range,
                level=level,
                max_chars=max_chars,
            )

            brand_image_url = (cache.get("video-summary-brand-image-url", "") or "").strip()
            voice_key = (
                "video-summary-voice-id-fr" if language == "fr" else "video-summary-voice-id-en"
            )
            voice_id = (cache.get(voice_key, "") or "").strip()
            avatar_id = (cache.get("video-summary-default-avatar-id", "") or "").strip()

            # Preferred path: content-focused (no avatar) via /v3/videos.
            # Requires the admin-configured brand background + a voice_id
            # for narration. Legacy v2 avatar path is kept for tenants
            # that haven't migrated; Video Agents is the no-config last
            # resort (uses an avatar, pre-#1854 behaviour).
            use_content_mode = bool(brand_image_url and voice_id)
            use_v2_avatar_mode = not use_content_mode and bool(avatar_id and voice_id)

            callback_url = self._heygen_callback_url()
            client = heygen_client or HeyGenClient()
            owns_client = heygen_client is None
            try:
                if use_content_mode:
                    result = await client.create_content_video(
                        script=script,
                        voice_id=voice_id,
                        image_url=brand_image_url,
                        language=language,
                        callback_url=callback_url,
                    )
                    api_version = "v3"
                elif use_v2_avatar_mode:
                    result = await client.create_video(
                        script=script,
                        avatar_id=avatar_id,
                        voice_id=voice_id,
                        callback_url=callback_url,
                        language=language,
                    )
                    api_version = "v2"
                else:
                    result = await client.create_video_agent(
                        prompt=script,
                        language=language,
                        callback_url=callback_url,
                    )
                    api_version = "v3-agent"
            finally:
                if owns_client and client._client is not None:
                    await client._client.aclose()

            record.provider_video_id = result.provider_video_id
            record.script_text = script
            record.media_metadata = {
                "api_version": api_version,
                "is_kids": is_kids,
            }
            await session.commit()

            logger.info(
                "Lesson video dispatched to HeyGen",
                lesson_id=str(lesson_id),
                media_id=str(record.id),
                provider_video_id=result.provider_video_id,
                api_version=api_version,
                script_chars=len(script),
            )

        except HeyGenError as exc:
            record.status = "failed"
            record.error_message = f"heygen: {exc}"
            await session.commit()
            logger.error(
                "Lesson video dispatch failed",
                lesson_id=str(lesson_id),
                media_id=str(record.id),
                error=str(exc),
            )
            raise
        except Exception as exc:
            record.status = "failed"
            record.error_message = str(exc)
            await session.commit()
            logger.error(
                "Lesson video generation errored",
                lesson_id=str(lesson_id),
                media_id=str(record.id),
                error=str(exc),
            )
            raise

        return record

    async def _find_cached(
        self,
        module_id: uuid.UUID,
        unit_id: str,
        language: str,
        session: AsyncSession,
    ) -> GeneratedAudio | None:
        result = await session.execute(
            select(GeneratedAudio)
            .where(
                GeneratedAudio.module_id == module_id,
                GeneratedAudio.unit_id == unit_id,
                GeneratedAudio.media_type == "video",
                GeneratedAudio.language == language,
                GeneratedAudio.status == "ready",
            )
            .order_by(GeneratedAudio.created_at.desc())
            .limit(1)
        )
        return result.scalars().first()

    async def _find_existing(
        self,
        module_id: uuid.UUID,
        unit_id: str,
        language: str,
        session: AsyncSession,
    ) -> GeneratedAudio | None:
        """Return any row (any status) for this (module, unit, lang, video)."""
        result = await session.execute(
            select(GeneratedAudio)
            .where(
                GeneratedAudio.module_id == module_id,
                GeneratedAudio.unit_id == unit_id,
                GeneratedAudio.media_type == "video",
                GeneratedAudio.language == language,
            )
            .order_by(GeneratedAudio.created_at.desc())
            .limit(1)
        )
        return result.scalars().first()

    async def _fetch_module(self, module_id: uuid.UUID, session: AsyncSession) -> Module | None:
        result = await session.execute(
            select(Module).where(Module.id == module_id).options(selectinload(Module.course))
        )
        return result.scalar_one_or_none()

    async def _generate_script(
        self,
        *,
        lesson_content: str,
        language: str,
        module_title: str,
        unit_id: str,
        course_title: str | None,
        is_kids: bool,
        age_range: str,
        level: int,
        max_chars: int,
    ) -> str:
        system_prompt = _build_video_system_prompt(
            language=language,
            course_title=course_title,
            max_chars=max_chars,
            is_kids=is_kids,
            age_range=age_range,
            level=level,
        )
        user_message = LESSON_VIDEO_USER_TEMPLATE.format(
            module_title=module_title or "Unknown",
            unit_id=unit_id or "Unknown",
            level=level,
            lesson_content=lesson_content[:4000],
        )

        script, _metadata = await self._call_claude_tool(
            system_prompt=system_prompt,
            user_message=user_message,
        )

        if len(script) > max_chars:
            retry_user = (
                user_message + f"\n\nYour previous attempt was {len(script)} characters. "
                f"Rewrite the script so the concatenated narration is "
                f"strictly under {max_chars} characters. Preserve the "
                "audience and domain framing."
            )
            script, _metadata = await self._call_claude_tool(
                system_prompt=system_prompt,
                user_message=retry_user,
            )

        if len(script) > max_chars:
            logger.warning(
                "Video script still over cap after re-prompt — truncating",
                original_chars=len(script),
                cap=max_chars,
            )
            script = _truncate_at_sentence(script, max_chars)

        return script

    async def _call_claude_tool(
        self,
        *,
        system_prompt: str,
        user_message: str,
    ) -> tuple[str, dict]:
        anthropic_client = self._claude.client
        async with anthropic_client.messages.stream(
            model="claude-sonnet-4-6",
            max_tokens=4000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
            tools=[VIDEO_SCRIPT_TOOL],
            tool_choice={"type": "tool", "name": "save_video_script"},
        ) as stream:
            message = await stream.get_final_message()

        for block in message.content:
            if (
                getattr(block, "type", None) == "tool_use"
                and getattr(block, "name", None) == "save_video_script"
            ):
                payload = block.input or {}
                scenes = payload.get("scenes") or []
                narration_parts: list[str] = []
                for scene in scenes:
                    text = (scene.get("narration") or "").strip()
                    if text:
                        narration_parts.append(text)
                script = " ".join(narration_parts).strip()
                metadata = {
                    "language": payload.get("language"),
                    "voice_tone": payload.get("voice_tone"),
                    "scenes": scenes,
                }
                if not script:
                    raise ValueError("Claude returned empty video script")
                return script, metadata

        raise ValueError("Claude did not invoke the save_video_script tool")

    def _heygen_callback_url(self) -> str | None:
        base = (settings.heygen_callback_base_url or "").rstrip("/")
        if not base:
            return None
        return f"{base}/api/v1/webhooks/heygen"
