"""Service for AI tutor functionality with agentic tool_use and Socratic pedagogical approach."""

import asyncio
import re
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
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
from app.domain.models.course import Course, UserCourseEnrollment
from app.domain.models.module import Module
from app.domain.models.source_image import SourceImage
from app.domain.models.user import User
from app.domain.services.learner_memory_service import LearnerMemoryService
from app.domain.services.platform_settings_service import SettingsCache
from app.domain.services.subscription_service import SubscriptionService
from app.domain.services.tutor_tools import TOOL_DEFINITIONS, TutorToolExecutor
from app.infrastructure.config.settings import get_settings

logger = structlog.get_logger()

_sc = SettingsCache.instance
MAX_TOOL_CALLS = _sc().get("tutor-max-tool-calls", 3)
COMPACT_TRIGGER = _sc().get("tutor-compaction-trigger-messages", 20)
COMPACT_KEEP_RECENT = _sc().get("tutor-compaction-keep-recent", 5)
COMPACT_SUMMARIZE_UP_TO = _sc().get("tutor-compaction-summarize-up-to", 15)

SESSION_CONTEXT_TOKEN_BUDGET = _sc().get("tutor-context-token-budget", 1500)


@dataclass
class SessionContext:
    """Composed session context for a tutor conversation."""

    learner_memory: str = ""
    previous_compact: str = ""
    current_compact: str = ""
    progress_snapshot: str = ""
    is_new_conversation: bool = True

    @property
    def has_prior_context(self) -> bool:
        """Return True if any prior context was loaded."""
        return bool(self.learner_memory or self.previous_compact or self.current_compact)

    def total_text(self) -> str:
        """Return concatenated context text for token estimation."""
        parts = [
            self.learner_memory,
            self.previous_compact,
            self.current_compact,
            self.progress_snapshot,
        ]
        return "\n".join(p for p in parts if p)

    def estimated_tokens(self) -> int:
        """Rough estimate: ~4 chars per token."""
        return len(self.total_text()) // 4


class SessionManager:
    """Composes full session context for a tutor conversation.

    Loads learner memory + compacted history + progress snapshot and enforces
    the SESSION_CONTEXT_TOKEN_BUDGET so injected context stays ≤1500 tokens.
    """

    def __init__(self, learner_memory_service: LearnerMemoryService) -> None:
        self.learner_memory_service = learner_memory_service

    async def build_session_context(
        self,
        user: User,
        conversation: TutorConversation,
        is_new_conversation: bool,
        session: AsyncSession,
    ) -> SessionContext:
        """Build full session context respecting the token budget.

        For a new conversation: loads learner_memory + last conversation's compacted_context.
        For a continuing conversation: loads learner_memory + current compacted_context.
        Progress snapshot is derived from the User model (level, country).
        """
        ctx = SessionContext(is_new_conversation=is_new_conversation)

        ctx.learner_memory = await self.learner_memory_service.format_for_prompt(user.id, session)

        if is_new_conversation:
            prior = await self._get_previous_compact(user.id, conversation.id, session)
            if prior:
                ctx.previous_compact = prior
        else:
            if conversation.compacted_context:
                ctx.current_compact = conversation.compacted_context

        ctx.progress_snapshot = _build_progress_snapshot(user)

        ctx = _trim_to_budget(ctx)

        logger.info(
            "Session context built",
            user_id=str(user.id),
            conversation_id=str(conversation.id),
            is_new=is_new_conversation,
            estimated_tokens=ctx.estimated_tokens(),
            has_prior_context=ctx.has_prior_context,
        )

        return ctx

    async def _get_previous_compact(
        self,
        user_id: uuid.UUID,
        current_conversation_id: uuid.UUID,
        session: AsyncSession,
    ) -> str | None:
        """Return compacted_context from the most recent prior conversation."""
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


