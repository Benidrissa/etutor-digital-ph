"""Service for flashcard generation and management."""

import json
import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.claude_service import ClaudeService
from app.ai.prompts.flashcard import format_rag_context_for_flashcards, get_flashcard_system_prompt
from app.ai.rag.retriever import SemanticRetriever
from app.api.v1.schemas.content import FlashcardContent, FlashcardSetResponse
from app.domain.models.content import GeneratedContent
from app.domain.models.module import Module

logger = structlog.get_logger()


class FlashcardGenerationService:
    """Service for generating and managing flashcard content."""

    def __init__(self, claude_service: ClaudeService, semantic_retriever: SemanticRetriever):
        """Initialize the flashcard generation service.

        Args:
            claude_service: Claude AI service for content generation
            semantic_retriever: RAG retriever for getting relevant content chunks
        """
        self.claude_service = claude_service
        self.semantic_retriever = semantic_retriever

    async def get_or_generate_flashcard_set(
        self,
        module_id: uuid.UUID,
        language: str,
        country: str,
        level: int,
        session: AsyncSession,
    ) -> FlashcardSetResponse:
        """Get existing flashcard set or generate new one.

        Args:
            module_id: Module UUID to generate flashcards for
            language: Target language (fr/en)
            country: User's country code for contextualization
            level: User's competency level (1-4)
            session: Database session

        Returns:
            FlashcardSetResponse with generated or cached flashcard set

        Raises:
            ValueError: If module not found or invalid parameters
            Exception: If generation fails
        """
        logger.info(
            "Starting flashcard generation request",
            module_id=str(module_id),
            language=language,
            country=country,
            level=level,
        )

        # Check cache first
        existing_content = await self._get_cached_flashcard_set(
            module_id=module_id,
            language=language,
            country_context=country,
            level=level,
            session=session,
        )

        if existing_content:
            logger.info("Returning cached flashcard set", content_id=str(existing_content.id))
            return self._build_response_from_content(existing_content, cached=True)

        # Generate new flashcard set
        logger.info("Generating new flashcard set")
        generated_content = await self._generate_flashcard_set(
            module_id=module_id,
            language=language,
            country=country,
            level=level,
            session=session,
        )

        return self._build_response_from_content(generated_content, cached=False)

    async def _get_cached_flashcard_set(
        self,
        module_id: uuid.UUID,
        language: str,
        country_context: str,
        level: int,
        session: AsyncSession,
    ) -> GeneratedContent | None:
        """Look for existing flashcard set in cache.

        Args:
            module_id: Module UUID
            language: Content language
            country_context: User's country
            level: Competency level
            session: Database session

        Returns:
            Existing GeneratedContent or None if not found
        """
        query = select(GeneratedContent).where(
            GeneratedContent.module_id == module_id,
            GeneratedContent.content_type == "flashcard",
            GeneratedContent.language == language,
            GeneratedContent.country_context == country_context,
            GeneratedContent.level == level,
        )

        result = await session.execute(query)
        return result.scalar_one_or_none()

    async def _generate_flashcard_set(
        self,
        module_id: uuid.UUID,
        language: str,
        country: str,
        level: int,
        session: AsyncSession,
    ) -> GeneratedContent:
        """Generate new flashcard set using Claude AI and RAG.

        Args:
            module_id: Module UUID
            language: Target language
            country: User's country code
            level: Competency level
            session: Database session

        Returns:
            Generated content stored in database

        Raises:
            ValueError: If module not found or generation fails
        """
        module_query = select(Module).where(Module.id == module_id)
        module_result = await session.execute(module_query)
        module = module_result.scalar_one_or_none()

        if module is None:
            raise ValueError(f"Module {module_id} not found")

        module_title = module.title_fr if language == "fr" else module.title_en

        if language == "fr":
            query = f"concepts clés vocabulaire définitions {module_title} santé publique niveau {level}"
        else:
            query = (
                f"key concepts vocabulary definitions {module_title} public health level {level}"
            )

        logger.info("Retrieving relevant content chunks", query=query)

        # Retrieve relevant chunks using RAG
        search_results = await self.semantic_retriever.search(
            query=query,
            k=12,  # Get more chunks for comprehensive flashcard generation
            filters={"level": {"$lte": level}},  # Only content appropriate for user's level
        )

        if not search_results:
            raise ValueError(f"No relevant content found for module {module_id}")

        logger.info(f"Retrieved {len(search_results)} content chunks")

        # Format context for Claude
        rag_context = format_rag_context_for_flashcards(
            chunks=search_results,
            module_title=module_title,
            language=language,
        )

        # Generate system prompt
        system_prompt = get_flashcard_system_prompt(
            language=language,
            country=country,
            level=level,
        )

        logger.info("Calling Claude API for flashcard generation")

        # Call Claude API
        try:
            response = await self.claude_service.generate_structured_content(
                system_prompt=system_prompt,
                user_prompt=rag_context,
                max_tokens=8000,  # Large token budget for 15-30 flashcards
            )

            # Parse the JSON response
            try:
                flashcard_data = json.loads(response)

                # Validate we got a list of flashcards
                if not isinstance(flashcard_data, list):
                    raise ValueError("Claude response is not a list of flashcards")

                if len(flashcard_data) < 15:
                    logger.warning(
                        f"Generated only {len(flashcard_data)} flashcards, expected 15-30"
                    )

            except json.JSONDecodeError:
                logger.error("Failed to parse Claude response as JSON", response=response[:500])
                raise ValueError("Invalid JSON response from Claude API")

            logger.info(f"Successfully generated {len(flashcard_data)} flashcards")

        except Exception as e:
            logger.error("Claude API call failed", error=str(e))
            raise ValueError(f"Content generation failed: {str(e)}")

        # Store in database
        content_id = uuid.uuid4()
        generated_content = GeneratedContent(
            id=content_id,
            module_id=module_id,
            content_type="flashcard",
            language=language,
            level=level,
            content={"flashcards": flashcard_data},
            sources_cited=self._extract_sources_from_flashcards(flashcard_data),
            country_context=country,
            validated=False,
        )

        session.add(generated_content)
        await session.commit()
        await session.refresh(generated_content)

        logger.info("Flashcard set saved to database", content_id=str(content_id))
        return generated_content

    def _extract_sources_from_flashcards(self, flashcard_data: list) -> list[str]:
        """Extract unique sources cited across all flashcards.

        Args:
            flashcard_data: List of flashcard dictionaries

        Returns:
            List of unique source citations
        """
        sources = set()
        for card in flashcard_data:
            if "sources_cited" in card and isinstance(card["sources_cited"], list):
                sources.update(card["sources_cited"])
        return list(sources)

    def _build_response_from_content(
        self, content: GeneratedContent, cached: bool
    ) -> FlashcardSetResponse:
        """Build FlashcardSetResponse from GeneratedContent.

        Args:
            content: Database content object
            cached: Whether this was retrieved from cache

        Returns:
            Properly formatted response object
        """
        # Parse flashcard content
        flashcard_data = content.content.get("flashcards", [])

        # Convert to Pydantic models for validation
        flashcards = []
        for card_data in flashcard_data:
            try:
                flashcard = FlashcardContent(**card_data)
                flashcards.append(flashcard)
            except Exception as e:
                logger.warning("Invalid flashcard data, skipping", error=str(e), card=card_data)
                continue

        return FlashcardSetResponse(
            id=content.id,
            module_id=content.module_id,
            content_type="flashcard",
            language=content.language,
            level=content.level,
            country_context=content.country_context or "",
            flashcards=flashcards,
            generated_at=content.generated_at.isoformat(),
            cached=cached,
        )
