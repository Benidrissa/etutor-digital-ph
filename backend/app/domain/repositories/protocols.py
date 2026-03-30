"""Repository protocol interfaces for SantePublique AOF.

Defines abstract interfaces for data access layer.
Implementations can be SQLAlchemy, MongoDB, or any other storage.
"""

from abc import abstractmethod
from typing import Any, Protocol
from uuid import UUID

from ..models.content import GeneratedContent
from ..models.conversation import TutorConversation
from ..models.flashcard import FlashcardReview
from ..models.module import Module
from ..models.progress import UserModuleProgress
from ..models.quiz import QuizAttempt
from ..models.user import User


class BaseRepositoryProtocol(Protocol):
    """Base repository interface with CRUD operations."""

    @abstractmethod
    async def get_by_id(self, id: UUID) -> Any | None:
        """Get entity by ID."""
        pass

    @abstractmethod
    async def create(self, entity: Any) -> Any:
        """Create new entity."""
        pass

    @abstractmethod
    async def update(self, entity: Any) -> Any:
        """Update existing entity."""
        pass

    @abstractmethod
    async def delete(self, entity: Any) -> None:
        """Delete entity."""
        pass


class UserRepositoryProtocol(BaseRepositoryProtocol):
    """User repository interface."""

    @abstractmethod
    async def get_by_id(self, user_id: UUID) -> User | None:
        """Get user by ID."""
        pass

    @abstractmethod
    async def get_by_email(self, email: str) -> User | None:
        """Get user by email address."""
        pass

    @abstractmethod
    async def create(self, user: User) -> User:
        """Create new user."""
        pass

    @abstractmethod
    async def update(self, user: User) -> User:
        """Update existing user."""
        pass

    @abstractmethod
    async def delete(self, user: User) -> None:
        """Delete user and related data."""
        pass

    @abstractmethod
    async def list_users(
        self, offset: int = 0, limit: int = 20, filters: dict[str, Any] | None = None
    ) -> list[User]:
        """List users with pagination."""
        pass


class ModuleRepositoryProtocol(BaseRepositoryProtocol):
    """Module repository interface."""

    @abstractmethod
    async def get_by_id(self, module_id: UUID) -> Module | None:
        """Get module by ID."""
        pass

    @abstractmethod
    async def get_by_number(self, module_number: int) -> Module | None:
        """Get module by number (1-15)."""
        pass

    @abstractmethod
    async def list_by_level(self, level: int) -> list[Module]:
        """List modules for a specific level."""
        pass

    @abstractmethod
    async def list_all(self) -> list[Module]:
        """List all modules."""
        pass


class ProgressRepositoryProtocol(BaseRepositoryProtocol):
    """User module progress repository interface."""

    @abstractmethod
    async def get_user_progress(self, user_id: UUID, module_id: UUID) -> UserModuleProgress | None:
        """Get user's progress for specific module."""
        pass

    @abstractmethod
    async def get_user_all_progress(self, user_id: UUID) -> list[UserModuleProgress]:
        """Get all progress records for user."""
        pass

    @abstractmethod
    async def create_or_update(self, progress: UserModuleProgress) -> UserModuleProgress:
        """Create or update progress record."""
        pass

    @abstractmethod
    async def update_completion(
        self,
        user_id: UUID,
        module_id: UUID,
        completion_pct: float,
        quiz_score_avg: float | None = None,
    ) -> UserModuleProgress:
        """Update completion percentage and quiz score."""
        pass


class ContentRepositoryProtocol(BaseRepositoryProtocol):
    """Generated content repository interface."""

    @abstractmethod
    async def get_by_id(self, content_id: UUID) -> GeneratedContent | None:
        """Get content by ID."""
        pass

    @abstractmethod
    async def find_content(
        self,
        module_id: UUID,
        content_type: str,
        language: str,
        level: int,
        country_context: str | None = None,
    ) -> GeneratedContent | None:
        """Find existing content matching criteria."""
        pass

    @abstractmethod
    async def create(self, content: GeneratedContent) -> GeneratedContent:
        """Create new content."""
        pass

    @abstractmethod
    async def list_by_module(
        self, module_id: UUID, content_type: str | None = None, language: str | None = None
    ) -> list[GeneratedContent]:
        """List content for module."""
        pass


class QuizRepositoryProtocol(BaseRepositoryProtocol):
    """Quiz attempt repository interface."""

    @abstractmethod
    async def get_by_id(self, attempt_id: UUID) -> QuizAttempt | None:
        """Get quiz attempt by ID."""
        pass

    @abstractmethod
    async def create(self, attempt: QuizAttempt) -> QuizAttempt:
        """Create new quiz attempt."""
        pass

    @abstractmethod
    async def get_user_attempts(
        self, user_id: UUID, quiz_id: UUID | None = None
    ) -> list[QuizAttempt]:
        """Get user's quiz attempts."""
        pass

    @abstractmethod
    async def get_latest_attempt(self, user_id: UUID, quiz_id: UUID) -> QuizAttempt | None:
        """Get user's most recent attempt for quiz."""
        pass


class FlashcardRepositoryProtocol(BaseRepositoryProtocol):
    """Flashcard review repository interface."""

    @abstractmethod
    async def get_by_id(self, review_id: UUID) -> FlashcardReview | None:
        """Get flashcard review by ID."""
        pass

    @abstractmethod
    async def create(self, review: FlashcardReview) -> FlashcardReview:
        """Create new flashcard review."""
        pass

    @abstractmethod
    async def get_user_reviews(self, user_id: UUID) -> list[FlashcardReview]:
        """Get all reviews for user."""
        pass

    @abstractmethod
    async def get_due_cards(self, user_id: UUID, limit: int = 20) -> list[FlashcardReview]:
        """Get flashcards due for review."""
        pass

    @abstractmethod
    async def get_card_review_history(self, user_id: UUID, card_id: UUID) -> list[FlashcardReview]:
        """Get review history for specific card."""
        pass


class ConversationRepositoryProtocol(BaseRepositoryProtocol):
    """Tutor conversation repository interface."""

    @abstractmethod
    async def get_by_id(self, conversation_id: UUID) -> TutorConversation | None:
        """Get conversation by ID."""
        pass

    @abstractmethod
    async def create(self, conversation: TutorConversation) -> TutorConversation:
        """Create new conversation."""
        pass

    @abstractmethod
    async def update(self, conversation: TutorConversation) -> TutorConversation:
        """Update conversation with new messages."""
        pass

    @abstractmethod
    async def get_user_conversations(
        self, user_id: UUID, module_id: UUID | None = None
    ) -> list[TutorConversation]:
        """Get user's conversations."""
        pass

    @abstractmethod
    async def get_recent_conversation(
        self, user_id: UUID, module_id: UUID | None = None
    ) -> TutorConversation | None:
        """Get user's most recent conversation."""
        pass
