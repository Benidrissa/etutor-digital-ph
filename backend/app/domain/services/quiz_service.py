"""Quiz generation service using Claude API and RAG."""

import uuid
from uuid import UUID

import structlog
from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.ai.claude_service import ClaudeService
from app.ai.prompts.quiz import get_quiz_system_prompt
from app.ai.rag.retriever import SemanticRetriever
from app.api.v1.schemas.quiz import QuizContent, QuizResponse
from app.domain.models.content import GeneratedContent
from app.domain.models.course import Course
from app.domain.models.module import Module
from app.domain.models.module_unit import ModuleUnit
from app.domain.services.platform_settings_service import SettingsCache

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
        force_regenerate: bool = False,
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
            cached_quiz = None
            if not force_regenerate:
                # Cache lookup: match all 6 fields that form the unique index
                # Use .first() with ORDER BY as safety net for any legacy duplicates
                query = (
                    select(GeneratedContent)
                    .where(
                        GeneratedContent.module_id == module_id,
                        GeneratedContent.content_type == "quiz",
                        GeneratedContent.language == language,
                        GeneratedContent.level == level,
                        GeneratedContent.country_context == country,
                        GeneratedContent.content["unit_id"].astext == unit_id,
                    )
                    .order_by(GeneratedContent.generated_at.desc())
                )

                result = await session.execute(query)
                cached_quiz = result.scalars().first()

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
                session=session,
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
                content={**quiz_content.model_dump(), "unit_id": unit_id},
                sources_cited=self._extract_sources_from_quiz(quiz_content),
                country_context=country,
                validated=False,
            )

            session.add(generated_content)
            try:
                await session.commit()
                await session.refresh(generated_content)
            except IntegrityError:
                await session.rollback()
                logger.warning(
                    "Quiz cache INSERT conflict (race condition), fetching existing row",
                    module_id=str(module_id),
                    unit_id=unit_id,
                    language=language,
                )
                conflict_result = await session.execute(
                    select(GeneratedContent)
                    .where(
                        GeneratedContent.module_id == module_id,
                        GeneratedContent.content_type == "quiz",
                        GeneratedContent.language == language,
                        GeneratedContent.level == level,
                        GeneratedContent.content["unit_id"].astext == unit_id,
                    )
                    .order_by(GeneratedContent.generated_at.desc())
                )
                existing = conflict_result.scalars().first()
                return QuizResponse(
                    id=existing.id,
                    module_id=existing.module_id,
                    unit_id=existing.content.get("unit_id", unit_id),
                    language=existing.language,
                    level=existing.level,
                    country_context=existing.country_context or country,
                    content=QuizContent(**existing.content),
                    generated_at=existing.generated_at.isoformat(),
                    cached=True,
                )

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
        session: AsyncSession | None = None,
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
            module: Module | None = None
            course: Course | None = None
            unit_obj: ModuleUnit | None = None
            all_units: list[ModuleUnit] | None = None
            if session is not None:
                module_result = await session.execute(
                    select(Module)
                    .where(Module.id == module_id)
                    .options(selectinload(Module.course))
                )
                module = module_result.scalar_one_or_none()
                if module:
                    course = module.course
                    if unit_id == "summative":
                        all_units_result = await session.execute(
                            select(ModuleUnit)
                            .where(ModuleUnit.module_id == module.id)
                            .order_by(ModuleUnit.order_index)
                        )
                        all_units = list(all_units_result.scalars().all())
                    else:
                        unit_number = self._unit_id_to_unit_number(unit_id, module.module_number)
                        if unit_number:
                            unit_result = await session.execute(
                                select(ModuleUnit).where(
                                    and_(
                                        ModuleUnit.module_id == module.id,
                                        ModuleUnit.unit_number == unit_number,
                                    )
                                )
                            )
                            unit_obj = unit_result.scalar_one_or_none()

            search_query = self._build_quiz_search_query(
                module, unit_id, language, unit=unit_obj, all_units=all_units
            )
            search_results = await self.semantic_retriever.search_for_module(
                query=search_query,
                user_level=level,
                user_language=language,
                books_sources=self._resolve_books_sources(module) if module else None,
                top_k=SettingsCache.instance().get("ai-rag-default-top-k", 8),
                session=session,
            )

            # Build context from retrieved chunks
            context_text = "\n\n".join(
                [
                    f"Source: {result.chunk.source}\n{result.chunk.content}"
                    for result in search_results
                ]
            )

            unit_title: str | None = None
            unit_description: str | None = None
            all_units_summary: str | None = None
            if unit_obj is not None:
                unit_title = unit_obj.title_fr if language == "fr" else unit_obj.title_en
                unit_description = (
                    unit_obj.description_fr if language == "fr" else unit_obj.description_en
                )
            elif all_units:
                lines = []
                for u in all_units:
                    t = u.title_fr if language == "fr" else u.title_en
                    d = (u.description_fr if language == "fr" else u.description_en) or ""
                    lines.append(f"- {t}: {d}".strip(": "))
                all_units_summary = "\n".join(lines)

            # Generate quiz using Claude API with structured prompt
            system_prompt, user_message = self._build_quiz_prompt(
                context=context_text,
                unit_id=unit_id,
                language=language,
                country=country,
                level=level,
                num_questions=num_questions,
                course_title=(
                    (course.title_fr if language == "fr" else course.title_en) if course else None
                ),
                course_description=(
                    (course.description_fr if language == "fr" else course.description_en)
                    if course
                    else None
                ),
                module_title=(
                    (module.title_fr if language == "fr" else module.title_en) if module else ""
                ),
                bloom_level=module.bloom_level if module else "",
                unit_title=unit_title,
                unit_description=unit_description,
                all_units_summary=all_units_summary,
            )

            response = await self.claude_service.generate_structured_content(
                system_prompt, user_message, "quiz"
            )

            # Validate and normalize the parsed dict from Claude
            quiz_data = self._validate_and_normalize_quiz(response, unit_id, num_questions)

            return QuizContent(**quiz_data)

        except Exception as e:
            logger.error("Quiz content generation failed", error=str(e))
            raise

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

    @staticmethod
    def _resolve_books_sources(module: "Module") -> dict | None:
        """Prefer course rag_collection_id over module.books_sources."""
        course = module.course
        if course and course.rag_collection_id:
            return {course.rag_collection_id: []}
        if module.books_sources:
            return module.books_sources
        return None

    def _build_quiz_search_query(
        self,
        module: "Module | None",
        unit_id: str,
        language: str,
        unit: "ModuleUnit | None" = None,
        all_units: "list[ModuleUnit] | None" = None,
    ) -> str:
        """Build a context-aware RAG search query from module/unit metadata."""
        if module is None:
            return f"unit {unit_id}"

        if unit is not None:
            unit_title = unit.title_fr if language == "fr" else unit.title_en
            unit_description = unit.description_fr if language == "fr" else unit.description_en
            parts = [unit_title]
            if unit_description:
                parts.append(unit_description[:200])
            return " ".join(parts)

        if all_units:
            module_title = module.title_fr if language == "fr" else module.title_en
            unit_titles = [(u.title_fr if language == "fr" else u.title_en) for u in all_units]
            return " ".join([module_title] + unit_titles)

        title = module.title_fr if language == "fr" else module.title_en
        description = module.description_fr if language == "fr" else module.description_en
        parts = [title]
        if unit_id:
            parts.append(unit_id)
        if description:
            parts.append(description[:200])
        return " ".join(parts)

    def _build_quiz_prompt(
        self,
        context: str,
        unit_id: str,
        language: str,
        country: str,
        level: int,
        num_questions: int,
        course_title: str | None = None,
        course_description: str | None = None,
        module_title: str = "",
        bloom_level: str = "",
        syllabus_context: str = "",
        course_domain: str = "",
        unit_title: str | None = None,
        unit_description: str | None = None,
        all_units_summary: str | None = None,
    ) -> tuple[str, str]:
        """Build the system and user prompts for Claude API to generate quiz questions."""

        lang_instruction = "in French" if language == "fr" else "in English"
        level_desc = {
            1: "beginner (basic concepts, definitions)",
            2: "intermediate (application, analysis)",
            3: "advanced (synthesis, evaluation)",
            4: "expert (research, policy implications)",
        }

        domain = course_title or "public health"

        effective_unit_title = unit_title or unit_id
        admin_system = get_quiz_system_prompt(
            language,
            country,
            level,
            bloom_level,
            course_title,
            course_description,
            module_title,
            effective_unit_title,
            syllabus_context,
            course_domain,
        )
        json_schema_block = (
            "\n\nCRITICAL: You MUST respond with valid JSON ONLY. "
            "No preamble, no explanation, no markdown code fences.\n\n"
            "Required JSON structure:\n"
            "{\n"
            '  "title": string,\n'
            '  "description": string,\n'
            '  "questions": [\n'
            "    {\n"
            '      "id": string (e.g. "q1"),\n'
            '      "question": string,\n'
            '      "options": [string, string, string, string],\n'
            '      "correct_answer": integer 0-3,\n'
            '      "explanation": string,\n'
            '      "sources_cited": [string],\n'
            '      "difficulty": "easy"|"medium"|"hard"\n'
            "    }\n"
            "  ],\n"
            '  "time_limit_minutes": number,\n'
            '  "passing_score": number,\n'
            '  "__complete": true\n'
            "}\n"
            'IMPORTANT: "__complete": true MUST be the last field '
            "in your JSON response."
        )

        if admin_system is not None:
            system_prompt = admin_system + json_schema_block
        else:
            system_prompt = (
                "You are an expert educator creating adaptive quiz "
                f"content for West African professionals in {domain}." + json_schema_block
            )

        audience = (
            f"professionals in {domain} in {country}"
            if course_title
            else f"public health professionals in {country}"
        )
        context_note = (
            f"Use examples relevant to {country} and West African context when possible, adapted to {domain}"
            if course_title
            else f"Use examples relevant to {country} and West African context when possible"
        )
        practical_note = (
            f"Focus on practical applications for {domain} work"
            if course_title
            else "Focus on practical applications for public health work"
        )
        closing_note = (
            f"Generate the quiz now, ensuring all questions are relevant to {domain} practice in West Africa."
            if course_title
            else "Generate the quiz now, ensuring all questions are relevant to public health practice in West Africa."
        )

        if unit_title is not None:
            topic_constraint = (
                f"IMPORTANT: All questions MUST be specifically about {unit_title!r}. "
                "Do NOT include questions about other topics in this module."
            )
            if unit_description:
                topic_constraint += f" Topic scope: {unit_description}"
        elif all_units_summary is not None:
            topic_constraint = (
                f"IMPORTANT: This is a summative quiz. Questions MUST cover ALL of the following units. "
                f"Distribute questions evenly across all units:\n{all_units_summary}"
            )
        else:
            topic_constraint = ""

        user_message = f"""Create a multiple-choice quiz for {audience}.

CONTEXT MATERIAL:
{context}

QUIZ REQUIREMENTS:
- Target audience: {audience.capitalize()}
- Domain: {domain}
- Language: {lang_instruction}
- Level: {level_desc.get(level, "intermediate")}
- Unit: {effective_unit_title}
- Number of questions: {num_questions}
- Format: Multiple choice with exactly 4 options each
- Include explanations and source citations
{("- " + topic_constraint) if topic_constraint else ""}

INSTRUCTIONS:
1. Create {num_questions} multiple-choice questions based on the provided context
2. Each question must have exactly 4 options (A, B, C, D)
3. Only ONE option should be correct
4. Include clear explanations for why the correct answer is right
5. Add source citations from the context material
6. {context_note}
7. Progress from easier to harder questions
8. {practical_note}

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
  "time_limit_minutes": {max(SettingsCache.instance().get("quiz-time-limit-min-minutes", 10), num_questions * SettingsCache.instance().get("quiz-time-limit-per-question-minutes", 1.5))},
  "passing_score": {SettingsCache.instance().get("quiz-passing-score", 80.0)},
  "__complete": true
}}

{closing_note}"""

        return system_prompt, user_message

    def _validate_and_normalize_quiz(
        self, quiz_data: dict, unit_id: str, expected_questions: int
    ) -> dict:
        """
        Validate and normalize parsed quiz data from Claude API.

        Args:
            quiz_data: Parsed dict returned by generate_structured_content
            unit_id: Unit identifier to include in response
            expected_questions: Expected number of questions for validation

        Returns:
            Normalized dictionary with quiz content

        Raises:
            ValueError: If quiz_data is invalid or missing required fields
        """
        try:
            if quiz_data.get("raw_response") is True:
                raw_preview = str(quiz_data.get("content", ""))[:200]
                raise ValueError(
                    f"Claude returned non-JSON text (JSON parsing failed). Raw preview: {raw_preview!r}"
                )

            required_fields = ["title", "questions"]
            for field in required_fields:
                if field not in quiz_data:
                    raise ValueError(f"Missing required field: {field}")

            quiz_data.setdefault("description", "")

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

            for i, question in enumerate(questions):
                self._validate_question(question, f"question {i + 1}")

            _passing = SettingsCache.instance().get("quiz-passing-score", 80.0)
            quiz_data.setdefault(
                "time_limit_minutes",
                max(
                    SettingsCache.instance().get("quiz-time-limit-min-minutes", 10),
                    len(questions)
                    * SettingsCache.instance().get("quiz-time-limit-per-question-minutes", 1.5),
                ),
            )
            quiz_data.setdefault("passing_score", _passing)
            if quiz_data.get("passing_score", _passing) < _passing:
                quiz_data["passing_score"] = _passing

            quiz_data["unit_id"] = unit_id

            return quiz_data

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
