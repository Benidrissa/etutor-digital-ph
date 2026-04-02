"""Service for AI tutor functionality with agentic tool_use and Socratic pedagogical approach."""

import asyncio
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any

import structlog
from anthropic import AsyncAnthropic
from anthropic.types import MessageParam, ToolResultBlockParam, ToolUseBlock
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.ai.prompts.tutor import (
    TutorContext,
    get_activity_suggestions,
    get_compaction_prompt,
    get_socratic_system_prompt,
)
from app.ai.rag.embeddings import EmbeddingService
from app.ai.rag.retriever import SemanticRetriever
from app.domain.models.conversation import TutorConversation
from app.domain.models.module import Module
from app.domain.models.user import User
from app.domain.services.tutor_tools import TOOL_DEFINITIONS, TutorToolExecutor
from app.infrastructure.config.settings import get_settings

logger = structlog.get_logger()

MAX_TOOL_CALLS = 3
COMPACT_TRIGGER = 20
COMPACT_KEEP_RECENT = 5
COMPACT_SUMMARIZE_UP_TO = 15


class TutorService:
    """Service for managing AI tutor conversations with agentic tool_use and Socratic approach."""

    def __init__(
        self,
        anthropic_client: AsyncAnthropic,
        semantic_retriever: SemanticRetriever,
        embedding_service: EmbeddingService,
    ):
        self.anthropic = anthropic_client
        self.retriever = semantic_retriever
        self.embedding_service = embedding_service
        self.settings = get_settings()
        self.daily_message_limit = 50

    async def send_message(
        self,
        user_id: str | uuid.UUID,
        message: str,
        session: AsyncSession,
        module_id: uuid.UUID | None = None,
        context_type: str | None = None,
        context_id: uuid.UUID | None = None,
        conversation_id: uuid.UUID | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        Send a message to the AI tutor and stream the response using agentic tool_use.

        Claude autonomously decides when to call tools (RAG search, progress lookup, etc.)
        The tool loop runs server-side; only text chunks are streamed to the client.

        Args:
            user_id: User ID
            message: User message
            session: Database session
            module_id: Optional module context
            context_type: Optional context type ("module", "lesson", "quiz")
            context_id: Optional context-specific ID
            conversation_id: Optional existing conversation ID

        Yields:
            Stream chunks with tutor response data
        """
        if isinstance(user_id, str):
            user_id = uuid.UUID(user_id)

        messages_used = await self._check_daily_limit(user_id, session)
        if messages_used >= self.daily_message_limit:
            yield {
                "type": "error",
                "data": {
                    "code": "limit_reached",
                    "message": "Daily message limit reached. Try again tomorrow.",
                    "limit_reached": True,
                },
            }
            return

        user = await session.get(User, user_id)
        if not user:
            yield {"type": "error", "data": {"message": "User not found"}}
            return

        try:
            conversation = await self._get_or_create_conversation(
                user_id, module_id, conversation_id, session
            )

            if not conversation_id and not conversation.compacted_context:
                prior_compact = await self._get_previous_compact(user_id, conversation.id, session)
                if prior_compact:
                    conversation.compacted_context = prior_compact
                    session.add(conversation)
                    await session.flush()

            yield {
                "type": "conversation_id",
                "data": {"conversation_id": str(conversation.id)},
            }

            context = TutorContext(
                user_level=user.current_level,
                user_language=user.preferred_language,
                user_country=user.country or "SN",
                module_id=str(module_id) if module_id else None,
                context_type=context_type,
                context_id=str(context_id) if context_id else None,
            )

            system_prompt = get_socratic_system_prompt(context, [])

            conversation_history = await self._prepare_conversation_history(conversation)

            user_msg_stored = {
                "role": "user",
                "content": message,
                "timestamp": datetime.utcnow().isoformat(),
            }
            conversation_history.append({"role": "user", "content": message})

            tool_executor = TutorToolExecutor(
                retriever=self.retriever,
                anthropic_client=self.anthropic,
                user_id=user_id,
                user_level=user.current_level,
                user_language=user.preferred_language,
            )

            tool_call_count = 0
            full_response = ""
            all_tool_calls: list[dict[str, Any]] = []
            sources_cited: list[dict[str, Any]] = []
            api_messages: list[MessageParam] = list(conversation_history)

            while tool_call_count <= MAX_TOOL_CALLS:
                response = await self.anthropic.messages.create(
                    model="claude-sonnet-4-6",
                    system=system_prompt,
                    messages=api_messages,
                    tools=TOOL_DEFINITIONS,
                    max_tokens=1500,
                    temperature=0.7,
                )

                tool_use_blocks = [
                    block for block in response.content if isinstance(block, ToolUseBlock)
                ]

                if not tool_use_blocks:
                    text_parts = [
                        block.text
                        for block in response.content
                        if hasattr(block, "text") and block.text
                    ]
                    full_response = "".join(text_parts)

                    for chunk_text in _split_into_chunks(full_response):
                        yield {
                            "type": "content",
                            "data": {"text": chunk_text},
                            "conversation_id": str(conversation.id),
                        }
                    break

                if tool_call_count >= MAX_TOOL_CALLS:
                    logger.warning(
                        "Max tool calls reached, forcing final response",
                        user_id=str(user_id),
                        tool_call_count=tool_call_count,
                    )
                    text_parts = [
                        block.text
                        for block in response.content
                        if hasattr(block, "text") and block.text
                    ]
                    full_response = "".join(text_parts)
                    if full_response:
                        for chunk_text in _split_into_chunks(full_response):
                            yield {
                                "type": "content",
                                "data": {"text": chunk_text},
                                "conversation_id": str(conversation.id),
                            }
                    break

                assistant_content: list[Any] = list(response.content)
                api_messages.append({"role": "assistant", "content": assistant_content})

                tool_results: list[ToolResultBlockParam] = []
                for tool_block in tool_use_blocks:
                    tool_call_count += 1

                    logger.info(
                        "Tutor tool call",
                        tool_name=tool_block.name,
                        tool_id=tool_block.id,
                        user_id=str(user_id),
                        call_number=tool_call_count,
                    )

                    yield {
                        "type": "tool_call",
                        "data": {
                            "tool_name": tool_block.name,
                            "call_number": tool_call_count,
                        },
                        "conversation_id": str(conversation.id),
                    }

                    tool_result_str = await tool_executor.execute(
                        tool_name=tool_block.name,
                        tool_input=tool_block.input,
                        session=session,
                    )

                    all_tool_calls.append(
                        {
                            "tool_name": tool_block.name,
                            "tool_id": tool_block.id,
                            "input": tool_block.input,
                            "result_preview": tool_result_str[:200],
                        }
                    )

                    if tool_block.name == "search_knowledge_base":
                        import json

                        try:
                            rag_result = json.loads(tool_result_str)
                            for chunk in rag_result.get("results", []):
                                source_info: dict[str, Any] = {
                                    "source": chunk.get("source", ""),
                                    "content_preview": chunk.get("content", "")[:100] + "...",
                                    "similarity_score": chunk.get("similarity", 0),
                                }
                                if chunk.get("chapter"):
                                    source_info["chapter"] = chunk["chapter"]
                                if chunk.get("page"):
                                    source_info["page"] = chunk["page"]
                                sources_cited.append(source_info)
                        except Exception:
                            pass

                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_block.id,
                            "content": tool_result_str,
                        }
                    )

                api_messages.append({"role": "user", "content": tool_results})

            unique_sources = _deduplicate_sources(sources_cited)

            activity_suggestions = self._extract_activity_suggestions(
                full_response, context_type, user.current_level
            )

            assistant_msg_stored = {
                "role": "assistant",
                "content": full_response,
                "sources": unique_sources,
                "timestamp": datetime.utcnow().isoformat(),
                "activity_suggestions": activity_suggestions,
                "tool_calls_count": tool_call_count,
            }

            updated_messages = conversation.messages + [user_msg_stored, assistant_msg_stored]
            conversation.messages = updated_messages
            conversation.message_count = len(updated_messages)
            session.add(conversation)
            await session.commit()

            if conversation.message_count > COMPACT_TRIGGER:
                asyncio.ensure_future(
                    self._compact_conversation_async(
                        conversation_id=conversation.id,
                        user_language=user.preferred_language,
                    )
                )

            yield {
                "type": "sources_retrieved",
                "data": {
                    "chunk_count": len(unique_sources),
                    "sources": [s.get("source", "") for s in unique_sources],
                },
                "conversation_id": str(conversation.id),
            }

            yield {
                "type": "sources_cited",
                "data": {"sources": unique_sources},
                "conversation_id": str(conversation.id),
            }

            yield {
                "type": "activity_suggestions",
                "data": {"suggestions": activity_suggestions},
                "conversation_id": str(conversation.id),
            }

            yield {
                "type": "finished",
                "data": {
                    "remaining_messages": self.daily_message_limit - messages_used - 1,
                    "conversation_id": str(conversation.id),
                    "tool_calls_made": tool_call_count,
                },
                "finished": True,
            }

        except Exception as e:
            logger.error("Error in tutor chat", error=str(e), user_id=str(user_id))
            yield {
                "type": "error",
                "data": {"code": "tutor_error", "message": "An error occurred. Please try again."},
            }

    async def get_conversation(
        self, user_id: str | uuid.UUID, conversation_id: uuid.UUID, session: AsyncSession
    ) -> dict[str, Any] | None:
        """Get a specific conversation."""
        if isinstance(user_id, str):
            user_id = uuid.UUID(user_id)

        query = select(TutorConversation).where(
            TutorConversation.id == conversation_id, TutorConversation.user_id == user_id
        )
        result = await session.execute(query)
        conversation = result.scalar_one_or_none()

        if not conversation:
            return None

        return {
            "id": conversation.id,
            "module_id": conversation.module_id,
            "messages": conversation.messages,
            "created_at": conversation.created_at,
        }

    async def list_conversations(
        self, user_id: str | uuid.UUID, session: AsyncSession, limit: int = 20, offset: int = 0
    ) -> dict[str, Any]:
        """List user's tutor conversations."""
        if isinstance(user_id, str):
            user_id = uuid.UUID(user_id)

        query = (
            select(TutorConversation)
            .where(TutorConversation.user_id == user_id)
            .order_by(TutorConversation.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(query)
        conversations = result.scalars().all()

        count_query = select(func.count(TutorConversation.id)).where(
            TutorConversation.user_id == user_id
        )
        count_result = await session.execute(count_query)
        total = count_result.scalar() or 0

        summaries = []
        for conv in conversations:
            preview = ""
            if conv.messages and len(conv.messages) > 0:
                first_user_msg = next(
                    (msg for msg in conv.messages if msg.get("role") == "user"), None
                )
                if first_user_msg:
                    preview = first_user_msg.get("content", "")[:50] + "..."

            last_message_at = conv.created_at
            if conv.messages:
                try:
                    last_ts = conv.messages[-1].get("timestamp")
                    if last_ts:
                        last_message_at = datetime.fromisoformat(last_ts)
                except (ValueError, TypeError):
                    pass

            summaries.append(
                {
                    "id": conv.id,
                    "module_id": conv.module_id,
                    "message_count": len(conv.messages),
                    "last_message_at": last_message_at,
                    "preview": preview,
                }
            )

        return {"conversations": summaries, "total": total}

    async def get_tutor_stats(
        self, user_id: str | uuid.UUID, session: AsyncSession
    ) -> dict[str, Any]:
        """Get tutor usage statistics for a user."""
        if isinstance(user_id, str):
            user_id = uuid.UUID(user_id)

        daily_messages = await self._check_daily_limit(user_id, session)

        count_query = select(func.count(TutorConversation.id)).where(
            TutorConversation.user_id == user_id
        )
        count_result = await session.execute(count_query)
        total_conversations = count_result.scalar() or 0

        most_discussed_topics: list[Any] = []

        return {
            "daily_messages_used": daily_messages,
            "daily_messages_limit": self.daily_message_limit,
            "total_conversations": total_conversations,
            "most_discussed_topics": most_discussed_topics,
        }

    async def _check_daily_limit(self, user_id: str | uuid.UUID, session: AsyncSession) -> int:
        """Check how many messages user has sent today."""
        if isinstance(user_id, str):
            user_id = uuid.UUID(user_id)

        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

        query = select(TutorConversation).where(
            TutorConversation.user_id == user_id,
            TutorConversation.created_at >= today_start,
        )
        result = await session.execute(query)
        conversations = result.scalars().all()

        message_count = 0
        for conv in conversations:
            user_messages = [msg for msg in conv.messages if msg.get("role") == "user"]
            message_count += len(user_messages)

        return message_count

    async def _get_or_create_conversation(
        self,
        user_id: str | uuid.UUID,
        module_id: uuid.UUID | None,
        conversation_id: uuid.UUID | None,
        session: AsyncSession,
    ) -> TutorConversation:
        """Get existing conversation or create a new one."""
        if isinstance(user_id, str):
            user_id = uuid.UUID(user_id)

        if conversation_id:
            query = select(TutorConversation).where(
                TutorConversation.id == conversation_id,
                TutorConversation.user_id == user_id,
            )
            result = await session.execute(query)
            conversation = result.scalar_one_or_none()
            if conversation:
                return conversation

        conversation = TutorConversation(
            id=uuid.uuid4(),
            user_id=user_id,
            module_id=module_id,
            messages=[],
            created_at=datetime.utcnow(),
        )
        session.add(conversation)
        await session.flush()

        return conversation

    async def _retrieve_relevant_context(
        self, query: str, user: User, module_id: uuid.UUID | None, session: AsyncSession
    ) -> list[Any]:
        """Retrieve relevant context using RAG (kept for backward compatibility)."""
        books_sources = None
        if module_id:
            module = await session.get(Module, module_id)
            if module:
                books_sources = module.books_sources

        search_results = await self.retriever.search_for_module(
            query=query,
            user_level=user.current_level,
            user_language=user.preferred_language,
            books_sources=books_sources,
            top_k=8,
            session=session,
        )

        logger.info(
            "RAG retrieval completed",
            user_id=str(user.id),
            query_length=len(query),
            results_count=len(search_results),
            module_id=str(module_id) if module_id else None,
        )

        return search_results

    async def _prepare_conversation_history(
        self, conversation: TutorConversation
    ) -> list[dict[str, str]]:
        """Prepare conversation history for Claude API.

        If compacted_context exists, prepend it as a system note then include the
        most recent COMPACT_KEEP_RECENT messages verbatim.  Otherwise fall back to
        the last 10 messages (pre-compaction behaviour).
        """
        recent_messages = conversation.messages[-COMPACT_KEEP_RECENT:]

        claude_messages: list[dict[str, str]] = []

        if conversation.compacted_context:
            claude_messages.append({"role": "user", "content": conversation.compacted_context})
            claude_messages.append(
                {
                    "role": "assistant",
                    "content": "Compris. Je vais tenir compte de ce contexte pour la suite.",
                }
            )
        else:
            recent_messages = (
                conversation.messages[-10:]
                if len(conversation.messages) > 10
                else conversation.messages
            )

        for msg in recent_messages:
            if msg.get("role") and msg.get("content"):
                claude_messages.append(
                    {
                        "role": msg["role"],
                        "content": msg["content"],
                    }
                )

        return claude_messages

    async def _compact_conversation_async(
        self,
        conversation_id: uuid.UUID,
        user_language: str,
    ) -> None:
        """Summarize old messages into compacted_context in its own DB session.

        Runs asynchronously (fire-and-forget) so it never blocks the response stream.
        Summarizes messages[0:COMPACT_SUMMARIZE_UP_TO], keeps messages[COMPACT_SUMMARIZE_UP_TO:]
        verbatim in the messages list.
        """
        try:
            engine = create_async_engine(self.settings.database_url, echo=False)
            session_factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )
            async with session_factory() as session:
                result = await session.execute(
                    select(TutorConversation).where(TutorConversation.id == conversation_id)
                )
                conversation = result.scalar_one_or_none()
                if not conversation:
                    return

                messages_to_compact = conversation.messages[:COMPACT_SUMMARIZE_UP_TO]
                messages_to_keep = conversation.messages[COMPACT_SUMMARIZE_UP_TO:]

                if not messages_to_compact:
                    return

                prompt = get_compaction_prompt(
                    messages=messages_to_compact,
                    existing_compact=conversation.compacted_context,
                    language=user_language,
                )

                compact_response = await self.anthropic.messages.create(
                    model="claude-sonnet-4-6",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=600,
                    temperature=0.3,
                )

                compact_text_parts = [
                    block.text
                    for block in compact_response.content
                    if hasattr(block, "text") and block.text
                ]
                new_compact = "".join(compact_text_parts).strip()

                conversation.compacted_context = new_compact
                conversation.compacted_at = datetime.utcnow()
                conversation.messages = messages_to_keep
                conversation.message_count = len(messages_to_keep)
                session.add(conversation)
                await session.commit()

                logger.info(
                    "Conversation compacted",
                    conversation_id=str(conversation_id),
                    messages_summarized=len(messages_to_compact),
                    messages_kept=len(messages_to_keep),
                    compact_length=len(new_compact),
                )
        except Exception:
            logger.exception("Failed to compact conversation", conversation_id=str(conversation_id))
        finally:
            import contextlib

            async with contextlib.AsyncExitStack():
                with contextlib.suppress(Exception):
                    await engine.dispose()

    async def _get_previous_compact(
        self, user_id: uuid.UUID, current_conversation_id: uuid.UUID, session: AsyncSession
    ) -> str | None:
        """Return the compacted_context from the most recent prior conversation (cross-session)."""
        result = await session.execute(
            select(TutorConversation)
            .where(
                TutorConversation.user_id == user_id,
                TutorConversation.id != current_conversation_id,
                TutorConversation.compacted_context.isnot(None),
            )
            .order_by(TutorConversation.created_at.desc())
            .limit(1)
        )
        prev = result.scalar_one_or_none()
        return prev.compacted_context if prev else None

    def _extract_activity_suggestions(
        self, response: str, context_type: str | None, user_level: int
    ) -> list[dict[str, str]]:
        """Extract activity suggestions from the response or generate them."""
        health_topics = [
            "surveillance",
            "épidémiologie",
            "biostatistics",
            "paludisme",
            "santé publique",
            "vaccination",
            "nutrition",
            "hygiène",
        ]

        topic = "santé publique"
        for health_topic in health_topics:
            if health_topic in response.lower():
                topic = health_topic
                break

        return get_activity_suggestions(context_type, user_level, topic)


def _split_into_chunks(text: str, chunk_size: int = 50) -> list[str]:
    """Split text into smaller chunks for streaming simulation."""
    if not text:
        return []
    chunks = []
    for i in range(0, len(text), chunk_size):
        chunks.append(text[i : i + chunk_size])
    return chunks


def _deduplicate_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove duplicate sources by source+chapter+page."""
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for source in sources:
        key = f"{source.get('source', '')}-{source.get('chapter', '')}-{source.get('page', '')}"
        if key not in seen:
            seen.add(key)
            unique.append(source)
    return unique[:5]
