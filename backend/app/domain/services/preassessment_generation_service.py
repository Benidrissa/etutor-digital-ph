"""Pre-assessment generation service using Claude API and RAG."""

import uuid
from uuid import UUID

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.claude_service import ClaudeService
from app.ai.prompts.preassessment import (
    get_preassessment_system_prompt,
    get_preassessment_user_message,
)
from app.ai.rag.retriever import SemanticRetriever
from app.domain.models.course import Course
from app.domain.models.document_chunk import DocumentChunk
from app.domain.models.module import Module
from app.domain.models.preassessment import CoursePreAssessment
from app.domain.services.platform_settings_service import SettingsCache

logger = structlog.get_logger(__name__)

EXPECTED_QUESTION_COUNT = 20
DIFFICULTY_LEVELS = [1, 2, 3, 4]
QUESTIONS_PER_LEVEL = 5


class PreAssessmentGenerationService:
    """Service for generating and storing course pre-assessments via RAG + Claude."""

    def __init__(self, claude_service: ClaudeService, semantic_retriever: SemanticRetriever):
        self.claude_service = claude_service
        self.semantic_retriever = semantic_retriever

    async def generate_and_store(
        self,
        course_id: UUID,
        language: str,
        session: AsyncSession,
        task_id: str | None = None,
    ) -> CoursePreAssessment:
        """Generate a 20-question pre-assessment for a course and store in DB.

        Args:
            course_id: UUID of the course
            language: Content language ("fr" or "en")
            session: Async DB session
            task_id: Optional Celery task ID for tracking

        Returns:
            Persisted CoursePreAssessment instance

        Raises:
            ValueError: If course not found or no RAG content indexed
            Exception: If Claude API call fails
        """
        course_result = await session.execute(select(Course).where(Course.id == course_id))
        course = course_result.scalar_one_or_none()
        if not course:
            raise ValueError(f"Course not found: {course_id}")

        module_result = await session.execute(
            select(Module).where(Module.course_id == course_id).order_by(Module.module_number)
        )
        modules = module_result.scalars().all()
        module_titles = [(m.title_fr if language == "fr" else m.title_en) for m in modules]

        chunk_count_result = await session.execute(
            select(func.count())
            .select_from(DocumentChunk)
            .where(DocumentChunk.source == course.rag_collection_id)
        )
        chunk_count = chunk_count_result.scalar_one()
        if chunk_count == 0:
            raise ValueError(
                f"No RAG content indexed for course {course_id}. "
                "Upload resources and run indexation first."
            )

        course_title = course.title_fr if language == "fr" else course.title_en
        course_description = course.description_fr if language == "fr" else course.description_en

        cats = course.taxonomy_categories or []
        domain_slugs = [tc.slug for tc in cats if tc.type == "domain"]
        course_domain = ", ".join(domain_slugs) if domain_slugs else ""

        search_query = self._build_search_query(course_title, module_titles, language)
        top_k = SettingsCache.instance().get("ai-rag-default-top-k", 8)
        top_k = max(top_k, 12)

        filters: dict = {}
        if course.rag_collection_id:
            filters["rag_collection_id"] = course.rag_collection_id

        search_results = await self.semantic_retriever.search(
            query=search_query,
            top_k=top_k,
            filters=filters if filters else None,
            session=session,
        )

        if not search_results:
            raise ValueError(
                f"RAG search returned no results for course {course_id}. "
                "Ensure resources are properly indexed."
            )

        context_text = "\n\n".join(
            f"Source: {r.chunk.source}\n{r.chunk.content}" for r in search_results
        )

        sources_cited = list(
            {
                f"{r.chunk.source} Ch.{r.chunk.chapter}, p.{r.chunk.page}"
                if r.chunk.chapter and r.chunk.page
                else r.chunk.source
                for r in search_results
            }
        )

        system_prompt = get_preassessment_system_prompt(
            language=language,
            course_title=course_title,
            course_description=course_description,
            course_domain=course_domain,
            module_titles=module_titles,
        )
        user_message = get_preassessment_user_message(
            context_text=context_text,
            course_title=course_title,
            language=language,
            module_titles=module_titles,
        )

        logger.info(
            "Calling Claude API for pre-assessment generation",
            course_id=str(course_id),
            language=language,
            rag_chunks=len(search_results),
        )

        raw_response = await self.claude_service.generate_structured_content(
            system_prompt, user_message, "preassessment"
        )

        questions, validated_sources = self._validate_and_normalize(raw_response, sources_cited)

        answer_key = {
            str(i + 1): q.get("correct_answer", "")
            for i, q in enumerate(questions)
        }
        question_levels = {
            str(i + 1): q.get("difficulty_level", 2)
            for i, q in enumerate(questions)
        }

        preassessment = CoursePreAssessment(
            id=uuid.uuid4(),
            course_id=course_id,
            language=language,
            questions=questions,
            answer_key=answer_key,
            question_levels=question_levels,
            question_count=len(questions),
            sources_cited=validated_sources,
            generated_by="ai",
            generation_task_id=task_id,
        )
        session.add(preassessment)
        await session.commit()
        await session.refresh(preassessment)

        logger.info(
            "Pre-assessment generated and stored",
            preassessment_id=str(preassessment.id),
            course_id=str(course_id),
            question_count=len(questions),
        )

        return preassessment

    def _build_search_query(
        self,
        course_title: str,
        module_titles: list[str],
        language: str,
    ) -> str:
        """Build a broad RAG search query covering the whole course."""
        parts = [course_title]
        parts.extend(module_titles[:5])
        if language == "fr":
            parts.append("évaluation diagnostique compétences santé publique")
        else:
            parts.append("diagnostic assessment competencies public health")
        return " ".join(parts)

    def _validate_and_normalize(
        self,
        raw_response: dict,
        fallback_sources: list[str],
    ) -> tuple[list[dict], list[str]]:
        """Validate and normalize the Claude API response.

        Returns:
            Tuple of (normalized questions list, sources list)

        Raises:
            ValueError: If response format is invalid
        """
        if raw_response.get("raw_response") is True:
            preview = str(raw_response.get("content", ""))[:200]
            raise ValueError(
                f"Claude returned non-JSON text (JSON parsing failed). Preview: {preview!r}"
            )

        questions_raw = raw_response.get("questions")
        if not isinstance(questions_raw, list) or len(questions_raw) == 0:
            raise ValueError("Pre-assessment response missing 'questions' list")

        if len(questions_raw) < EXPECTED_QUESTION_COUNT - 2:
            logger.warning(
                "Fewer questions than expected",
                expected=EXPECTED_QUESTION_COUNT,
                got=len(questions_raw),
            )

        normalized = []
        for i, q in enumerate(questions_raw):
            normalized.append(self._validate_question(q, f"question {i + 1}", i))

        sources = raw_response.get("sources_cited")
        if not isinstance(sources, list):
            sources = fallback_sources

        return normalized, sources

    def _validate_question(self, question: dict, context: str, index: int = 0) -> dict:
        """Validate a single pre-assessment question and return normalized dict.

        Raises:
            ValueError: If required fields are missing or invalid
        """
        required = ["question", "options", "correct_answer", "explanation"]
        for field in required:
            if field not in question:
                raise ValueError(f"{context}: Missing required field '{field}'")

        options = question["options"]
        if isinstance(options, dict):
            if not all(k in options for k in ("a", "b", "c", "d")):
                raise ValueError(f"{context}: options dict must have keys a, b, c, d")
        elif isinstance(options, list):
            if len(options) != 4:
                raise ValueError(f"{context}: options list must have exactly 4 items")
            options = {"a": options[0], "b": options[1], "c": options[2], "d": options[3]}
            question["options"] = options
        else:
            raise ValueError(f"{context}: 'options' must be dict or list")

        correct = question["correct_answer"]
        if isinstance(correct, int):
            letters = ["a", "b", "c", "d"]
            if 0 <= correct <= 3:
                question["correct_answer"] = letters[correct]
            else:
                raise ValueError(f"{context}: correct_answer int must be 0-3")
        elif isinstance(correct, str):
            if correct.lower() not in ("a", "b", "c", "d"):
                raise ValueError(f"{context}: correct_answer must be a, b, c, or d")
            question["correct_answer"] = correct.lower()
        else:
            raise ValueError(f"{context}: correct_answer must be str or int")

        question.setdefault("id", f"q{index + 1}")
        question.setdefault("difficulty_level", 2)
        question.setdefault("domain_tag", "")
        question.setdefault("sources_cited", [])

        difficulty = question["difficulty_level"]
        if not isinstance(difficulty, int) or difficulty not in DIFFICULTY_LEVELS:
            question["difficulty_level"] = 2

        return question
