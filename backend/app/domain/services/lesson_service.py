"""Service for lesson and case study content generation and management."""

import re
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime

import structlog
from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.ai.claude_service import ClaudeService
from app.ai.prompts.case_study import (
    format_rag_context_for_case_study,
    get_case_study_system_prompt,
)
from app.ai.prompts.lesson import format_rag_context_for_lesson, get_lesson_system_prompt
from app.ai.rag.retriever import SemanticRetriever
from app.api.v1.schemas.content import (
    CaseStudyContent,
    CaseStudyResponse,
    LessonContent,
    LessonResponse,
    SourceImageRef,
    StreamingEvent,
)
from app.domain.models.content import GeneratedContent
from app.domain.models.course import Course
from app.domain.models.module import Module
from app.domain.models.module_unit import ModuleUnit
from app.domain.services.platform_settings_service import SettingsCache

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

        # Get module information (eager-load course for prompt context)
        module_result = await session.execute(
            select(Module).where(Module.id == module_id).options(selectinload(Module.course))
        )
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

            # Get module information (eager-load course for prompt context)
            module_result = await session.execute(
                select(Module).where(Module.id == module_id).options(selectinload(Module.course))
            )
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
                top_k=SettingsCache.instance().get("ai-rag-default-top-k", 8),
                session=session,
            )

            if not rag_chunks:
                yield StreamingEvent(
                    event="error",
                    data={"error": "no_content_found", "message": "Aucun contenu pertinent trouvé"},
                )
                return

            yield StreamingEvent(event="chunk", data="Documents trouvés, génération en cours...")

            # Fetch source images linked to retrieved chunks
            chunk_ids = [
                c.chunk.id if hasattr(c, "chunk") else c.id
                for c in rag_chunks
                if (c.chunk.id if hasattr(c, "chunk") else getattr(c, "id", None)) is not None
            ]
            linked_images: dict = {}
            try:
                linked_images = await self.semantic_retriever.get_linked_images(chunk_ids, session)
            except Exception as exc:
                logger.warning(
                    "get_linked_images failed in streaming, continuing without images",
                    error=str(exc),
                )

            # Generate lesson using Claude API with streaming
            course: Course | None = module.course
            system_prompt = get_lesson_system_prompt(
                language,
                country,
                level,
                module.bloom_level,
                course_title=(
                    (course.title_fr if language == "fr" else course.title_en) if course else None
                ),
                course_description=(
                    (course.description_fr if language == "fr" else course.description_en)
                    if course
                    else None
                ),
            )
            user_message = format_rag_context_for_lesson(
                rag_chunks,
                query,
                module.title_fr if language == "fr" else module.title_en,
                unit_id,
                language,
                linked_images=linked_images or None,
            )

            # Stream content generation
            accumulated_content = ""
            async for chunk in self.claude_service.generate_lesson_content_stream(
                system_prompt, user_message
            ):
                accumulated_content += chunk
                yield StreamingEvent(event="chunk", data=chunk)

            # Post-process to extract {{source_image:UUID}} markers
            source_image_refs = self._extract_source_image_refs(accumulated_content, linked_images)

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
                source_image_refs=source_image_refs,
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
            .order_by(GeneratedContent.generated_at.desc())
        )

        result = await session.execute(query)
        cached_content = result.scalars().first()

        if cached_content:
            raw = cached_content.content
            source_image_refs_raw = raw.get("source_image_refs", [])
            source_image_refs = [
                SourceImageRef(**ref) for ref in source_image_refs_raw if isinstance(ref, dict)
            ]
            content_fields = {
                k: v for k, v in raw.items() if k not in {"unit_id", "source_image_refs"}
            }
            return LessonResponse(
                id=cached_content.id,
                module_id=cached_content.module_id,
                unit_id=unit_id,
                language=cached_content.language,
                level=cached_content.level,
                country_context=cached_content.country_context,
                content=LessonContent(**content_fields),
                generated_at=cached_content.generated_at.isoformat(),
                cached=True,
                source_image_refs=source_image_refs,
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

        # Fetch source images linked to retrieved chunks
        chunk_ids = [
            c.chunk.id if hasattr(c, "chunk") else c.id
            for c in rag_chunks
            if (c.chunk.id if hasattr(c, "chunk") else getattr(c, "id", None)) is not None
        ]
        linked_images: dict = {}
        try:
            linked_images = await self.semantic_retriever.get_linked_images(chunk_ids, session)
        except Exception as exc:
            logger.warning("get_linked_images failed, continuing without images", error=str(exc))

        # Generate content with Claude
        course: Course | None = module.course
        system_prompt = get_lesson_system_prompt(
            language,
            country,
            level,
            module.bloom_level,
            course_title=(
                (course.title_fr if language == "fr" else course.title_en) if course else None
            ),
            course_description=(
                (course.description_fr if language == "fr" else course.description_en)
                if course
                else None
            ),
        )
        user_message = format_rag_context_for_lesson(
            rag_chunks,
            query,
            module.title_fr if language == "fr" else module.title_en,
            unit_id,
            language,
            linked_images=linked_images or None,
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

        # Post-process to extract {{source_image:UUID}} markers
        source_image_refs = self._extract_source_image_refs(content_text, linked_images)

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
            source_image_refs=source_image_refs,
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

    @staticmethod
    def _extract_source_image_refs(content_text: str, linked_images: dict) -> list[SourceImageRef]:
        """Extract {{source_image:UUID}} markers from Claude output and resolve to SourceImageRef.

        Args:
            content_text: Raw text output from Claude
            linked_images: Mapping of chunk_id -> list of image metadata dicts

        Returns:
            Deduplicated list of SourceImageRef for UUIDs found in content_text
        """
        pattern = re.compile(r"\{\{source_image:([0-9a-f-]{36})\}\}", re.IGNORECASE)
        found_ids = list(dict.fromkeys(pattern.findall(content_text)))

        all_images: dict[str, dict] = {}
        for img_list in linked_images.values():
            for img in img_list:
                img_id = img.get("id", "")
                if img_id and img_id not in all_images:
                    all_images[img_id] = img

        refs = []
        for img_id in found_ids:
            img = all_images.get(img_id)
            if img:
                refs.append(
                    SourceImageRef(
                        id=img_id,
                        figure_number=img.get("figure_number"),
                        caption=img.get("caption"),
                        image_type=img.get("image_type") or "unknown",
                        storage_url=f"/api/v1/source-images/{img_id}/data",
                        alt_text_fr=img.get("alt_text_fr"),
                        alt_text_en=img.get("alt_text_en"),
                    )
                )
        return refs

    async def _cache_lesson_content(
        self, lesson_response: LessonResponse, session: AsyncSession
    ) -> None:
        """Save generated lesson content to cache."""
        content_with_unit = lesson_response.content.model_dump()
        content_with_unit["unit_id"] = lesson_response.unit_id
        content_with_unit["source_image_refs"] = [
            ref.model_dump() for ref in lesson_response.source_image_refs
        ]

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
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            logger.warning(
                "Lesson cache INSERT conflict (race condition), fetching existing row",
                module_id=str(lesson_response.module_id),
                unit_id=lesson_response.unit_id,
                language=lesson_response.language,
            )
            return

        logger.info(
            "Cached lesson content",
            content_id=str(cached_content.id),
            module_id=str(cached_content.module_id),
            unit_id=lesson_response.unit_id,
        )

        lesson_text = ""
        content_dict = lesson_response.content.model_dump()
        for key in ("introduction", "body", "summary", "content", "text"):
            if key in content_dict and content_dict[key]:
                lesson_text = str(content_dict[key])
                break
        if not lesson_text:
            lesson_text = str(content_dict)[:2000]

        try:
            from app.tasks.content_generation import generate_lesson_image

            generate_lesson_image.delay(
                str(cached_content.id),
                str(cached_content.module_id),
                lesson_response.unit_id,
                lesson_text[:2000],
            )
            logger.info(
                "Dispatched image generation task",
                lesson_id=str(cached_content.id),
            )
        except Exception as exc:
            logger.warning(
                "Failed to dispatch image generation task",
                lesson_id=str(cached_content.id),
                error=str(exc),
            )


class CaseStudyGenerationService:
    """Service for orchestrating case study content generation."""

    def __init__(
        self,
        claude_service: ClaudeService,
        semantic_retriever: SemanticRetriever,
    ):
        self.claude_service = claude_service
        self.semantic_retriever = semantic_retriever

    async def get_or_generate_case_study(
        self,
        module_id: uuid.UUID,
        unit_id: str,
        language: str,
        country: str,
        level: int,
        session: AsyncSession,
        force_regenerate: bool = False,
    ) -> CaseStudyResponse:
        """
        Get cached case study or generate new one.

        Args:
            module_id: Target module UUID
            unit_id: Unit identifier within module
            language: Content language (fr/en)
            country: User's country code
            level: User's competency level (1-4)
            session: Database session
            force_regenerate: Force new generation even if cached

        Returns:
            CaseStudyResponse with generated or cached content
        """
        if not force_regenerate:
            cached = await self._get_cached_case_study(
                module_id, unit_id, language, country, level, session
            )
            if cached:
                logger.info(
                    "Retrieved cached case study",
                    module_id=str(module_id),
                    unit_id=unit_id,
                    language=language,
                )
                return cached

        module_result = await session.execute(
            select(Module).where(Module.id == module_id).options(selectinload(Module.course))
        )
        module = module_result.scalar_one_or_none()

        if not module:
            raise ValueError(f"Module {module_id} not found")

        logger.info(
            "Generating new case study",
            module_id=str(module_id),
            unit_id=unit_id,
            language=language,
            level=level,
            country=country,
        )

        case_study_response = await self._generate_case_study_content(
            module, unit_id, language, country, level, session
        )

        await self._cache_case_study_content(case_study_response, session)

        return case_study_response

    async def stream_case_study_generation(
        self,
        module_id: uuid.UUID,
        unit_id: str,
        language: str,
        country: str,
        level: int,
        session: AsyncSession,
    ) -> AsyncGenerator[StreamingEvent, None]:
        """
        Stream case study generation in real-time.

        Yields:
            StreamingEvent objects for real-time updates
        """
        try:
            cached = await self._get_cached_case_study(
                module_id, unit_id, language, country, level, session
            )

            if cached:
                yield StreamingEvent(event="complete", data=cached.model_dump())
                return

            module_result = await session.execute(
                select(Module).where(Module.id == module_id).options(selectinload(Module.course))
            )
            module = module_result.scalar_one_or_none()

            if not module:
                yield StreamingEvent(
                    event="error",
                    data={"error": "module_not_found", "message": f"Module {module_id} not found"},
                )
                return

            yield StreamingEvent(event="chunk", data="Démarrage de la génération...")
            yield StreamingEvent(event="chunk", data="Recherche des documents pertinents...")

            query = await self._build_case_study_query(module, unit_id, language, session)
            rag_chunks = await self.semantic_retriever.search_for_module(
                query=query,
                user_level=level,
                user_language=language,
                books_sources=module.books_sources,
                top_k=SettingsCache.instance().get("ai-rag-default-top-k", 8),
                session=session,
            )

            if not rag_chunks:
                yield StreamingEvent(
                    event="error",
                    data={"error": "no_content_found", "message": "Aucun contenu pertinent trouvé"},
                )
                return

            yield StreamingEvent(event="chunk", data="Documents trouvés, génération en cours...")

            module_key = f"M{module.module_number:02d}"
            course: Course | None = module.course
            system_prompt = get_case_study_system_prompt(
                language,
                country,
                level,
                module.bloom_level,
                course_title=(
                    (course.title_fr if language == "fr" else course.title_en) if course else None
                ),
                course_description=(
                    (course.description_fr if language == "fr" else course.description_en)
                    if course
                    else None
                ),
            )
            user_message = format_rag_context_for_case_study(
                rag_chunks,
                query,
                module.title_fr if language == "fr" else module.title_en,
                unit_id,
                language,
                module_id=module_key,
                syllabus_json=course.syllabus_json if course else None,
            )

            accumulated_content = ""
            async for chunk in self.claude_service.generate_lesson_content_stream(
                system_prompt, user_message
            ):
                accumulated_content += chunk
                yield StreamingEvent(event="chunk", data=chunk)

            case_study_content = await self._parse_case_study_content(
                accumulated_content, rag_chunks
            )

            case_study_response = CaseStudyResponse(
                module_id=module_id,
                unit_id=unit_id,
                language=language,
                level=level,
                country_context=country,
                content=case_study_content,
                generated_at=datetime.utcnow().isoformat(),
                cached=False,
            )

            await self._cache_case_study_content(case_study_response, session)

            yield StreamingEvent(event="complete", data=case_study_response.model_dump())

        except Exception as e:
            logger.error("Case study generation streaming failed", error=str(e))
            yield StreamingEvent(
                event="error", data={"error": "generation_failed", "message": str(e)}
            )

    async def _get_cached_case_study(
        self,
        module_id: uuid.UUID,
        unit_id: str,
        language: str,
        country: str,
        level: int,
        session: AsyncSession,
    ) -> CaseStudyResponse | None:
        """Check for existing cached case study content."""
        query = (
            select(GeneratedContent)
            .where(GeneratedContent.module_id == module_id)
            .where(GeneratedContent.content_type == "case")
            .where(GeneratedContent.language == language)
            .where(GeneratedContent.level == level)
            .where(GeneratedContent.country_context == country)
            .where(GeneratedContent.content["unit_id"].astext == unit_id)
            .order_by(GeneratedContent.generated_at.desc())
        )

        result = await session.execute(query)
        cached_content = result.scalars().first()

        if cached_content:
            return CaseStudyResponse(
                id=cached_content.id,
                module_id=cached_content.module_id,
                unit_id=unit_id,
                language=cached_content.language,
                level=cached_content.level,
                country_context=cached_content.country_context,
                content=CaseStudyContent(**cached_content.content),
                generated_at=cached_content.generated_at.isoformat(),
                cached=True,
            )

        return None

    async def _generate_case_study_content(
        self,
        module: Module,
        unit_id: str,
        language: str,
        country: str,
        level: int,
        session: AsyncSession,
    ) -> CaseStudyResponse:
        """Generate new case study content using RAG + Claude."""
        query = await self._build_case_study_query(module, unit_id, language, session)

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

        module_key = f"M{module.module_number:02d}"
        course: Course | None = module.course
        system_prompt = get_case_study_system_prompt(
            language,
            country,
            level,
            module.bloom_level,
            course_title=(
                (course.title_fr if language == "fr" else course.title_en) if course else None
            ),
            course_description=(
                (course.description_fr if language == "fr" else course.description_en)
                if course
                else None
            ),
        )
        user_message = format_rag_context_for_case_study(
            rag_chunks,
            query,
            module.title_fr if language == "fr" else module.title_en,
            unit_id,
            language,
            module_id=module_key,
            syllabus_json=course.syllabus_json if course else None,
        )

        response = await self.claude_service.generate_lesson_content(system_prompt, user_message)

        if not response or not response.content:
            raise ValueError("Empty response from Claude API")

        content_text = ""
        for block in response.content:
            if hasattr(block, "text"):
                content_text += block.text

        case_study_content = await self._parse_case_study_content(content_text, rag_chunks)

        return CaseStudyResponse(
            module_id=module.id,
            unit_id=unit_id,
            language=language,
            level=level,
            country_context=country,
            content=case_study_content,
            generated_at=datetime.utcnow().isoformat(),
            cached=False,
        )

    async def _build_case_study_query(
        self, module: Module, unit_id: str, language: str, session: AsyncSession
    ) -> str:
        """Build search query for case study RAG retrieval."""
        unit_number = LessonGenerationService._unit_id_to_unit_number(unit_id, module.module_number)
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
                query_parts.append(
                    f"étude de cas {unit_id}" if language == "fr" else f"case study {unit_id}"
                )
            if description:
                query_parts.append(description[:200])

        return " ".join(query_parts)

    async def _parse_case_study_content(
        self, content_text: str, rag_chunks: list
    ) -> CaseStudyContent:
        """Parse generated content into structured case study format.

        Claude produces 4 numbered sections with bold headers like:
          1. **Contexte AOF** / 1. **AOF Context**
          2. **Données réelles** / 2. **Real Data**
          3. **Questions guidées** / 3. **Guided Questions**
          4. **Correction annotée** / 4. **Annotated Correction**

        This method splits on those headers and maps each section.
        """
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

        # Split on numbered section headers: "1. **...**", "## 1. **...**", etc.
        section_pattern = r"(?:^|\n)(?:#{1,3}\s*)?(\d+)\.\s*\*\*[^*]+\*\*"
        splits = list(re.finditer(section_pattern, content_text))

        sections: dict[int, str] = {}
        for i, match in enumerate(splits):
            section_num = int(match.group(1))
            start = match.end()
            end = splits[i + 1].start() if i + 1 < len(splits) else len(content_text)
            sections[section_num] = content_text[start:end].strip()

        # Fallback: if regex found no sections, split by paragraphs proportionally
        if not sections:
            logger.warning("Case study section headers not found, using paragraph fallback")
            paragraphs = [p.strip() for p in content_text.split("\n\n") if p.strip()]
            if len(paragraphs) >= 4:
                quarter = max(1, len(paragraphs) // 4)
                sections = {
                    1: "\n\n".join(paragraphs[:quarter]),
                    2: "\n\n".join(paragraphs[quarter : 2 * quarter]),
                    3: "\n\n".join(paragraphs[2 * quarter : 3 * quarter]),
                    4: "\n\n".join(paragraphs[3 * quarter :]),
                }
            else:
                # Too few paragraphs — split by character position
                chunk_size = max(1, len(content_text) // 4)
                sections = {
                    1: content_text[:chunk_size].strip(),
                    2: content_text[chunk_size : 2 * chunk_size].strip(),
                    3: content_text[2 * chunk_size : 3 * chunk_size].strip(),
                    4: content_text[3 * chunk_size :].strip(),
                }

        # Parse guided questions from section 3 (numbered or bulleted lines)
        questions_text = sections.get(3, "")
        question_lines = re.findall(
            r"(?:^|\n)\s*(?:\d+[\.\)]\s*|-\s*|\*\s*)(.+?)(?=\n\s*(?:\d+[\.\)]|-|\*)|\Z)",
            questions_text,
            re.DOTALL,
        )
        guided_questions = [q.strip() for q in question_lines if q.strip()]

        # If individual question extraction failed, use the whole section text
        if not guided_questions and questions_text.strip():
            guided_questions = [
                line.strip()
                for line in questions_text.strip().split("\n")
                if line.strip() and not re.match(r"^#{1,3}\s", line)
            ]

        # Ensure minimum 2 questions (schema constraint: min_length=2)
        if len(guided_questions) < 2:
            guided_questions = [questions_text.strip() or sections.get(3, "")]
            if len(guided_questions) < 2:
                guided_questions.append("")

        return CaseStudyContent(
            aof_context=sections.get(1, content_text[:500]),
            real_data=sections.get(2, ""),
            guided_questions=guided_questions,
            annotated_correction=sections.get(4, ""),
            sources_cited=sources_cited,
        )

    async def _cache_case_study_content(
        self, case_study_response: CaseStudyResponse, session: AsyncSession
    ) -> None:
        """Save generated case study content to cache."""
        content_with_unit = case_study_response.content.model_dump()
        content_with_unit["unit_id"] = case_study_response.unit_id

        cached_content = GeneratedContent(
            id=case_study_response.id,
            module_id=case_study_response.module_id,
            content_type="case",
            language=case_study_response.language,
            level=case_study_response.level,
            content=content_with_unit,
            sources_cited=case_study_response.content.sources_cited,
            country_context=case_study_response.country_context,
            validated=False,
        )

        session.add(cached_content)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            logger.warning(
                "Case study cache INSERT conflict (race condition), fetching existing row",
                module_id=str(case_study_response.module_id),
                unit_id=case_study_response.unit_id,
                language=case_study_response.language,
            )
            return

        logger.info(
            "Cached case study content",
            content_id=str(cached_content.id),
            module_id=str(cached_content.module_id),
            unit_id=case_study_response.unit_id,
        )
