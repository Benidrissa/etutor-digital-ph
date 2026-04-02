"""Service for AI tutor functionality with agentic tool_use loop."""

import uuid
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any

import structlog
from anthropic import AsyncAnthropic
from anthropic.types import MessageParam, ToolResultBlockParam, ToolUseBlock
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.prompts.tutor import TutorContext, get_activity_suggestions, get_socratic_system_prompt
from app.ai.rag.embeddings import EmbeddingService
from app.ai.rag.retriever import SemanticRetriever
from app.domain.models.conversation import TutorConversation
from app.domain.models.module import Module
from app.domain.models.user import User
from app.domain.services.tutor_tools import TOOL_DEFINITIONS, TutorToolExecutor
from app.infrastructure.config.settings import get_settings

logger = structlog.get_logger()

MAX_TOOL_CALLS = 3


class TutorService:
    """Service for managing AI tutor conversations with agentic tool_use."""

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
        Send a message to the AI tutor and stream the response.

        Uses Claude tool_use API with up to MAX_TOOL_CALLS tool invocations per message.

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

            user_msg: dict[str, Any] = {
                "role": "user",
                "content": message,
                "timestamp": datetime.utcnow().isoformat(),
            }
            conversation_history.append(user_msg)

            tool_executor = TutorToolExecutor(
                anthropic_client=self.anthropic,
                semantic_retriever=self.retriever,
                user_id=user_id,
                user_level=user.current_level,
                user_language=user.preferred_language,
                module_id=module_id,
                session=session,
            )

            api_messages: list[MessageParam] = [
                {"role": msg["role"], "content": msg["content"]} for msg in conversation_history
            ]

            full_response = ""
            tool_call_count = 0
            sources_cited: list[dict[str, Any]] = []
            activity_suggestions: list[dict[str, str]] = []

            while tool_call_count <= MAX_TOOL_CALLS:
                response = await self.anthropic.messages.create(
                    model="claude-sonnet-4-6",
                    system=system_prompt,
                    messages=api_messages,
                    tools=TOOL_DEFINITIONS,
                    max_tokens=1500,
                )

                tool_use_blocks: list[ToolUseBlock] = [
                    block for block in response.content if isinstance(block, ToolUseBlock)
                ]

                if not tool_use_blocks:
                    for block in response.content:
                        if hasattr(block, "text") and block.text:
                            full_response += block.text
                            yield {
                                "type": "content",
                                "data": {"text": block.text},
                                "conversation_id": str(conversation.id),
                            }
                    break

                if tool_call_count >= MAX_TOOL_CALLS:
                    logger.warning(
                        "Max tool calls reached, stopping loop",
                        user_id=str(user_id),
                        tool_call_count=tool_call_count,
                    )
                    for block in response.content:
                        if hasattr(block, "text") and block.text:
                            full_response += block.text
                            yield {
                                "type": "content",
                                "data": {"text": block.text},
                                "conversation_id": str(conversation.id),
                            }
                    break

                api_messages.append({"role": "assistant", "content": response.content})

                tool_results: list[ToolResultBlockParam] = []
                for tool_block in tool_use_blocks:
                    tool_call_count += 1
                    logger.info(
                        "Tool called by Claude",
                        tool_name=tool_block.name,
                        tool_id=tool_block.id,
                        user_id=str(user_id),
                        call_number=tool_call_count,
                    )

                    yield {
                        "type": "tool_call",
                        "data": {
                            "tool_name": tool_block.name,
                            "tool_id": tool_block.id,
                        },
                        "conversation_id": str(conversation.id),
                    }

                    result_content = await tool_executor.execute(
                        tool_block.name,
                        tool_block.input if isinstance(tool_block.input, dict) else {},
                    )

                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_block.id,
                            "content": result_content,
                        }
                    )

                api_messages.append({"role": "user", "content": tool_results})

            sources_cited = self._extract_sources_from_response(full_response, [])
            activity_suggestions = self._extract_activity_suggestions(
                full_response, context_type, user.current_level
            )

            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": full_response,
                "sources": sources_cited,
                "timestamp": datetime.utcnow().isoformat(),
                "activity_suggestions": activity_suggestions,
                "tool_calls_used": tool_call_count,
            }

            updated_messages = conversation.messages + [user_msg, assistant_msg]
            conversation.messages = updated_messages
            session.add(conversation)
            await session.commit()

            yield {
                "type": "sources_cited",
                "data": {"sources": sources_cited},
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
                    "tool_calls_used": tool_call_count,
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
        """Prepare conversation history for Claude API."""
        messages = (
            conversation.messages[-10:]
            if len(conversation.messages) > 10
            else conversation.messages
        )

        claude_messages = []
        for msg in messages:
            if msg.get("role") and msg.get("content"):
                claude_messages.append(
                    {
                        "role": msg["role"],
                        "content": msg["content"],
                    }
                )

        return claude_messages

    def _extract_sources_from_response(
        self, response: str, available_chunks: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Extract source citations from the tutor response."""
        sources = []

        for chunk in available_chunks:
            source_name = chunk.get("source", "")
            chapter = chunk.get("chapter")
            page = chunk.get("page")

            if source_name.lower() in response.lower():
                source_info: dict[str, Any] = {
                    "source": source_name,
                    "content_preview": chunk.get("content", "")[:100] + "...",
                    "similarity_score": chunk.get("similarity", 0),
                }
                if chapter:
                    source_info["chapter"] = chapter
                if page:
                    source_info["page"] = page

                sources.append(source_info)

        seen_sources: set[str] = set()
        unique_sources = []
        for source in sources:
            source_key = f"{source['source']}-{source.get('chapter', '')}-{source.get('page', '')}"
            if source_key not in seen_sources:
                seen_sources.add(source_key)
                unique_sources.append(source)

        return unique_sources[:5]

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
