"""Service for lesson content generation and management."""

import uuid
from collections.abc import AsyncGenerator
from datetime import datetime

import structlog
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.claude_service import ClaudeService
from app.ai.prompts.lesson import format_rag_context_for_lesson, get_lesson_system_prompt
from app.ai.rag.retriever import SemanticRetriever
from app.api.v1.schemas.content import LessonContent, LessonResponse, StreamingEvent
from app.domain.models.content import GeneratedContent
from app.domain.models.module import Module
from app.domain.models.module_unit import ModuleUnit

logger = structlog.get_logger()


class LessonGenerationService:
    """Service for orchestrating lesson content generation."""

    def __init__(
        self,
        claude_service: ClaudeService,
        semantic_retriever: SemanticRetriever,
    ):
        self.claude_service = claude_service
        self.semantic_retriever = semantic_retriever

    async def get_or_generate_lesson(
        self,
        module_id: uuid.UUID,
        unit_id: str,
        language: str,
        country: str,
        level: int,
        session: AsyncSession,
        force_regenerate: bool = False,
    ) -> LessonResponse:
        """
        Get cached lesson or generate new one.

        Args:
            module_id: Target module UUID
            unit_id: Unit identifier within module
            language: Content language (fr/en)
            country: User's country code
            level: User's competency level (1-4)
            session: Database session
            force_regenerate: Force new generation even if cached

        Returns:
            LessonResponse with generated or cached content
        """
        # Check for existing cached content first
        if not force_regenerate:
            cached_lesson = await self._get_cached_lesson(
                module_id, unit_id, language, country, level, session
            )
            if cached_lesson:
                logger.info(
                    "Retrieved cached lesson",
                    module_id=str(module_id),
                    unit_id=unit_id,
                    language=language,
                )
                return cached_lesson

        # Get module information
        module_result = await session.execute(select(Module).where(Module.id == module_id))
        module = module_result.scalar_one_or_none()

        if not module:
            raise ValueError(f"Module {module_id} not found")

        # Generate new lesson
        logger.info(
            "Generating new lesson",
            module_id=str(module_id),
            unit_id=unit_id,
            language=language,
            level=level,
            country=country,
        )

        lesson_response = await self._generate_lesson_content(
            module, unit_id, language, country, level, session
        )

        # Cache the generated content
        await self._cache_lesson_content(lesson_response, session)

        return lesson_response

    async def stream_lesson_generation(
        self,
        module_id: uuid.UUID,
        unit_id: str,
        language: str,
        country: str,
        level: int,
        session: AsyncSession,
    ) -> AsyncGenerator[StreamingEvent, None]:
        """
        Stream lesson generation in real-time.

        Args:
            module_id: Target module UUID
            unit_id: Unit identifier within module
            language: Content language (fr/en)
            country: User's country code
            level: User's competency level (1-4)
            session: Database session

        Yields:
            StreamingEvent objects for real-time updates
        """
        try:
            # Check cache first
            cached_lesson = await self._get_cached_lesson(
                module_id, unit_id, language, country, level, session
            )

            if cached_lesson:
                yield StreamingEvent(event="complete", data=cached_lesson.model_dump())
                return

            # Get module information
            module_result = await session.execute(select(Module).where(Module.id == module_id))
            module = module_result.scalar_one_or_none()

            if not module:
                yield StreamingEvent(
                    event="error",
                    data={"error": "module_not_found", "message": f"Module {module_id} not found"},
                )
                return

            yield StreamingEvent(event="chunk", data="Démarrage de la génération...")

            # Perform RAG retrieval
            yield StreamingEvent(event="chunk", data="Recherche des documents pertinents...")

            query = await self._build_lesson_query(module, unit_id, language, session)
            rag_chunks = await self.semantic_retriever.search_for_module(
                query=query,
                user_level=level,
                user_language=language,
                books_sources=module.books_sources,
                top_k=8,
                session=session,
            )

            if not rag_chunks:
                yield StreamingEvent(
                    event="error",
                    data={"error": "no_content_found", "message": "Aucun contenu pertinent trouvé"},
                )
                return

            yield StreamingEvent(event="chunk", data="Documents trouvés, génération en cours...")

            # Generate lesson using Claude API with streaming
            system_prompt = get_lesson_system_prompt(language, country, level, module.bloom_level)
            user_message = format_rag_context_for_lesson(
                rag_chunks,
                query,
                module.title_fr if language == "fr" else module.title_en,
                unit_id,
                language,
            )

            # Stream content generation
            accumulated_content = ""
            async for chunk in self.claude_service.generate_lesson_content_stream(
                system_prompt, user_message
            ):
                accumulated_content += chunk
                yield StreamingEvent(event="chunk", data=chunk)

            # Parse and structure the generated content
            lesson_content = await self._parse_lesson_content(accumulated_content, rag_chunks)

            # Create response object
            lesson_response = LessonResponse(
                module_id=module_id,
                unit_id=unit_id,
                language=language,
                level=level,
                country_context=country,
                content=lesson_content,
                generated_at=datetime.utcnow().isoformat(),
                cached=False,
            )

            # Cache the result
            await self._cache_lesson_content(lesson_response, session)

            yield StreamingEvent(event="complete", data=lesson_response.model_dump())

        except Exception as e:
            logger.error("Lesson generation streaming failed", error=str(e))
            yield StreamingEvent(
                event="error", data={"error": "generation_failed", "message": str(e)}
            )

    async def _get_cached_lesson(
        self,
        module_id: uuid.UUID,
        unit_id: str,
        language: str,
        country: str,
        level: int,
        session: AsyncSession,
    ) -> LessonResponse | None:
        """Check for existing cached lesson content."""
        query = (
            select(GeneratedContent)
            .where(GeneratedContent.module_id == module_id)
            .where(GeneratedContent.content_type == "lesson")
            .where(GeneratedContent.language == language)
            .where(GeneratedContent.level == level)
            .where(GeneratedContent.country_context == country)
            .where(GeneratedContent.content["unit_id"].astext == unit_id)
        )

        result = await session.execute(query)
        cached_content = result.scalar_one_or_none()

        if cached_content:
            return LessonResponse(
                id=cached_content.id,
                module_id=cached_content.module_id,
                unit_id=unit_id,
                language=cached_content.language,
                level=cached_content.level,
                country_context=cached_content.country_context,
                content=LessonContent(**cached_content.content),
                generated_at=cached_content.generated_at.isoformat(),
                cached=True,
            )

        return None

    async def _generate_lesson_content(
        self,
        module: Module,
        unit_id: str,
        language: str,
        country: str,
        level: int,
        session: AsyncSession,
    ) -> LessonResponse:
        """Generate new lesson content using RAG + Claude."""
        # Build search query
        query = await self._build_lesson_query(module, unit_id, language, session)

        # Perform RAG retrieval
        rag_chunks = await self.semantic_retriever.search_for_module(
            query=query,
            user_level=level,
            user_language=language,
            books_sources=module.books_sources,
            top_k=8,
            session=session,
        )

        if not rag_chunks:
            raise ValueError(f"No relevant content found for module {module.id}, unit {unit_id}")

        # Generate content with Claude
        system_prompt = get_lesson_system_prompt(language, country, level, module.bloom_level)
        user_message = format_rag_context_for_lesson(
            rag_chunks,
            query,
            module.title_fr if language == "fr" else module.title_en,
            unit_id,
            language,
        )

        # Get non-streaming response for structured parsing
        response = await self.claude_service.generate_lesson_content(system_prompt, user_message)

        if not response or not response.content:
            raise ValueError("Empty response from Claude API")

        # Extract content text
        content_text = ""
        for block in response.content:
            if hasattr(block, "text"):
                content_text += block.text

        # Parse structured content
        lesson_content = await self._parse_lesson_content(content_text, rag_chunks)

        return LessonResponse(
            module_id=module.id,
            unit_id=unit_id,
            language=language,
            level=level,
            country_context=country,
            content=lesson_content,
            generated_at=datetime.utcnow().isoformat(),
            cached=False,
        )

    async def _build_lesson_query(
        self, module: Module, unit_id: str, language: str, session: AsyncSession
    ) -> str:
        """Build search query for RAG retrieval using unit-specific metadata."""
        unit_number = self._unit_id_to_unit_number(unit_id, module.module_number)
        unit: ModuleUnit | None = None

        if unit_number:
            unit_result = await session.execute(
                select(ModuleUnit).where(
                    and_(
                        ModuleUnit.module_id == module.id,
                        ModuleUnit.unit_number == unit_number,
                    )
                )
            )
            unit = unit_result.scalar_one_or_none()

        if unit:
            unit_title = unit.title_fr if language == "fr" else unit.title_en
            unit_description = unit.description_fr if language == "fr" else unit.description_en
            query_parts = [unit_title]
            if unit_description:
                query_parts.append(unit_description[:200])
        else:
            title = module.title_fr if language == "fr" else module.title_en
            description = module.description_fr if language == "fr" else module.description_en
            query_parts = [title]
            if unit_id:
                query_parts.append(f"unit {unit_id}")
            if description:
                query_parts.append(description[:200])

        return " ".join(query_parts)

    @staticmethod
    def _unit_id_to_unit_number(unit_id: str, module_number: int) -> str | None:
        """Convert unit_id like 'M01-U02' to unit_number like '1.2'."""
        try:
            parts = unit_id.upper().split("-U")
            if len(parts) != 2:
                return None
            unit_ordinal = int(parts[1])
            return f"{module_number}.{unit_ordinal}"
        except (ValueError, IndexError):
            return None

    async def _parse_lesson_content(self, content_text: str, rag_chunks: list) -> LessonContent:
        """Parse generated content into structured lesson format."""
        # Extract source citations from RAG chunks
        sources_cited = []
        for chunk in rag_chunks:
            if hasattr(chunk, "chunk"):
                source = chunk.chunk.source
                chapter = getattr(chunk.chunk, "chapter", None)
                page = getattr(chunk.chunk, "page", None)
            else:
                source = chunk.source
                chapter = getattr(chunk, "chapter", None)
                page = getattr(chunk, "page", None)

            source_citation = source.title()
            if chapter:
                source_citation += f" Ch.{chapter}"
            if page:
                source_citation += f", p.{page}"

            if source_citation not in sources_cited:
                sources_cited.append(source_citation)

        # For now, return a basic structure with the full content
        # In a production system, you would parse the structured sections
        return LessonContent(
            introduction=content_text[:200] + "..." if len(content_text) > 200 else content_text,
            concepts=[content_text],  # Simplified - would parse sections in production
            aof_example="Exemple contextuel sera extrait du contenu généré...",
            synthesis="Synthèse sera extraite du contenu généré...",
            key_points=["Point clé 1", "Point clé 2", "Point clé 3"],  # Would be parsed
            sources_cited=sources_cited,
        )

    async def _cache_lesson_content(
        self, lesson_response: LessonResponse, session: AsyncSession
    ) -> None:
        """Save generated lesson content to cache."""
        # Add unit_id to content for querying
        content_with_unit = lesson_response.content.model_dump()
        content_with_unit["unit_id"] = lesson_response.unit_id

        cached_content = GeneratedContent(
            id=lesson_response.id,
            module_id=lesson_response.module_id,
            content_type="lesson",
            language=lesson_response.language,
            level=lesson_response.level,
            content=content_with_unit,
            sources_cited=lesson_response.content.sources_cited,
            country_context=lesson_response.country_context,
            validated=False,
        )

        session.add(cached_content)
        await session.commit()

        logger.info(
            "Cached lesson content",
            content_id=str(cached_content.id),
            module_id=str(cached_content.module_id),
            unit_id=lesson_response.unit_id,
        )
