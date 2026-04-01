"""Service for AI tutor functionality with Socratic pedagogical approach."""

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

import structlog
from anthropic import AsyncAnthropic
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.prompts.tutor import TutorContext, get_activity_suggestions, get_socratic_system_prompt
from app.ai.rag.embeddings import EmbeddingService
from app.ai.rag.retriever import SemanticRetriever
from app.domain.models.conversation import TutorConversation
from app.domain.models.module import Module
from app.domain.models.user import User
from app.infrastructure.config.settings import get_settings

logger = structlog.get_logger()


class TutorService:
    """Service for managing AI tutor conversations with Socratic approach."""

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
        self.daily_message_limit = 50  # Free tier limit

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
        # Convert user_id to UUID if it's a string
        if isinstance(user_id, str):
            user_id = uuid.UUID(user_id)

        # Check daily message limit
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

        # Get user context
        user = await session.get(User, user_id)
        if not user:
            yield {"type": "error", "data": {"message": "User not found"}}
            return

        try:
            # Get or create conversation
            conversation = await self._get_or_create_conversation(
                user_id, module_id, conversation_id, session
            )

            yield {
                "type": "conversation_id",
                "data": {"conversation_id": str(conversation.id)},
            }

            # Build context
            context = TutorContext(
                user_level=user.current_level,
                user_language=user.preferred_language,
                user_country=user.country,
                module_id=str(module_id) if module_id else None,
                context_type=context_type,
                context_id=str(context_id) if context_id else None,
            )

            # Perform RAG retrieval
            rag_chunks = await self._retrieve_relevant_context(message, user, module_id, session)

            yield {
                "type": "sources_retrieved",
                "data": {
                    "chunk_count": len(rag_chunks),
                    "sources": [chunk.chunk.source for chunk in rag_chunks],
                },
            }

            # Generate system prompt
            chunks_dict = [
                {
                    "content": chunk.chunk.content,
                    "source": chunk.chunk.source,
                    "chapter": chunk.chunk.chapter,
                    "page": chunk.chunk.page,
                    "similarity": chunk.similarity_score,
                }
                for chunk in rag_chunks
            ]

            system_prompt = get_socratic_system_prompt(context, chunks_dict)

            # Prepare conversation history
            conversation_history = await self._prepare_conversation_history(conversation)

            # Add user message
            user_msg = {
                "role": "user",
                "content": message,
                "timestamp": datetime.now(UTC).isoformat(),
            }
            conversation_history.append(user_msg)

            # Stream Claude response
            full_response = ""
            sources_cited = []
            activity_suggestions = []

            async with self.anthropic.messages.stream(
                model="claude-sonnet-4-6",
                system=system_prompt,
                messages=[
                    {"role": msg["role"], "content": msg["content"]} for msg in conversation_history
                ],
                max_tokens=1000,
                temperature=0.7,
            ) as stream:
                async for event in stream:
                    if event.type == "content_block_delta" and hasattr(event.delta, "text"):
                        chunk_text = event.delta.text
                        full_response += chunk_text
                        yield {
                            "type": "content",
                            "data": {"text": chunk_text},
                            "conversation_id": str(conversation.id),
                        }

            # Extract sources and activity suggestions from response
            sources_cited = self._extract_sources_from_response(full_response, chunks_dict)
            activity_suggestions = self._extract_activity_suggestions(
                full_response, context_type, user.current_level
            )

            # Save messages to conversation
            assistant_msg = {
                "role": "assistant",
                "content": full_response,
                "sources": sources_cited,
                "timestamp": datetime.now(UTC).isoformat(),
                "activity_suggestions": activity_suggestions,
            }

            # Update conversation
            updated_messages = conversation.messages + [user_msg, assistant_msg]
            conversation.messages = updated_messages
            session.add(conversation)
            await session.commit()

            # Send final metadata
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
        # Convert user_id to UUID if it's a string
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
        # Convert user_id to UUID if it's a string
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

        # Count total conversations
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
        # Convert user_id to UUID if it's a string
        if isinstance(user_id, str):
            user_id = uuid.UUID(user_id)

        # Count daily messages
        daily_messages = await self._check_daily_limit(user_id, session)

        # Count total conversations
        count_query = select(func.count(TutorConversation.id)).where(
            TutorConversation.user_id == user_id
        )
        count_result = await session.execute(count_query)
        total_conversations = count_result.scalar() or 0

        # For now, return basic stats
        # TODO: Implement topic extraction and frequency analysis
        most_discussed_topics = []

        return {
            "daily_messages_used": daily_messages,
            "daily_messages_limit": self.daily_message_limit,
            "total_conversations": total_conversations,
            "most_discussed_topics": most_discussed_topics,
        }

    async def _check_daily_limit(self, user_id: str | uuid.UUID, session: AsyncSession) -> int:
        """Check how many messages user has sent today."""
        # Convert user_id to UUID if it's a string
        if isinstance(user_id, str):
            user_id = uuid.UUID(user_id)

        today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)

        query = select(TutorConversation).where(
            TutorConversation.user_id == user_id,
            TutorConversation.created_at >= today_start,
        )
        result = await session.execute(query)
        conversations = result.scalars().all()

        message_count = 0
        for conv in conversations:
            # Count user messages only
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
        # Convert user_id to UUID if it's a string
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

        # Create new conversation
        conversation = TutorConversation(
            id=uuid.uuid4(),
            user_id=user_id,
            module_id=module_id,
            messages=[],
            created_at=datetime.now(UTC),
        )
        session.add(conversation)
        await session.flush()  # Get the ID

        return conversation

    async def _retrieve_relevant_context(
        self, query: str, user: User, module_id: uuid.UUID | None, session: AsyncSession
    ) -> list[Any]:
        """Retrieve relevant context using RAG."""
        # Get module context if available
        books_sources = None
        if module_id:
            module = await session.get(Module, module_id)
            if module:
                books_sources = module.books_sources

        # Search for relevant chunks
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
        # Limit to last 10 messages to stay within context limits
        messages = (
            conversation.messages[-10:]
            if len(conversation.messages) > 10
            else conversation.messages
        )

        # Convert to Claude format (role and content only)
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

        # Look for citation patterns in the response
        for chunk in available_chunks:
            source_name = chunk.get("source", "")
            chapter = chunk.get("chapter")
            page = chunk.get("page")

            # Simple matching - look for source name in response
            if source_name.lower() in response.lower():
                source_info = {
                    "source": source_name,
                    "content_preview": chunk.get("content", "")[:100] + "...",
                    "similarity_score": chunk.get("similarity", 0),
                }
                if chapter:
                    source_info["chapter"] = chapter
                if page:
                    source_info["page"] = page

                sources.append(source_info)

        # Remove duplicates based on source name
        seen_sources = set()
        unique_sources = []
        for source in sources:
            source_key = f"{source['source']}-{source.get('chapter', '')}-{source.get('page', '')}"
            if source_key not in seen_sources:
                seen_sources.add(source_key)
                unique_sources.append(source)

        return unique_sources[:5]  # Limit to 5 sources

    def _extract_activity_suggestions(
        self, response: str, context_type: str | None, user_level: int
    ) -> list[dict[str, str]]:
        """Extract activity suggestions from the response or generate them."""
        # For now, generate basic suggestions
        # TODO: Implement NLP to extract suggestions from response

        # Look for key health topics
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

        topic = "santé publique"  # default
        for health_topic in health_topics:
            if health_topic in response.lower():
                topic = health_topic
                break

        return get_activity_suggestions(context_type, user_level, topic)
