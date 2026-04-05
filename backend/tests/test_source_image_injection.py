"""Tests for source image injection into lesson generation prompts."""

import uuid
from unittest.mock import MagicMock

from app.ai.prompts.lesson import format_rag_context_for_lesson, get_lesson_system_prompt
from app.api.v1.schemas.content import LessonContent, LessonResponse, SourceImageRef
from app.domain.services.lesson_service import LessonGenerationService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_chunk(chunk_id=None, source="donaldson", chapter="3", page=45, content="Test content."):
    chunk = MagicMock()
    chunk.id = chunk_id or uuid.uuid4()
    chunk.content = content
    chunk.source = source
    chunk.chapter = chapter
    chunk.page = page
    return chunk


def _make_search_result(chunk_id=None, **kwargs):
    sr = MagicMock()
    sr.chunk = _make_chunk(chunk_id=chunk_id, **kwargs)
    return sr


def _make_image_meta(
    image_id=None, figure_number="1.3", caption="Test figure", image_type="diagram"
):
    return {
        "id": str(image_id or uuid.uuid4()),
        "figure_number": figure_number,
        "caption": caption,
        "image_type": image_type,
        "storage_url": "https://cdn.example.com/img/test.webp",
        "alt_text_fr": "Diagramme de test",
        "alt_text_en": "Test diagram",
    }


# ---------------------------------------------------------------------------
# SourceImageRef schema tests
# ---------------------------------------------------------------------------


class TestSourceImageRefSchema:
    def test_minimal_fields(self):
        ref = SourceImageRef(id="abc-123", image_type="diagram")
        assert ref.id == "abc-123"
        assert ref.image_type == "diagram"
        assert ref.figure_number is None
        assert ref.caption is None
        assert ref.storage_url is None

    def test_all_fields(self):
        ref = SourceImageRef(
            id="abc-123",
            figure_number="1.3",
            caption="Steps in the Marketing Process",
            image_type="diagram",
            storage_url="https://cdn.example.com/img.webp",
            alt_text_fr="Diagramme",
            alt_text_en="Diagram",
        )
        assert ref.figure_number == "1.3"
        assert ref.caption == "Steps in the Marketing Process"
        assert ref.storage_url == "https://cdn.example.com/img.webp"


def _make_lesson_content(**overrides):
    defaults = dict(
        introduction="intro",
        concepts=["concept"],
        aof_example="example",
        synthesis="synthesis",
        key_points=["point"],
        sources_cited=["src"],
    )
    defaults.update(overrides)
    return LessonContent(**defaults)


class TestLessonResponseSourceImageRefs:
    def test_default_empty_list(self):
        resp = LessonResponse(
            module_id=uuid.uuid4(),
            unit_id="M01-U01",
            language="fr",
            level=1,
            country_context="SN",
            content=_make_lesson_content(),
            generated_at="2026-01-01T00:00:00",
        )
        assert resp.source_image_refs == []

    def test_accepts_source_image_refs(self):
        ref = SourceImageRef(id="abc", image_type="diagram")
        resp = LessonResponse(
            module_id=uuid.uuid4(),
            unit_id="M01-U01",
            language="fr",
            level=1,
            country_context="SN",
            content=_make_lesson_content(),
            generated_at="2026-01-01T00:00:00",
            source_image_refs=[ref],
        )
        assert len(resp.source_image_refs) == 1
        assert resp.source_image_refs[0].id == "abc"


# ---------------------------------------------------------------------------
# format_rag_context_for_lesson tests
# ---------------------------------------------------------------------------


class TestFormatRagContextWithImages:
    def test_no_linked_images_works_as_before(self):
        chunk = _make_search_result()
        result = format_rag_context_for_lesson([chunk], "epidemiology", "Module 1", "M01-U01", "fr")
        assert "DEMANDE" in result
        assert "DOCUMENTS DE RÉFÉRENCE" in result
        assert "FIGURE DISPONIBLE" not in result

    def test_no_linked_images_en(self):
        chunk = _make_search_result()
        result = format_rag_context_for_lesson([chunk], "epidemiology", "Module 1", "M01-U01", "en")
        assert "REQUEST" in result
        assert "FIGURE AVAILABLE" not in result

    def test_image_annotation_appended_when_linked(self):
        chunk_id = uuid.uuid4()
        chunk = _make_search_result(chunk_id=chunk_id)
        img = _make_image_meta(figure_number="1.3", caption="Test figure")
        linked_images = {chunk_id: [img]}

        result = format_rag_context_for_lesson(
            [chunk], "epidemiology", "Module 1", "M01-U01", "fr", linked_images=linked_images
        )
        assert "FIGURE DISPONIBLE" in result
        assert img["id"] in result
        assert "{{source_image:" in result

    def test_caps_at_5_total_annotations(self):
        chunk_ids = [uuid.uuid4() for _ in range(3)]
        chunks = [_make_search_result(chunk_id=cid) for cid in chunk_ids]
        linked_images = {cid: [_make_image_meta() for _ in range(3)] for cid in chunk_ids}

        result = format_rag_context_for_lesson(
            chunks, "query", "Module", "M01-U01", "fr", linked_images=linked_images
        )
        count = result.count("{{source_image:")
        assert count <= 5

    def test_no_annotations_for_unknown_chunk(self):
        chunk = _make_search_result()
        other_id = uuid.uuid4()
        linked_images = {other_id: [_make_image_meta()]}

        result = format_rag_context_for_lesson(
            [chunk], "query", "Module", "M01-U01", "fr", linked_images=linked_images
        )
        assert "FIGURE DISPONIBLE" not in result

    def test_empty_linked_images_dict(self):
        chunk = _make_search_result()
        result = format_rag_context_for_lesson(
            [chunk], "query", "Module", "M01-U01", "fr", linked_images={}
        )
        assert "FIGURE DISPONIBLE" not in result


