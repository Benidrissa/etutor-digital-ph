"""Tests for SemanticRetriever.get_linked_images and search_source_images."""

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

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


def _make_image(image_id=None, source="donaldson"):
    from app.domain.models.source_image import SourceImage

    img = SourceImage(
        id=image_id or uuid.uuid4(),
        source=source,
        rag_collection_id=None,
        figure_number="Fig 1.1",
        caption="Test caption",
        attribution=None,
        image_type="diagram",
        page_number=10,
        chapter="1",
        section=None,
        surrounding_text=None,
        storage_key="img/test.webp",
        storage_url="https://cdn.example.com/img/test.webp",
        format="webp",
        width=800,
        height=600,
        file_size_bytes=12345,
        original_format=None,
        alt_text_fr="Diagramme de test",
        alt_text_en="Test diagram",
        semantic_tags=None,
        created_at=datetime(2025, 1, 1),
    )
    return img


def _make_chunk_pair(chunk_id, image, ref_type="contextual"):
    from app.domain.models.source_image import SourceImageChunk

    sic = MagicMock(spec=SourceImageChunk)
    sic.document_chunk_id = chunk_id
    sic.source_image_id = image.id
    sic.reference_type = ref_type
    return (sic, image)


class TestGetLinkedImages:
    async def test_empty_chunk_ids_returns_empty(self, retriever):
        session = AsyncMock()
        result = await retriever.get_linked_images([], session)
        assert result == {}

    async def test_returns_images_for_chunks(self, retriever):
        chunk_id = uuid.uuid4()
        img = _make_image()
        pair = _make_chunk_pair(chunk_id, img, ref_type="explicit")

        mock_result = MagicMock()
        mock_result.all.return_value = [pair]
        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)

        result = await retriever.get_linked_images([chunk_id], session)

        assert chunk_id in result
        assert len(result[chunk_id]) == 1
        assert result[chunk_id][0]["id"] == str(img.id)

    async def test_respects_max_per_chunk(self, retriever):
        chunk_id = uuid.uuid4()
        images = [_make_image() for _ in range(5)]
        pairs = [_make_chunk_pair(chunk_id, img) for img in images]

        mock_result = MagicMock()
        mock_result.all.return_value = pairs
        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)

        result = await retriever.get_linked_images([chunk_id], session, max_per_chunk=2)
        assert len(result[chunk_id]) <= 2

    async def test_respects_max_total(self, retriever):
        chunk_ids = [uuid.uuid4() for _ in range(3)]
        pairs = []
        for cid in chunk_ids:
            for _ in range(3):
                pairs.append(_make_chunk_pair(cid, _make_image()))

        mock_result = MagicMock()
        mock_result.all.return_value = pairs
        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)

        result = await retriever.get_linked_images(chunk_ids, session, max_total=4)
        total = sum(len(v) for v in result.values())
        assert total <= 4

    async def test_unknown_chunk_ids_get_empty_lists(self, retriever):
        chunk_id = uuid.uuid4()
        other_chunk_id = uuid.uuid4()

        mock_result = MagicMock()
        mock_result.all.return_value = []
        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)

        result = await retriever.get_linked_images([chunk_id, other_chunk_id], session)
        assert result[chunk_id] == []
        assert result[other_chunk_id] == []

    async def test_demotes_semantic_when_explicit_exists_for_chunk(self, retriever):
        """Chunk with 1 explicit + 2 semantic returns only the explicit row (#2072)."""
        chunk_id = uuid.uuid4()
        explicit_img = _make_image()
        semantic_imgs = [_make_image(), _make_image()]
        pairs = [
            _make_chunk_pair(chunk_id, explicit_img, ref_type="explicit"),
            _make_chunk_pair(chunk_id, semantic_imgs[0], ref_type="semantic"),
            _make_chunk_pair(chunk_id, semantic_imgs[1], ref_type="semantic"),
        ]
        mock_result = MagicMock()
        mock_result.all.return_value = pairs
        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)

        result = await retriever.get_linked_images([chunk_id], session)

        returned_ids = [r["id"] for r in result[chunk_id]]
        assert returned_ids == [str(explicit_img.id)]

    async def test_demotes_semantic_when_contextual_exists_for_chunk(self, retriever):
        """Contextual is also high-precision; semantic for the same chunk is dropped (#2072)."""
        chunk_id = uuid.uuid4()
        contextual_img = _make_image()
        semantic_img = _make_image()
        pairs = [
            _make_chunk_pair(chunk_id, contextual_img, ref_type="contextual"),
            _make_chunk_pair(chunk_id, semantic_img, ref_type="semantic"),
        ]
        mock_result = MagicMock()
        mock_result.all.return_value = pairs
        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)

        result = await retriever.get_linked_images([chunk_id], session)

        returned_ids = [r["id"] for r in result[chunk_id]]
        assert returned_ids == [str(contextual_img.id)]

    async def test_keeps_semantic_when_no_higher_precision_link(self, retriever):
        """Chunk with 0 explicit + 0 contextual + 2 semantic keeps semantic rows (#2072)."""
        chunk_id = uuid.uuid4()
        semantic_imgs = [_make_image(), _make_image()]
        pairs = [
            _make_chunk_pair(chunk_id, semantic_imgs[0], ref_type="semantic"),
            _make_chunk_pair(chunk_id, semantic_imgs[1], ref_type="semantic"),
        ]
        mock_result = MagicMock()
        mock_result.all.return_value = pairs
        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)

        result = await retriever.get_linked_images([chunk_id], session)

        returned_ids = sorted(r["id"] for r in result[chunk_id])
        expected_ids = sorted(str(i.id) for i in semantic_imgs)
        assert returned_ids == expected_ids

    async def test_demotion_is_per_chunk_not_global(self, retriever):
        """Chunk A (with explicit) drops its semantic; chunk B (no explicit) keeps its semantic (#2072)."""
        chunk_a = uuid.uuid4()
        chunk_b = uuid.uuid4()
        explicit_a = _make_image()
        semantic_a = _make_image()
        semantic_b = _make_image()
        pairs = [
            _make_chunk_pair(chunk_a, explicit_a, ref_type="explicit"),
            _make_chunk_pair(chunk_a, semantic_a, ref_type="semantic"),
            _make_chunk_pair(chunk_b, semantic_b, ref_type="semantic"),
        ]
        mock_result = MagicMock()
        mock_result.all.return_value = pairs
        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)

        result = await retriever.get_linked_images([chunk_a, chunk_b], session)

        assert [r["id"] for r in result[chunk_a]] == [str(explicit_a.id)]
        assert [r["id"] for r in result[chunk_b]] == [str(semantic_b.id)]

    async def test_excludes_stock_thumbnail_kinds_at_query_level(self, retriever):
        """The compiled SQL must filter (figure_kind in photo/decorative) AND (width<=200 OR null)."""
        chunk_id = uuid.uuid4()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)

        await retriever.get_linked_images([chunk_id], session)

        stmt = session.execute.call_args.args[0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True})).lower()
        assert "figure_kind" in compiled
        assert "'photo'" in compiled and "'decorative'" in compiled
        assert "width" in compiled
        assert "200" in compiled


