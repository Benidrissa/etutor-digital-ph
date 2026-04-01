"""Quiz generation service using Claude API and RAG."""

import json
import uuid
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.claude_service import ClaudeService
from app.ai.rag.retriever import SemanticRetriever
from app.api.v1.schemas.quiz import QuizContent, QuizResponse
from app.domain.models.content import GeneratedContent

logger = structlog.get_logger()


class QuizService:
    """Service for generating and managing quiz content."""

    def __init__(self, claude_service: ClaudeService, semantic_retriever: SemanticRetriever):
        self.claude_service = claude_service
        self.semantic_retriever = semantic_retriever

    async def get_or_generate_quiz(
        self,
        module_id: UUID,
        unit_id: str,
        language: str,
        country: str,
        level: int,
        num_questions: int,
        session: AsyncSession,
    ) -> QuizResponse:
        """
        Get existing quiz from cache or generate new one using RAG + Claude API.

        Args:
            module_id: Module ID for the quiz
            unit_id: Unit identifier within module
            language: Content language (fr/en)
            country: User's country for contextualization
            level: Learning level (1-4)
            num_questions: Number of questions to generate (5-15)
            session: Database session

        Returns:
            QuizResponse with quiz content and metadata

        Raises:
            ValueError: If module not found or invalid parameters
            Exception: If quiz generation fails
        """
        try:
            # Cache lookup: match module, unit, language, and level
            query = select(GeneratedContent).where(
                GeneratedContent.module_id == module_id,
                GeneratedContent.content_type == "quiz",
                GeneratedContent.language == language,
                GeneratedContent.level == level,
                GeneratedContent.content["unit_id"].astext == unit_id,
            )

            result = await session.execute(query)
            cached_quiz = result.scalar_one_or_none()

            if cached_quiz:
                logger.info(
                    "Retrieved quiz from cache",
                    quiz_id=str(cached_quiz.id),
                    module_id=str(module_id),
                    unit_id=unit_id,
                )

                return QuizResponse(
                    id=cached_quiz.id,
                    module_id=cached_quiz.module_id,
                    unit_id=cached_quiz.content.get("unit_id", unit_id),
                    language=cached_quiz.language,
                    level=cached_quiz.level,
                    country_context=cached_quiz.country_context or country,
                    content=QuizContent(**cached_quiz.content),
                    generated_at=cached_quiz.generated_at.isoformat(),
                    cached=True,
                )

            # Generate new quiz using RAG + Claude
            logger.info(
                "Generating new quiz",
                module_id=str(module_id),
                unit_id=unit_id,
                num_questions=num_questions,
            )

            quiz_content = await self._generate_quiz_content(
                module_id=module_id,
                unit_id=unit_id,
                language=language,
                country=country,
                level=level,
                num_questions=num_questions,
            )

            # Store in cache
            generated_content = GeneratedContent(
                id=uuid.uuid4(),
                module_id=module_id,
                content_type="quiz",
                language=language,
                level=level,
                content=quiz_content.model_dump(),
                sources_cited=self._extract_sources_from_quiz(quiz_content),
                country_context=country,
                validated=False,
            )

            session.add(generated_content)
            await session.commit()
            await session.refresh(generated_content)

            logger.info(
                "Quiz generated and cached",
                quiz_id=str(generated_content.id),
                num_questions=len(quiz_content.questions),
            )

            return QuizResponse(
                id=generated_content.id,
                module_id=module_id,
                unit_id=unit_id,
                language=language,
                level=level,
                country_context=country,
                content=quiz_content,
                generated_at=generated_content.generated_at.isoformat(),
                cached=False,
            )

        except Exception as e:
            logger.error(
                "Quiz generation failed",
                module_id=str(module_id),
                unit_id=unit_id,
                error=str(e),
                exc_info=True,
            )
            raise

    async def _generate_quiz_content(
        self,
        module_id: UUID,
        unit_id: str,
        language: str,
        country: str,
        level: int,
        num_questions: int,
    ) -> QuizContent:
        """
        Generate quiz content using RAG retrieval and Claude API.

        Args:
            module_id: Module ID for context
            unit_id: Unit identifier
            language: Content language
            country: User's country for examples
            level: Learning level (1-4)
            num_questions: Number of questions to generate

        Returns:
            QuizContent with generated questions and metadata
        """
        try:
            # Retrieve relevant content chunks using RAG
            search_query = f"module {module_id} unit {unit_id} public health epidemiology concepts"
            retrieved_chunks = await self.semantic_retriever.retrieve_chunks(
                query=search_query,
                top_k=8,  # Get more chunks for quiz questions
                module_filter=str(module_id) if module_id else None,
            )

            # Build context from retrieved chunks
            context_text = "\n\n".join(
                [f"Source: {chunk.source_reference}\n{chunk.content}" for chunk in retrieved_chunks]
            )

            # Generate quiz using Claude API with structured prompt
            quiz_prompt = self._build_quiz_prompt(
                context=context_text,
                unit_id=unit_id,
                language=language,
                country=country,
                level=level,
                num_questions=num_questions,
            )

            response = await self.claude_service.generate_content(quiz_prompt)

            # Parse Claude's response into structured quiz content
            quiz_data = self._parse_quiz_response(response, unit_id, num_questions)

            return QuizContent(**quiz_data)

        except Exception as e:
            logger.error("Quiz content generation failed", error=str(e))
            raise

    def _build_quiz_prompt(
        self,
        context: str,
        unit_id: str,
        language: str,
        country: str,
        level: int,
        num_questions: int,
    ) -> str:
        """Build the prompt for Claude API to generate quiz questions."""

        lang_instruction = "in French" if language == "fr" else "in English"
        level_desc = {
            1: "beginner (basic concepts, definitions)",
            2: "intermediate (application, analysis)",
            3: "advanced (synthesis, evaluation)",
            4: "expert (research, policy implications)",
        }

        return f"""You are creating a multiple-choice quiz for public health professionals in West Africa.

CONTEXT MATERIAL:
{context}

QUIZ REQUIREMENTS:
- Target audience: Public health professionals in {country}
- Language: {lang_instruction}
- Level: {level_desc.get(level, "intermediate")}
- Unit: {unit_id}
- Number of questions: {num_questions}
- Format: Multiple choice with exactly 4 options each
- Include explanations and source citations

INSTRUCTIONS:
1. Create {num_questions} multiple-choice questions based on the provided context
2. Each question must have exactly 4 options (A, B, C, D)
3. Only ONE option should be correct
4. Include clear explanations for why the correct answer is right
5. Add source citations from the context material
6. Use examples relevant to {country} and West African context when possible
7. Progress from easier to harder questions
8. Focus on practical applications for public health work

RESPONSE FORMAT (JSON):
{{
  "title": "Quiz title",
  "description": "Brief description of quiz content",
  "questions": [
    {{
      "id": "q1",
      "question": "Question text here?",
      "options": [
        "Option A text",
        "Option B text",
        "Option C text",
        "Option D text"
      ],
      "correct_answer": 1,
      "explanation": "Explanation of why option B is correct and why others are wrong.",
      "sources_cited": ["Source reference from context"],
      "difficulty": "easy|medium|hard"
    }}
  ],
  "time_limit_minutes": {max(10, num_questions * 1.5)},
  "passing_score": 80.0
}}

Generate the quiz now, ensuring all questions are relevant to public health practice in West Africa."""

    def _parse_quiz_response(self, response: str, unit_id: str, expected_questions: int) -> dict:
        """
        Parse Claude's response into structured quiz data.

        Args:
            response: Raw response from Claude API
            unit_id: Unit identifier to include in response
            expected_questions: Expected number of questions for validation

        Returns:
            Dictionary with parsed quiz content

        Raises:
            ValueError: If response cannot be parsed or is invalid
        """
        try:
            # Try to extract JSON from Claude's response
            # Claude sometimes wraps JSON in markdown code blocks
            response_text = response.strip()

            if "```json" in response_text:
                start = response_text.find("```json") + 7
                end = response_text.find("```", start)
                response_text = response_text[start:end].strip()
            elif "```" in response_text:
                start = response_text.find("```") + 3
                end = response_text.rfind("```")
                response_text = response_text[start:end].strip()

            # Parse JSON
            quiz_data = json.loads(response_text)

            # Validate structure
            required_fields = ["title", "description", "questions"]
            for field in required_fields:
                if field not in quiz_data:
                    raise ValueError(f"Missing required field: {field}")

            questions = quiz_data["questions"]
            if not isinstance(questions, list) or len(questions) == 0:
                raise ValueError("Quiz must have at least one question")
            if (
                len(questions) < max(1, expected_questions - 2)
                or len(questions) > expected_questions + 2
            ):
                logger.warning(
                    "Question count mismatch",
                    expected=expected_questions,
                    got=len(questions),
                )

            # Validate each question
            for i, question in enumerate(questions):
                self._validate_question(question, f"question {i + 1}")

            # Set defaults for optional fields
            quiz_data.setdefault("time_limit_minutes", max(10, len(questions) * 2))
            quiz_data.setdefault("passing_score", 80.0)
            if quiz_data.get("passing_score", 80.0) < 80.0:
                quiz_data["passing_score"] = 80.0

            # Add unit_id to content
            quiz_data["unit_id"] = unit_id

            return quiz_data

        except json.JSONDecodeError as e:
            logger.error("Failed to parse quiz JSON", response_preview=response[:200], error=str(e))
            raise ValueError(f"Invalid JSON response from Claude API: {e}")
        except Exception as e:
            logger.error("Quiz response validation failed", error=str(e))
            raise ValueError(f"Invalid quiz format: {e}")

    def _validate_question(self, question: dict, context: str) -> None:
        """
        Validate a single quiz question structure.

        Args:
            question: Question dictionary to validate
            context: Context string for error messages

        Raises:
            ValueError: If question is invalid
        """
        required_fields = ["id", "question", "options", "correct_answer", "explanation"]
        for field in required_fields:
            if field not in question:
                raise ValueError(f"{context}: Missing required field '{field}'")

        # Validate options
        options = question["options"]
        if not isinstance(options, list) or len(options) != 4:
            raise ValueError(f"{context}: Must have exactly 4 options")

        # Validate correct_answer
        correct_answer = question["correct_answer"]
        if not isinstance(correct_answer, int) or not (0 <= correct_answer <= 3):
            raise ValueError(f"{context}: correct_answer must be 0, 1, 2, or 3")

        # Set defaults
        question.setdefault("sources_cited", [])
        question.setdefault("difficulty", "medium")

    def _extract_sources_from_quiz(self, quiz_content: QuizContent) -> list[str]:
        """
        Extract all source citations from quiz questions.

        Args:
            quiz_content: Quiz content with questions

        Returns:
            List of unique source citations
        """
        sources = set()
        for question in quiz_content.questions:
            sources.update(question.sources_cited)
        return list(sources)
