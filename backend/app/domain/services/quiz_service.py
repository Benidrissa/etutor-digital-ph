"""Quiz generation service using Claude API and RAG."""

import uuid
from uuid import UUID

import structlog
from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.ai.claude_service import ClaudeService
from app.ai.prompts.audience import detect_audience
from app.ai.prompts.quiz import get_quiz_system_prompt
from app.ai.rag.retriever import SemanticRetriever
from app.api.v1.schemas.quiz import QuizContent, QuizResponse
from app.api.v1.schemas.story_course import ValidationIssue
from app.domain.models.content import GeneratedContent
from app.domain.models.course import Course
from app.domain.models.module import Module
from app.domain.models.module_unit import ModuleUnit
from app.domain.services import content_revisions, mcq_checks
from app.domain.services.platform_settings_service import SettingsCache

logger = structlog.get_logger()


def default_question_count(unit_id: str) -> int:
    """Quiz length when the caller does not say.

    The platform settings the generate endpoints use:
    ``quiz-summative-questions-count`` for a summative,
    ``quiz-unit-questions-count`` for a unit quiz.
    """
    key, fallback = (
        ("quiz-summative-questions-count", 20)
        if unit_id == "summative"
        else ("quiz-unit-questions-count", 10)
    )
    try:
        return int(SettingsCache.instance().get(key, fallback))
    except (TypeError, ValueError):
        return fallback


