"""Tests for source image injection into lesson prompts and responses."""

import uuid
from unittest.mock import MagicMock

from app.ai.prompts.lesson import format_rag_context_for_lesson
from app.api.v1.schemas.content import LessonResponse, SourceImageRef
from app.domain.services.lesson_service import LessonGenerationService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_chunk(chunk_id=None, source="donaldson", chapter="3", page=45, content="Some content."):
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
    sr.similarity_score = 0.9
    return sr


def _make_image_meta(
    img_id=None,
    figure_number="1.3",
    caption="Steps in the Marketing Process",
    image_type="diagram",
    storage_url="https://cdn.example.com/img/test.webp",
    alt_text_fr="Diagramme",
    alt_text_en="Diagram",
):
    return {
        "id": str(img_id or uuid.uuid4()),
        "figure_number": figure_number,
        "caption": caption,
        "image_type": image_type,
        "storage_url": storage_url,
        "alt_text_fr": alt_text_fr,
        "alt_text_en": alt_text_en,
    }


# ---------------------------------------------------------------------------
# Tests: format_rag_context_for_lesson
# ---------------------------------------------------------------------------


class TestFormatRagContextForLesson:
    def test_no_images_produces_same_output_as_before(self):
        chunks = [_make_search_result()]
        result = format_rag_context_for_lesson(chunks, "epidemiology", "M01", "M01-U01", "fr")
        assert "DOCUMENTS DE RÉFÉRENCE" in result
        assert "FIGURE DISPONIBLE" not in result

    def test_with_linked_images_appends_annotation_fr(self):
        chunk_id = uuid.uuid4()
        img = _make_image_meta()
        chunks = [_make_search_result(chunk_id=chunk_id)]
        linked = {chunk_id: [img]}
        result = format_rag_context_for_lesson(
            chunks, "epidemiology", "M01", "M01-U01", "fr", linked_images=linked
        )
        assert "FIGURE DISPONIBLE" in result
        assert img["id"] in result
        assert "source_image:" in result

    def test_with_linked_images_appends_annotation_en(self):
        chunk_id = uuid.uuid4()
        img = _make_image_meta()
        chunks = [_make_search_result(chunk_id=chunk_id)]
        linked = {chunk_id: [img]}
        result = format_rag_context_for_lesson(
            chunks, "epidemiology", "M01", "M01-U01", "en", linked_images=linked
        )
        assert "FIGURE AVAILABLE" in result
        assert img["id"] in result

    def test_caps_at_5_total_annotations(self):
        chunks = []
        linked = {}
        for _ in range(8):
            cid = uuid.uuid4()
            sr = _make_search_result(chunk_id=cid)
            chunks.append(sr)
            linked[cid] = [_make_image_meta()]
        result = format_rag_context_for_lesson(
            chunks, "query", "M01", "M01-U01", "en", linked_images=linked
        )
        count = result.count("source_image:")
        assert count <= 5

    def test_empty_linked_images_dict_no_annotation(self):
        chunks = [_make_search_result()]
        result = format_rag_context_for_lesson(
            chunks, "q", "M01", "M01-U01", "en", linked_images={}
        )
        assert "FIGURE AVAILABLE" not in result

    def test_none_linked_images_no_annotation(self):
        chunks = [_make_search_result()]
        result = format_rag_context_for_lesson(
            chunks, "q", "M01", "M01-U01", "fr", linked_images=None
        )
        assert "FIGURE DISPONIBLE" not in result

    def test_annotation_includes_figure_number_and_caption(self):
        chunk_id = uuid.uuid4()
        img = _make_image_meta(figure_number="2.5", caption="Epidemiology cycle")
        chunks = [_make_search_result(chunk_id=chunk_id)]
        result = format_rag_context_for_lesson(
            chunks, "q", "M01", "M01-U01", "en", linked_images={chunk_id: [img]}
        )
        assert "Figure 2.5" in result
        assert "Epidemiology cycle" in result

    def test_chunk_without_id_skips_images(self):
        sr = MagicMock()
        sr.chunk = MagicMock()
        sr.chunk.id = None
        sr.chunk.content = "Content"
        sr.chunk.source = "donaldson"
        sr.chunk.chapter = "1"
        sr.chunk.page = 10
        result = format_rag_context_for_lesson([sr], "q", "M01", "M01-U01", "en", linked_images={})
        assert "FIGURE AVAILABLE" not in result


# ---------------------------------------------------------------------------
# Tests: SourceImageRef schema
# ---------------------------------------------------------------------------


class TestSourceImageRefSchema:
    def test_valid_schema_creation(self):
        ref = SourceImageRef(
            id=str(uuid.uuid4()),
            figure_number="1.3",
            caption="Test caption",
            image_type="diagram",
            storage_url="https://cdn.example.com/img.webp",
            alt_text_fr="Diagramme",
            alt_text_en="Diagram",
        )
        assert ref.image_type == "diagram"

    def test_optional_fields_default_to_none(self):
        ref = SourceImageRef(id=str(uuid.uuid4()), image_type="photo")
        assert ref.figure_number is None
        assert ref.caption is None
        assert ref.storage_url is None
        assert ref.alt_text_fr is None
        assert ref.alt_text_en is None


