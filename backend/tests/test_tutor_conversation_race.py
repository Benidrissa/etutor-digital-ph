"""Regression tests for issue #1625 — the tutor chat endpoint must commit
the new conversation row before yielding its `conversation_id` to the
client, so a follow-up GET on that id (from a different HTTP/DB session)
returns 200 instead of 404."""

from __future__ import annotations

import uuid

import pytest

from app.domain.models.conversation import TutorConversation
from app.domain.models.user import User, UserRole
from app.domain.services.tutor_service import TutorService


@pytest.fixture
async def user(db_session) -> User:
    u = User(
        id=uuid.uuid4(),
        email="learner@example.com",
        name="Test Learner",
        phone_number=None,
        role=UserRole.user,
        email_verified=True,
        preferred_language="fr",
    )
    db_session.add(u)
    await db_session.commit()
    return u


async def test_new_conversation_is_committed_before_returning(db_session, user) -> None:
    """`_get_or_create_conversation` must commit newly-created rows so that
    a fresh session (simulating a follow-up HTTP request) can see them."""
    svc = TutorService()
    conversation = await svc._get_or_create_conversation(
        user_id=user.id,
        module_id=None,
        conversation_id=None,
        session=db_session,
    )
    assert conversation.id is not None

    # Read back through a different session to prove the row is committed.
    from app.infrastructure.persistence.database import async_session_factory

    async with async_session_factory() as fresh:
        from sqlalchemy import select

        result = await fresh.execute(
            select(TutorConversation).where(TutorConversation.id == conversation.id)
        )
        fetched = result.scalar_one_or_none()

    assert fetched is not None, (
        "new conversation must be visible from a different session — "
        "was previously only flushed, not committed (#1625)"
    )
    assert fetched.user_id == user.id


async def test_existing_conversation_is_returned_unchanged(db_session, user) -> None:
    """Helper must return an existing conversation without re-creating."""
    existing = TutorConversation(
        id=uuid.uuid4(),
        user_id=user.id,
        module_id=None,
        messages=[],
    )
    db_session.add(existing)
    await db_session.commit()

    svc = TutorService()
    fetched = await svc._get_or_create_conversation(
        user_id=user.id,
        module_id=None,
        conversation_id=existing.id,
        session=db_session,
    )
    assert fetched.id == existing.id
