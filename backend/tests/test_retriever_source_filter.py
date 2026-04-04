"""Tests for SemanticRetriever.search_for_module source-filtering logic."""

from unittest.mock import AsyncMock, patch

import pytest

from app.ai.rag.retriever import SemanticRetriever


@pytest.fixture
def mock_embedding_service():
    svc = AsyncMock()
    svc.generate_embedding = AsyncMock(return_value=[0.1] * 1536)
    return svc


@pytest.fixture
def retriever(mock_embedding_service):
    return SemanticRetriever(mock_embedding_service)


class TestSearchForModuleSourceFiltering:
    async def test_uuid_keys_added_as_source_filter(self, retriever):
        rag_id = "a1b2c3d4-1234-5678-abcd-ef0123456789"
        books_sources = {rag_id: []}

        with patch.object(retriever, "search", new=AsyncMock(return_value=[])) as mock_search:
            await retriever.search_for_module(
                query="internal audit definition",
                user_level=1,
                user_language="fr",
                books_sources=books_sources,
            )
            filters_used = mock_search.call_args.kwargs["filters"]
            assert "source" in filters_used
            assert filters_used["source"] == [rag_id]

    async def test_named_keys_added_as_source_filter(self, retriever):
        books_sources = {"donaldson": ["ch1", "ch2"], "triola": []}

        with patch.object(retriever, "search", new=AsyncMock(return_value=[])) as mock_search:
            await retriever.search_for_module(
                query="epidemiology",
                user_level=2,
                user_language="en",
                books_sources=books_sources,
            )
            filters_used = mock_search.call_args.kwargs["filters"]
            assert "source" in filters_used
            assert set(filters_used["source"]) == {"donaldson", "triola"}

    async def test_no_source_filter_when_books_sources_none(self, retriever):
        with patch.object(retriever, "search", new=AsyncMock(return_value=[])) as mock_search:
            await retriever.search_for_module(
                query="health data",
                user_level=1,
                user_language="fr",
                books_sources=None,
            )
            filters_used = mock_search.call_args.kwargs["filters"]
            assert "source" not in filters_used

    async def test_no_source_filter_when_books_sources_empty(self, retriever):
        with patch.object(retriever, "search", new=AsyncMock(return_value=[])) as mock_search:
            await retriever.search_for_module(
                query="health data",
                user_level=1,
                user_language="fr",
                books_sources={},
            )
            filters_used = mock_search.call_args.kwargs["filters"]
            assert "source" not in filters_used

    async def test_mixed_keys_uses_only_named_sources(self, retriever):
        rag_id = "a1b2c3d4-1234-5678-abcd-ef0123456789"
        books_sources = {"donaldson": [], rag_id: []}

        with patch.object(retriever, "search", new=AsyncMock(return_value=[])) as mock_search:
            await retriever.search_for_module(
                query="public health",
                user_level=1,
                user_language="fr",
                books_sources=books_sources,
            )
            filters_used = mock_search.call_args.kwargs["filters"]
            assert "source" in filters_used
            assert filters_used["source"] == ["donaldson"]

    async def test_level_filter_always_present(self, retriever):
        with patch.object(retriever, "search", new=AsyncMock(return_value=[])) as mock_search:
            await retriever.search_for_module(
                query="biostatistics",
                user_level=3,
                user_language="en",
                books_sources=None,
            )
            filters_used = mock_search.call_args.kwargs["filters"]
            assert filters_used["level"] == {"$lte": 3}