# ---------------------------------------------------------------------------
# get_lesson_system_prompt tests
# ---------------------------------------------------------------------------


class TestGetLessonSystemPromptImages:
    def test_fr_prompt_contains_source_image_syntax(self):
        prompt = get_lesson_system_prompt("fr", "SN", 1, "remember")
        assert "source_image" in prompt
        assert "FIGURES DE RÉFÉRENCE" in prompt

    def test_en_prompt_contains_source_image_syntax(self):
        prompt = get_lesson_system_prompt("en", "SN", 1, "remember")
        assert "source_image" in prompt
        assert "REFERENCE FIGURES" in prompt

    def test_fr_prompt_max_3_markers_instruction(self):
        prompt = get_lesson_system_prompt("fr", "SN", 2, "apply")
        assert "3" in prompt

    def test_en_prompt_max_3_markers_instruction(self):
        prompt = get_lesson_system_prompt("en", "GH", 2, "apply")
        assert "3" in prompt


# ---------------------------------------------------------------------------
# _extract_source_image_refs tests
# ---------------------------------------------------------------------------


class TestExtractSourceImageRefs:
    def test_no_markers_returns_empty(self):
        refs = LessonGenerationService._extract_source_image_refs("No markers here.", [])
        assert refs == []

    def test_extracts_single_marker(self):
        img_id = str(uuid.uuid4())
        img = _make_image_meta(image_id=uuid.UUID(img_id))
        text = f"See diagram {{{{source_image:{img_id}}}}} for details."
        refs = LessonGenerationService._extract_source_image_refs(text, [img])
        assert len(refs) == 1
        assert refs[0].id == img_id

    def test_extracts_multiple_markers(self):
        ids = [str(uuid.uuid4()) for _ in range(3)]
        images = [_make_image_meta(image_id=uuid.UUID(i)) for i in ids]
        text = " ".join(f"{{{{source_image:{i}}}}}" for i in ids)
        refs = LessonGenerationService._extract_source_image_refs(text, images)
        assert len(refs) == 3

    def test_deduplicates_repeated_marker(self):
        img_id = str(uuid.uuid4())
        img = _make_image_meta(image_id=uuid.UUID(img_id))
        text = f"{{{{source_image:{img_id}}}}} and again {{{{source_image:{img_id}}}}}"
        refs = LessonGenerationService._extract_source_image_refs(text, [img])
        assert len(refs) == 1

    def test_unknown_uuid_not_included(self):
        unknown_id = str(uuid.uuid4())
        text = f"{{{{source_image:{unknown_id}}}}}"
        refs = LessonGenerationService._extract_source_image_refs(text, [])
        assert refs == []

    def test_ref_fields_populated_correctly(self):
        img_id = str(uuid.uuid4())
        img = {
            "id": img_id,
            "figure_number": "2.1",
            "caption": "Epidemiological triangle",
            "image_type": "diagram",
            "storage_url": "https://cdn.example.com/img.webp",
            "alt_text_fr": "Triangle épidémiologique",
            "alt_text_en": "Epidemiological triangle",
        }
        text = f"{{{{source_image:{img_id}}}}}"
        refs = LessonGenerationService._extract_source_image_refs(text, [img])
        assert refs[0].figure_number == "2.1"
        assert refs[0].caption == "Epidemiological triangle"
        assert refs[0].image_type == "diagram"
        assert refs[0].storage_url == "https://cdn.example.com/img.webp"
        assert refs[0].alt_text_fr == "Triangle épidémiologique"

    def test_empty_available_images_returns_empty(self):
        img_id = str(uuid.uuid4())
        text = f"{{{{source_image:{img_id}}}}}"
        refs = LessonGenerationService._extract_source_image_refs(text, [])
        assert refs == []
