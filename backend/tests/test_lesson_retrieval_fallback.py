"""Tests for graceful RAG retrieval fallback (#2487).

`retrieve_with_fallback` recovers thin / partially-indexed courses by retrying
at a relaxed similarity threshold before failing, and distinguishes a course
with zero indexed chunks (CourseNotIndexedError) from a unit whose query simply
found nothing (plain ValueError).

These tests mock the SemanticRetriever entirely — no DB, no embeddings.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.ai.rag.retriever import SearchResult, SemanticRetriever
from app.domain.services.exceptions import CourseNotIndexedError
from app.domain.services.lesson_service import (
    RAG_FALLBACK_MIN_SIMILARITY,
    retrieve_with_fallback,
)

BOOKS = {"a1cc100e-266d-42c5-87ff-3930eba2e075": []}


def _module() -> MagicMock:
    module = MagicMock()
    module.id = uuid.uuid4()
    return module


def _chunk() -> MagicMock:
    return MagicMock(spec=SearchResult)


@pytest.fixture
def retriever() -> AsyncMock:
    r = AsyncMock(spec=SemanticRetriever)
    # _build_module_filters is a sync staticmethod — keep it sync so the
    # filters dict (not a coroutine) is handed to search().
    r._build_module_filters = MagicMock(return_value={"level": {"$lte": 1}})
    return r


async def _call(retriever: AsyncMock):
    return await retrieve_with_fallback(
        retriever, _module(), BOOKS, "unit query", "2.4", 1, "fr", AsyncMock()
    )


@pytest.mark.asyncio
async def test_primary_hit_skips_fallback_and_count(retriever):
    chunks = [_chunk()]
    retriever.search_for_module.return_value = chunks

    out = await _call(retriever)

    assert out == chunks
    retriever.search.assert_not_called()
    retriever.count_source_chunks.assert_not_called()


@pytest.mark.asyncio
async def test_relaxed_threshold_recovers_thin_course(retriever):
    fallback_chunks = [_chunk(), _chunk()]
    retriever.search_for_module.return_value = []
    retriever.search.return_value = fallback_chunks

    out = await _call(retriever)

    assert out == fallback_chunks
    _, kwargs = retriever.search.call_args
    assert kwargs["min_similarity"] == RAG_FALLBACK_MIN_SIMILARITY
    retriever.count_source_chunks.assert_not_called()


@pytest.mark.asyncio
async def test_zero_chunks_raises_course_not_indexed(retriever):
    retriever.search_for_module.return_value = []
    retriever.search.return_value = []
    retriever.count_source_chunks.return_value = 0

    with pytest.raises(CourseNotIndexedError) as exc:
        await _call(retriever)

    assert str(exc.value) == "course_not_indexed"
    args, _ = retriever.count_source_chunks.call_args
    assert args[0] == list(BOOKS.keys())


@pytest.mark.asyncio
async def test_indexed_but_unit_miss_raises_plain_valueerror(retriever):
    retriever.search_for_module.return_value = []
    retriever.search.return_value = []
    retriever.count_source_chunks.return_value = 42

    with pytest.raises(ValueError) as exc:
        await _call(retriever)

    # Must NOT be the "not indexed" sentinel — the course has content,
    # this unit just didn't match.
    assert not isinstance(exc.value, CourseNotIndexedError)
    assert "No relevant content" in str(exc.value)
