"""Flashcard RAG retrieval is scoped to the module's course (#2491).

Before #2491 the flashcard generator called ``semantic_retriever.search()`` with
only a level filter, so it could pull chunks from *any* course's documents. It
now routes through ``retrieve_with_fallback`` with the course-scoped
``books_sources`` (so an un-indexed course raises ``CourseNotIndexedError``
instead of silently borrowing off-topic chunks).

The retriever and Claude are mocked — no DB, no embeddings, no network.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.services import flashcard_service as fc_module
from app.domain.services.exceptions import CourseNotIndexedError
from app.domain.services.flashcard_service import FlashcardGenerationService


def _module(rag_collection_id=None, books_sources=None) -> MagicMock:
    module = MagicMock()
    module.id = uuid.uuid4()
    module.title_fr = "Titre"
    module.title_en = "Title"
    module.books_sources = books_sources
    course = MagicMock()
    course.rag_collection_id = rag_collection_id
    module.course = course
    return module


def test_resolve_books_sources_prefers_rag_collection_id():
    rag_id = str(uuid.uuid4())
    module = _module(rag_collection_id=rag_id, books_sources={"old.pdf": []})
    assert FlashcardGenerationService._resolve_books_sources(module) == {rag_id: []}


def test_resolve_books_sources_falls_back_to_books_sources():
    module = _module(rag_collection_id=None, books_sources={"donaldson": []})
    assert FlashcardGenerationService._resolve_books_sources(module) == {"donaldson": []}


def test_resolve_books_sources_none_when_unindexed_legacy():
    module = _module(rag_collection_id=None, books_sources=None)
    assert FlashcardGenerationService._resolve_books_sources(module) is None


@pytest.mark.asyncio
async def test_generate_uses_scoped_retrieval_and_propagates_not_indexed(monkeypatch):
    rag_id = str(uuid.uuid4())
    module = _module(rag_collection_id=rag_id)

    # session.execute(...).scalar_one_or_none() -> the module
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = module
    session = AsyncMock()
    session.execute.return_value = exec_result

    captured: dict = {}

    async def fake_retrieve(
        retriever, mod, books_sources, query, unit_id, level, language, sess, top_k
    ):
        captured["books_sources"] = books_sources
        captured["unit_id"] = unit_id
        captured["top_k"] = top_k
        # Simulate a course with zero indexed chunks.
        raise CourseNotIndexedError()

    monkeypatch.setattr(fc_module, "retrieve_with_fallback", fake_retrieve)

    service = FlashcardGenerationService(claude_service=MagicMock(), semantic_retriever=MagicMock())

    with pytest.raises(CourseNotIndexedError):
        await service._generate_flashcard_set(
            module_id=module.id,
            language="fr",
            country="CI",
            level=1,
            session=session,
        )

    # The fix: retrieval is scoped to the course's rag_collection_id, module-level
    # (no unit), and the flashcard top_k setting is forwarded.
    assert captured["books_sources"] == {rag_id: []}
    assert captured["unit_id"] == "flashcards"
    assert isinstance(captured["top_k"], int)
