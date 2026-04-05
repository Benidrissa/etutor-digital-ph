"""Tests for source image injection into lesson generation prompts."""

import re
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.ai.prompts.lesson import format_rag_context_for_lesson, get_lesson_system_prompt
from app.ai.rag.retriever import LinkedImage, SemanticRetriever
from app.api.v1.schemas.content import LessonContent, LessonResponse, SourceImageRef
from app.domain.services.lesson_service import LessonGenerationService


def _make_lesson_content() -> LessonContent:
    return LessonContent(
        introduction="intro",
        concepts=["concept"],
        aof_example="example",
        synthesis="synthesis",
        key_points=["key point"],
        sources_cited=["Donaldson Ch.3"],
    )


def _make_chunk(chunk_id: uuid.UUID | None = None, content: str = "Some content") -> MagicMock:
    chunk = MagicMock()
    chunk.id = chunk_id or uuid.uuid4()
    chunk.content = content
    chunk.source = "donaldson"
    chunk.chapter = "3"
    chunk.page = "45"
    return chunk


def _make_search_result(chunk_id: uuid.UUID | None = None, content: str = "Some content"):
    sr = MagicMock()
    inner = _make_chunk(chunk_id, content)
    sr.chunk = inner
    sr.similarity_score = 0.9
    return sr


def _make_linked_image(
    chunk_id: uuid.UUID | None = None,
    figure_number: str | None = "1.3",
    caption: str | None = "Steps in the Marketing Process",
    image_type: str | None = "diagram",
) -> LinkedImage:
    return LinkedImage(
        id=uuid.uuid4(),
        chunk_id=chunk_id or uuid.uuid4(),
        figure_number=figure_number,
        caption=caption,
        image_type=image_type,
        storage_url="https://storage.example.com/img.webp",
        alt_text_fr="Schéma des étapes",
        alt_text_en="Steps diagram",
    )


class TestFormatRagContextNoImages:
    def test_no_images_returns_normal_context(self):
        chunks = [_make_search_result()]
        result = format_rag_context_for_lesson(chunks, "query", "Module 1", "M01-U01", "fr")
        assert "Extrait 1" in result
        assert "FIGURE DISPONIBLE" not in result

    def test_none_linked_images_backward_compat(self):
        chunks = [_make_search_result()]
        result = format_rag_context_for_lesson(
            chunks, "query", "Module 1", "M01-U01", "fr", linked_images=None
        )
        assert "FIGURE DISPONIBLE" not in result

    def test_empty_linked_images_list(self):
        chunks = [_make_search_result()]
        result = format_rag_context_for_lesson(
            chunks, "query", "Module 1", "M01-U01", "fr", linked_images=[]
        )
        assert "FIGURE DISPONIBLE" not in result


class TestFormatRagContextWithImages:
    def test_image_annotation_appended_to_chunk(self):
        chunk_id = uuid.uuid4()
        sr = _make_search_result(chunk_id=chunk_id)
        img = _make_linked_image(chunk_id=chunk_id)
        result = format_rag_context_for_lesson(
            [sr], "query", "Module 1", "M01-U01", "fr", linked_images=[img]
        )
        assert "FIGURE DISPONIBLE" in result
        assert str(img.id) in result
        assert "source_image:" in result

    def test_annotation_includes_figure_number_and_caption(self):
        chunk_id = uuid.uuid4()
        sr = _make_search_result(chunk_id=chunk_id)
        img = _make_linked_image(chunk_id=chunk_id, figure_number="3.7", caption="Mortality curve")
        result = format_rag_context_for_lesson(
            [sr], "query", "Module 1", "M01-U01", "en", linked_images=[img]
        )
        assert "3.7" in result
        assert "Mortality curve" in result

    def test_cap_at_5_annotations(self):
        chunk_ids = [uuid.uuid4() for _ in range(6)]
        chunks = [_make_search_result(chunk_id=cid) for cid in chunk_ids]
        images = [_make_linked_image(chunk_id=cid) for cid in chunk_ids]
        result = format_rag_context_for_lesson(
            chunks, "query", "Module 1", "M01-U01", "fr", linked_images=images
        )
        count = result.count("FIGURE DISPONIBLE")
        assert count == 5

    def test_image_only_appended_to_linked_chunk(self):
        chunk_a_id = uuid.uuid4()
        chunk_b_id = uuid.uuid4()
        sr_a = _make_search_result(chunk_id=chunk_a_id, content="Content A")
        sr_b = _make_search_result(chunk_id=chunk_b_id, content="Content B")
        img = _make_linked_image(chunk_id=chunk_a_id)
        result = format_rag_context_for_lesson(
            [sr_a, sr_b], "query", "Module 1", "M01-U01", "fr", linked_images=[img]
        )
        assert result.count("FIGURE DISPONIBLE") == 1

    def test_image_annotation_contains_uuid_marker(self):
        chunk_id = uuid.uuid4()
        sr = _make_search_result(chunk_id=chunk_id)
        img = _make_linked_image(chunk_id=chunk_id)
        result = format_rag_context_for_lesson(
            [sr], "query", "Module 1", "M01-U01", "fr", linked_images=[img]
        )
        pattern = re.compile(r"\{\{source_image:[0-9a-f\-]{36}\}\}")
        assert pattern.search(result) is not None