class QuizService:
    """Service for generating and managing quiz content."""

    def __init__(self, claude_service: ClaudeService, semantic_retriever: SemanticRetriever):
        self.claude_service = claude_service
        self.semantic_retriever = semantic_retriever

    async def _find_cached_content_row(
        self,
        session: AsyncSession,
        module_id: UUID,
        unit_id: str,
        module_unit_uuid: UUID | None,
        language: str,
        country: str,
        level: int,
    ) -> tuple[GeneratedContent | None, bool]:
        """Read-only cache lookup: exact 6-field match, then country fallback.

        Returns ``(row, is_fallback)``; never generates. Shared by
        ``get_or_generate_quiz`` and ``get_cached_quiz`` so the cache key stays
        in sync between the generating and polling paths (#2608).
        """

        def _apply_unit_filter(q):
            if module_unit_uuid is not None:
                return q.where(GeneratedContent.module_unit_id == module_unit_uuid)
            return q.where(
                GeneratedContent.module_id == module_id,
                GeneratedContent.module_unit_id.is_(None),
                GeneratedContent.content["unit_id"].astext == unit_id,
            )

        # Match all fields of the unique index; .first() with ORDER BY guards
        # against any legacy duplicate rows.
        query = _apply_unit_filter(
            select(GeneratedContent).where(
                GeneratedContent.content_type == "quiz",
                GeneratedContent.language == language,
                GeneratedContent.level == level,
                GeneratedContent.country_context == country,
            )
        ).order_by(GeneratedContent.generated_at.desc())
        result = await session.execute(query)
        row = result.scalars().first()
        if row is not None:
            return row, False

        fallback_query = _apply_unit_filter(
            select(GeneratedContent).where(
                GeneratedContent.content_type == "quiz",
                GeneratedContent.language == language,
                GeneratedContent.level == level,
            )
        ).order_by(GeneratedContent.generated_at.desc())
        fallback_result = await session.execute(fallback_query)
        row = fallback_result.scalars().first()
        return row, row is not None

    async def _overwrite_cached_quiz(
        self,
        session: AsyncSession,
        *,
        module_id: UUID,
        unit_id: str,
        module_unit_uuid: UUID | None,
        language: str,
        country: str,
        level: int,
        content: dict,
        sources: list[str],
    ) -> GeneratedContent | None:
        """Replace the cached quiz row for this exact key; ``None`` if there is none.

        Unit-scoped rows are matched like ``update_cached_content_in_place``
        (the lesson fix for #2561). Summative quizzes are module-scoped
        (``module_unit_id IS NULL`` + the ``content.unit_id`` sentinel), which
        that helper does not cover, so they are matched here on the same key as
        ``idx_unique_module_scoped_content``. Manually edited rows are never
        overwritten (returns ``None``), matching the lesson helper.

        The row keeps its id and question ids, so before it is overwritten its
        current content is saved as the pre-image of its current revision
        (unless the caller — quality agent, backfill — already saved one).
        A learner who was served that revision is then still graded against
        the questions they saw (``app.api.v1.quiz._content_to_grade``).
        """
        from app.domain.services.lesson_service import (
            apply_in_place_update,
            find_in_place_target,
        )

        # Re-read under a row lock: the session may hold this row from long
        # before (the quality run loads every candidate up front), and another
        # writer may have regenerated it since. The pre-image and the bump
        # below must start from the database's revision.
        if module_unit_uuid is not None:
            row = await find_in_place_target(
                session,
                module_unit_uuid=module_unit_uuid,
                content_type="quiz",
                language=language,
                level=level,
                country_context=country,
                for_update=True,
            )
        else:
            result = await session.execute(
                content_revisions.locked_for_overwrite(
                    select(GeneratedContent)
                    .where(
                        GeneratedContent.content_type == "quiz",
                        GeneratedContent.module_id == module_id,
                        GeneratedContent.module_unit_id.is_(None),
                        GeneratedContent.content["unit_id"].astext == unit_id,
                        GeneratedContent.language == language,
                        GeneratedContent.level == level,
                        GeneratedContent.country_context == country,
                    )
                    .order_by(GeneratedContent.generated_at.desc())
                )
            )
            row = result.scalars().first()
        if row is None or row.is_manually_edited:
            return None

        await content_revisions.ensure_pre_image(session, row)
        apply_in_place_update(row, content=content, sources_cited=sources)
        return row

    @staticmethod
    def _quiz_response_from_row(
        row: GeneratedContent, unit_id: str, country: str, is_fallback: bool
    ) -> QuizResponse:
        """Build a cached QuizResponse from a GeneratedContent row."""
        return QuizResponse(
            id=row.id,
            module_id=row.module_id,
            unit_id=row.content.get("unit_id", unit_id),
            language=row.language,
            level=row.level,
            country_context=row.country_context or country,
            content=QuizContent(**row.content),
            generated_at=row.generated_at.isoformat(),
            cached=True,
            country_fallback=is_fallback,
            content_revision=content_revisions.current_revision(row),
        )

    async def get_cached_quiz(
        self,
        module_id: UUID,
        unit_id: str,
        language: str,
        country: str,
        level: int,
        session: AsyncSession,
    ) -> QuizResponse | None:
        """Return cached quiz content without ever generating; ``None`` if not cached.

        Backs the async summative flow: the frontend polls this until the
        background ``generate_quiz_task`` has written the content (#2608).
        """
        from app.domain.services._unit_resolution import resolve_module_unit_id

        module_unit_uuid = await resolve_module_unit_id(session, module_id, unit_id)
        row, is_fallback = await self._find_cached_content_row(
            session, module_id, unit_id, module_unit_uuid, language, country, level
        )
        if row is None:
            return None
        return self._quiz_response_from_row(row, unit_id, country, is_fallback)

    async def get_or_generate_quiz(
        self,
        module_id: UUID,
        unit_id: str,
        language: str,
        country: str,
        level: int,
        num_questions: int | None = None,
        *,
        session: AsyncSession,
        force_regenerate: bool = False,
        user_id: UUID | None = None,
        quality_constraints: list[str] | None = None,
    ) -> QuizResponse:
        """
        Get existing quiz from cache or generate new one using RAG + Claude API.

        Args:
            module_id: Module ID for the quiz
            unit_id: Unit identifier within module
            language: Content language (fr/en)
            country: User's country for contextualization
            level: Learning level (1-4)
            num_questions: Number of questions to generate (5-15). ``None``
                means the platform setting for the quiz kind
                (:func:`default_question_count`). Regenerating callers (quality
                agent, backfill) pass the cached row's own count instead, so a
                regeneration keeps the quiz's length.
            session: Database session
            force_regenerate: Skip the cache and overwrite the cached row for
                this key in place (it used to INSERT, collide with the unique
                index and silently keep the stale row). The old content is kept
                as a revision pre-image, so answers to it stay gradeable.
            user_id: Optional user UUID for background task logging

        Returns:
            QuizResponse with quiz content and metadata

        Raises:
            ValueError: If module not found or invalid parameters
            Exception: If quiz generation fails
        """
        if num_questions is None:
            num_questions = default_question_count(unit_id)
        try:
            from app.domain.services._unit_resolution import resolve_module_unit_id

            # For unit-scoped quizzes use the FK; summative stays module-scoped
            # (module_unit_id IS NULL + JSON unit_id="summative" sentinel).
            module_unit_uuid = await resolve_module_unit_id(session, module_id, unit_id)

            cached_quiz = None
            is_fallback = False
            if not force_regenerate:
                cached_quiz, is_fallback = await self._find_cached_content_row(
                    session, module_id, unit_id, module_unit_uuid, language, country, level
                )

            if cached_quiz:
                logger.info(
                    "Retrieved quiz from cache",
                    quiz_id=str(cached_quiz.id),
                    module_id=str(module_id),
                    unit_id=unit_id,
                    country_fallback=is_fallback,
                )

                if is_fallback:
                    from app.tasks.content_generation import generate_country_content_task

                    generate_country_content_task.delay(
                        module_id=str(module_id),
                        unit_id=unit_id,
                        content_type="quiz",
                        language=language,
                        level=level,
                        country=country,
                        user_id=str(user_id) if user_id else "",
                    )

                return self._quiz_response_from_row(cached_quiz, unit_id, country, is_fallback)

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
                quality_constraints=quality_constraints,
            )

            content_payload = {**quiz_content.model_dump(), "unit_id": unit_id}
            sources = self._extract_sources_from_quiz(quiz_content)

            # Regeneration replaces the cached row for this exact key in place.
            # INSERTing instead collides with the unique index, rolls back and
            # returns the stale row — the same no-op the lesson Refresh had (#2561).
            if force_regenerate:
                overwritten = await self._overwrite_cached_quiz(
                    session,
                    module_id=module_id,
                    unit_id=unit_id,
                    module_unit_uuid=module_unit_uuid,
                    language=language,
                    country=country,
                    level=level,
                    content=content_payload,
                    sources=sources,
                )
                if overwritten is not None:
                    await session.commit()
                    await session.refresh(overwritten)
                    logger.info(
                        "Quiz regenerated in place",
                        quiz_id=str(overwritten.id),
                        num_questions=len(quiz_content.questions),
                        content_revision=overwritten.content_revision,
                    )
                    return QuizResponse(
                        id=overwritten.id,
                        module_id=module_id,
                        unit_id=unit_id,
                        language=language,
                        level=level,
                        country_context=country,
                        content=quiz_content,
                        generated_at=overwritten.generated_at.isoformat(),
                        cached=False,
                        content_revision=content_revisions.current_revision(overwritten),
                    )

            # Store in cache. module_unit_uuid was resolved at the top of this
            # function and stays None for "summative" quizzes.
            generated_content = GeneratedContent(
                id=uuid.uuid4(),
                module_id=module_id,
                module_unit_id=module_unit_uuid,
                content_type="quiz",
                language=language,
                level=level,
                content=content_payload,
                sources_cited=sources,
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
                existing, existing_fallback = await self._find_cached_content_row(
                    session, module_id, unit_id, module_unit_uuid, language, country, level
                )
                return self._quiz_response_from_row(existing, unit_id, country, existing_fallback)

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
                content_revision=content_revisions.current_revision(generated_content),
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
        quality_constraints: list[str] | None = None,
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

            # Detect audience and override config for kids courses
            audience_ctx = detect_audience(course)
            if audience_ctx.is_kids and unit_id != "summative":
                num_questions = SettingsCache.instance().get("quiz-kids-unit-questions-count", 5)

            if module:
                if unit_id == "summative":
                    all_units_result = await session.execute(
                        select(ModuleUnit)
                        .where(ModuleUnit.module_id == module.id)
                        .order_by(ModuleUnit.order_index)
                    )
                    all_units = list(all_units_result.scalars().all())
                else:
                    unit_result = await session.execute(
                        select(ModuleUnit).where(
                            and_(
                                ModuleUnit.module_id == module.id,
                                ModuleUnit.unit_number == unit_id,
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
                course=course,
            )

            # Append quality-loop constraints if provided (#2215).
            if quality_constraints:
                from app.ai.prompts.quality import constraints_block_from_report

                user_message = user_message + constraints_block_from_report(quality_constraints)

            response = await self.claude_service.generate_structured_content(
                system_prompt, user_message, "quiz"
            )

            # Summative quizzes have a hard requirement on question count
            # (a 10-Q "summative" defeats the purpose of a final exam).
            # If Claude undercounts, retry once with a stronger nudge.
            if unit_id == "summative":
                got = len(response.get("questions") or [])
                if got < num_questions:
                    logger.warning(
                        "Summative undercount, retrying with stronger nudge",
                        expected=num_questions,
                        got=got,
                    )
                    retry_message = (
                        f"Your previous response returned only {got} questions, but {num_questions} "
                        f"are REQUIRED for this summative assessment. Generate the full quiz again "
                        f"with EXACTLY {num_questions} questions covering all the units listed above. "
                        f"Do not abbreviate or summarize.\n\n" + user_message
                    )
                    response = await self.claude_service.generate_structured_content(
                        system_prompt, retry_message, "quiz"
                    )
                    final_got = len(response.get("questions") or [])
                    if final_got < num_questions:
                        logger.error(
                            "Summative still undercount after retry",
                            expected=num_questions,
                            got=final_got,
                        )

            # Validate and normalize the parsed dict from Claude
            quiz_data = self._validate_and_normalize_quiz(
                response, unit_id, num_questions, is_kids=audience_ctx.is_kids
            )

            return QuizContent(**quiz_data)

        except Exception as e:
            logger.error("Quiz content generation failed", error=str(e))
            raise

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
        course: Course | None = None,
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
        system_prompt = get_quiz_system_prompt(
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
            course=course,
        )

        audience_ctx = detect_audience(course)
        if audience_ctx.is_kids:
            age_range = f"{audience_ctx.age_min}-{audience_ctx.age_max}"
            audience = f"young learners aged {age_range} in {country}"
            context_note = (
                f"Use examples from daily life in {country} that children aged {age_range} can relate to "
                f"(school, market, family, games)"
            )
            practical_note = (
                f"Focus on fun, engaging questions that make {domain} exciting for children"
            )
            closing_note = (
                f"Generate the quiz now. Make it fun and encouraging for children aged {age_range} "
                f"learning {domain} in West Africa."
            )
            difficulty_instruction = (
                f"- Difficulty distribution: exactly 3 easy, 1 medium, 1 hard question\n"
                f"- CRITICAL: All questions must be age-appropriate for children aged "
                f"{age_range}. Use simple vocabulary and concepts from the lesson content only."
            )
            effective_passing = SettingsCache.instance().get("quiz-kids-passing-score", 60.0)
        else:
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
            difficulty_instruction = ""
            effective_passing = SettingsCache.instance().get("quiz-passing-score", 80.0)

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
{difficulty_instruction}
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
9. Every wrong option must be a trap built on a real misconception, never a random distractor. In "option_misconceptions" (same order as "options", exactly 4 entries) write one short sentence per WRONG option naming the misconception that would make a learner choose it, and null for the correct option
10. Never repeat the correct option's wording in the question text, and never give two options the same wording

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
      "option_misconceptions": [
        "Misconception that makes a learner choose option A",
        null,
        "Misconception that makes a learner choose option C",
        "Misconception that makes a learner choose option D"
      ],
      "explanation": "Explanation of why option B is correct and why others are wrong.",
      "sources_cited": ["Source reference from context"],
      "difficulty": "easy|medium|hard"
    }}
  ],
  "time_limit_minutes": {max(SettingsCache.instance().get("quiz-time-limit-min-minutes", 10), num_questions * SettingsCache.instance().get("quiz-time-limit-per-question-minutes", 1.5))},
  "passing_score": {effective_passing},
  "__complete": true
}}

