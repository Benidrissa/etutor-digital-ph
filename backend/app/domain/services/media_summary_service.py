"""Audio summary generation service using Claude (script) + Gemini TTS (MP3)."""

from __future__ import annotations

import uuid
from datetime import datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.ai.claude_service import ClaudeService
from app.ai.prompts.audience import detect_audience
from app.ai.rag.embeddings import EmbeddingService
from app.ai.rag.retriever import SemanticRetriever
from app.domain.models.module import Module
from app.domain.models.module_media import ModuleMedia
from app.domain.models.module_unit import ModuleUnit
from app.infrastructure.config.settings import settings
from app.infrastructure.storage.s3 import S3StorageService

logger = structlog.get_logger(__name__)


def _build_audio_system_prompt(
    language: str,
    course_title: str | None = None,
    is_kids: bool = False,
    age_range: str = "",
) -> str:
    """Build a context-aware audio summary system prompt.

    Args:
        language: Content language code ("fr" or "en").
        course_title: Optional course title used as domain descriptor.
        is_kids: Whether the course targets children.
        age_range: Age range string (e.g. "6-12") used when is_kids=True.

    Returns:
        Formatted system prompt string for Claude.
    """
    domain = course_title or "public health"
    if is_kids:
        audience = f"young learners aged {age_range}"
        style = f"clear, engaging, and fun narration suitable for children aged {age_range}"
        west_africa_note = (
            "Reference concrete examples from West Africa that children can relate to"
        )
    else:
        audience = f"professionals in {domain}"
        style = f"clear, engaging narration suitable for {audience}"
        west_africa_note = (
            "Reference concrete examples from West African health systems where possible"
        )

    return f"""You are an expert educator in {domain} for West Africa (ECOWAS region).
Your task is to write a spoken audio summary script for a learning module.

Guidelines:
- Write in {language} (French or English as specified)
- Length: approximately 2000 words — about 10-12 minutes of spoken audio
- Style: {style}
- Structure: brief introduction → core concepts → real West African examples → key takeaways
- Use simple language accessible on 2G/3G with limited bandwidth
- {west_africa_note}
- DO NOT include headers, bullet points, or markdown — write plain spoken prose
- DO NOT include source citations in the script itself (they are tracked separately)
- End with 3-5 key takeaways the listener should remember

Output only the script text, nothing else."""


AUDIO_SUMMARY_USER_TEMPLATE = """Module: {module_title}
Language: {language}
Level: {level}

Module units covered:
{unit_titles}

Reference material excerpts (RAG context):
{rag_context}

Write the audio summary script now."""


def _format_rag_context(chunks: list) -> str:
    """Format RAG chunks into a readable context block."""
    parts = []
    for i, result in enumerate(chunks, 1):
        chunk = result.chunk
        source = chunk.source or "unknown"
        chapter = f" ch.{chunk.chapter}" if chunk.chapter else ""
        page = f" p.{chunk.page}" if chunk.page else ""
        parts.append(f"[{i}] Source: {source}{chapter}{page}\n{chunk.content}")
    return "\n\n".join(parts) if parts else "No reference material available."


