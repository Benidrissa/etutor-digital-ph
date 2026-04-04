"""Tool definitions and execution handlers for the agentic AI tutor."""

import json
import uuid
from typing import Any

import structlog
from anthropic.types import ToolParam
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.rag.retriever import SemanticRetriever
from app.domain.models.content import GeneratedContent
from app.domain.models.module import Module
from app.domain.models.progress import UserModuleProgress
from app.domain.models.quiz import PlacementTestAttempt, QuizAttempt
from app.domain.services.learner_memory_service import LearnerMemoryService
from app.domain.services.platform_settings_service import SettingsCache

logger = structlog.get_logger()

TOOL_DEFINITIONS: list[ToolParam] = [
    {
        "name": "search_knowledge_base",
        "description": (
            "Search the knowledge base (reference textbooks on public health) for relevant information. "
            "Use this when you need to cite sources, verify a concept, or find supporting material "
            "for your Socratic guidance. Returns relevant text chunks with source citations."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query to find relevant knowledge base content.",
                },
                "module_id": {
                    "type": "string",
                    "description": "Optional UUID of the current module to narrow source filtering.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_learner_progress",
        "description": (
            "Retrieve the learner's current progress, quiz scores, completed modules, "
            "weak domains, and placement test results. Use this to personalize your guidance, "
            "adapt difficulty, and address knowledge gaps."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "string",
                    "description": "UUID of the learner.",
                },
            },
            "required": ["user_id"],
        },
    },
    {
        "name": "generate_mini_quiz",
        "description": (
            "Generate an inline mini quiz (2-3 questions) to test the learner's comprehension "
            "of a specific topic. Use this after explaining a difficult concept to reinforce learning. "
            "Returns structured quiz questions with options."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "The topic or concept to quiz the learner on.",
                },
                "num_questions": {
                    "type": "integer",
                    "description": "Number of questions to generate (2-3 recommended).",
                    "minimum": 1,
                    "maximum": 3,
                },
                "difficulty": {
                    "type": "string",
                    "enum": ["easy", "medium", "hard"],
                    "description": "Difficulty level of the quiz questions.",
                },
            },
            "required": ["topic", "num_questions", "difficulty"],
        },
    },
    {
        "name": "search_flashcards",
        "description": (
            "Find relevant flashcards for a concept to suggest to the learner for review. "
            "Use this to recommend spaced repetition material after covering a topic."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "concept": {
                    "type": "string",
                    "description": "The concept or term to search flashcards for.",
                },
                "module_id": {
                    "type": "string",
                    "description": "Optional UUID of the module to filter flashcards.",
                },
            },
            "required": ["concept"],
        },
    },
    {
        "name": "save_learner_preference",
        "description": (
            "Save a detected learner preference or learning pattern to personalize future interactions. "
            "Use this when you detect consistent patterns such as: the learner prefers analogies, "
            "responds well to examples, prefers a specific language, struggles with statistics, etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "preference_type": {
                    "type": "string",
                    "description": (
                        "Category of the preference (e.g., 'learning_style', 'difficulty_preference', "
                        "'language_preference', 'topic_strength', 'topic_weakness')."
                    ),
                },
                "value": {
                    "type": "object",
                    "description": (
                        "The preference value as a JSON object with relevant details. "
                        'Example: {"style": "analogies", "confidence": 0.9}'
                    ),
                },
            },
            "required": ["preference_type", "value"],
        },
    },
]


