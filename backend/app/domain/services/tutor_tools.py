"""Tool definitions and execution handlers for the agentic AI tutor."""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING, Any

import structlog
from anthropic.types import ToolParam
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.content import GeneratedContent
from app.domain.models.learner_memory import LearnerMemory
from app.domain.models.progress import UserModuleProgress
from app.domain.models.quiz import PlacementTestAttempt, QuizAttempt

if TYPE_CHECKING:
    from anthropic import AsyncAnthropic

    from app.ai.rag.retriever import SemanticRetriever

logger = structlog.get_logger()

TOOL_DEFINITIONS: list[ToolParam] = [
    {
        "name": "search_knowledge_base",
        "description": (
            "Search the knowledge base (RAG) for relevant public health information from the "
            "3 reference textbooks. Call this when you need to cite sources, verify information, "
            "or retrieve context about a specific topic."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query to find relevant knowledge base chunks.",
                },
                "module_id": {
                    "type": "string",
                    "description": "Optional module UUID to filter results by module context.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_learner_progress",
        "description": (
            "Retrieve the learner's current progress, including completed modules, quiz scores, "
            "weak domains, and current level. Call this to personalize advice and tailor responses "
            "to the learner's actual knowledge state."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "string",
                    "description": "The UUID of the user whose progress to retrieve.",
                },
            },
            "required": ["user_id"],
        },
    },
    {
        "name": "generate_mini_quiz",
        "description": (
            "Generate 2-3 inline quiz questions to test the learner's comprehension of a topic. "
            "Call this after explaining a difficult concept to verify understanding."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "The topic or concept to quiz on.",
                },
                "num_questions": {
                    "type": "integer",
                    "description": "Number of questions to generate (2 or 3).",
                    "minimum": 2,
                    "maximum": 3,
                },
                "difficulty": {
                    "type": "string",
                    "enum": ["easy", "medium", "hard"],
                    "description": "Difficulty level of the questions.",
                },
            },
            "required": ["topic", "num_questions", "difficulty"],
        },
    },
    {
        "name": "search_flashcards",
        "description": (
            "Find relevant flashcards for a concept or term to suggest review material. "
            "Call this when the learner needs to memorize specific terms or definitions."
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
                    "description": "Optional module UUID to filter flashcards by module.",
                },
            },
            "required": ["concept"],
        },
    },
    {
        "name": "save_learner_preference",
        "description": (
            "Store a detected learner preference or learning pattern. Call this when you detect "
            "a consistent pattern such as a preference for analogies over definitions, visual "
            "learning style, or a specific topic interest."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "preference_type": {
                    "type": "string",
                    "description": (
                        "Type of preference detected (e.g. 'learning_style', 'explanation_format', "
                        "'difficulty_preference', 'language_preference')."
                    ),
                },
                "value": {
                    "type": "string",
                    "description": "The detected preference value (e.g. 'analogies', 'visual', 'formal').",
                },
            },
            "required": ["preference_type", "value"],
        },
    },
]


