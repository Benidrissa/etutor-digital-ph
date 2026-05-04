"""Service for lesson and case study content generation and management."""

import json
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
from app.ai.prompts.lesson import (
    format_rag_context_for_lesson,
    get_lesson_system_prompt,
)
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
from app.domain.models.source_image import SourceImage
from app.domain.services.platform_settings_service import SettingsCache

logger = structlog.get_logger()


def extract_lesson_text(content) -> str:
    """Extract readable text from lesson content (dict or LessonContent model).

    Works with both raw dicts (from GeneratedContent.content JSON column)
    and Pydantic LessonContent objects.
    """
    if isinstance(content, dict):
        d = content
    elif hasattr(content, "model_dump"):
        d = content.model_dump()
    else:
        return str(content)[:2000]

    parts: list[str] = []
    if d.get("introduction"):
        parts.append(str(d["introduction"]))
    if d.get("concepts"):
        concepts = d["concepts"]
        if isinstance(concepts, list):
            parts.extend(str(c) for c in concepts if c)
        else:
            parts.append(str(concepts))
    if d.get("aof_example"):
        parts.append(str(d["aof_example"]))
    if d.get("synthesis"):
        parts.append(str(d["synthesis"]))
    return "\n\n".join(parts) if parts else str(d)[:2000]


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
        user_id: uuid.UUID | None = None,
        quality_constraints: list[str] | None = None,
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
            user_id: Optional user UUID for background task logging

        Returns:
            LessonResponse with generated or cached content
        """
        # Always return manually edited content, even with force_regenerate
        if force_regenerate:
            from app.domain.services._unit_resolution import resolve_module_unit_id

            locked_unit_uuid = await resolve_module_unit_id(session, module_id, unit_id)
            locked_query = (
                (
                    select(GeneratedContent.id)
                    .where(GeneratedContent.module_unit_id == locked_unit_uuid)
                    .where(GeneratedContent.content_type == "lesson")
                    .where(GeneratedContent.language == language)
                    .where(GeneratedContent.is_manually_edited.is_(True))
                    .limit(1)
                )
                if locked_unit_uuid
                else None
            )
            locked_result = (
                await session.execute(locked_query) if locked_query is not None else None
            )
            if locked_result is not None and locked_result.scalar_one_or_none():
                logger.info(
                    "Returning manually edited lesson (locked, ignoring force_regenerate)",
                    module_id=str(module_id),
                    unit_id=unit_id,
                )
                # Fetch via the normal cache path which handles image refs
                cached, _ = await self._get_cached_lesson(
                    module_id, unit_id, language, country, level, session
                )
                if cached:
                    return cached

        # Check for existing cached content first
        if not force_regenerate:
            cached_lesson, is_fallback = await self._get_cached_lesson(
                module_id, unit_id, language, country, level, session
            )
            if cached_lesson:
                logger.info(
                    "Retrieved cached lesson",
                    module_id=str(module_id),
                    unit_id=unit_id,
                    language=language,
                    country_fallback=is_fallback,
                )
                if is_fallback:
                    from app.tasks.content_generation import generate_country_content_task

                    generate_country_content_task.delay(
                        module_id=str(module_id),
                        unit_id=unit_id,
                        content_type="lesson",
                        language=language,
                        level=level,
                        country=country,
                        user_id=str(user_id) if user_id else "",
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
            module, unit_id, language, country, level, session,
            quality_constraints=quality_constraints,
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
        user_id: uuid.UUID | None = None,
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
            user_id: Optional user UUID for background task logging

        Yields:
            StreamingEvent objects for real-time updates
        """
        try:
            # Check cache first
            cached_lesson, is_fallback = await self._get_cached_lesson(
                module_id, unit_id, language, country, level, session
            )

            if cached_lesson:
                if is_fallback:
                    from app.tasks.content_generation import generate_country_content_task

                    generate_country_content_task.delay(
                        module_id=str(module_id),
                        unit_id=unit_id,
                        content_type="lesson",
                        language=language,
                        level=level,
                        country=country,
                        user_id=str(user_id) if user_id else "",
                    )
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
                    data={
                        "error": "module_not_found",
                        "message": f"Module {module_id} not found",
                    },
                )
                return

            yield StreamingEvent(event="chunk", data="Démarrage de la génération...")

            # Resolve unit metadata once — for prompt grounding + RAG query.
            unit = await self._resolve_unit(module, unit_id, session)
            unit_title = (unit.title_fr if language == "fr" else unit.title_en) if unit else ""
            unit_description = (
                (unit.description_fr if language == "fr" else unit.description_en) if unit else None
            )
            module_title = module.title_fr if language == "fr" else module.title_en

            # Perform RAG retrieval
            yield StreamingEvent(event="chunk", data="Recherche des documents pertinents...")

            query = await self._build_lesson_query(module, unit_id, language, session)
            rag_chunks = await self.semantic_retriever.search_for_module(
                query=query,
                user_level=level,
                user_language=language,
                books_sources=self._resolve_books_sources(module),
                top_k=SettingsCache.instance().get("ai-rag-default-top-k", 8),
                session=session,
            )

            if not rag_chunks:
                yield StreamingEvent(
                    event="error",
                    data={
                        "error": "no_content_found",
                        "message": "Aucun contenu pertinent trouvé",
                    },
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

            total_linked = sum(len(v) for v in linked_images.values()) if linked_images else 0
            logger.info(
                "lesson.image_pipeline",
                chunk_count=len(chunk_ids),
                linked_images_total=total_linked,
                module_id=str(module.id),
                unit_id=unit_id,
                streaming=True,
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
                module_title=module_title,
                unit_title=unit_title,
                course=course,
            )
            user_message = format_rag_context_for_lesson(
                rag_chunks,
                query,
                module_title,
                unit_id,
                language,
                linked_images=linked_images or None,
                unit_title=unit_title,
                unit_description=unit_description,
            )

            # Stream content generation
            accumulated_content = ""
            async for chunk in self.claude_service.generate_lesson_content_stream(
                system_prompt, user_message
            ):
                accumulated_content += chunk
                yield StreamingEvent(event="chunk", data=chunk)

            # Post-process to extract {{source_image:UUID}} markers
            source_image_refs = await self._extract_source_image_refs(
                accumulated_content, linked_images, session
            )

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

    @staticmethod
    async def _rehydrate_source_image_refs(
        raw_refs: list,
        session: AsyncSession | None,
    ) -> list[SourceImageRef]:
        """Re-apply current DB values (especially FR/EN captions + alt text) to
        cached ``source_image_refs`` before returning a cached lesson.

        Lessons generated before the figure-translation backfill (#1820) baked
        the raw English caption into both ``caption_fr`` and ``caption_en``.
        Cached JSON can't know about later translations, so we hydrate the
        per-locale fields from ``source_images`` on every read. Falls back to
        the cached values when the row can no longer be found.
        """
        parsed: list[SourceImageRef] = []
        ids: list[uuid.UUID] = []
        for ref in raw_refs:
            if not isinstance(ref, dict):
                continue
            parsed.append(SourceImageRef(**ref))
            try:
                ids.append(uuid.UUID(ref.get("id")))
            except (TypeError, ValueError):
                continue

        if not parsed or session is None or not ids:
            return parsed

        rows = await session.execute(select(SourceImage).where(SourceImage.id.in_(ids)))
        by_id = {str(r.id): r for r in rows.scalars().all()}

        rehydrated: list[SourceImageRef] = []
        for ref in parsed:
            db_img = by_id.get(ref.id)
            if db_img is None:
                rehydrated.append(ref)
                continue
            caption = db_img.caption or ref.caption
            rehydrated.append(
                SourceImageRef(
                    id=ref.id,
                    figure_number=db_img.figure_number or ref.figure_number,
                    caption=caption,
                    caption_fr=db_img.caption_fr or caption,
                    caption_en=db_img.caption_en or caption,
                    attribution=db_img.attribution or ref.attribution,
                    image_type=db_img.image_type or ref.image_type,
                    storage_url=db_img.storage_url or ref.storage_url,
                    storage_url_fr=db_img.storage_url_fr or ref.storage_url_fr,
                    alt_text_fr=db_img.alt_text_fr or ref.alt_text_fr,
                    alt_text_en=db_img.alt_text_en or ref.alt_text_en,
                )
            )
        return rehydrated

    async def _get_cached_lesson(
        self,
        module_id: uuid.UUID,
        unit_id: str,
        language: str,
        country: str,
        level: int,
        session: AsyncSession,
    ) -> tuple[LessonResponse | None, bool]:
        """Check for existing cached lesson content.

        Returns:
            Tuple of (LessonResponse | None, country_fallback: bool).
            country_fallback is True when content is from a different country's cache.
        """
        from app.domain.services._unit_resolution import resolve_module_unit_id

        module_unit_uuid = await resolve_module_unit_id(session, module_id, unit_id)
        if module_unit_uuid is None:
            return None, False

        query = (
            select(GeneratedContent)
            .where(GeneratedContent.module_unit_id == module_unit_uuid)
            .where(GeneratedContent.content_type == "lesson")
            .where(GeneratedContent.language == language)
            .where(GeneratedContent.level == level)
            .where(GeneratedContent.country_context == country)
            .order_by(GeneratedContent.generated_at.desc())
        )

        result = await session.execute(query)
        cached_content = result.scalars().first()

        if not cached_content:
            fallback_query = (
                select(GeneratedContent)
                .where(GeneratedContent.module_unit_id == module_unit_uuid)
                .where(GeneratedContent.content_type == "lesson")
                .where(GeneratedContent.language == language)
                .where(GeneratedContent.level == level)
                .order_by(GeneratedContent.generated_at.desc())
            )
            fallback_result = await session.execute(fallback_query)
            cached_content = fallback_result.scalars().first()
            is_fallback = cached_content is not None
        else:
            is_fallback = False

        if cached_content:
            raw_refs = cached_content.content.get("source_image_refs", [])
            source_image_refs = await self._rehydrate_source_image_refs(raw_refs, session)

            content_dict = cached_content.content
            all_text_fields = " ".join(
                str(content_dict.get(f, "") or "")
                for f in ("introduction", "aof_example", "synthesis")
            )
            for field in ("concepts", "key_points"):
                for item in content_dict.get(field, []):
                    if isinstance(item, dict):
                        all_text_fields += " " + " ".join(str(v or "") for v in item.values())
                    else:
                        all_text_fields += " " + str(item or "")

            existing_ids = {ref.id for ref in source_image_refs}
            if re.search(r"\{\{source_image:[0-9a-f-]{36}\}\}", all_text_fields, re.IGNORECASE):
                extra_refs = await self._extract_source_image_refs(all_text_fields, {}, session)
                for ref in extra_refs:
                    if ref.id not in existing_ids:
                        source_image_refs.append(ref)
                        existing_ids.add(ref.id)

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
                country_fallback=is_fallback,
                source_image_refs=source_image_refs,
            ), is_fallback

        return None, False

    async def _generate_lesson_content(
        self,
        module: Module,
        unit_id: str,
        language: str,
        country: str,
        level: int,
        session: AsyncSession,
        quality_constraints: list[str] | None = None,
    ) -> LessonResponse:
        """Generate new lesson content using RAG + Claude."""
        # Resolve unit metadata once — used for prompt grounding and RAG query.
        unit = await self._resolve_unit(module, unit_id, session)
        unit_title = (unit.title_fr if language == "fr" else unit.title_en) if unit else ""
        unit_description = (
            (unit.description_fr if language == "fr" else unit.description_en) if unit else None
        )
        module_title = module.title_fr if language == "fr" else module.title_en

        # Build search query
        query = await self._build_lesson_query(module, unit_id, language, session)

        # Perform RAG retrieval
        rag_chunks = await self.semantic_retriever.search_for_module(
            query=query,
            user_level=level,
            user_language=language,
            books_sources=self._resolve_books_sources(module),
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

        total_linked = sum(len(v) for v in linked_images.values()) if linked_images else 0
        logger.info(
            "lesson.image_pipeline",
            chunk_count=len(chunk_ids),
            linked_images_total=total_linked,
            module_id=str(module.id),
            unit_id=unit_id,
        )

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
            module_title=module_title,
            unit_title=unit_title,
            course=course,
        )
        user_message = format_rag_context_for_lesson(
            rag_chunks,
            query,
            module_title,
            unit_id,
            language,
            linked_images=linked_images or None,
            unit_title=unit_title,
            unit_description=unit_description,
        )

        # Append quality-loop constraints if provided (#2215).
        if quality_constraints:
            from app.ai.prompts.quality import constraints_block_from_report

            user_message = user_message + constraints_block_from_report(quality_constraints)

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
        source_image_refs = await self._extract_source_image_refs(
            content_text, linked_images, session
        )

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

    @staticmethod
    def _resolve_books_sources(module: Module) -> dict | None:
        """Return books_sources for the semantic retriever.

        Admin-created courses index chunks with source=rag_collection_id,
        so always prefer that over books_sources (which may contain PDF
        filenames that don't match the stored chunk source).
        Legacy courses (no rag_collection_id) use books_sources as-is.
        """
        course = module.course
        if course and course.rag_collection_id:
            return {course.rag_collection_id: []}
        if module.books_sources:
            return module.books_sources
        return None

    async def _resolve_unit(
        self, module: Module, unit_id: str, session: AsyncSession
    ) -> ModuleUnit | None:
        """Resolve a ModuleUnit row from `(module, unit_id)` for prompt grounding.

        Same logic as the helper on CaseStudyGenerationService — duplicated here
        because the prompt-grounding paths in this class call `self._resolve_unit`
        and the two services don't share a base class. Issue #2007.
        """
        unit_result = await session.execute(
            select(ModuleUnit).where(
                and_(
                    ModuleUnit.module_id == module.id,
                    ModuleUnit.unit_number == unit_id,
                )
            )
        )
        return unit_result.scalar_one_or_none()

    async def _build_lesson_query(
        self, module: Module, unit_id: str, language: str, session: AsyncSession
    ) -> str:
        """Build search query for RAG retrieval using unit-specific metadata."""
        unit_result = await session.execute(
            select(ModuleUnit).where(
                and_(
                    ModuleUnit.module_id == module.id,
                    ModuleUnit.unit_number == unit_id,
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

    async def _parse_lesson_content(self, content_text: str, rag_chunks: list) -> LessonContent:
        """Parse generated content into structured lesson format.

        Tries JSON parsing first (new prompt format), falls back to wrapping
        raw markdown in concepts[] for backward compatibility with cached content.
        """
        import json as _json

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

        # --- Attempt JSON parsing (new prompt format) ---
        try:
            stripped = content_text.strip()
            if stripped.startswith("```"):
                stripped = re.sub(r"^```[a-zA-Z]*\n?", "", stripped)
                stripped = re.sub(r"\n?```$", "", stripped.rstrip())

            data = _json.loads(stripped)

            if isinstance(data, dict) and ("concepts" in data or "introduction" in data):
                raw_concepts = data.get("concepts") or []
                concepts = (
                    [str(c) for c in raw_concepts if str(c).strip()]
                    if isinstance(raw_concepts, list)
                    else [str(raw_concepts)]
                )
                raw_key_points = data.get("key_points") or []
                key_points = (
                    [str(k) for k in raw_key_points if str(k).strip()]
                    if isinstance(raw_key_points, list)
                    else [str(raw_key_points)]
                )
                raw_sources = data.get("sources_cited") or sources_cited
                if isinstance(raw_sources, list):
                    all_sources = [str(s) for s in raw_sources if str(s).strip()]
                    # Merge with RAG-extracted sources
                    for sc in sources_cited:
                        if sc not in all_sources:
                            all_sources.append(sc)
                else:
                    all_sources = sources_cited

                return LessonContent(
                    introduction=str(data.get("introduction") or ""),
                    concepts=concepts if concepts else [""],
                    aof_example=str(data.get("aof_example") or ""),
                    synthesis=str(data.get("synthesis") or ""),
                    key_points=key_points,
                    sources_cited=all_sources,
                )
        except (_json.JSONDecodeError, ValueError, TypeError):
            pass

        # --- Fallback: old markdown format (for cached content) ---
        return LessonContent(
            introduction="",
            concepts=[content_text],
            aof_example="",
            synthesis="",
            key_points=[],
            sources_cited=sources_cited,
        )

    @staticmethod
    async def _extract_source_image_refs(
        content_text: str,
        linked_images: dict,
        session: AsyncSession | None = None,
    ) -> list[SourceImageRef]:
        """Extract {{source_image:UUID}} markers from Claude output and resolve to SourceImageRef.

        First resolves UUIDs from the pre-loaded linked_images dict; for any UUID not found
        there (e.g. Claude referenced an image that wasn't directly linked to a RAG chunk),
        falls back to a DB query on the source_images table.

        Args:
            content_text: Raw text output from Claude (or assembled content dict text)
            linked_images: Mapping of chunk_id -> list of image metadata dicts
            session: Database session for fallback DB lookups

        Returns:
            Deduplicated list of SourceImageRef for UUIDs found in content_text
        """
        pattern = re.compile(r"\{\{source_image:([0-9a-f-]{36})\}\}", re.IGNORECASE)
        found_ids = list(dict.fromkeys(pattern.findall(content_text)))

        logger.debug(
            "_extract_source_image_refs: scanned content",
            content_length=len(content_text),
            found_ids=found_ids,
        )

        if not found_ids:
            return []

        all_images: dict[str, dict] = {}
        for img_list in linked_images.values():
            for img in img_list:
                img_id = img.get("id", "")
                if img_id and img_id not in all_images:
                    all_images[img_id] = img

        missing_ids = [img_id for img_id in found_ids if img_id not in all_images]
        if missing_ids and session is not None:
            logger.debug(
                "_extract_source_image_refs: DB fallback for missing image IDs",
                missing_ids=missing_ids,
            )
            try:
                missing_uuids = [uuid.UUID(img_id) for img_id in missing_ids]
                db_result = await session.execute(
                    select(SourceImage).where(SourceImage.id.in_(missing_uuids))
                )
                db_rows = db_result.scalars().all()
                logger.debug(
                    "_extract_source_image_refs: DB fallback returned rows",
                    row_count=len(db_rows),
                    returned_ids=[str(r.id) for r in db_rows],
                )
                for db_img in db_rows:
                    img_id = str(db_img.id)
                    all_images[img_id] = db_img.to_meta_dict()
            except Exception as exc:
                logger.warning(
                    "DB fallback for source_image_refs failed",
                    missing_ids=missing_ids,
                    error=str(exc),
                )
        elif missing_ids and session is None:
            logger.warning(
                "_extract_source_image_refs: session is None, cannot resolve missing image IDs",
                missing_ids=missing_ids,
            )

        refs = []
        for img_id in found_ids:
            img = all_images.get(img_id)
            if img:
                refs.append(
                    SourceImageRef(
                        id=img_id,
                        figure_number=img.get("figure_number"),
                        caption=img.get("caption"),
                        caption_fr=img.get("caption_fr") or img.get("caption"),
                        caption_en=img.get("caption_en") or img.get("caption"),
                        attribution=img.get("attribution"),
                        image_type=img.get("image_type") or "unknown",
                        storage_url=img.get("storage_url"),
                        storage_url_fr=img.get("storage_url_fr"),
                        alt_text_fr=img.get("alt_text_fr"),
                        alt_text_en=img.get("alt_text_en"),
                    )
                )
            else:
                logger.warning(
                    "source_image UUID in content not found in DB",
                    image_id=img_id,
                )
        return refs

    async def _cache_lesson_content(
        self, lesson_response: LessonResponse, session: AsyncSession
    ) -> None:
        """Save generated lesson content to cache."""
        from app.domain.services._unit_resolution import resolve_module_unit_id

        # Resolve FK so the unique index `idx_unique_content_per_module_unit`
        # can enforce one cached lesson per (unit, lang, level, country).
        # JSON unit_id is still written for backwards compat with audio/video
        # readers that haven't been migrated yet (#2007 — deferred Step 5).
        module_unit_uuid = await resolve_module_unit_id(
            session, lesson_response.module_id, lesson_response.unit_id
        )

        content_with_unit = lesson_response.content.model_dump()
        content_with_unit["unit_id"] = lesson_response.unit_id
        content_with_unit["source_image_refs"] = [
            ref.model_dump() for ref in lesson_response.source_image_refs
        ]

        cached_content = GeneratedContent(
            id=lesson_response.id,
            module_id=lesson_response.module_id,
            module_unit_id=module_unit_uuid,
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

        # Extract text from all lesson sections for audio/image generation
        lesson_text = extract_lesson_text(lesson_response.content)

        try:
            from sqlalchemy import select as sa_select

            from app.domain.models.generated_image import GeneratedImage

            existing_img = await session.execute(
                sa_select(GeneratedImage.id)
                .where(
                    GeneratedImage.lesson_id == cached_content.id,
                    GeneratedImage.status.in_(["ready", "generating", "pending"]),
                )
                .limit(1)
            )
            if existing_img.scalar_one_or_none() is not None:
                logger.info(
                    "Image already exists — skipping dispatch",
                    lesson_id=str(cached_content.id),
                )
            else:
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

        try:
            # Audio is shared per (module, unit, language) — skip if one
            # already exists. Filter by media_type='audio' so a sibling
            # video row (same table since #1802) does not masquerade as
            # audio and block dispatch. See issue #1802 regression notes.
            from app.domain.models.generated_audio import GeneratedAudio

            existing_audio = await session.execute(
                select(GeneratedAudio.id)
                .where(
                    GeneratedAudio.module_id == cached_content.module_id,
                    GeneratedAudio.unit_id == lesson_response.unit_id,
                    GeneratedAudio.language == lesson_response.language,
                    GeneratedAudio.media_type == "audio",
                )
                .limit(1)
            )
            if existing_audio.scalars().first() is not None:
                logger.info(
                    "Audio already exists for (module, unit, language) — skipping dispatch",
                    module_id=str(cached_content.module_id),
                    unit_id=lesson_response.unit_id,
                    language=lesson_response.language,
                )
            else:
                from app.tasks.content_generation import generate_lesson_audio

                generate_lesson_audio.delay(
                    str(cached_content.id),
                    str(cached_content.module_id),
                    lesson_response.unit_id,
                    lesson_response.language,
                    lesson_text[:4000],
                )
                logger.info(
                    "Dispatched audio generation task",
                    lesson_id=str(cached_content.id),
                )
        except Exception as exc:
            logger.warning(
                "Failed to dispatch audio generation task",
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
        user_id: uuid.UUID | None = None,
        quality_constraints: list[str] | None = None,
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
            user_id: Optional user UUID for background task logging

        Returns:
            CaseStudyResponse with generated or cached content
        """
        module_result = await session.execute(
            select(Module).where(Module.id == module_id).options(selectinload(Module.course))
        )
        module = module_result.scalar_one_or_none()

        if not module:
            raise ValueError(f"Module {module_id} not found")

        if not force_regenerate:
            cached, is_fallback = await self._get_cached_case_study(
                module_id, unit_id, language, country, level, session
            )
            if cached:
                logger.info(
                    "Retrieved cached case study",
                    module_id=str(module_id),
                    unit_id=unit_id,
                    language=language,
                    country_fallback=is_fallback,
                )
                if is_fallback:
                    from app.tasks.content_generation import generate_country_content_task

                    generate_country_content_task.delay(
                        module_id=str(module_id),
                        unit_id=unit_id,
                        content_type="case",
                        language=language,
                        level=level,
                        country=country,
                        user_id=str(user_id) if user_id else "",
                    )
                unit = await self._resolve_unit(module, unit_id, session)
                if unit:
                    cached.unit_title = unit.title_fr if language == "fr" else unit.title_en
                    cached.unit_description = (
                        unit.description_fr if language == "fr" else unit.description_en
                    )
                return cached

        logger.info(
            "Generating new case study",
            module_id=str(module_id),
            unit_id=unit_id,
            language=language,
            level=level,
            country=country,
        )

        case_study_response = await self._generate_case_study_content(
            module, unit_id, language, country, level, session,
            quality_constraints=quality_constraints,
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
        user_id: uuid.UUID | None = None,
    ) -> AsyncGenerator[StreamingEvent, None]:
        """
        Stream case study generation in real-time.

        Yields:
            StreamingEvent objects for real-time updates
        """
        try:
            module_result = await session.execute(
                select(Module).where(Module.id == module_id).options(selectinload(Module.course))
            )
            module = module_result.scalar_one_or_none()

            if not module:
                yield StreamingEvent(
                    event="error",
                    data={
                        "error": "module_not_found",
                        "message": f"Module {module_id} not found",
                    },
                )
                return

            cached, is_fallback = await self._get_cached_case_study(
                module_id, unit_id, language, country, level, session
            )

            if cached:
                if is_fallback:
                    from app.tasks.content_generation import generate_country_content_task

                    generate_country_content_task.delay(
                        module_id=str(module_id),
                        unit_id=unit_id,
                        content_type="case",
                        language=language,
                        level=level,
                        country=country,
                        user_id=str(user_id) if user_id else "",
                    )
                unit = await self._resolve_unit(module, unit_id, session)
                if unit:
                    cached.unit_title = unit.title_fr if language == "fr" else unit.title_en
                    cached.unit_description = (
                        unit.description_fr if language == "fr" else unit.description_en
                    )
                yield StreamingEvent(event="complete", data=cached.model_dump())
                return

            yield StreamingEvent(event="chunk", data="Démarrage de la génération...")
            yield StreamingEvent(event="chunk", data="Recherche des documents pertinents...")

            query = await self._build_case_study_query(module, unit_id, language, session)
            rag_chunks = await self.semantic_retriever.search_for_module(
                query=query,
                user_level=level,
                user_language=language,
                books_sources=self._resolve_books_sources(module),
                top_k=SettingsCache.instance().get("ai-rag-default-top-k", 8),
                session=session,
            )

            if not rag_chunks:
                yield StreamingEvent(
                    event="error",
                    data={
                        "error": "no_content_found",
                        "message": "Aucun contenu pertinent trouvé",
                    },
                )
                return

            yield StreamingEvent(event="chunk", data="Documents trouvés, génération en cours...")

            module_key = f"M{module.module_number:02d}"
            course: Course | None = module.course
            unit = await self._resolve_unit(module, unit_id, session)
            stream_unit_title = (
                (unit.title_fr if language == "fr" else unit.title_en) if unit else ""
            )
            stream_unit_description = (
                (unit.description_fr if language == "fr" else unit.description_en) if unit else None
            )
            stream_module_title = module.title_fr if language == "fr" else module.title_en
            stream_learning_objectives = (
                (
                    module.learning_objectives_fr
                    if language == "fr"
                    else module.learning_objectives_en
                )
                if hasattr(module, "learning_objectives_fr")
                else None
            )
            stream_syllabus_context = (
                "\n".join(f"- {obj}" for obj in stream_learning_objectives)
                if isinstance(stream_learning_objectives, list) and stream_learning_objectives
                else ""
            )
            stream_course_title = (
                (course.title_fr if language == "fr" else course.title_en) if course else None
            )
            system_prompt = get_case_study_system_prompt(
                language,
                country,
                level,
                module.bloom_level,
                course_title=stream_course_title,
                course_description=(
                    (course.description_fr if language == "fr" else course.description_en)
                    if course
                    else None
                ),
                module_title=stream_module_title,
                unit_title=stream_unit_title,
                syllabus_context=stream_syllabus_context,
                course_domain=stream_course_title or "",
                course=course,
            )
            user_message = format_rag_context_for_case_study(
                rag_chunks,
                query,
                stream_module_title,
                unit_id,
                language,
                module_id=module_key,
                syllabus_json=course.syllabus_json if course else None,
                unit_title=stream_unit_title,
                unit_description=stream_unit_description,
            )

            logger.debug(
                "Case study system prompt preview",
                system_prompt_prefix=system_prompt[:200],
                system_prompt_len=len(system_prompt),
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
                unit_title=stream_unit_title or None,
                unit_description=stream_unit_description,
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
    ) -> tuple[CaseStudyResponse | None, bool]:
        """Check for existing cached case study content.

        Returns:
            Tuple of (CaseStudyResponse | None, country_fallback: bool).
            country_fallback is True when content is from a different country's cache.
        """
        from app.domain.services._unit_resolution import resolve_module_unit_id

        module_unit_uuid = await resolve_module_unit_id(session, module_id, unit_id)
        if module_unit_uuid is None:
            return None, False

        query = (
            select(GeneratedContent)
            .where(GeneratedContent.module_unit_id == module_unit_uuid)
            .where(GeneratedContent.content_type == "case")
            .where(GeneratedContent.language == language)
            .where(GeneratedContent.level == level)
            .where(GeneratedContent.country_context == country)
            .order_by(GeneratedContent.generated_at.desc())
        )

        result = await session.execute(query)
        cached_content = result.scalars().first()

        if not cached_content:
            fallback_query = (
                select(GeneratedContent)
                .where(GeneratedContent.module_unit_id == module_unit_uuid)
                .where(GeneratedContent.content_type == "case")
                .where(GeneratedContent.language == language)
                .where(GeneratedContent.level == level)
                .order_by(GeneratedContent.generated_at.desc())
            )
            fallback_result = await session.execute(fallback_query)
            cached_content = fallback_result.scalars().first()
            is_fallback = cached_content is not None
        else:
            is_fallback = False

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
                country_fallback=is_fallback,
            ), is_fallback

        return None, False

    async def _generate_case_study_content(
        self,
        module: Module,
        unit_id: str,
        language: str,
        country: str,
        level: int,
        session: AsyncSession,
        quality_constraints: list[str] | None = None,
    ) -> CaseStudyResponse:
        """Generate new case study content using RAG + Claude."""
        unit = await self._resolve_unit(module, unit_id, session)
        query = await self._build_case_study_query(module, unit_id, language, session)

        rag_chunks = await self.semantic_retriever.search_for_module(
            query=query,
            user_level=level,
            user_language=language,
            books_sources=self._resolve_books_sources(module),
            top_k=8,
            session=session,
        )

        if not rag_chunks:
            raise ValueError(f"No relevant content found for module {module.id}, unit {unit_id}")

        module_key = f"M{module.module_number:02d}"
        course: Course | None = module.course
        resolved_unit_title = (unit.title_fr if language == "fr" else unit.title_en) if unit else ""
        resolved_unit_description = (
            (unit.description_fr if language == "fr" else unit.description_en) if unit else None
        )
        resolved_module_title = module.title_fr if language == "fr" else module.title_en
        learning_objectives = (
            (module.learning_objectives_fr if language == "fr" else module.learning_objectives_en)
            if hasattr(module, "learning_objectives_fr")
            else None
        )
        syllabus_context = (
            "\n".join(f"- {obj}" for obj in learning_objectives)
            if isinstance(learning_objectives, list) and learning_objectives
            else ""
        )
        course_title = (
            (course.title_fr if language == "fr" else course.title_en) if course else None
        )
        system_prompt = get_case_study_system_prompt(
            language,
            country,
            level,
            module.bloom_level,
            course_title=course_title,
            course_description=(
                (course.description_fr if language == "fr" else course.description_en)
                if course
                else None
            ),
            module_title=resolved_module_title,
            unit_title=resolved_unit_title,
            syllabus_context=syllabus_context,
            course_domain=course_title or "",
            course=course,
        )
        user_message = format_rag_context_for_case_study(
            rag_chunks,
            query,
            resolved_module_title,
            unit_id,
            language,
            module_id=module_key,
            syllabus_json=course.syllabus_json if course else None,
            unit_title=resolved_unit_title,
            unit_description=resolved_unit_description,
        )

        # Append quality-loop constraints if provided (#2215).
        if quality_constraints:
            from app.ai.prompts.quality import constraints_block_from_report

            user_message = user_message + constraints_block_from_report(quality_constraints)

        logger.debug(
            "Case study system prompt preview (non-streaming)",
            system_prompt_prefix=system_prompt[:200],
            system_prompt_len=len(system_prompt),
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
            unit_title=resolved_unit_title or None,
            unit_description=resolved_unit_description,
        )

    @staticmethod
    def _resolve_books_sources(module: Module) -> dict | None:
        """Resolve books_sources — same logic as LessonGenerationService."""
        course = module.course
        if course and course.rag_collection_id:
            return {course.rag_collection_id: []}
        if module.books_sources:
            return module.books_sources
        if course and course.id:
            logger.warning(
                "No rag_collection_id or books_sources for module; falling back to course ID filter",
                module_id=str(module.id),
                course_id=str(course.id),
            )
            return {str(course.id): []}
        logger.warning(
            "Cannot resolve books_sources — module has no course or RAG config; "
            "retrieval will be unfiltered",
            module_id=str(module.id),
        )
        return None

    async def _resolve_unit(
        self, module: Module, unit_id: str, session: AsyncSession
    ) -> ModuleUnit | None:
        """Resolve a ModuleUnit from unit_id and module."""
        unit_result = await session.execute(
            select(ModuleUnit).where(
                and_(
                    ModuleUnit.module_id == module.id,
                    ModuleUnit.unit_number == unit_id,
                )
            )
        )
        return unit_result.scalar_one_or_none()

    async def _build_case_study_query(
        self, module: Module, unit_id: str, language: str, session: AsyncSession
    ) -> str:
        """Build search query for case study RAG retrieval."""
        unit = await self._resolve_unit(module, unit_id, session)

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

        Attempts JSON parsing first (new prompt format), then falls back to
        legacy regex-based section splitting for backward compatibility with
        cached markdown content.
        """
        # Extract source citations from RAG chunks (fallback when JSON sources_cited is empty)
        rag_sources: list[str] = []
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

            if source_citation not in rag_sources:
                rag_sources.append(source_citation)

        # --- Attempt JSON parsing (new prompt format) ---
        try:
            stripped = content_text.strip()
            if stripped.startswith("```"):
                stripped = re.sub(r"^```[a-zA-Z]*\n?", "", stripped)
                stripped = re.sub(r"\n?```$", "", stripped.rstrip())

            data = json.loads(stripped)

            aof_context = str(data.get("aof_context") or "")
            real_data = str(data.get("real_data") or "")
            annotated_correction = str(data.get("annotated_correction") or "")

            raw_questions = data.get("guided_questions") or []
            guided_questions = (
                [str(q) for q in raw_questions if str(q).strip()]
                if isinstance(raw_questions, list)
                else [str(raw_questions)]
            )

            json_sources = [str(s) for s in (data.get("sources_cited") or []) if str(s).strip()]
            sources_cited = json_sources if json_sources else rag_sources

            while len(guided_questions) < 2:
                guided_questions.append("")

            logger.debug("Case study parsed via JSON", questions_count=len(guided_questions))
            return CaseStudyContent(
                aof_context=aof_context or content_text[:500],
                real_data=real_data,
                guided_questions=guided_questions,
                annotated_correction=annotated_correction,
                sources_cited=sources_cited,
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            logger.warning(
                "JSON parsing failed for case study; falling back to regex parser",
                error=str(exc),
            )

        # --- Legacy regex fallback (backward compat with cached markdown content) ---
        sources_cited = rag_sources

        section_pattern = r"(?:^|\n)(?:#{1,3}\s*)?(\d+)\.\s*\*\*[^*]+\*\*"
        splits = list(re.finditer(section_pattern, content_text))

        sections: dict[int, str] = {}
        for i, match in enumerate(splits):
            section_num = int(match.group(1))
            start = match.end()
            end = splits[i + 1].start() if i + 1 < len(splits) else len(content_text)
            sections[section_num] = content_text[start:end].strip()

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
                chunk_size = max(1, len(content_text) // 4)
                sections = {
                    1: content_text[:chunk_size].strip(),
                    2: content_text[chunk_size : 2 * chunk_size].strip(),
                    3: content_text[2 * chunk_size : 3 * chunk_size].strip(),
                    4: content_text[3 * chunk_size :].strip(),
                }

        questions_text = sections.get(3, "")
        question_lines = re.findall(
            r"(?:^|\n)\s*(?:\d+[\.\.\)]\s*|-\s*|\*\s*)(.+?)(?=\n\s*(?:\d+[\.\.\)]|-|\*)|\Z)",
            questions_text,
            re.DOTALL,
        )
        guided_questions = [q.strip() for q in question_lines if q.strip()]

        if not guided_questions and questions_text.strip():
            guided_questions = [
                line.strip()
                for line in questions_text.strip().split("\n")
                if line.strip() and not re.match(r"^#{1,3}\s", line)
            ]

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
        from app.domain.services._unit_resolution import resolve_module_unit_id

        module_unit_uuid = await resolve_module_unit_id(
            session,
            case_study_response.module_id,
            case_study_response.unit_id,
        )

        content_with_unit = case_study_response.content.model_dump()
        content_with_unit["unit_id"] = case_study_response.unit_id

        cached_content = GeneratedContent(
            id=case_study_response.id,
            module_id=case_study_response.module_id,
            module_unit_id=module_unit_uuid,
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