def _build_progress_snapshot(user: User) -> str:
    """Build a short progress snapshot from the user model."""
    level_labels = {
        1: "Beginner (L1)",
        2: "Intermediate (L2)",
        3: "Advanced (L3)",
        4: "Expert (L4)",
    }
    level_label = level_labels.get(user.current_level, f"Level {user.current_level}")
    parts = [f"Level: {level_label}", f"Country: {user.country or 'SN'}"]
    if hasattr(user, "streak_days") and user.streak_days:
        parts.append(f"Streak: {user.streak_days} days")
    return ", ".join(parts)


def _trim_to_budget(ctx: SessionContext) -> SessionContext:
    """Trim context fields to stay within SESSION_CONTEXT_TOKEN_BUDGET.

    Priority order (least to most likely trimmed):
    progress_snapshot > learner_memory > previous_compact/current_compact
    """
    if ctx.estimated_tokens() <= SESSION_CONTEXT_TOKEN_BUDGET:
        return ctx

    budget_chars = SESSION_CONTEXT_TOKEN_BUDGET * 4

    if ctx.previous_compact:
        available = budget_chars - len(ctx.learner_memory) - len(ctx.progress_snapshot)
        if available < len(ctx.previous_compact):
            ctx.previous_compact = ctx.previous_compact[: max(0, available)]

    if ctx.current_compact:
        available = budget_chars - len(ctx.learner_memory) - len(ctx.progress_snapshot)
        if available < len(ctx.current_compact):
            ctx.current_compact = ctx.current_compact[: max(0, available)]

    if ctx.estimated_tokens() > SESSION_CONTEXT_TOKEN_BUDGET:
        available = budget_chars - len(ctx.progress_snapshot)
        if available < len(ctx.learner_memory):
            ctx.learner_memory = ctx.learner_memory[: max(0, available)]

    return ctx