class MediaSummaryService:
    """Pipeline: DB cache check → Claude script → Gemini TTS → MinIO upload."""

    def __init__(
        self,
        claude_service: ClaudeService | None = None,
        retriever: SemanticRetriever | None = None,
        storage: S3StorageService | None = None,
    ) -> None:
        self._claude = claude_service or ClaudeService()
        self._retriever = retriever
        self._storage = storage or S3StorageService()

    async def generate_audio_summary(
        self,
        module_id: uuid.UUID,
        language: str,
        session: AsyncSession,
    ) -> ModuleMedia:
        """Generate or return cached audio summary for a module.

        Status transitions: pending → generating → ready | failed

        Args:
            module_id: UUID of the module
            language: Language code ("fr" or "en")
            session: Async SQLAlchemy session

        Returns:
            ModuleMedia record with status "ready" (or "failed" on error)
        """
        cached = await self._find_cached(module_id, language, session)
        if cached is not None:
            logger.info(
                "Returning cached audio summary",
                module_id=str(module_id),
                language=language,
                media_id=str(cached.id),
            )
            return cached

        # Reuse existing pending record (created by API endpoint) or create new
        pending = await self._find_pending(module_id, language, session)
        if pending is not None:
            record = pending
        else:
            record = ModuleMedia(
                id=uuid.uuid4(),
                module_id=module_id,
                media_type="audio_summary",
                language=language,
                status="pending",
            )
            session.add(record)
            await session.flush()

        try:
            record.status = "generating"
            await session.flush()

            module = await self._fetch_module(module_id, session)
            if module is None:
                raise ValueError(f"Module {module_id} not found")

            unit_titles = await self._fetch_unit_titles(module_id, session)

            module_title = module.title_fr if language == "fr" else module.title_en
            query = f"{module_title} {' '.join(unit_titles[:5])}"
            rag_chunks = await self._fetch_rag_chunks(
                query=query,
                user_level=module.level,
                user_language=language,
                books_sources=self._resolve_books_sources(module),
                session=session,
            )

            course = module.course
            audience_ctx = detect_audience(course)
            course_title = None
            if course is not None:
                course_title = course.title_fr if language == "fr" else course.title_en
            age_range = (
                f"{audience_ctx.age_min}-{audience_ctx.age_max}" if audience_ctx.is_kids else ""
            )

            script = await self._generate_script(
                module_title=module_title or f"Module {module.module_number}",
                language=language,
                level=module.level,
                unit_titles=unit_titles,
                rag_chunks=rag_chunks,
                course_title=course_title,
                is_kids=audience_ctx.is_kids,
                age_range=age_range,
            )

            audio_bytes = await self._call_tts(script, language)

            storage_key = f"audio/{module_id}/{language}/summary.opus"
            storage_url = await self._storage.upload_bytes(
                key=storage_key,
                data=audio_bytes,
                content_type="audio/ogg",
            )

            duration_seconds = self._estimate_duration(len(audio_bytes))

            record.status = "ready"
            record.script_text = script
            record.storage_key = storage_key
            record.storage_url = storage_url
            record.duration_seconds = duration_seconds
            record.file_size_bytes = len(audio_bytes)
            record.generated_at = datetime.utcnow()
            await session.commit()

            logger.info(
                "Audio summary generated successfully",
                module_id=str(module_id),
                language=language,
                media_id=str(record.id),
                duration_seconds=duration_seconds,
                file_size_bytes=len(audio_bytes),
            )

        except Exception as exc:
            record.status = "failed"
            record.error_message = str(exc)
            await session.commit()
            logger.error(
                "Audio summary generation failed",
                module_id=str(module_id),
                language=language,
                media_id=str(record.id),
                error=str(exc),
            )
            raise

        return record

    async def _find_cached(
        self,
        module_id: uuid.UUID,
        language: str,
        session: AsyncSession,
    ) -> ModuleMedia | None:
        """Return existing ready audio summary if available."""
        result = await session.execute(
            select(ModuleMedia).where(
                ModuleMedia.module_id == module_id,
                ModuleMedia.language == language,
                ModuleMedia.media_type == "audio_summary",
                ModuleMedia.status == "ready",
            )
        )
        return result.scalar_one_or_none()

    async def _find_pending(
        self,
        module_id: uuid.UUID,
        language: str,
        session: AsyncSession,
    ) -> ModuleMedia | None:
        """Return existing pending/generating record to avoid duplicates."""
        result = await session.execute(
            select(ModuleMedia).where(
                ModuleMedia.module_id == module_id,
                ModuleMedia.language == language,
                ModuleMedia.media_type == "audio_summary",
                ModuleMedia.status.in_(["pending", "generating"]),
            )
        )
        return result.scalar_one_or_none()

    async def _fetch_module(self, module_id: uuid.UUID, session: AsyncSession) -> Module | None:
        result = await session.execute(
            select(Module).where(Module.id == module_id).options(selectinload(Module.course))
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _resolve_books_sources(module: Module) -> dict | None:
        """Prefer course rag_collection_id over module.books_sources."""
        course = module.course
        if course and course.rag_collection_id:
            return {course.rag_collection_id: []}
        if module.books_sources:
            return module.books_sources
        return None

    async def _fetch_unit_titles(self, module_id: uuid.UUID, session: AsyncSession) -> list[str]:
        result = await session.execute(
            select(ModuleUnit)
            .where(ModuleUnit.module_id == module_id)
            .order_by(ModuleUnit.order_index)
        )
        units = result.scalars().all()
        titles = []
        for u in units:
            title = u.title_fr or u.title_en or ""
            if title:
                titles.append(title)
        return titles

    async def _fetch_rag_chunks(
        self,
        query: str,
        user_level: int,
        user_language: str,
        books_sources: dict,
        session: AsyncSession,
    ) -> list:
        if self._retriever is None:
            embedding_service = EmbeddingService(
                api_key=settings.openai_api_key,
                model=settings.embedding_model,
            )
            self._retriever = SemanticRetriever(embedding_service)

        try:
            return await self._retriever.search_for_module(
                query=query,
                user_level=user_level,
                user_language=user_language,
                books_sources=books_sources if books_sources else None,
                top_k=12,
                session=session,
            )
        except Exception as exc:
            logger.warning("RAG retrieval failed, proceeding without context", error=str(exc))
            return []

    async def _generate_script(
        self,
        module_title: str,
        language: str,
        level: int,
        unit_titles: list[str],
        rag_chunks: list,
        course_title: str | None = None,
        is_kids: bool = False,
        age_range: str = "",
    ) -> str:
        """Call Claude to generate a ~2000-word spoken summary script."""
        system_prompt = _build_audio_system_prompt(
            language=language,
            course_title=course_title,
            is_kids=is_kids,
            age_range=age_range,
        )
        unit_list = "\n".join(f"- {t}" for t in unit_titles) if unit_titles else "- (no units)"
        rag_context = _format_rag_context(rag_chunks)

        language_label = "French" if language == "fr" else "English"
        user_message = AUDIO_SUMMARY_USER_TEMPLATE.format(
            module_title=module_title,
            language=language_label,
            level=level,
            unit_titles=unit_list,
            rag_context=rag_context,
        )

        response = await self._claude.generate_lesson_content(
            system_prompt=system_prompt,
            user_message=user_message,
        )

        script_text = ""
        for block in response.content:
            if hasattr(block, "text"):
                script_text += block.text

        if not script_text.strip():
            raise ValueError("Claude returned empty script")

        logger.info(
            "Claude script generated",
            module_title=module_title,
            language=language,
            script_length=len(script_text),
        )
        return script_text.strip()

    async def _call_tts(self, script: str, language: str) -> bytes:
        """Call OpenAI TTS API to convert script to OGG Opus audio.

        Uses gpt-4o-mini-tts model with opus output format.
        """
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=settings.openai_api_key)

        voice = "nova" if language == "fr" else "ash"
        lang_label = "French" if language == "fr" else "English"

        response = await client.audio.speech.create(
            model="gpt-4o-mini-tts",
            voice=voice,
            input=script,
            instructions=f"Speak in {lang_label} with a clear, warm, educational tone suitable for a learning platform.",
            response_format="opus",
        )

        audio_bytes = response.content
        if not audio_bytes:
            raise ValueError("OpenAI TTS returned empty audio")

        logger.info(
            "OpenAI TTS audio generated",
            language=language,
            voice=voice,
            audio_size_bytes=len(audio_bytes),
        )
        return audio_bytes

    def _estimate_duration(self, file_size_bytes: int) -> int:
        """Estimate audio duration from OGG Opus file size (~48kbps speech)."""
        bytes_per_second = 6 * 1024
        return max(1, file_size_bytes // bytes_per_second)