class TestSystemPromptSourceImageInstructions:
    def test_fr_system_prompt_contains_source_image_syntax(self):
        prompt = get_lesson_system_prompt("fr", "SN", 2, "application")
        assert "source_image" in prompt

    def test_en_system_prompt_contains_source_image_syntax(self):
        prompt = get_lesson_system_prompt("en", "GH", 2, "application")
        assert "source_image" in prompt

    def test_fr_prompt_mentions_max_3_references(self):
        prompt = get_lesson_system_prompt("fr", "SN", 1, "knowledge")
        assert "3" in prompt

    def test_en_prompt_mentions_max_3_references(self):
        prompt = get_lesson_system_prompt("en", "NG", 3, "analysis")
        assert "3" in prompt


class TestExtractSourceImageRefs:
    def test_no_markers_returns_empty(self):
        result = LessonGenerationService._extract_source_image_refs("No markers here.", [])
        assert result == []

    def test_no_linked_images_returns_empty(self):
        result = LessonGenerationService._extract_source_image_refs(
            "Some text {{source_image:abc123}}", []
        )
        assert result == []

    def test_extracts_known_uuid(self):
        img = _make_linked_image()
        content = f"See figure {{{{source_image:{img.id}}}}}"
        refs = LessonGenerationService._extract_source_image_refs(content, [img])
        assert len(refs) == 1
        assert refs[0].id == img.id

    def test_unknown_uuid_ignored(self):
        img = _make_linked_image()
        unknown_id = uuid.uuid4()
        content = f"See figure {{{{source_image:{unknown_id}}}}}"
        refs = LessonGenerationService._extract_source_image_refs(content, [img])
        assert refs == []

    def test_deduplicates_repeated_markers(self):
        img = _make_linked_image()
        content = f"{{{{source_image:{img.id}}}}} again {{{{source_image:{img.id}}}}}"
        refs = LessonGenerationService._extract_source_image_refs(content, [img])
        assert len(refs) == 1

    def test_ref_fields_populated_from_linked_image(self):
        img = _make_linked_image(
            figure_number="2.1",
            caption="Transmission cycle",
            image_type="diagram",
        )
        content = f"{{{{source_image:{img.id}}}}}"
        refs = LessonGenerationService._extract_source_image_refs(content, [img])
        assert refs[0].figure_number == "2.1"
        assert refs[0].caption == "Transmission cycle"
        assert refs[0].image_type == "diagram"
        assert refs[0].storage_url == img.storage_url


class TestSourceImageRefSchema:
    def test_source_image_ref_instantiation(self):
        uid = uuid.uuid4()
        ref = SourceImageRef(
            id=uid,
            figure_number="1.3",
            caption="Test figure",
            image_type="chart",
            storage_url="https://example.com/img.webp",
            alt_text_fr="Graphique",
            alt_text_en="Chart",
        )
        assert ref.id == uid
        assert ref.figure_number == "1.3"

    def test_source_image_ref_optional_fields_none(self):
        uid = uuid.uuid4()
        ref = SourceImageRef(id=uid)
        assert ref.figure_number is None
        assert ref.caption is None
        assert ref.storage_url is None

    def test_lesson_response_has_source_image_refs_field(self):
        uid = uuid.uuid4()
        ref = SourceImageRef(id=uid, caption="A figure")
        response = LessonResponse(
            module_id=uuid.uuid4(),
            unit_id="M01-U01",
            language="fr",
            level=1,
            country_context="SN",
            content=_make_lesson_content(),
            source_image_refs=[ref],
            generated_at="2026-04-05T00:00:00",
        )
        assert len(response.source_image_refs) == 1
        assert response.source_image_refs[0].id == uid

    def test_lesson_response_source_image_refs_defaults_empty(self):
        response = LessonResponse(
            module_id=uuid.uuid4(),
            unit_id="M01-U01",
            language="en",
            level=2,
            country_context="GH",
            content=_make_lesson_content(),
            generated_at="2026-04-05T00:00:00",
        )
        assert response.source_image_refs == []


class TestLinkedImageRetrieverGracefulFallback:
    @pytest.mark.asyncio
    async def test_get_linked_images_empty_chunk_ids(self):
        retriever = SemanticRetriever(embedding_service=MagicMock())
        session = AsyncMock()
        result = await retriever.get_linked_images([], session)
        assert result == []
        session.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_linked_images_db_error_returns_empty(self):
        retriever = SemanticRetriever(embedding_service=MagicMock())
        session = AsyncMock()
        session.execute.side_effect = Exception("table source_images does not exist")
        result = await retriever.get_linked_images([uuid.uuid4()], session)
        assert result == []