class TutorService:
    """Service for managing AI tutor conversations with agentic tool_use and Socratic approach."""

    def __init__(
        self,
        anthropic_client: AsyncAnthropic,
        semantic_retriever: SemanticRetriever,
        embedding_service: EmbeddingService,
        learner_memory_service: LearnerMemoryService | None = None,
    ):
        self.anthropic = anthropic_client
        self.retriever = semantic_retriever
        self.embedding_service = embedding_service
        self.learner_memory_service = learner_memory_service or LearnerMemoryService()
        self.session_manager = SessionManager(self.learner_memory_service)
        self.settings = get_settings()

    async def send_message(
        self,
        user_id: str | uuid.UUID,
        message: str,
        session: AsyncSession,
        module_id: uuid.UUID | None = None,
        context_type: str | None = None,
        context_id: uuid.UUID | None = None,
        conversation_id: uuid.UUID | None = None,
        tutor_mode: str = "socratic",
        file_content_blocks: list[dict[str, Any]] | None = None,
        course_id: uuid.UUID | None = None,
        locale: str | None = None,
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
            file_content_blocks: Optional list of Claude API content blocks (images/text) from uploads
            course_id: Optional course ID (derived from enrollment if absent)

        Yields:
            Stream chunks with tutor response data
        """
        if isinstance(user_id, str):
            user_id = uuid.UUID(user_id)

        subscription = await SubscriptionService().get_active_subscription(user_id, session)
        messages_used = await self._check_daily_limit(user_id, session)
        if subscription:
            effective_limit = subscription.daily_message_limit + subscription.message_credits
        else:
            effective_limit = 5
        if messages_used >= effective_limit:
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
            is_new_conversation = conversation_id is None
            conversation = await self._get_or_create_conversation(
                user_id, module_id, conversation_id, session
            )

            session_ctx = await self.session_manager.build_session_context(
                user=user,
                conversation=conversation,
                is_new_conversation=is_new_conversation,
                session=session,
            )

            if (
                is_new_conversation
                and session_ctx.previous_compact
                and not conversation.compacted_context
            ):
                conversation.compacted_context = session_ctx.previous_compact
                session.add(conversation)
                await session.flush()

            yield {
                "type": "conversation_id",
                "data": {"conversation_id": str(conversation.id)},
            }

            effective_language = locale if locale in ("fr", "en") else user.preferred_language

            if locale in ("fr", "en") and user.preferred_language != locale:
                user.preferred_language = locale
                session.add(user)

            # Resolve module title for human-readable system prompt
            module_title = None
            module_number = None
            module_obj = None
            if module_id:
                module_obj = await session.get(Module, module_id)
                if module_obj:
                    module_title = (
                        module_obj.title_fr if effective_language == "fr" else module_obj.title_en
                    )
                    module_number = module_obj.module_number

            # Resolve course context: explicit > from module > from enrollment
            course = await self._resolve_course(course_id, module_id, module_obj, user_id, session)
            course_title = None
            course_domain = None
            rag_collection_id = None
            if course:
                course_title = course.title_fr if effective_language == "fr" else course.title_en
                course_domain = course_domain or course_title
                rag_collection_id = course.rag_collection_id

            context = TutorContext(
                user_level=user.current_level,
                user_language=effective_language,
                user_country=user.country or "SN",
                module_id=str(module_id) if module_id else None,
                module_title=module_title,
                module_number=module_number,
                context_type=context_type,
                tutor_mode=tutor_mode,
                context_id=str(context_id) if context_id else None,
                course_title=course_title,
                course_domain=course_domain,
                learner_memory=session_ctx.learner_memory,
                previous_session_context=session_ctx.previous_compact,
                progress_snapshot=session_ctx.progress_snapshot,
            )

            system_prompt = get_socratic_system_prompt(context, [])

            conversation_history = await self._prepare_conversation_history(conversation)

            user_msg_stored = {
                "role": "user",
                "content": message,
                "timestamp": datetime.utcnow().isoformat(),
                "has_files": bool(file_content_blocks),
            }

            if file_content_blocks:
                user_content: list[Any] = [*file_content_blocks, {"type": "text", "text": message}]
                conversation_history.append({"role": "user", "content": user_content})
            else:
                conversation_history.append({"role": "user", "content": message})

            tool_executor = TutorToolExecutor(
                retriever=self.retriever,
                anthropic_client=self.anthropic,
                user_id=user_id,
                user_level=user.current_level,
                user_language=effective_language,
                rag_collection_id=rag_collection_id,
            )

            tool_call_count = 0
            full_response = ""
            all_tool_calls: list[dict[str, Any]] = []
            sources_cited: list[dict[str, Any]] = []
            source_image_refs: list[dict[str, Any]] = []
            api_messages: list[MessageParam] = list(conversation_history)

            while tool_call_count <= MAX_TOOL_CALLS:
                response = await self.anthropic.messages.create(
                    model="claude-sonnet-4-6",
                    system=system_prompt,
                    messages=api_messages,
                    tools=TOOL_DEFINITIONS,
                    max_tokens=_sc().get("tutor-response-max-tokens", 1500),
                    temperature=_sc().get("tutor-response-temperature", 0.7),
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

                    elif tool_block.name == "search_source_images":
                        try:
                            import json as _json

                            img_result = _json.loads(tool_result_str)
                            prefix = "{{source_image:"
                            img_ids_to_fetch: list[str] = []
                            for fig in img_result.get("figures", []):
                                ref: str = fig.get("ref", "")
                                if ref.startswith(prefix) and ref.endswith("}}"):
                                    img_ids_to_fetch.append(ref[len(prefix) : -2])

                            if img_ids_to_fetch:
                                try:
                                    db_imgs = await session.execute(
                                        select(SourceImage).where(
                                            SourceImage.id.in_(
                                                [uuid.UUID(i) for i in img_ids_to_fetch]
                                            )
                                        )
                                    )
                                    db_img_map = {str(r.id): r for r in db_imgs.scalars().all()}
                                except Exception:
                                    db_img_map = {}

                                seen_img_ids: set[str] = {r["id"] for r in source_image_refs}
                                for img_id in img_ids_to_fetch:
                                    if img_id in seen_img_ids:
                                        continue
                                    seen_img_ids.add(img_id)
                                    db_img = db_img_map.get(img_id)
                                    if db_img:
                                        meta = db_img.to_meta_dict()
                                        source_image_refs.append(
                                            {
                                                "id": img_id,
                                                "figure_number": meta.get("figure_number"),
                                                "caption": meta.get("caption"),
                                                "caption_fr": meta.get("caption"),
                                                "caption_en": meta.get("caption"),
                                                "attribution": meta.get("attribution"),
                                                "image_type": meta.get("image_type", "unknown"),
                                                "storage_url": meta.get("storage_url"),
                                                "alt_text_fr": meta.get("alt_text_fr"),
                                                "alt_text_en": meta.get("alt_text_en"),
                                            }
                                        )
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

            if (
                subscription
                and messages_used >= subscription.daily_message_limit
                and subscription.message_credits > 0
            ):
                subscription.message_credits -= 1
                session.add(subscription)

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

            # Resolve any {{source_image:UUID}} markers in the response that
            # weren't captured via tool calls (e.g. from conversation history)
            _IMG_RE = re.compile(r"\{\{source_image:([0-9a-f-]{36})\}\}", re.IGNORECASE)
            seen_ids = {r["id"] for r in source_image_refs}
            extra_ids = [
                m.group(1) for m in _IMG_RE.finditer(full_response) if m.group(1) not in seen_ids
            ]
            if extra_ids:
                try:
                    db_imgs = await session.execute(
                        select(SourceImage).where(
                            SourceImage.id.in_([uuid.UUID(i) for i in extra_ids])
                        )
                    )
                    for img in db_imgs.scalars().all():
                        meta = img.to_meta_dict()
                        source_image_refs.append(
                            {
                                "id": str(img.id),
                                "figure_number": meta.get("figure_number"),
                                "caption": meta.get("caption"),
                                "caption_fr": meta.get("caption"),
                                "caption_en": meta.get("caption"),
                                "attribution": meta.get("attribution"),
                                "image_type": meta.get("image_type", "unknown"),
                                "storage_url": meta.get("storage_url"),
                                "alt_text_fr": meta.get("alt_text_fr"),
                                "alt_text_en": meta.get("alt_text_en"),
                            }
                        )
                except Exception as exc:
                    logger.warning("Failed to resolve extra image markers", error=str(exc))

            if source_image_refs:
                yield {
                    "type": "source_image_refs",
                    "data": {"refs": source_image_refs},
                    "conversation_id": str(conversation.id),
                }

            yield {
                "type": "activity_suggestions",
                "data": {"suggestions": activity_suggestions},
                "conversation_id": str(conversation.id),
            }

            credits_after = subscription.message_credits if subscription else 0
            yield {
                "type": "finished",
                "data": {
                    "remaining_messages": max(0, effective_limit - messages_used - 1),
                    "message_credits": credits_after,
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
                    "has_context": bool(conv.compacted_context),
                }
            )

        return {"conversations": summaries, "total": total}

    async def delete_conversation(
        self,
        user_id: str | uuid.UUID,
        conversation_id: uuid.UUID,
        session: AsyncSession,
    ) -> bool:
        """Delete a specific conversation. Returns True if deleted."""
        if isinstance(user_id, str):
            user_id = uuid.UUID(user_id)

        query = select(TutorConversation).where(
            TutorConversation.id == conversation_id,
            TutorConversation.user_id == user_id,
        )
        result = await session.execute(query)
        conversation = result.scalar_one_or_none()

        if not conversation:
            return False

        await session.delete(conversation)
        await session.commit()

        logger.info(
            "Conversation deleted",
            user_id=str(user_id),
            conversation_id=str(conversation_id),
            message_count=len(conversation.messages) if conversation.messages else 0,
        )
        return True

    async def delete_all_conversations(
        self,
        user_id: str | uuid.UUID,
        session: AsyncSession,
    ) -> int:
        """Delete all conversations for a user. Returns count deleted."""
        if isinstance(user_id, str):
            user_id = uuid.UUID(user_id)

        query = select(TutorConversation).where(
            TutorConversation.user_id == user_id,
        )
        result = await session.execute(query)
        conversations = result.scalars().all()

        count = len(conversations)
        for conv in conversations:
            await session.delete(conv)

        if count:
            await session.commit()
            logger.info(
                "All conversations deleted",
                user_id=str(user_id),
                deleted_count=count,
            )

        return count

    async def get_tutor_stats(
        self, user_id: str | uuid.UUID, session: AsyncSession
    ) -> dict[str, Any]:
        """Get tutor usage statistics for a user."""
        if isinstance(user_id, str):
            user_id = uuid.UUID(user_id)

        daily_messages = await self._check_daily_limit(user_id, session)

        subscription = await SubscriptionService().get_active_subscription(user_id, session)
        if subscription:
            limit = subscription.daily_message_limit + subscription.message_credits
            message_credits = subscription.message_credits
        else:
            limit = 5
            message_credits = 0

        count_query = select(func.count(TutorConversation.id)).where(
            TutorConversation.user_id == user_id
        )
        count_result = await session.execute(count_query)
        total_conversations = count_result.scalar() or 0

        most_discussed_topics: list[Any] = []

        return {
            "daily_messages_used": daily_messages,
            "daily_messages_limit": limit,
            "message_credits": message_credits,
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

    async def _resolve_course(
        self,
        course_id: uuid.UUID | None,
        module_id: uuid.UUID | None,
        module_obj: Module | None,
        user_id: uuid.UUID,
        session: AsyncSession,
    ) -> Course | None:
        """Resolve course: explicit course_id > module's course > active enrollment.

        When course_id is explicit, verifies the user is enrolled (active)
        to prevent access to paid content. Falls back to enrollment if not.
        """
        # 1. Explicit course_id — verify enrollment
        if course_id:
            enrolled = await session.execute(
                select(UserCourseEnrollment).where(
                    UserCourseEnrollment.user_id == user_id,
                    UserCourseEnrollment.course_id == course_id,
                    UserCourseEnrollment.status == "active",
                )
            )
            if enrolled.scalar_one_or_none():
                course = await session.get(Course, course_id)
                if course:
                    return course
            else:
                logger.warning(
                    "Tutor course_id not enrolled, falling back",
                    user_id=str(user_id),
                    course_id=str(course_id),
                )

        # 2. From module's course_id
        if module_obj and module_obj.course_id:
            course = await session.get(Course, module_obj.course_id)
            if course:
                return course

        # 3. Fallback: most recent active enrollment
        result = await session.execute(
            select(UserCourseEnrollment)
            .where(
                UserCourseEnrollment.user_id == user_id,
                UserCourseEnrollment.status == "active",
            )
            .order_by(UserCourseEnrollment.enrolled_at.desc())
            .limit(1)
        )
        enrollment = result.scalar_one_or_none()
        if enrollment:
            return await session.get(Course, enrollment.course_id)

        return None

    async def _retrieve_relevant_context(
        self, query: str, user: User, module_id: uuid.UUID | None, session: AsyncSession
    ) -> list[Any]:
        """Retrieve relevant context using RAG (kept for backward compatibility)."""
        books_sources = None
        if module_id:
            from sqlalchemy.orm import selectinload

            result = await session.execute(
                select(Module).where(Module.id == module_id).options(selectinload(Module.course))
            )
            module = result.scalar_one_or_none()
            if module:
                course = module.course
                if course and course.rag_collection_id:
                    books_sources = {course.rag_collection_id: []}
                elif module.books_sources:
                    books_sources = module.books_sources

        search_results = await self.retriever.search_for_module(
            query=query,
            user_level=user.current_level,
            user_language=user.preferred_language,
            books_sources=books_sources,
            top_k=_sc().get("ai-rag-default-top-k", 8),
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
            content = (msg.get("content") or "").strip()
            if msg.get("role") and content:
                claude_messages.append(
                    {
                        "role": msg["role"],
                        "content": content,
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
                    max_tokens=_sc().get("tutor-compaction-max-tokens", 600),
                    temperature=_sc().get("tutor-compaction-temperature", 0.3),
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
