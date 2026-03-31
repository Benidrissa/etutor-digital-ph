"""Quiz generation service using RAG + Claude API."""

import json
import uuid
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.claude_service import ClaudeService
from app.ai.prompts.quiz import QUIZ_GENERATION_PROMPT, QUIZ_GENERATION_PROMPT_EN
from app.ai.rag.retriever import SemanticRetriever
from app.api.v1.schemas.content import QuizContent, QuizResponse
from app.domain.models.content import GeneratedContent
from app.domain.models.module import Module

logger = structlog.get_logger()


class QuizGenerationService:
    """Service for generating quiz content using RAG + Claude API."""

    def __init__(self, claude_service: ClaudeService, semantic_retriever: SemanticRetriever):
        self.claude_service = claude_service
        self.semantic_retriever = semantic_retriever

    async def get_or_generate_quiz(
        self,
        module_id: UUID,
        unit_id: str,
        language: str,
        difficulty_level: str,
        session: AsyncSession,
    ) -> QuizResponse:
        """
        Get existing quiz or generate new one.

        Args:
            module_id: Target module UUID
            unit_id: Unit identifier within module
            language: Content language (fr/en)
            difficulty_level: Overall difficulty level
            session: Database session

        Returns:
            QuizResponse with generated or cached content

        Raises:
            ValueError: If module not found or invalid parameters
            Exception: If generation fails
        """
        try:
            # Check if quiz already exists in cache
            cached_quiz = await self._get_cached_quiz(
                module_id=module_id,
                unit_id=unit_id,
                language=language,
                difficulty_level=difficulty_level,
                session=session,
            )

            if cached_quiz:
                logger.info(
                    "Quiz found in cache",
                    quiz_id=str(cached_quiz.id),
                    module_id=str(module_id),
                    unit_id=unit_id,
                )
                return self._build_quiz_response(cached_quiz, cached=True)

            # Generate new quiz
            logger.info(
                "Generating new quiz",
                module_id=str(module_id),
                unit_id=unit_id,
                language=language,
                difficulty_level=difficulty_level,
            )

            # Verify module exists
            module = await self._get_module(module_id, session)
            if not module:
                raise ValueError(f"Module {module_id} not found")

            # Retrieve relevant content using RAG
            relevant_chunks = await self._retrieve_relevant_content(
                module=module, unit_id=unit_id, language=language
            )

            # Generate quiz content using Claude
            quiz_content = await self._generate_quiz_content(
                chunks=relevant_chunks,
                language=language,
                difficulty_level=difficulty_level,
                module=module,
                unit_id=unit_id,
            )

            # Save to database
            generated_quiz = await self._save_quiz_to_db(
                module_id=module_id,
                unit_id=unit_id,
                language=language,
                difficulty_level=difficulty_level,
                content=quiz_content,
                session=session,
            )

            logger.info(
                "Quiz generated successfully",
                quiz_id=str(generated_quiz.id),
                module_id=str(module_id),
                unit_id=unit_id,
            )

            return self._build_quiz_response(generated_quiz, cached=False)

        except ValueError as e:
            logger.warning("Invalid quiz generation parameters", error=str(e))
            raise

        except Exception as e:
            logger.error("Quiz generation failed", error=str(e), exc_info=True)
            raise Exception(f"Failed to generate quiz: {e}")

    async def _get_cached_quiz(
        self,
        module_id: UUID,
        unit_id: str,
        language: str,
        difficulty_level: str,
        session: AsyncSession,
    ) -> GeneratedContent | None:
        """Check if quiz already exists in cache."""
        query = select(GeneratedContent).where(
            GeneratedContent.module_id == module_id,
            GeneratedContent.content_type == "quiz",
            GeneratedContent.language == language,
            GeneratedContent.content["unit_id"].astext == unit_id,
            GeneratedContent.content["difficulty_level"].astext == difficulty_level,
        )
        result = await session.execute(query)
        return result.scalar_one_or_none()

    async def _get_module(self, module_id: UUID, session: AsyncSession) -> Module | None:
        """Get module by ID."""
        query = select(Module).where(Module.id == module_id)
        result = await session.execute(query)
        return result.scalar_one_or_none()

    async def _retrieve_relevant_content(
        self, module: Module, unit_id: str, language: str
    ) -> list[dict[str, Any]]:
        """Retrieve relevant content chunks using semantic search."""
        try:
            # Build search query based on module and unit
            search_query = f"Module {module.module_number} Unit {unit_id}"

            # Add module title for better context
            if language == "fr" and module.title_fr:
                search_query += f" {module.title_fr}"
            elif language == "en" and module.title_en:
                search_query += f" {module.title_en}"

            logger.info(
                "Searching for relevant content",
                search_query=search_query,
                module_id=str(module.id),
            )

            # Retrieve relevant chunks (top-8 as per SRS)
            chunks = await self.semantic_retriever.search(
                query=search_query,
                k=8,
                filters={"level": {"$lte": module.level}},
            )

            logger.info(f"Retrieved {len(chunks)} relevant chunks")
            return chunks

        except Exception as e:
            logger.error("Content retrieval failed", error=str(e))
            # Return empty list to allow generation with base knowledge
            return []

    async def _generate_quiz_content(
        self,
        chunks: list[dict[str, Any]],
        language: str,
        difficulty_level: str,
        module: Module,
        unit_id: str,
    ) -> dict[str, Any]:
        """Generate quiz content using Claude API."""
        try:
            # Prepare content for Claude
            content_text = self._format_chunks_for_generation(chunks)

            # Select appropriate prompt template
            prompt_template = (
                QUIZ_GENERATION_PROMPT if language == "fr" else QUIZ_GENERATION_PROMPT_EN
            )

            # Format prompt with content
            system_prompt = prompt_template.format(
                language=language,
                content=content_text,
            )

            # Generate content using Claude
            user_message = f"""
Crée un quiz formatif de 10 QCM pour:
- Module: {module.title_fr if language == "fr" else module.title_en}
- Unité: {unit_id}
- Niveau de difficulté: {difficulty_level}

Distribution requise:
- 3 questions faciles
- 4 questions moyennes
- 3 questions difficiles

Assure-toi que chaque question ait exactement 4 options avec une seule réponse correcte.
"""

            response = await self.claude_service.generate_content(
                system_prompt=system_prompt,
                user_message=user_message,
                max_tokens=4000,
            )

            # Parse JSON response
            try:
                quiz_data = json.loads(response)
                return self._validate_and_clean_quiz_data(quiz_data)
            except json.JSONDecodeError as e:
                logger.error("Invalid JSON response from Claude", error=str(e))
                raise Exception("Failed to parse quiz content from AI response")

        except Exception as e:
            logger.error("Quiz content generation failed", error=str(e), exc_info=True)
            raise Exception(f"Failed to generate quiz content: {e}")

    def _format_chunks_for_generation(self, chunks: list[dict[str, Any]]) -> str:
        """Format retrieved chunks for Claude input."""
        if not chunks:
            return "Aucun contenu spécifique trouvé. Générez basé sur vos connaissances en santé publique."

        formatted_chunks = []
        for i, chunk in enumerate(chunks, 1):
            text = chunk.get("text", "")
            metadata = chunk.get("metadata", {})
            source = metadata.get("source", "Unknown")

            formatted_chunks.append(f"""
Extrait {i}:
Source: {source}
Contenu: {text}
""")

        return "\n".join(formatted_chunks)

    def _validate_and_clean_quiz_data(self, quiz_data: dict[str, Any]) -> dict[str, Any]:
        """Validate and clean quiz data from Claude response."""
        # Ensure required fields exist
        if "title" not in quiz_data:
            quiz_data["title"] = "Quiz - Évaluation formative"

        if "questions" not in quiz_data or not isinstance(quiz_data["questions"], list):
            raise ValueError("Invalid quiz format: missing or invalid questions")

        # Ensure exactly 10 questions
        questions = quiz_data["questions"][:10]  # Take first 10 if more
        if len(questions) < 10:
            raise ValueError(f"Insufficient questions generated: {len(questions)}/10")

        # Validate each question structure
        cleaned_questions = []
        difficulty_count = {"easy": 0, "medium": 0, "hard": 0}

        for i, question in enumerate(questions):
            if not self._validate_question_structure(question):
                logger.warning(f"Invalid question {i + 1} structure, skipping")
                continue

            # Count difficulties
            difficulty = question.get("difficulty", "medium")
            if difficulty in difficulty_count:
                difficulty_count[difficulty] += 1

            cleaned_questions.append(question)

        quiz_data["questions"] = cleaned_questions

        # Set defaults if missing
        if "estimated_duration_minutes" not in quiz_data:
            quiz_data["estimated_duration_minutes"] = 15

        if "sources_cited" not in quiz_data:
            quiz_data["sources_cited"] = []

        logger.info(
            "Quiz validation completed",
            total_questions=len(cleaned_questions),
            difficulty_distribution=difficulty_count,
        )

        return quiz_data

    def _validate_question_structure(self, question: dict[str, Any]) -> bool:
        """Validate individual question structure."""
        required_fields = ["question", "options", "explanation", "difficulty", "source_reference"]

        for field in required_fields:
            if field not in question:
                return False

        # Validate options
        options = question.get("options", [])
        if not isinstance(options, list) or len(options) != 4:
            return False

        # Ensure exactly one correct answer
        correct_count = sum(1 for opt in options if opt.get("is_correct", False))
        return correct_count == 1

    async def _save_quiz_to_db(
        self,
        module_id: UUID,
        unit_id: str,
        language: str,
        difficulty_level: str,
        content: dict[str, Any],
        session: AsyncSession,
    ) -> GeneratedContent:
        """Save generated quiz to database."""
        # Add metadata to content
        content_with_metadata = {
            **content,
            "unit_id": unit_id,
            "difficulty_level": difficulty_level,
            "generation_metadata": {
                "questions_count": len(content.get("questions", [])),
                "estimated_duration": content.get("estimated_duration_minutes", 15),
            },
        }

        # Extract sources for the sources_cited field
        sources_cited = content.get("sources_cited", [])

        # Create database record
        generated_content = GeneratedContent(
            id=uuid.uuid4(),
            module_id=module_id,
            content_type="quiz",
            language=language,
            level=1,  # Will be determined by module level in production
            content=content_with_metadata,
            sources_cited=sources_cited,
            country_context=None,  # Can be added later for country-specific quizzes
            validated=False,  # Will be validated by content reviewers
        )

        session.add(generated_content)
        await session.commit()
        await session.refresh(generated_content)

        logger.info(
            "Quiz saved to database",
            quiz_id=str(generated_content.id),
            module_id=str(module_id),
        )

        return generated_content

    def _build_quiz_response(
        self, generated_content: GeneratedContent, cached: bool
    ) -> QuizResponse:
        """Build QuizResponse from GeneratedContent."""
        content_data = generated_content.content

        # Extract metadata
        unit_id = content_data.get("unit_id", "")
        difficulty_level = content_data.get("difficulty_level", "medium")

        # Build QuizContent
        quiz_content = QuizContent(
            title=content_data.get("title", "Quiz"),
            questions=content_data.get("questions", []),
            estimated_duration_minutes=content_data.get("estimated_duration_minutes", 15),
            sources_cited=content_data.get("sources_cited", []),
        )

        return QuizResponse(
            id=generated_content.id,
            module_id=generated_content.module_id,
            unit_id=unit_id,
            language=generated_content.language,
            difficulty_level=difficulty_level,
            content=quiz_content,
            generated_at=generated_content.generated_at.isoformat(),
            cached=cached,
        )