# ---------------------------------------------------------------------------
# Tests: LessonResponse.source_image_refs
# ---------------------------------------------------------------------------


class TestLessonResponseSourceImageRefs:
    def _make_lesson_response(self, refs=None):
        from app.api.v1.schemas.content import LessonContent

        content = LessonContent(
            introduction="Intro",
            concepts=["Concept 1"],
            aof_example="Example",
            synthesis="Synthesis",
            key_points=["Point 1"],
            sources_cited=["Donaldson Ch.1"],
        )
        return LessonResponse(
            module_id=uuid.uuid4(),
            unit_id="M01-U01",
            language="fr",
            level=1,
            country_context="SN",
            content=content,
            generated_at="2026-01-01T00:00:00",
            source_image_refs=refs or [],
        )

    def test_source_image_refs_defaults_to_empty_list(self):
        resp = self._make_lesson_response()
        assert resp.source_image_refs == []

    def test_source_image_refs_populated(self):
        ref = SourceImageRef(id=str(uuid.uuid4()), image_type="chart")
        resp = self._make_lesson_response(refs=[ref])
        assert len(resp.source_image_refs) == 1
        assert resp.source_image_refs[0].image_type == "chart"

    def test_model_dump_includes_source_image_refs(self):
        ref = SourceImageRef(id=str(uuid.uuid4()), image_type="diagram")
        resp = self._make_lesson_response(refs=[ref])
        dumped = resp.model_dump()
        assert "source_image_refs" in dumped
        assert len(dumped["source_image_refs"]) == 1


# ---------------------------------------------------------------------------
# Tests: LessonGenerationService._extract_source_image_refs
# ---------------------------------------------------------------------------


class TestExtractSourceImageRefs:
    def _make_linked_images(self, img_ids):
        cid = uuid.uuid4()
        images = [_make_image_meta(img_id=uuid.UUID(i)) for i in img_ids]
        return {cid: images}

    async def test_no_markers_returns_empty(self):
        result = await LessonGenerationService._extract_source_image_refs("No markers here.", {})
        assert result == []

    async def test_single_marker_resolved(self):
        img_id = str(uuid.uuid4())
        text = f"See figure {{{{source_image:{img_id}}}}}"
        linked = {uuid.uuid4(): [_make_image_meta(img_id=uuid.UUID(img_id))]}
        result = await LessonGenerationService._extract_source_image_refs(text, linked)
        assert len(result) == 1
        assert result[0].id == img_id

    async def test_duplicate_markers_deduplicated(self):
        img_id = str(uuid.uuid4())
        text = f"Figure {{{{source_image:{img_id}}}}} and again {{{{source_image:{img_id}}}}}"
        linked = {uuid.uuid4(): [_make_image_meta(img_id=uuid.UUID(img_id))]}
        result = await LessonGenerationService._extract_source_image_refs(text, linked)
        assert len(result) == 1

    async def test_unknown_id_skipped(self):
        random_id = str(uuid.uuid4())
        text = f"See {{{{source_image:{random_id}}}}}"
        result = await LessonGenerationService._extract_source_image_refs(text, {})
        assert result == []

    async def test_multiple_distinct_markers(self):
        id1 = str(uuid.uuid4())
        id2 = str(uuid.uuid4())
        text = f"{{{{source_image:{id1}}}}} and {{{{source_image:{id2}}}}}"
        cid = uuid.uuid4()
        linked = {
            cid: [
                _make_image_meta(img_id=uuid.UUID(id1)),
                _make_image_meta(img_id=uuid.UUID(id2)),
            ]
        }
        result = await LessonGenerationService._extract_source_image_refs(text, linked)
        assert len(result) == 2

    async def test_ref_fields_populated_correctly(self):
        img_id = str(uuid.uuid4())
        text = f"{{{{source_image:{img_id}}}}}"
        img_meta = _make_image_meta(
            img_id=uuid.UUID(img_id),
            figure_number="3.1",
            caption="A diagram",
            image_type="diagram",
            storage_url="https://cdn.example.com/x.webp",
            alt_text_fr="Diag FR",
            alt_text_en="Diag EN",
        )
        linked = {uuid.uuid4(): [img_meta]}
        result = await LessonGenerationService._extract_source_image_refs(text, linked)
        assert result[0].figure_number == "3.1"
        assert result[0].caption == "A diagram"
        assert result[0].image_type == "diagram"
        assert result[0].storage_url == "https://cdn.example.com/x.webp"
        assert result[0].alt_text_fr == "Diag FR"
        assert result[0].alt_text_en == "Diag EN"