{closing_note}"""

        return system_prompt, user_message

    def _validate_and_normalize_quiz(
        self,
        quiz_data: dict,
        unit_id: str,
        expected_questions: int,
        is_kids: bool = False,
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

            findings: list[ValidationIssue] = []
            for i, question in enumerate(questions):
                findings.extend(self._validate_question(question, f"question {i + 1}"))
            self._log_mcq_findings(findings, unit_id=unit_id, question_count=len(questions))

            if is_kids:
                _passing = SettingsCache.instance().get("quiz-kids-passing-score", 60.0)
            else:
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

    def _validate_question(self, question: dict, context: str) -> list[ValidationIssue]:
        """
        Validate a single quiz question structure, then run the shared MCQ checks.

        Structural problems raise, as before. The shared checks
        (``mcq_checks``: answer leaked into the stem, duplicate options,
        a distractor without a misconception) are returned, not raised: this
        runs on the learner's request path (``generate_quiz_task`` has no
        retry), and a regeneration would not deterministically fix them, so
        failing would only turn an imperfect quiz into no quiz. The caller
        logs them and the admin MCQ audit reports them.

        ``option_misconceptions`` is normalised in place: aligned with
        ``options`` and ``None`` at ``correct_answer``'s index.

        Args:
            question: Question dictionary to validate
            context: Context string for error messages

        Returns:
            The shared-check findings for this question.

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

        # Prompts are admin-overridable, so the field may be missing or
        # misshapen; normalise rather than trust it.
        question["option_misconceptions"] = mcq_checks.normalise_option_misconceptions(
            question.get("option_misconceptions"), len(options), correct_answer
        )
        return mcq_checks.check_quiz_question(question, path=f"questions[{question['id']}]")

    @staticmethod
    def _log_mcq_findings(
        findings: list[ValidationIssue], *, unit_id: str, question_count: int
    ) -> None:
        """One log line per quiz: defects kept, and how much went unchecked."""
        defects = mcq_checks.hard_errors(findings)
        unchecked = sum(1 for f in findings if f.code == mcq_checks.MISCONCEPTIONS_UNCHECKED)
        if defects:
            logger.warning(
                "Generated quiz has MCQ defects (kept; see admin MCQ audit)",
                unit_id=unit_id,
                question_count=question_count,
                defects=[f"{f.code}@{f.path}" for f in defects],
            )
        if unchecked:
            logger.info(
                "Generated quiz lacks option_misconceptions",
                unit_id=unit_id,
                questions_without=unchecked,
                question_count=question_count,
            )

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