class TutorToolExecutor:
    """Executes tool calls made by Claude in the agentic tutor loop."""

    def __init__(
        self,
        retriever: SemanticRetriever,
        anthropic_client: Any,
        user_id: uuid.UUID,
        user_level: int,
        user_language: str,
        learner_memory_service: LearnerMemoryService | None = None,
        course_filter: list[uuid.UUID] | None = None,
    ):
        self.retriever = retriever
        self.anthropic = anthropic_client
        self.user_id = user_id
        self.user_level = user_level
        self.user_language = user_language
        self.learner_memory_service = learner_memory_service or LearnerMemoryService()
        self.course_filter = course_filter

    async def execute(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        session: AsyncSession,
    ) -> str:
        """
        Execute a tool call and return the result as a JSON string.

        Args:
            tool_name: Name of the tool to execute
            tool_input: Tool input parameters
            session: Database session

        Returns:
            JSON string with tool result
        """
        logger.info(
            "Executing tutor tool",
            tool_name=tool_name,
            user_id=str(self.user_id),
            tool_input_keys=list(tool_input.keys()),
        )

        try:
            if tool_name == "search_knowledge_base":
                return await self._search_knowledge_base(tool_input, session)
            elif tool_name == "get_learner_progress":
                return await self._get_learner_progress(tool_input, session)
            elif tool_name == "generate_mini_quiz":
                return await self._generate_mini_quiz(tool_input)
            elif tool_name == "search_flashcards":
                return await self._search_flashcards(tool_input, session)
            elif tool_name == "save_learner_preference":
                return await self._save_learner_preference(tool_input, session)
            else:
                logger.warning("Unknown tool called", tool_name=tool_name)
                return json.dumps({"error": f"Unknown tool: {tool_name}"})
        except Exception as e:
            logger.error(
                "Tool execution failed",
                tool_name=tool_name,
                error=str(e),
                user_id=str(self.user_id),
            )
            return json.dumps({"error": f"Tool execution failed: {str(e)}"})

    async def _search_knowledge_base(
        self, tool_input: dict[str, Any], session: AsyncSession
    ) -> str:
        """Execute search_knowledge_base tool."""
        query = tool_input["query"]
        module_id_str = tool_input.get("module_id")

        books_sources = None
        if module_id_str:
            try:
                module_id = uuid.UUID(module_id_str)
                module = await session.get(Module, module_id)
                if module:
                    books_sources = module.books_sources
            except (ValueError, TypeError):
                pass

        if not books_sources and self.course_filter:
            books_sources = await self._get_books_sources_for_courses(
                self.course_filter, session
            )

        results = await self.retriever.search_for_module(
            query=query,
            user_level=self.user_level,
            user_language=self.user_language,
            books_sources=books_sources,
            top_k=5,
            session=session,
        )

        if not results and books_sources:
            results = await self.retriever.search_for_module(
                query=query,
                user_level=self.user_level,
                user_language=self.user_language,
                books_sources=None,
                top_k=5,
                session=session,
            )

        chunks = []
        for result in results:
            chunks.append(
                {
                    "content": result.chunk.content,
                    "source": result.chunk.source,
                    "chapter": result.chunk.chapter,
                    "page": result.chunk.page,
                    "similarity": round(result.similarity_score, 3),
                }
            )

        logger.info(
            "search_knowledge_base tool completed",
            query=query,
            results_count=len(chunks),
            user_id=str(self.user_id),
        )
        return json.dumps({"query": query, "results": chunks, "count": len(chunks)})

    async def _get_books_sources_for_courses(
        self,
        course_ids: list[uuid.UUID],
        session: AsyncSession,
    ) -> dict[str, list[str]] | None:
        """Aggregate books_sources from all modules belonging to the given courses."""
        from sqlalchemy import select as sa_select

        result = await session.execute(
            sa_select(Module).where(Module.course_id.in_(course_ids))
        )
        modules = result.scalars().all()
        merged: dict[str, list[str]] = {}
        for module in modules:
            if module.books_sources:
                for key, val in module.books_sources.items():
                    if key not in merged:
                        merged[key] = val
        return merged if merged else None

    async def _get_learner_progress(self, tool_input: dict[str, Any], session: AsyncSession) -> str:
        """Execute get_learner_progress tool."""
        progress_query = select(UserModuleProgress).where(
            UserModuleProgress.user_id == self.user_id
        )
        progress_result = await session.execute(progress_query)
        progress_rows = progress_result.scalars().all()

        modules_progress = []
        completed_modules = []
        weak_domains = []

        for row in progress_rows:
            module_data = {
                "module_id": str(row.module_id),
                "status": row.status,
                "completion_pct": row.completion_pct,
                "quiz_score_avg": row.quiz_score_avg,
                "time_spent_minutes": row.time_spent_minutes,
            }
            modules_progress.append(module_data)

            if row.status == "completed":
                completed_modules.append(str(row.module_id))

            if row.quiz_score_avg is not None and row.quiz_score_avg < 60:
                weak_domains.append(
                    {"module_id": str(row.module_id), "quiz_score_avg": row.quiz_score_avg}
                )

        quiz_query = (
            select(QuizAttempt)
            .where(QuizAttempt.user_id == self.user_id)
            .order_by(QuizAttempt.attempted_at.desc())
            .limit(5)
        )
        quiz_result = await session.execute(quiz_query)
        recent_quizzes = quiz_result.scalars().all()

        recent_scores = [
            {"quiz_id": str(q.quiz_id), "score": q.score, "attempted_at": str(q.attempted_at)}
            for q in recent_quizzes
        ]

        placement_query = (
            select(PlacementTestAttempt)
            .where(PlacementTestAttempt.user_id == self.user_id)
            .order_by(PlacementTestAttempt.attempted_at.desc())
            .limit(1)
        )
        placement_result = await session.execute(placement_query)
        placement = placement_result.scalar_one_or_none()

        placement_data = None
        if placement:
            placement_data = {
                "assigned_level": placement.assigned_level,
                "raw_score": placement.raw_score,
                "domain_scores": placement.domain_scores,
                "competency_areas": placement.competency_areas,
            }

        result = {
            "user_id": str(self.user_id),
            "current_level": self.user_level,
            "modules_progress": modules_progress,
            "completed_modules_count": len(completed_modules),
            "weak_domains": weak_domains,
            "recent_quiz_scores": recent_scores,
            "placement_test": placement_data,
        }

        logger.info(
            "get_learner_progress tool completed",
            user_id=str(self.user_id),
            modules_count=len(modules_progress),
        )
        return json.dumps(result)

    async def _generate_mini_quiz(self, tool_input: dict[str, Any]) -> str:
        """Execute generate_mini_quiz tool via a separate Claude call."""
        topic = tool_input["topic"]
        num_questions = min(int(tool_input.get("num_questions", 2)), 3)
        difficulty = tool_input.get("difficulty", "medium")

        language_instruction = "en français" if self.user_language == "fr" else "in English"
        difficulty_map = {
            "easy": "simples, définitions et reconnaissance",
            "medium": "application de concepts",
            "hard": "analyse et évaluation critique",
        }
        difficulty_desc = difficulty_map.get(difficulty, "application de concepts")

        prompt = f"""Generate a mini quiz {language_instruction} on the topic: "{topic}"

Requirements:
- {num_questions} multiple-choice questions
- Difficulty: {difficulty_desc}
- Each question has 4 options (A, B, C, D)
- One correct answer per question
- Brief explanation for the correct answer
- Context: West African public health setting

Respond ONLY with valid JSON in this exact format:
{{
  "topic": "{topic}",
  "questions": [
    {{
      "question": "Question text here?",
      "options": {{
        "A": "Option A text",
        "B": "Option B text",
        "C": "Option C text",
        "D": "Option D text"
      }},
      "correct_answer": "A",
      "explanation": "Brief explanation why A is correct."
    }}
  ]
}}"""

        response = await self.anthropic.messages.create(
            model="claude-sonnet-4-6",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=SettingsCache.instance().get("tutor-suggestions-max-tokens", 800),
            temperature=SettingsCache.instance().get("tutor-suggestions-temperature", 0.5),
        )

        quiz_text = response.content[0].text.strip()

        try:
            if "```json" in quiz_text:
                quiz_text = quiz_text.split("```json")[1].split("```")[0].strip()
            elif "```" in quiz_text:
                quiz_text = quiz_text.split("```")[1].split("```")[0].strip()
            quiz_data = json.loads(quiz_text)
        except (json.JSONDecodeError, IndexError):
            quiz_data = {"topic": topic, "raw": quiz_text, "parse_error": True}

        logger.info(
            "generate_mini_quiz tool completed",
            topic=topic,
            num_questions=num_questions,
            user_id=str(self.user_id),
        )
        return json.dumps(quiz_data)

    async def _search_flashcards(self, tool_input: dict[str, Any], session: AsyncSession) -> str:
        """Execute search_flashcards tool."""
        concept = tool_input["concept"]
        module_id_str = tool_input.get("module_id")

        query = select(GeneratedContent).where(GeneratedContent.content_type == "flashcard")

        if module_id_str:
            try:
                module_id = uuid.UUID(module_id_str)
                query = query.where(GeneratedContent.module_id == module_id)
            except (ValueError, TypeError):
                pass

        query = query.limit(20)
        result = await session.execute(query)
        all_flashcards = result.scalars().all()

        concept_lower = concept.lower()
        matching = []

        for card in all_flashcards:
            content = card.content or {}
            term_fr = str(content.get("term_fr", "")).lower()
            term_en = str(content.get("term_en", "")).lower()
            definition_fr = str(content.get("definition_fr", "")).lower()

            if (
                concept_lower in term_fr
                or concept_lower in term_en
                or concept_lower in definition_fr
            ):
                matching.append(
                    {
                        "id": str(card.id),
                        "module_id": str(card.module_id),
                        "term_fr": content.get("term_fr"),
                        "term_en": content.get("term_en"),
                        "definition_fr": content.get("definition_fr"),
                        "definition_en": content.get("definition_en"),
                    }
                )

            if len(matching) >= 5:
                break

        logger.info(
            "search_flashcards tool completed",
            concept=concept,
            results_count=len(matching),
            user_id=str(self.user_id),
        )
        return json.dumps({"concept": concept, "flashcards": matching, "count": len(matching)})

    async def _save_learner_preference(
        self, tool_input: dict[str, Any], session: AsyncSession
    ) -> str:
        """Execute save_learner_preference tool using LearnerMemoryService."""
        preference_type = tool_input["preference_type"]
        value = tool_input["value"]

        existing = await self.learner_memory_service._fetch(self.user_id, session)
        was_existing = existing is not None

        await self.learner_memory_service.update_preference(
            self.user_id, preference_type, value, session
        )

        logger.info(
            "save_learner_preference tool completed",
            preference_type=preference_type,
            user_id=str(self.user_id),
            updated=was_existing,
        )
        return json.dumps(
            {
                "saved": True,
                "preference_type": preference_type,
                "value": value,
                "updated": was_existing,
            }
        )