class TestSearchSourceImages:
    async def test_empty_query_returns_empty(self, retriever):
        session = AsyncMock()
        result = await retriever.search_source_images("   ", session=session)
        assert result == []

    async def test_returns_metadata_dicts(self, retriever):
        img = _make_image()
        row = MagicMock()
        row.id = img.id
        row.source = img.source
        row.rag_collection_id = img.rag_collection_id
        row.figure_number = img.figure_number
        row.caption = img.caption
        row.attribution = img.attribution
        row.image_type = img.image_type
        row.page_number = img.page_number
        row.chapter = img.chapter
        row.section = img.section
        row.surrounding_text = img.surrounding_text
        row.storage_key = img.storage_key
        row.storage_url = img.storage_url
        row.format = img.format
        row.width = img.width
        row.height = img.height
        row.file_size_bytes = img.file_size_bytes
        row.original_format = img.original_format
        row.alt_text_fr = img.alt_text_fr
        row.alt_text_en = img.alt_text_en
        row.semantic_tags = img.semantic_tags
        row.created_at = img.created_at
        row.similarity = 0.85

        mock_result = MagicMock()
        mock_result.fetchall.return_value = [row]
        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)

        result = await retriever.search_source_images("epidemiology diagram", session=session)

        assert len(result) == 1
        assert result[0]["id"] == str(img.id)
        assert result[0]["similarity"] == pytest.approx(0.85)
        assert "storage_url" in result[0]
