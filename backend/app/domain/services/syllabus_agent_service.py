"""Syllabus creator/editor agent service.

Implements the admin AI agent that creates and edits curriculum modules using
Claude tool_use. The agent is equipped with 4 tools:
  - get_existing_modules
  - get_book_chapters
  - search_knowledge_base
  - save_module_draft
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

import structlog
from anthropic import AsyncAnthropic
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.prompts.syllabus_agent import get_syllabus_agent_system_prompt, get_tool_definitions
from app.ai.rag.embeddings import EmbeddingService
from app.ai.rag.retriever import SemanticRetriever
from app.domain.models.module import Module

logger = structlog.get_logger()

_BOOK_CHAPTERS: dict[str, list[dict[str, str]]] = {
    "donaldson": [
        {"chapter": "1", "title": "Introduction to Community Health"},
        {"chapter": "2", "title": "Epidemiology: The Basic Science of Public Health"},
        {"chapter": "3", "title": "Demography and Health"},
        {"chapter": "4", "title": "Communicable Diseases"},
        {"chapter": "5", "title": "Noncommunicable and Chronic Diseases"},
        {"chapter": "6", "title": "Environmental Health"},
        {"chapter": "7", "title": "Community Health and the Health Care System"},
        {"chapter": "8", "title": "International Health"},
    ],
    "gordis": [
        {"chapter": "1", "title": "Introduction to Epidemiology"},
        {"chapter": "2", "title": "The Dynamics of Disease Transmission"},
        {"chapter": "3", "title": "Measuring the Occurrence of Disease"},
        {"chapter": "4", "title": "Assessing the Validity and Reliability of Diagnostic Tests"},
        {"chapter": "5", "title": "Randomized Trials"},
        {"chapter": "6", "title": "Cohort Studies"},
        {"chapter": "7", "title": "Case-Control and Other Study Designs"},
        {"chapter": "8", "title": "From Association to Causation"},
        {"chapter": "9", "title": "Using Epidemiology to Evaluate Health Services"},
        {"chapter": "10", "title": "Epidemiology and Public Policy"},
    ],
    "triola": [
        {"chapter": "1", "title": "Introduction to Statistics"},
        {"chapter": "2", "title": "Summarizing and Graphing Data"},
        {"chapter": "3", "title": "Statistics for Describing, Exploring, and Comparing Data"},
        {"chapter": "4", "title": "Probability"},
        {"chapter": "5", "title": "Discrete Probability Distributions"},
        {"chapter": "6", "title": "Normal Probability Distributions"},
        {"chapter": "7", "title": "Estimating Parameters and Determining Sample Sizes"},
        {"chapter": "8", "title": "Hypothesis Testing"},
        {"chapter": "9", "title": "Inferences from Two Samples"},
        {"chapter": "10", "title": "Correlation and Regression"},
        {"chapter": "11", "title": "Goodness-of-Fit and Contingency Tables"},
    ],
}


class SyllabusAgentService:
    """Service for the admin syllabus creator/editor agent."""

    def __init__(
        self,
        anthropic_client: AsyncAnthropic,
        semantic_retriever: SemanticRetriever,
        embedding_service: EmbeddingService,
    ) -> None:
        self._client = anthropic_client
        self._retriever = semantic_retriever
        self._embedding_service = embedding_service
        self._system_prompt = get_syllabus_agent_system_prompt()
        self._tools = get_tool_definitions()

    async def stream_agent_response(
        self,
        admin_id: str,
        admin_email: str,
        message: str,
        session: AsyncSession,
        module_id: uuid.UUID | None = None,
        conversation_history: list[dict[str, Any]] | None = None,
    ) -> AsyncGenerator[str, None]:
        """Stream the agent response as SSE chunks.

        Args:
            admin_id: ID of the admin user
            admin_email: Email of the admin user
            message: Admin's message/request
            session: DB session
            module_id: Optional existing module ID for editing
            conversation_history: Previous conversation turns

        Yields:
            JSON-encoded SSE data strings
        """
        history = list(conversation_history or [])
        history.append({"role": "user", "content": message})

        logger.info(
            "Syllabus agent request",
            admin_id=admin_id,
            message_length=len(message),
            module_id=str(module_id) if module_id else None,
        )

        try:
            async for chunk in self._run_agent_loop(
                admin_id=admin_id,
                admin_email=admin_email,
                messages=history,
                session=session,
                module_id=module_id,
            ):
                yield chunk
        except Exception as e:
            logger.error("Syllabus agent error", error=str(e), admin_id=admin_id)
            yield f"data: {json.dumps({'type': 'error', 'data': {'message': str(e)}})}\n\n"

    async def _run_agent_loop(
        self,
        admin_id: str,
        admin_email: str,
        messages: list[dict[str, Any]],
        session: AsyncSession,
        module_id: uuid.UUID | None,
    ) -> AsyncGenerator[str, None]:
        """Run the Claude tool_use agent loop."""
        max_iterations = 5

        for _ in range(max_iterations):
            response = await self._client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=8192,
                system=self._system_prompt,
                tools=self._tools,
                messages=messages,
            )

            if response.stop_reason == "tool_use":
                tool_results = []
                tool_use_blocks = []

                for block in response.content:
                    if block.type == "text" and block.text.strip():
                        yield f"data: {json.dumps({'type': 'content', 'data': {'text': block.text}})}\n\n"
                    elif block.type == "tool_use":
                        tool_use_blocks.append(block)
                        tool_result = await self._execute_tool(
                            tool_name=block.name,
                            tool_input=block.input,
                            admin_id=admin_id,
                            admin_email=admin_email,
                            session=session,
                            module_id=module_id,
                        )
                        yield f"data: {json.dumps({'type': 'tool_call', 'data': {'tool': block.name, 'result_summary': self._summarize_tool_result(block.name, tool_result)}})}\n\n"
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": json.dumps(tool_result),
                            }
                        )

                messages = [
                    *messages,
                    {"role": "assistant", "content": response.content},
                    {"role": "user", "content": tool_results},
                ]

            else:
                full_text = ""
                for block in response.content:
                    if hasattr(block, "text"):
                        full_text += block.text

                yield f"data: {json.dumps({'type': 'content', 'data': {'text': full_text}})}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'data': {}})}\n\n"
                return

        yield f"data: {json.dumps({'type': 'done', 'data': {}})}\n\n"

    def _summarize_tool_result(self, tool_name: str, result: Any) -> str:
        """Return a brief human-readable summary of a tool result."""
        if tool_name == "get_existing_modules":
            count = len(result) if isinstance(result, list) else 0
            return f"{count} modules found"
        if tool_name == "get_book_chapters":
            count = len(result) if isinstance(result, list) else 0
            return f"{count} chapters found"
        if tool_name == "search_knowledge_base":
            count = len(result) if isinstance(result, list) else 0
            return f"{count} relevant passages found"
        if tool_name == "save_module_draft":
            return result.get("message", "Module saved") if isinstance(result, dict) else "Saved"
        return "OK"

    async def _execute_tool(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        admin_id: str,
        admin_email: str,
        session: AsyncSession,
        module_id: uuid.UUID | None,
    ) -> Any:
        """Dispatch tool calls to the appropriate handler."""
        handlers = {
            "get_existing_modules": self._tool_get_existing_modules,
            "get_book_chapters": self._tool_get_book_chapters,
            "search_knowledge_base": self._tool_search_knowledge_base,
            "save_module_draft": self._tool_save_module_draft,
        }
        handler = handlers.get(tool_name)
        if not handler:
            return {"error": f"Unknown tool: {tool_name}"}
        try:
            if tool_name == "save_module_draft":
                return await handler(
                    tool_input,
                    admin_id=admin_id,
                    admin_email=admin_email,
                    session=session,
                    existing_module_id=module_id,
                )
            elif tool_name == "search_knowledge_base":
                return await handler(tool_input, session=session)
            elif tool_name in ("get_existing_modules",):
                return await handler(session=session)
            else:
                return await handler(tool_input)
        except Exception as e:
            logger.error("Tool execution error", tool=tool_name, error=str(e))
            return {"error": str(e)}

    async def _tool_get_existing_modules(self, session: AsyncSession) -> list[dict]:
        """Return a list of existing modules (number, level, title)."""
        result = await session.execute(
            select(Module.module_number, Module.level, Module.title_fr, Module.title_en).order_by(
                Module.module_number
            )
        )
        rows = result.fetchall()
        return [
            {
                "module_number": r.module_number,
                "level": r.level,
                "title_fr": r.title_fr,
                "title_en": r.title_en,
            }
            for r in rows
        ]

    async def _tool_get_book_chapters(self, tool_input: dict) -> list[dict]:
        """Return chapters for a reference book."""
        book_name = tool_input.get("book_name", "").lower()
        return _BOOK_CHAPTERS.get(book_name, [])

    async def _tool_search_knowledge_base(
        self, tool_input: dict, session: AsyncSession
    ) -> list[dict]:
        """Search the RAG knowledge base for relevant content."""
        query = tool_input.get("query", "")
        if not query:
            return []
        try:
            results = await self._retriever.retrieve(query=query, session=session, top_k=5)
            return [
                {
                    "content": r.chunk.content[:500] if hasattr(r, "chunk") else str(r)[:500],
                    "source": r.chunk.source if hasattr(r, "chunk") else "unknown",
                    "chapter": getattr(r.chunk, "chapter", None) if hasattr(r, "chunk") else None,
                    "page": getattr(r.chunk, "page", None) if hasattr(r, "chunk") else None,
                    "score": round(r.score, 3) if hasattr(r, "score") else 0,
                }
                for r in results
            ]
        except Exception as e:
            logger.warning("Knowledge base search failed", error=str(e))
            return []

    async def _tool_save_module_draft(
        self,
        tool_input: dict,
        admin_id: str,
        admin_email: str,
        session: AsyncSession,
        existing_module_id: uuid.UUID | None,
    ) -> dict:
        """Save or update a module draft in the database."""
        module_data = tool_input.get("module_data", {})
        if not module_data:
            return {"error": "module_data is required"}

        books_sources: dict[str, Any] = {}
        activities = module_data.get("activities", {})

        existing: Module | None = None
        if existing_module_id:
            result = await session.execute(select(Module).where(Module.id == existing_module_id))
            existing = result.scalar_one_or_none()

        if existing:
            existing.level = module_data.get("level", existing.level)
            existing.title_fr = module_data.get("title_fr", existing.title_fr)
            existing.title_en = module_data.get("title_en", existing.title_en)
            existing.description_fr = module_data.get("description_fr", existing.description_fr)
            existing.description_en = module_data.get("description_en", existing.description_en)
            existing.estimated_hours = module_data.get("estimated_hours", existing.estimated_hours)
            existing.bloom_level = module_data.get("bloom_level", existing.bloom_level)
            existing.books_sources = {
                **(existing.books_sources or {}),
                "objectives_fr": module_data.get("objectives_fr", []),
                "objectives_en": module_data.get("objectives_en", []),
                "key_contents_fr": module_data.get("key_contents_fr", []),
                "key_contents_en": module_data.get("key_contents_en", []),
                "aof_context_fr": module_data.get("aof_context_fr", ""),
                "aof_context_en": module_data.get("aof_context_en", ""),
                "activities": activities,
                "source_references": module_data.get("source_references", []),
            }
            await session.flush()
            module_id = existing.id
            module_number = existing.module_number
            created = False
        else:
            module_number = module_data.get("module_number")
            if module_number is None:
                result = await session.execute(
                    text("SELECT COALESCE(MAX(module_number), 0) + 1 FROM modules")
                )
                module_number = result.scalar() or 16

            books_sources = {
                "objectives_fr": module_data.get("objectives_fr", []),
                "objectives_en": module_data.get("objectives_en", []),
                "key_contents_fr": module_data.get("key_contents_fr", []),
                "key_contents_en": module_data.get("key_contents_en", []),
                "aof_context_fr": module_data.get("aof_context_fr", ""),
                "aof_context_en": module_data.get("aof_context_en", ""),
                "activities": activities,
                "source_references": module_data.get("source_references", []),
            }
            new_module = Module(
                id=uuid.uuid4(),
                module_number=module_number,
                level=module_data.get("level", 1),
                title_fr=module_data.get("title_fr", ""),
                title_en=module_data.get("title_en", ""),
                description_fr=module_data.get("description_fr"),
                description_en=module_data.get("description_en"),
                estimated_hours=module_data.get("estimated_hours", 20),
                bloom_level=module_data.get("bloom_level"),
                books_sources=books_sources,
            )
            session.add(new_module)
            await session.flush()
            module_id = new_module.id
            created = True

        await self._write_audit_log(
            session=session,
            admin_id=admin_id,
            admin_email=admin_email,
            action="create" if created else "update",
            module_id=module_id,
            module_number=module_number,
            changes=module_data,
        )
        await session.commit()

        return {
            "id": str(module_id),
            "module_number": module_number,
            "created": created,
            "message": f"Module M{module_number:02d} {'created' if created else 'updated'} successfully",
        }

    async def _write_audit_log(
        self,
        session: AsyncSession,
        admin_id: str,
        admin_email: str,
        action: str,
        module_id: uuid.UUID,
        module_number: int,
        changes: dict,
    ) -> None:
        """Write an entry to the admin_syllabus_audit_log table."""
        try:
            await session.execute(
                text(
                    """
                    INSERT INTO admin_syllabus_audit_log
                        (id, admin_id, admin_email, action, module_id, module_number, changes, created_at)
                    VALUES
                        (:id, :admin_id, :admin_email, :action, :module_id, :module_number, :changes::jsonb, :created_at)
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "admin_id": admin_id,
                    "admin_email": admin_email,
                    "action": action,
                    "module_id": str(module_id),
                    "module_number": module_number,
                    "changes": json.dumps(changes),
                    "created_at": datetime.now(UTC).isoformat(),
                },
            )
        except Exception as e:
            logger.warning("Audit log write failed (non-fatal)", error=str(e))

    async def get_modules_list(self, session: AsyncSession) -> list[dict]:
        """Return module list for the admin syllabus view."""
        result = await session.execute(select(Module).order_by(Module.module_number))
        modules = result.scalars().all()
        out = []
        for m in modules:
            books = m.books_sources or {}
            sources = books.get("source_references", [])
            unit_count = len([u for u in (m.units if hasattr(m, "units") else [])])
            out.append(
                {
                    "id": str(m.id),
                    "module_number": m.module_number,
                    "level": m.level,
                    "title_fr": m.title_fr,
                    "title_en": m.title_en,
                    "description_fr": m.description_fr,
                    "description_en": m.description_en,
                    "estimated_hours": m.estimated_hours,
                    "bloom_level": m.bloom_level,
                    "unit_count": unit_count,
                    "source_references": sources,
                }
            )
        return out

    async def export_module_as_markdown(self, module_id: uuid.UUID, session: AsyncSession) -> str:
        """Export a module as Markdown in the canonical syllabus format."""
        result = await session.execute(select(Module).where(Module.id == module_id))
        module = result.scalar_one_or_none()
        if not module:
            return ""

        books = module.books_sources or {}
        objectives_fr = books.get("objectives_fr", [])
        objectives_en = books.get("objectives_en", [])
        key_contents_fr = books.get("key_contents_fr", [])
        key_contents_en = books.get("key_contents_en", [])
        aof_fr = books.get("aof_context_fr", "")
        aof_en = books.get("aof_context_en", "")
        activities = books.get("activities", {})
        source_refs = books.get("source_references", [])

        lines = [
            f"## Module M{module.module_number:02d} — {module.title_fr} / {module.title_en}",
            "",
            f"**Niveau :** {module.level} | **Bloom :** {module.bloom_level or 'N/A'} | **Durée estimée :** {module.estimated_hours}h",
            "",
            "### Description",
            f"**FR :** {module.description_fr or ''}",
            f"**EN :** {module.description_en or ''}",
            "",
            "### Objectifs d'apprentissage / Learning Objectives",
        ]
        for i, (obj_fr, obj_en) in enumerate(
            zip(objectives_fr, objectives_en, strict=False), start=1
        ):
            lines.append(f"{i}. {obj_fr} / {obj_en}")
        lines += [
            "",
            "### Contenus clés / Key Contents",
        ]
        for cf, ce in zip(key_contents_fr, key_contents_en, strict=False):
            lines.append(f"- {cf} / {ce}")
        lines += [
            "",
            "### Contextualisation AOF",
            f"**FR :** {aof_fr}",
            f"**EN :** {aof_en}",
            "",
            "### Activités pédagogiques",
            f"- Quiz : {', '.join(activities.get('quiz_topics', []))}",
            f"- Flashcards : {activities.get('flashcard_count', 20)}",
            f"- Étude de cas : {activities.get('case_study_scenario', '')}",
            "",
            "### Références",
        ]
        for ref in source_refs:
            lines.append(f"- {ref}")
        return "\n".join(lines)
