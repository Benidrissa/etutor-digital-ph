"""Tests for source image injection into lesson generation prompts (issue #741)."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.ai.prompts.lesson import format_rag_context_for_lesson
from app.ai.rag.retriever import LinkedImage, SemanticRetriever
from app.domain.models.document_chunk import DocumentChunk
from app.domain.services.lesson_service import LessonGenerationService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_chunk(chunk_id: str | None = None) -> MagicMock:
    chunk = MagicMock(spec=DocumentChunk)
    chunk.id = chunk_id or str(uuid.uuid4())
    chunk.content = "Public health surveillance monitors disease patterns."
    chunk.source = "donaldson"
    chunk.chapter = "3"
    chunk.page = 45
    return chunk


def _make_search_result(chunk_id: str | None = None) -> MagicMock:
    result = MagicMock()
    result.chunk = _make_chunk(chunk_id)
    result.similarity_score = 0.85
    return result


def _make_linked_image(
    image_id: str | None = None,
    chunk_id: str | None = None,
    figure_number: str = "1.3",
    caption: str = "Steps in the Marketing Process",
    image_type: str = "diagram",
) -> LinkedImage:
    return LinkedImage(
        id=image_id or str(uuid.uuid4()),
        chunk_id=chunk_id or str(uuid.uuid4()),
        figure_number=figure_number,
        caption=caption,
        image_type=image_type,
        storage_url="https://storage.example.com/images/fig-1-3.webp",
        alt_text_fr="Schéma des étapes du processus",
        alt_text_en="Diagram of process steps",
    )


# ---------------------------------------------------------------------------
# format_rag_context_for_lesson — image annotation tests
# ---------------------------------------------------------------------------


class TestFormatRagContextImageAnnotations:
    def test_no_linked_images_produces_no_annotation(self):
        chunk_id = str(uuid.uuid4())
        chunks = [_make_search_result(chunk_id)]
        result = format_rag_context_for_lesson(chunks, "surveillance", "Module 1", "M01-U01", "fr")
        assert "FIGURE DISPONIBLE" not in result
        assert "source_image:" not in result

    def test_linked_image_produces_fr_annotation(self):
        chunk_id = str(uuid.uuid4())
        chunks = [_make_search_result(chunk_id)]
        img_id = str(uuid.uuid4())
        linked_images = [_make_linked_image(image_id=img_id, chunk_id=chunk_id)]

        result = format_rag_context_for_lesson(
            chunks, "surveillance", "Module 1", "M01-U01", "fr", linked_images=linked_images
        )

        assert "FIGURE DISPONIBLE" in result
        assert img_id in result
        assert "source_image:" in result

    def test_linked_image_produces_en_annotation(self):
        chunk_id = str(uuid.uuid4())
        chunks = [_make_search_result(chunk_id)]
        img_id = str(uuid.uuid4())
        linked_images = [_make_linked_image(image_id=img_id, chunk_id=chunk_id)]

        result = format_rag_context_for_lesson(
            chunks, "surveillance", "Module 1", "M01-U01", "en", linked_images=linked_images
        )

        assert "FIGURE AVAILABLE" in result
        assert img_id in result

    def test_annotation_capped_at_five(self):
        chunk_id = str(uuid.uuid4())
        chunks = [_make_search_result(chunk_id)]

        linked_images = [
            _make_linked_image(image_id=str(uuid.uuid4()), chunk_id=chunk_id) for _ in range(8)
        ]

        result = format_rag_context_for_lesson(
            chunks, "surveillance", "Module 1", "M01-U01", "fr", linked_images=linked_images
        )

        assert result.count("source_image:") <= 5

    def test_image_not_linked_to_chunk_not_annotated(self):
        chunk_id = str(uuid.uuid4())
        other_chunk_id = str(uuid.uuid4())
        chunks = [_make_search_result(chunk_id)]
        img_id = str(uuid.uuid4())
        linked_images = [_make_linked_image(image_id=img_id, chunk_id=other_chunk_id)]

        result = format_rag_context_for_lesson(
            chunks, "surveillance", "Module 1", "M01-U01", "fr", linked_images=linked_images
        )

        assert "FIGURE DISPONIBLE" not in result
        assert img_id not in result

    def test_annotation_includes_figure_number_and_caption(self):
        chunk_id = str(uuid.uuid4())
        chunks = [_make_search_result(chunk_id)]
        img_id = str(uuid.uuid4())
        linked_images = [
            _make_linked_image(
                image_id=img_id,
                chunk_id=chunk_id,
                figure_number="Figure 3.2",
                caption="Epidemiological Triangle",
                image_type="diagram",
            )
        ]

        result = format_rag_context_for_lesson(
            chunks, "surveillance", "Module 1", "M01-U01", "fr", linked_images=linked_images
        )

        assert "Figure 3.2" in result
        assert "Epidemiological Triangle" in result
        assert "diagram" in result


# ---------------------------------------------------------------------------
# LessonGenerationService._extract_source_image_refs
# ---------------------------------------------------------------------------


class TestExtractSourceImageRefs:
    def _make_service(self):
        return LessonGenerationService(
            claude_service=AsyncMock(),
            semantic_retriever=AsyncMock(spec=SemanticRetriever),
        )

    def test_no_markers_returns_empty_list(self):
        service = self._make_service()
        refs = service._extract_source_image_refs("No markers here.", [])
        assert refs == []

    def test_extracts_single_marker(self):
        img_id = str(uuid.uuid4())
        img = _make_linked_image(image_id=img_id)
        content = f"See the figure {{{{source_image:{img_id}}}}} for details."

        refs = LessonGenerationService._extract_source_image_refs(content, [img])

        assert len(refs) == 1
        assert refs[0].id == img_id
        assert refs[0].image_type == img.image_type

    def test_unknown_uuid_not_in_refs(self):
        known_id = str(uuid.uuid4())
        unknown_id = str(uuid.uuid4())
        img = _make_linked_image(image_id=known_id)
        content = (
            f"Ref1: {{{{source_image:{unknown_id}}}}} and Ref2: {{{{source_image:{known_id}}}}}."
        )

        refs = LessonGenerationService._extract_source_image_refs(content, [img])

        assert len(refs) == 1
        assert refs[0].id == known_id

    def test_duplicate_markers_de_duplicated(self):
        img_id = str(uuid.uuid4())
        img = _make_linked_image(image_id=img_id)
        content = f"First: {{{{source_image:{img_id}}}}} Second: {{{{source_image:{img_id}}}}}."

        refs = LessonGenerationService._extract_source_image_refs(content, [img])

        assert len(refs) == 1

    def test_ref_fields_mapped_from_linked_image(self):
        img_id = str(uuid.uuid4())
        img = LinkedImage(
            id=img_id,
            chunk_id=str(uuid.uuid4()),
            figure_number="2.1",
            caption="Public Health Model",
            image_type="chart",
            storage_url="https://cdn.example.com/img.webp",
            alt_text_fr="Modèle de santé publique",
            alt_text_en="Public Health Model",
        )
        content = f"{{{{source_image:{img_id}}}}}"

        refs = LessonGenerationService._extract_source_image_refs(content, [img])

        assert len(refs) == 1
        ref = refs[0]
        assert ref.figure_number == "2.1"
        assert ref.caption == "Public Health Model"
        assert ref.image_type == "chart"
        assert ref.storage_url == "https://cdn.example.com/img.webp"
        assert ref.alt_text_fr == "Modèle de santé publique"
        assert ref.alt_text_en == "Public Health Model"


# ---------------------------------------------------------------------------
# SemanticRetriever.get_linked_images — graceful fallback
# ---------------------------------------------------------------------------


class TestGetLinkedImages:
    @pytest.fixture
    def retriever(self):
        return SemanticRetriever(embedding_service=AsyncMock())

    @pytest.mark.asyncio
    async def test_empty_chunk_ids_returns_empty(self, retriever):
        session = AsyncMock()
        result = await retriever.get_linked_images([], session)
        assert result == []
        session.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_empty_on_db_error(self, retriever):
        session = AsyncMock()
        session.execute.side_effect = Exception("relation does not exist")

        result = await retriever.get_linked_images(["some-uuid"], session)
        assert result == []

    @pytest.mark.asyncio
    async def test_maps_rows_to_linked_images(self, retriever):
        img_id = str(uuid.uuid4())
        chunk_id = str(uuid.uuid4())

        row = MagicMock()
        row.id = img_id
        row.chunk_id = chunk_id
        row.figure_number = "1.1"
        row.caption = "Test Caption"
        row.image_type = "diagram"
        row.storage_url = "https://example.com/img.webp"
        row.alt_text_fr = "Alt FR"
        row.alt_text_en = "Alt EN"

        mock_result = MagicMock()
        mock_result.fetchall.return_value = [row]
        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)

        results = await retriever.get_linked_images([chunk_id], session)

        assert len(results) == 1
        assert results[0].id == img_id
        assert results[0].chunk_id == chunk_id
        assert results[0].figure_number == "1.1"
        assert results[0].image_type == "diagram"

    @pytest.mark.asyncio
    async def test_max_images_respected(self, retriever):
        rows = []
        for _ in range(3):
            row = MagicMock()
            row.id = str(uuid.uuid4())
            row.chunk_id = str(uuid.uuid4())
            row.figure_number = None
            row.caption = None
            row.image_type = "unknown"
            row.storage_url = "https://example.com/img.webp"
            row.alt_text_fr = None
            row.alt_text_en = None
            rows.append(row)

        mock_result = MagicMock()
        mock_result.fetchall.return_value = rows
        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)

        results = await retriever.get_linked_images(
            [r.chunk_id for r in rows], session, max_images=2
        )

        assert len(results) == 3