class TutorToolExecutor:
    """Handles execution of tools registered for the agentic tutor."""

    def __init__(
        self,
        anthropic_client: AsyncAnthropic,
        semantic_retriever: SemanticRetriever,
        user_id: uuid.UUID,
        user_level: int,
        user_language: str,
        module_id: uuid.UUID | None,
        session: AsyncSession,
    ):
        self.anthropic = anthropic_client
        self.retriever = semantic_retriever
        self.user_id = user_id
        self.user_level = user_level
        self.user_language = user_language
        self.module_id = module_id
        self.session = session

    async def execute(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        """Dispatch a tool call to its handler and return JSON-serialised result."""
        logger.info(
            "Executing tutor tool",
            tool_name=tool_name,
            user_id=str(self.user_id),
            tool_input_keys=list(tool_input.keys()),
        )

        handlers: dict[str, Any] = {
            "search_knowledge_base": self._search_knowledge_base,
            "get_learner_progress": self._get_learner_progress,
            "generate_mini_quiz": self._generate_mini_quiz,
            "search_flashcards": self._search_flashcards,
            "save_learner_preference": self._save_learner_preference,
        }

        handler = handlers.get(tool_name)
        if handler is None:
            logger.warning("Unknown tool called", tool_name=tool_name)
            return json.dumps({"error": f"Unknown tool: {tool_name}"})

        try:
            result = await handler(**tool_input)
            return json.dumps(result, default=str)
        except Exception as e:
            logger.error("Tool execution failed", tool_name=tool_name, error=str(e))
            return json.dumps({"error": str(e)})

    async def _search_knowledge_base(
        self, query: str, module_id: str | None = None
    ) -> dict[str, Any]:
        """Execute search_knowledge_base tool via SemanticRetriever."""
        target_module_id: uuid.UUID | None = None
        books_sources: dict[str, Any] | None = None

        if module_id:
            try:
                target_module_id = uuid.UUID(module_id)
                from app.domain.models.module import Module

                module = await self.session.get(Module, target_module_id)
                if module:
                    books_sources = module.books_sources
            except (ValueError, Exception):
                target_module_id = self.module_id
        elif self.module_id:
            target_module_id = self.module_id
            from app.domain.models.module import Module

            module = await self.session.get(Module, target_module_id)
            if module:
                books_sources = module.books_sources

        results = await self.retriever.search_for_module(
            query=query,
            user_level=self.user_level,
            user_language=self.user_language,
            books_sources=books_sources,
            top_k=5,
            session=self.session,
        )

        chunks = [
            {
                "content": r.chunk.content,
                "source": r.chunk.source,
                "chapter": r.chunk.chapter,
                "page": r.chunk.page,
                "similarity": r.similarity_score,
            }
            for r in results
        ]

        logger.info(
            "search_knowledge_base completed",
            query=query[:50],
            results_count=len(chunks),
            user_id=str(self.user_id),
        )

        return {"query": query, "results": chunks, "total": len(chunks)}

    async def _get_learner_progress(self, user_id: str) -> dict[str, Any]:
        """Execute get_learner_progress tool — queries DB for user progress data."""
        try:
            uid = uuid.UUID(user_id)
        except ValueError:
            uid = self.user_id

        progress_query = select(UserModuleProgress).where(UserModuleProgress.user_id == uid)
        progress_result = await self.session.execute(progress_query)
        progress_rows = progress_result.scalars().all()

        completed_modules = [
            {
                "module_id": str(p.module_id),
                "status": p.status,
                "completion_pct": p.completion_pct,
                "quiz_score_avg": p.quiz_score_avg,
                "time_spent_minutes": p.time_spent_minutes,
            }
            for p in progress_rows
        ]

        quiz_query = (
            select(QuizAttempt)
            .where(QuizAttempt.user_id == uid)
            .order_by(QuizAttempt.attempted_at.desc())
            .limit(10)
        )
        quiz_result = await self.session.execute(quiz_query)
        quiz_rows = quiz_result.scalars().all()

        recent_quiz_scores = [
            {"quiz_id": str(q.quiz_id), "score": q.score, "attempted_at": str(q.attempted_at)}
            for q in quiz_rows
        ]

        placement_query = (
            select(PlacementTestAttempt)
            .where(PlacementTestAttempt.user_id == uid)
            .order_by(PlacementTestAttempt.attempted_at.desc())
            .limit(1)
        )
        placement_result = await self.session.execute(placement_query)
        placement = placement_result.scalar_one_or_none()

        weak_domains: list[str] = []
        if placement and placement.domain_scores:
            weak_domains = [
                domain
                for domain, score in placement.domain_scores.items()
                if isinstance(score, (int, float)) and score < 60
            ]

        avg_score: float | None = None
        if recent_quiz_scores:
            scores = [q["score"] for q in recent_quiz_scores if q["score"] is not None]
            if scores:
                avg_score = sum(scores) / len(scores)

        logger.info(
            "get_learner_progress completed",
            user_id=str(uid),
            modules_count=len(completed_modules),
            weak_domains_count=len(weak_domains),
        )

        return {
            "user_id": str(uid),
            "current_level": self.user_level,
            "completed_modules": completed_modules,
            "recent_quiz_scores": recent_quiz_scores,
            "average_quiz_score": avg_score,
            "weak_domains": weak_domains,
        }

    async def _generate_mini_quiz(
        self, topic: str, num_questions: int, difficulty: str
    ) -> dict[str, Any]:
        """Execute generate_mini_quiz tool — generates inline quiz via Claude."""
        num_questions = max(2, min(3, num_questions))

        lang_instruction = "en français" if self.user_language == "fr" else "in English"
        difficulty_map = {"easy": "facile", "medium": "moyen", "hard": "difficile"}
        diff_label = difficulty_map.get(difficulty, "moyen")

        prompt = (
            f"Génère exactement {num_questions} questions QCM à choix unique sur le sujet: "
            f'"{topic}". '
            f"Niveau de difficulté: {diff_label}. "
            f"Réponds {lang_instruction}. "
            "Format de réponse JSON strict:\n"
            '{"questions": [{"question": "...", "options": ["A) ...", "B) ...", "C) ...", "D) ..."], '
            '"correct": "A", "explanation": "..."}]}\n'
            "Ne fournis QUE le JSON, sans texte supplémentaire."
        )

        response = await self.anthropic.messages.create(
            model="claude-sonnet-4-6",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=800,
        )

        raw_text = ""
        for block in response.content:
            if hasattr(block, "text"):
                raw_text += block.text

        try:
            start = raw_text.find("{")
            end = raw_text.rfind("}") + 1
            if start >= 0 and end > start:
                quiz_data = json.loads(raw_text[start:end])
            else:
                quiz_data = {"questions": []}
        except json.JSONDecodeError:
            quiz_data = {"questions": []}

        logger.info(
            "generate_mini_quiz completed",
            topic=topic,
            num_questions=num_questions,
            generated_count=len(quiz_data.get("questions", [])),
        )

        return {
            "topic": topic,
            "difficulty": difficulty,
            "questions": quiz_data.get("questions", []),
        }

    async def _search_flashcards(
        self, concept: str, module_id: str | None = None
    ) -> dict[str, Any]:
        """Execute search_flashcards tool — queries generated_content for flashcards."""
        query = select(GeneratedContent).where(GeneratedContent.content_type == "flashcard")

        if module_id:
            try:
                mid = uuid.UUID(module_id)
                query = query.where(GeneratedContent.module_id == mid)
            except ValueError:
                if self.module_id:
                    query = query.where(GeneratedContent.module_id == self.module_id)
        elif self.module_id:
            query = query.where(GeneratedContent.module_id == self.module_id)

        query = query.where(GeneratedContent.language == self.user_language).limit(20)

        result = await self.session.execute(query)
        flashcards = result.scalars().all()

        concept_lower = concept.lower()
        matched = []
        for fc in flashcards:
            content = fc.content or {}
            term = str(content.get("term_fr", content.get("term_en", ""))).lower()
            definition = str(content.get("definition_fr", content.get("definition_en", ""))).lower()
            if concept_lower in term or concept_lower in definition:
                matched.append(
                    {
                        "id": str(fc.id),
                        "term": content.get("term_fr") or content.get("term_en", ""),
                        "definition": content.get("definition_fr")
                        or content.get("definition_en", ""),
                        "module_id": str(fc.module_id),
                    }
                )

        logger.info(
            "search_flashcards completed",
            concept=concept,
            total_flashcards=len(flashcards),
            matched_count=len(matched),
        )

        return {
            "concept": concept,
            "flashcards": matched[:5],
            "total_found": len(matched),
        }

    async def _save_learner_preference(self, preference_type: str, value: str) -> dict[str, Any]:
        """Execute save_learner_preference tool — upserts to learner_memory table."""
        existing_query = select(LearnerMemory).where(
            LearnerMemory.user_id == self.user_id,
            LearnerMemory.preference_type == preference_type,
        )
        result = await self.session.execute(existing_query)
        existing = result.scalar_one_or_none()

        if existing:
            existing.value = value
            self.session.add(existing)
        else:
            memory = LearnerMemory(
                id=uuid.uuid4(),
                user_id=self.user_id,
                preference_type=preference_type,
                value=value,
            )
            self.session.add(memory)

        await self.session.flush()

        logger.info(
            "save_learner_preference completed",
            user_id=str(self.user_id),
            preference_type=preference_type,
            value=value,
            action="updated" if existing else "created",
        )

        return {
            "saved": True,
            "preference_type": preference_type,
            "value": value,
            "action": "updated" if existing else "created",
        }
