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
    caption_fr=None,
    caption_en=None,
    image_type="diagram",
    storage_url="https://cdn.example.com/img/test.webp",
    storage_url_fr=None,
    alt_text_fr="Diagramme",
    alt_text_en="Diagram",
):
    return {
        "id": str(img_id or uuid.uuid4()),
        "figure_number": figure_number,
        "caption": caption,
        "caption_fr": caption_fr,
        "caption_en": caption_en,
        "image_type": image_type,
        "storage_url": storage_url,
        "storage_url_fr": storage_url_fr,
        "alt_text_fr": alt_text_fr,
        "alt_text_en": alt_text_en,
    }


# ---------------------------------------------------------------------------
# Tests: format_rag_context_for_lesson
# ---------------------------------------------------------------------------


class TestFormatRagContextForLesson:
    def test_no_images_produces_same_output_as_before(self):
        chunks = [_make_search_result()]
        result = format_rag_context_for_lesson(chunks, "epidemiology", "M01", "1.1", "fr")
        assert "DOCUMENTS DE RÉFÉRENCE" in result
        assert "FIGURE DISPONIBLE" not in result

    def test_with_linked_images_appends_annotation_fr(self):
        chunk_id = uuid.uuid4()
        img = _make_image_meta()
        chunks = [_make_search_result(chunk_id=chunk_id)]
        linked = {chunk_id: [img]}
        result = format_rag_context_for_lesson(
            chunks, "epidemiology", "M01", "1.1", "fr", linked_images=linked
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
            chunks, "epidemiology", "M01", "1.1", "en", linked_images=linked
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
            chunks, "query", "M01", "1.1", "en", linked_images=linked
        )
        count = result.count("source_image:")
        assert count <= 5

    def test_empty_linked_images_dict_no_annotation(self):
        chunks = [_make_search_result()]
        result = format_rag_context_for_lesson(chunks, "q", "M01", "1.1", "en", linked_images={})
        assert "FIGURE AVAILABLE" not in result

    def test_none_linked_images_no_annotation(self):
        chunks = [_make_search_result()]
        result = format_rag_context_for_lesson(chunks, "q", "M01", "1.1", "fr", linked_images=None)
        assert "FIGURE DISPONIBLE" not in result

    def test_annotation_includes_figure_number_and_caption(self):
        chunk_id = uuid.uuid4()
        img = _make_image_meta(figure_number="2.5", caption="Epidemiology cycle")
        chunks = [_make_search_result(chunk_id=chunk_id)]
        result = format_rag_context_for_lesson(
            chunks, "q", "M01", "1.1", "en", linked_images={chunk_id: [img]}
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
        result = format_rag_context_for_lesson([sr], "q", "M01", "1.1", "en", linked_images={})
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
            unit_id="1.1",
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

    async def test_caption_locale_prefers_translated_fields(self):
        img_id = str(uuid.uuid4())
        text = f"{{{{source_image:{img_id}}}}}"
        img_meta = _make_image_meta(
            img_id=uuid.UUID(img_id),
            caption="Steps in the scientific method",
            caption_fr="Étapes de la méthode scientifique",
            caption_en="Steps in the scientific method",
        )
        linked = {uuid.uuid4(): [img_meta]}
        result = await LessonGenerationService._extract_source_image_refs(text, linked)
        assert result[0].caption_fr == "Étapes de la méthode scientifique"
        assert result[0].caption_en == "Steps in the scientific method"

    async def test_caption_locale_falls_back_to_raw_when_null(self):
        img_id = str(uuid.uuid4())
        text = f"{{{{source_image:{img_id}}}}}"
        img_meta = _make_image_meta(
            img_id=uuid.UUID(img_id),
            caption="Raw caption",
            caption_fr=None,
            caption_en=None,
        )
        linked = {uuid.uuid4(): [img_meta]}
        result = await LessonGenerationService._extract_source_image_refs(text, linked)
        assert result[0].caption_fr == "Raw caption"
        assert result[0].caption_en == "Raw caption"

    async def test_caption_locale_partial_translation_mixed_with_fallback(self):
        img_id = str(uuid.uuid4())
        text = f"{{{{source_image:{img_id}}}}}"
        img_meta = _make_image_meta(
            img_id=uuid.UUID(img_id),
            caption="Scientific method",
            caption_fr="Méthode scientifique",
            caption_en=None,
        )
        linked = {uuid.uuid4(): [img_meta]}
        result = await LessonGenerationService._extract_source_image_refs(text, linked)
        assert result[0].caption_fr == "Méthode scientifique"
        assert result[0].caption_en == "Scientific method"


# ---------------------------------------------------------------------------
# Tests: LessonGenerationService._rehydrate_source_image_refs
# ---------------------------------------------------------------------------


def _make_db_image(
    img_id,
    caption="English caption",
    caption_fr=None,
    caption_en=None,
    alt_text_fr=None,
    alt_text_en=None,
    storage_url="https://cdn.example.com/x.webp",
    storage_url_fr=None,
    figure_number="1.1",
    image_type="diagram",
    attribution=None,
):
    m = MagicMock()
    m.id = img_id
    m.caption = caption
    m.caption_fr = caption_fr
    m.caption_en = caption_en
    m.alt_text_fr = alt_text_fr
    m.alt_text_en = alt_text_en
    m.storage_url = storage_url
    m.storage_url_fr = storage_url_fr
    m.figure_number = figure_number
    m.image_type = image_type
    m.attribution = attribution
    return m


class _FakeSession:
    def __init__(self, rows):
        self._rows = rows

    async def execute(self, stmt):
        result = MagicMock()
        scalars = MagicMock()
        scalars.all = MagicMock(return_value=list(self._rows))
        result.scalars = MagicMock(return_value=scalars)
        return result


class TestRehydrateSourceImageRefs:
    async def test_overlays_fresh_db_translations_over_cached_refs(self):
        img_id = uuid.uuid4()
        cached = [
            {
                "id": str(img_id),
                "figure_number": "1.1",
                "caption": "English caption",
                "caption_fr": "English caption",
                "caption_en": "English caption",
                "image_type": "diagram",
                "storage_url": "https://cdn.example.com/x.webp",
                "alt_text_fr": None,
                "alt_text_en": None,
            }
        ]
        db_row = _make_db_image(
            img_id,
            caption="English caption",
            caption_fr="Légende française",
            caption_en="English caption",
            alt_text_fr="Texte alt FR",
            alt_text_en="Alt text EN",
        )
        session = _FakeSession([db_row])
        out = await LessonGenerationService._rehydrate_source_image_refs(cached, session)
        assert len(out) == 1
        assert out[0].caption_fr == "Légende française"
        assert out[0].caption_en == "English caption"
        assert out[0].alt_text_fr == "Texte alt FR"
        assert out[0].alt_text_en == "Alt text EN"

    async def test_keeps_cached_values_when_db_row_not_found(self):
        img_id = uuid.uuid4()
        cached = [
            {
                "id": str(img_id),
                "caption": "Cached only",
                "caption_fr": "Cached only",
                "caption_en": "Cached only",
                "image_type": "diagram",
            }
        ]
        session = _FakeSession([])  # DB returns nothing
        out = await LessonGenerationService._rehydrate_source_image_refs(cached, session)
        assert out[0].caption_fr == "Cached only"

    async def test_falls_back_to_caption_when_db_locale_fields_still_null(self):
        img_id = uuid.uuid4()
        cached = [
            {
                "id": str(img_id),
                "caption": "Pre-backfill",
                "caption_fr": "Pre-backfill",
                "caption_en": "Pre-backfill",
                "image_type": "diagram",
            }
        ]
        db_row = _make_db_image(
            img_id,
            caption="Pre-backfill",
            caption_fr=None,
            caption_en=None,
        )
        session = _FakeSession([db_row])
        out = await LessonGenerationService._rehydrate_source_image_refs(cached, session)
        assert out[0].caption_fr == "Pre-backfill"
        assert out[0].caption_en == "Pre-backfill"

    async def test_session_none_returns_refs_unchanged(self):
        img_id = str(uuid.uuid4())
        cached = [
            {
                "id": img_id,
                "caption": "x",
                "caption_fr": "x",
                "caption_en": "x",
                "image_type": "diagram",
            }
        ]
        out = await LessonGenerationService._rehydrate_source_image_refs(cached, None)
        assert len(out) == 1
        assert out[0].id == img_id

    async def test_skips_invalid_ref_entries(self):
        cached = [
            {"id": str(uuid.uuid4()), "image_type": "diagram"},
            "not a dict",
            {"id": "not-a-uuid", "image_type": "diagram"},
        ]
        session = _FakeSession([])
        out = await LessonGenerationService._rehydrate_source_image_refs(cached, session)
        assert len(out) == 2  # second entry skipped entirely; third parsed but no DB overlay

    async def test_overlays_storage_url_fr_from_db(self):
        img_id = uuid.uuid4()
        cached = [
            {
                "id": str(img_id),
                "caption": "English caption",
                "image_type": "diagram",
                "storage_url": "https://cdn.example.com/default.webp",
                "storage_url_fr": None,
            }
        ]
        db_row = _make_db_image(
            img_id,
            storage_url="https://cdn.example.com/default.webp",
            storage_url_fr="https://cdn.example.com/fr.webp",
        )
        session = _FakeSession([db_row])
        out = await LessonGenerationService._rehydrate_source_image_refs(cached, session)
        assert out[0].storage_url_fr == "https://cdn.example.com/fr.webp"

    async def test_storage_url_fr_null_when_no_french_variant(self):
        img_id = uuid.uuid4()
        cached = [
            {
                "id": str(img_id),
                "caption": "English caption",
                "image_type": "diagram",
                "storage_url": "https://cdn.example.com/default.webp",
            }
        ]
        db_row = _make_db_image(img_id, storage_url_fr=None)
        session = _FakeSession([db_row])
        out = await LessonGenerationService._rehydrate_source_image_refs(cached, session)
        assert out[0].storage_url_fr is None


class TestExtractSourceImageRefsStorageUrlFr:
    async def test_storage_url_fr_passed_through_from_img_meta(self):
        img_id = str(uuid.uuid4())
        text = f"{{{{source_image:{img_id}}}}}"
        img_meta = _make_image_meta(
            img_id=uuid.UUID(img_id),
            storage_url="https://cdn.example.com/default.webp",
            storage_url_fr="https://cdn.example.com/fr.webp",
        )
        linked = {uuid.uuid4(): [img_meta]}
        result = await LessonGenerationService._extract_source_image_refs(text, linked)
        assert result[0].storage_url_fr == "https://cdn.example.com/fr.webp"

    async def test_storage_url_fr_null_when_not_in_meta(self):
        img_id = str(uuid.uuid4())
        text = f"{{{{source_image:{img_id}}}}}"
        img_meta = _make_image_meta(
            img_id=uuid.UUID(img_id),
            storage_url="https://cdn.example.com/default.webp",
        )
        linked = {uuid.uuid4(): [img_meta]}
        result = await LessonGenerationService._extract_source_image_refs(text, linked)
        assert result[0].storage_url_fr is None
