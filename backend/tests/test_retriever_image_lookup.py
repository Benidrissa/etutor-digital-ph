"""Tests for SemanticRetriever.get_linked_images and search_source_images (issue #740)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.ai.rag.retriever import SemanticRetriever


def _make_retriever() -> SemanticRetriever:
    embedding_service = MagicMock()
    embedding_service.generate_embedding = AsyncMock(return_value=[0.1] * 1536)
    return SemanticRetriever(embedding_service=embedding_service)


class TestGetLinkedImages:
    @pytest.mark.asyncio
    async def test_empty_chunk_ids_returns_empty_dict(self):
        retriever = _make_retriever()
        session = MagicMock()
        result = await retriever.get_linked_images([], session)
        assert result == {}
        session.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_images_grouped_by_chunk(self):
        retriever = _make_retriever()
        chunk_id_1 = uuid.uuid4()
        chunk_id_2 = uuid.uuid4()
        img_id_1 = uuid.uuid4()
        img_id_2 = uuid.uuid4()

        def _row(chunk_id, img_id, ref_type, figure_number=None):
            return SimpleNamespace(
                chunk_id=chunk_id,
                id=img_id,
                source="donaldson",
                rag_collection_id=None,
                figure_number=figure_number,
                caption="Figure caption",
                attribution=None,
                image_type="diagram",
                page_number=10,
                chapter="Chapter 1",
                width=800,
                height=600,
                file_size_bytes=12000,
                storage_url="https://example.com/img.webp",
                alt_text_fr="Diagramme",
                alt_text_en="Diagram",
                reference_type=ref_type,
            )

        fake_rows = [
            _row(chunk_id_1, img_id_1, "explicit", "Figure 1.2"),
            _row(chunk_id_2, img_id_2, "contextual"),
        ]
        mock_result = MagicMock()
        mock_result.fetchall.return_value = fake_rows

        session = MagicMock()
        session.execute = AsyncMock(return_value=mock_result)

        result = await retriever.get_linked_images([chunk_id_1, chunk_id_2], session)

        assert chunk_id_1 in result
        assert chunk_id_2 in result
        assert len(result[chunk_id_1]) == 1
        assert result[chunk_id_1][0]["id"] == str(img_id_1)
        assert result[chunk_id_1][0]["figure_number"] == "Figure 1.2"
        assert result[chunk_id_1][0]["reference_type"] == "explicit"
        assert len(result[chunk_id_2]) == 1
        assert result[chunk_id_2][0]["id"] == str(img_id_2)

    @pytest.mark.asyncio
    async def test_caps_at_3_images_per_chunk(self):
        retriever = _make_retriever()
        chunk_id = uuid.uuid4()

        def _row(img_id):
            return SimpleNamespace(
                chunk_id=chunk_id,
                id=img_id,
                source="triola",
                rag_collection_id=None,
                figure_number=None,
                caption=None,
                attribution=None,
                image_type="chart",
                page_number=5,
                chapter=None,
                width=400,
                height=300,
                file_size_bytes=5000,
                storage_url=None,
                alt_text_fr=None,
                alt_text_en=None,
                reference_type="contextual",
            )

        fake_rows = [_row(uuid.uuid4()) for _ in range(5)]
        mock_result = MagicMock()
        mock_result.fetchall.return_value = fake_rows

        session = MagicMock()
        session.execute = AsyncMock(return_value=mock_result)

        result = await retriever.get_linked_images([chunk_id], session)

        assert len(result[chunk_id]) == 3

    @pytest.mark.asyncio
    async def test_caps_total_at_5_images(self):
        retriever = _make_retriever()
        chunk_ids = [uuid.uuid4() for _ in range(4)]

        def _row(chunk_id):
            return SimpleNamespace(
                chunk_id=chunk_id,
                id=uuid.uuid4(),
                source="donaldson",
                rag_collection_id=None,
                figure_number=None,
                caption=None,
                attribution=None,
                image_type="unknown",
                page_number=1,
                chapter=None,
                width=200,
                height=200,
                file_size_bytes=2000,
                storage_url=None,
                alt_text_fr=None,
                alt_text_en=None,
                reference_type="contextual",
            )

        fake_rows = [_row(cid) for cid in chunk_ids for _ in range(2)]
        mock_result = MagicMock()
        mock_result.fetchall.return_value = fake_rows

        session = MagicMock()
        session.execute = AsyncMock(return_value=mock_result)

        result = await retriever.get_linked_images(chunk_ids, session)

        total = sum(len(imgs) for imgs in result.values())
        assert total == 5


class TestSearchSourceImages:
    @pytest.mark.asyncio
    async def test_empty_query_returns_empty_list(self):
        retriever = _make_retriever()
        session = MagicMock()
        result = await retriever.search_source_images("  ", session=session)
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_metadata_dicts(self):
        retriever = _make_retriever()
        img_id = uuid.uuid4()

        fake_row = SimpleNamespace(
            id=img_id,
            source="donaldson",
            rag_collection_id=None,
            figure_number="Figure 3.1",
            caption="Epidemiology diagram",
            attribution=None,
            image_type="diagram",
            page_number=42,
            chapter="Chapter 3",
            width=800,
            height=600,
            file_size_bytes=15000,
            storage_url="https://example.com/fig3.1.webp",
            alt_text_fr="Diagramme épidémiologique",
            alt_text_en="Epidemiology diagram",
            similarity=0.87,
        )

        mock_result = MagicMock()
        mock_result.fetchall.return_value = [fake_row]
        session = MagicMock()
        session.execute = AsyncMock(return_value=mock_result)

        results = await retriever.search_source_images(
            "epidemiology surveillance",
            source="donaldson",
            session=session,
        )

        assert len(results) == 1
        img = results[0]
        assert img["id"] == str(img_id)
        assert img["source"] == "donaldson"
        assert img["caption"] == "Epidemiology diagram"
        assert img["similarity"] == pytest.approx(0.87)
        assert "storage_url" in img
        assert "image_data" not in img

    @pytest.mark.asyncio
    async def test_filter_by_rag_collection_id_included_in_query(self):
        retriever = _make_retriever()

        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        session = MagicMock()
        session.execute = AsyncMock(return_value=mock_result)

        await retriever.search_source_images(
            "public health",
            rag_collection_id="some-collection-uuid",
            session=session,
        )

        call_args = session.execute.call_args
        query_text = str(call_args[0][0])
        assert "rag_collection_id" in query_text
