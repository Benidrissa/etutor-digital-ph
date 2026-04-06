"""Audio summary generation service using Claude (script) + Gemini TTS (MP3)."""

from __future__ import annotations

import uuid
from datetime import datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.ai.claude_service import ClaudeService
from app.ai.rag.embeddings import EmbeddingService
from app.ai.rag.retriever import SemanticRetriever
from app.domain.models.module import Module
from app.domain.models.module_media import ModuleMedia
from app.domain.models.module_unit import ModuleUnit
from app.infrastructure.config.settings import settings
from app.infrastructure.storage.s3 import S3StorageService

logger = structlog.get_logger(__name__)

AUDIO_SUMMARY_SYSTEM_PROMPT = """You are an expert in public health for West Africa (ECOWAS region).
Your task is to write a spoken audio summary script for a learning module.

Guidelines:
- Write in {language} (French or English as specified)
- Length: approximately 2000 words — about 10-12 minutes of spoken audio
- Style: clear, engaging narration suitable for public health professionals
- Structure: brief introduction → core concepts → real West African examples → key takeaways
- Use simple language accessible on 2G/3G with limited bandwidth
- Reference concrete examples from West African health systems where possible
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

            script = await self._generate_script(
                module_title=module_title or f"Module {module.module_number}",
                language=language,
                level=module.level,
                unit_titles=unit_titles,
                rag_chunks=rag_chunks,
            )

            audio_bytes = await self._call_gemini_tts(script, language)

            storage_key = f"audio/{module_id}/{language}/summary.mp3"
            storage_url = await self._storage.upload_bytes(
                key=storage_key,
                data=audio_bytes,
                content_type="audio/mpeg",
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
    ) -> str:
        """Call Claude to generate a ~2000-word spoken summary script."""
        system_prompt = AUDIO_SUMMARY_SYSTEM_PROMPT.format(language=language)
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

    async def _call_gemini_tts(self, script: str, language: str) -> bytes:
        """Call Gemini TTS API to convert script to MP3 bytes.

        Uses google-generativeai SDK with gemini-2.5-flash-preview-tts model.
        """
        if not settings.google_api_key:
            raise ValueError("GOOGLE_API_KEY is required for Gemini TTS")

        import google.generativeai as genai  # type: ignore[import-untyped]

        genai.configure(api_key=settings.google_api_key)

        voice_name = "Aoede" if language == "fr" else "Charon"

        model = genai.GenerativeModel("gemini-2.5-flash-preview-tts")

        response = await model.generate_content_async(
            script,
            generation_config=genai.GenerationConfig(
                response_modalities=["AUDIO"],
                speech_config=genai.SpeechConfig(
                    voice_config=genai.VoiceConfig(
                        prebuilt_voice_config=genai.PrebuiltVoiceConfig(voice_name=voice_name)
                    )
                ),
            ),
        )

        audio_bytes = self._extract_audio_bytes(response)

        logger.info(
            "Gemini TTS audio generated",
            language=language,
            audio_size_bytes=len(audio_bytes),
        )
        return audio_bytes

    def _extract_audio_bytes(self, response: object) -> bytes:
        """Extract raw audio bytes from Gemini TTS response."""
        try:
            for candidate in response.candidates:  # type: ignore[union-attr]
                for part in candidate.content.parts:
                    if hasattr(part, "inline_data") and part.inline_data:
                        return part.inline_data.data
        except Exception as exc:
            logger.error("Failed to extract audio bytes from Gemini response", error=str(exc))

        raise ValueError("No audio data found in Gemini TTS response")

    def _estimate_duration(self, file_size_bytes: int) -> int:
        """Estimate audio duration from file size.

        Assumes ~128kbps MP3 encoding.
        """
        bits_per_second = 128 * 1024
        bytes_per_second = bits_per_second // 8
        return max(1, file_size_bytes // bytes_per_second)
