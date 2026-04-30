"""Unit tests for ImageLinker — explicit and contextual chunk↔image linkage."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.ai.rag.image_linker import _FIGURE_RE, ImageLinker, _normalize_figure_number

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uuid():
    return uuid.uuid4()


def _mock_session():
    session = AsyncMock()
    session.add_all = MagicMock()
    session.flush = AsyncMock()
    return session


def _make_execute_result(rows: list):
    result = MagicMock()
    result.all.return_value = rows
    return result


def _make_count_result(img: int, chunk: int):
    """Mock for the semantic-pass count probe (#2063). Returns a row with
    ``img_count`` and ``chunk_count`` accessible via ``.one()``.
    """
    row = MagicMock()
    row.img_count = img
    row.chunk_count = chunk
    result = MagicMock()
    result.one.return_value = row
    return result


# Default mock returned by `session.execute` once a test's explicit
# side_effect list is exhausted. Lets the semantic matcher (#2063) — which
# adds 1 count-probe DB call per linker run — short-circuit cleanly
# without forcing every existing test to extend its side_effect list.
def _semantic_default():
    return _make_count_result(0, 0)


@pytest.fixture(autouse=True)
def _async_mock_fallback(monkeypatch):
    """Patch AsyncMock so an exhausted side_effect list returns the
    semantic count-zero default instead of raising StopAsyncIteration."""
    import unittest.mock as _mock

    original = _mock.AsyncMock._execute_mock_call

    async def patched(self, *args, **kwargs):
        try:
            return await original(self, *args, **kwargs)
        except StopAsyncIteration:
            return _semantic_default()

    monkeypatch.setattr(_mock.AsyncMock, "_execute_mock_call", patched)
    yield


# ---------------------------------------------------------------------------
# Regex tests
# ---------------------------------------------------------------------------


class TestFigureRegex:
    def test_matches_simple_figure(self):
        matches = _FIGURE_RE.findall("See Figure 1.3 for details.")
        assert matches == ["1.3"]

    def test_matches_integer_figure(self):
        matches = _FIGURE_RE.findall("Figure 5 shows the trend.")
        assert matches == ["5"]

    def test_case_insensitive(self):
        matches = _FIGURE_RE.findall("figure 2.1 and FIGURE 3")
        assert "2.1" in matches
        assert "3" in matches

    def test_no_match(self):
        matches = _FIGURE_RE.findall("No figures here.")
        assert matches == []

    def test_multiple_figures(self):
        matches = _FIGURE_RE.findall("See Figure 1.1 and Figure 1.2.")
        assert matches == ["1.1", "1.2"]

    def test_matches_fig_abbreviation(self):
        matches = _FIGURE_RE.findall("See Fig. 3.2 above.")
        assert matches == ["3.2"]

    def test_matches_fig_without_dot(self):
        matches = _FIGURE_RE.findall("See Fig 4.1 for the chart.")
        assert matches == ["4.1"]

    def test_matches_dash_figure_number(self):
        matches = _FIGURE_RE.findall("See Figure 1-3 for details.")
        assert matches == ["1-3"]


# ---------------------------------------------------------------------------
# Normalisation helper
# ---------------------------------------------------------------------------


class TestNormalizeFigureNumber:
    def test_dot_unchanged(self):
        assert _normalize_figure_number("1.3") == "1.3"

    def test_dash_converted_to_dot(self):
        assert _normalize_figure_number("1-3") == "1.3"

    def test_strips_whitespace(self):
        assert _normalize_figure_number("  2.5  ") == "2.5"

    def test_integer_unchanged(self):
        assert _normalize_figure_number("5") == "5"


# ---------------------------------------------------------------------------
# link_images_to_chunks — explicit linkage
# ---------------------------------------------------------------------------


class TestExplicitLinkage:
    @pytest.mark.asyncio
    async def test_explicit_link_created_when_figure_matches(self):
        linker = ImageLinker()
        session = _mock_session()
        img_id = _uuid()
        chunk_id = _uuid()

        session.execute.side_effect = [
            _make_execute_result([(chunk_id, "See Figure 1.3 for the diagram.")]),
            _make_execute_result([(img_id, "1.3")]),
            _make_execute_result([]),
            _make_execute_result([(img_id, 5, "chapter_1")]),
            _make_execute_result([(chunk_id, 5, "chapter_1")]),
            _make_execute_result([]),
        ]

        count = await linker.link_images_to_chunks("donaldson", session)

        assert count >= 1
        session.add_all.assert_called_once()
        added = session.add_all.call_args[0][0]
        explicit_rows = [r for r in added if r.reference_type == "explicit"]
        assert len(explicit_rows) == 1
        assert explicit_rows[0].source_image_id == img_id
        assert explicit_rows[0].document_chunk_id == chunk_id

    @pytest.mark.asyncio
    async def test_explicit_link_dash_figure_number(self):
        """DB stores '1-3', text says 'Figure 1.3' — must still match after normalisation."""
        linker = ImageLinker()
        session = _mock_session()
        img_id = _uuid()
        chunk_id = _uuid()

        session.execute.side_effect = [
            _make_execute_result([(chunk_id, "See Figure 1.3 for the diagram.")]),
            _make_execute_result([(img_id, "1-3")]),
            _make_execute_result([]),
            _make_execute_result([(img_id, 5, None)]),
            _make_execute_result([(chunk_id, 5, None)]),
            _make_execute_result([]),
        ]

        count = await linker.link_images_to_chunks("donaldson", session)

        assert count >= 1
        added = session.add_all.call_args[0][0]
        explicit_rows = [r for r in added if r.reference_type == "explicit"]
        assert len(explicit_rows) == 1

    @pytest.mark.asyncio
    async def test_explicit_link_fig_abbreviation(self):
        """'Fig. 2.1' in chunk text should match image with figure_number '2.1'."""
        linker = ImageLinker()
        session = _mock_session()
        img_id = _uuid()
        chunk_id = _uuid()

        session.execute.side_effect = [
            _make_execute_result([(chunk_id, "As shown in Fig. 2.1, the data reveals...")]),
            _make_execute_result([(img_id, "2.1")]),
            _make_execute_result([]),
            _make_execute_result([(img_id, 10, None)]),
            _make_execute_result([(chunk_id, 10, None)]),
            _make_execute_result([]),
        ]

        await linker.link_images_to_chunks("donaldson", session)

        added = session.add_all.call_args[0][0]
        explicit_rows = [r for r in added if r.reference_type == "explicit"]
        assert len(explicit_rows) == 1

    @pytest.mark.asyncio
    async def test_no_explicit_link_when_figure_not_in_text(self):
        linker = ImageLinker()
        session = _mock_session()
        img_id = _uuid()
        chunk_id = _uuid()

        session.execute.side_effect = [
            _make_execute_result([(chunk_id, "No figures mentioned here.")]),
            _make_execute_result([(img_id, "1.3")]),
            _make_execute_result([]),
            _make_execute_result([(img_id, 3, None)]),
            _make_execute_result([]),
            _make_execute_result([]),
        ]

        count = await linker.link_images_to_chunks("donaldson", session)

        assert count == 0

    @pytest.mark.asyncio
    async def test_no_explicit_link_when_no_matching_image(self):
        linker = ImageLinker()
        session = _mock_session()
        chunk_id = _uuid()

        session.execute.side_effect = [
            _make_execute_result([(chunk_id, "Figure 9.9 details.")]),
            _make_execute_result([]),
            _make_execute_result([]),
            _make_execute_result([]),
            _make_execute_result([]),
            _make_execute_result([]),
        ]

        count = await linker.link_images_to_chunks("donaldson", session)

        assert count == 0

    @pytest.mark.asyncio
    async def test_duplicate_explicit_pair_skipped(self):
        linker = ImageLinker()
        session = _mock_session()
        img_id = _uuid()
        chunk_id = _uuid()

        session.execute.side_effect = [
            _make_execute_result([(chunk_id, "Figure 1.3 is important.")]),
            _make_execute_result([(img_id, "1.3")]),
            _make_execute_result([(img_id,)]),
            _make_execute_result([(img_id, chunk_id)]),
            _make_execute_result([(img_id, 5, None)]),
            _make_execute_result([(chunk_id, 5, None)]),
            _make_execute_result([(img_id,)]),
            _make_execute_result([(img_id, chunk_id)]),
        ]

        count = await linker.link_images_to_chunks("donaldson", session)

        assert count == 0


# ---------------------------------------------------------------------------
# link_images_to_chunks — contextual linkage
# ---------------------------------------------------------------------------


class TestContextualLinkage:
    @pytest.mark.asyncio
    async def test_contextual_link_created_for_same_page(self):
        linker = ImageLinker()
        session = _mock_session()
        img_id = _uuid()
        chunk_id = _uuid()

        session.execute.side_effect = [
            _make_execute_result([(chunk_id, "No figures here.")]),
            _make_execute_result([]),
            _make_execute_result([]),
            _make_execute_result([(img_id, 7, None)]),
            _make_execute_result([(chunk_id, 7, None)]),
            _make_execute_result([]),
        ]

        count = await linker.link_images_to_chunks("donaldson", session)

        assert count == 1
        added = session.add_all.call_args[0][0]
        contextual_rows = [r for r in added if r.reference_type == "contextual"]
        assert len(contextual_rows) == 1
        assert contextual_rows[0].source_image_id == img_id
        assert contextual_rows[0].document_chunk_id == chunk_id

    @pytest.mark.asyncio
    async def test_contextual_link_adjacent_page(self):
        """Chunk on page N-1 should be contextually linked to image on page N."""
        linker = ImageLinker()
        session = _mock_session()
        img_id = _uuid()
        chunk_id = _uuid()

        session.execute.side_effect = [
            _make_execute_result([(chunk_id, "Text on page 6.")]),
            _make_execute_result([]),
            _make_execute_result([]),
            _make_execute_result([(img_id, 7, None)]),
            _make_execute_result([(chunk_id, 6, None)]),
            _make_execute_result([]),
        ]

        count = await linker.link_images_to_chunks("donaldson", session)

        assert count == 1
        added = session.add_all.call_args[0][0]
        contextual_rows = [r for r in added if r.reference_type == "contextual"]
        assert len(contextual_rows) == 1

    @pytest.mark.asyncio
    async def test_contextual_link_chapter_fallback_when_page_null(self):
        """Chunks with NULL page should be linked via chapter matching."""
        linker = ImageLinker()
        session = _mock_session()
        img_id = _uuid()
        chunk_id = _uuid()

        session.execute.side_effect = [
            _make_execute_result([(chunk_id, "No figures mentioned here.")]),
            _make_execute_result([]),
            _make_execute_result([]),
            _make_execute_result([(img_id, 5, "chapter_2")]),
            _make_execute_result([(chunk_id, None, "chapter_2")]),
            _make_execute_result([]),
        ]

        count = await linker.link_images_to_chunks("donaldson", session)

        assert count == 1
        added = session.add_all.call_args[0][0]
        contextual_rows = [r for r in added if r.reference_type == "contextual"]
        assert len(contextual_rows) == 1

    @pytest.mark.asyncio
    async def test_no_contextual_link_when_page_null_and_no_chapter(self):
        """Chunks with NULL page and NULL chapter produce no contextual links."""
        linker = ImageLinker()
        session = _mock_session()
        img_id = _uuid()
        chunk_id = _uuid()

        session.execute.side_effect = [
            _make_execute_result([(chunk_id, "No figures mentioned here.")]),
            _make_execute_result([]),
            _make_execute_result([]),
            _make_execute_result([(img_id, 5, None)]),
            _make_execute_result([(chunk_id, None, None)]),
            _make_execute_result([]),
        ]

        count = await linker.link_images_to_chunks("donaldson", session)

        assert count == 0

    @pytest.mark.asyncio
    async def test_contextual_link_skipped_when_explicit_exists(self):
        linker = ImageLinker()
        session = _mock_session()
        img_id = _uuid()
        chunk_id = _uuid()

        session.execute.side_effect = [
            _make_execute_result([(chunk_id, "See Figure 2.0 here.")]),
            _make_execute_result([(img_id, "2.0")]),
            _make_execute_result([]),
            _make_execute_result([(img_id, 10, None)]),
            _make_execute_result([(chunk_id, 10, None)]),
            _make_execute_result([]),
        ]

        count = await linker.link_images_to_chunks("donaldson", session)

        assert count == 1
        added = session.add_all.call_args[0][0]
        explicit_rows = [r for r in added if r.reference_type == "explicit"]
        contextual_rows = [r for r in added if r.reference_type == "contextual"]
        assert len(explicit_rows) == 1
        assert len(contextual_rows) == 0

    @pytest.mark.asyncio
    async def test_no_contextual_link_different_pages(self):
        linker = ImageLinker()
        session = _mock_session()
        img_id = _uuid()
        chunk_id = _uuid()

        session.execute.side_effect = [
            _make_execute_result([(chunk_id, "Text on page 3.")]),
            _make_execute_result([]),
            _make_execute_result([]),
            _make_execute_result([(img_id, 8, None)]),
            _make_execute_result([(chunk_id, 3, None)]),
            _make_execute_result([]),
        ]

        count = await linker.link_images_to_chunks("donaldson", session)

        assert count == 0

    @pytest.mark.asyncio
    async def test_duplicate_contextual_pair_skipped(self):
        linker = ImageLinker()
        session = _mock_session()
        img_id = _uuid()
        chunk_id = _uuid()

        session.execute.side_effect = [
            _make_execute_result([(chunk_id, "Text on page 5.")]),
            _make_execute_result([]),
            _make_execute_result([]),
            _make_execute_result([(img_id, 5, None)]),
            _make_execute_result([(chunk_id, 5, None)]),
            _make_execute_result([(img_id,)]),
            _make_execute_result([(img_id, chunk_id)]),
        ]

        count = await linker.link_images_to_chunks("donaldson", session)

        assert count == 0


# ---------------------------------------------------------------------------
# clear_links_for_source
# ---------------------------------------------------------------------------


class TestClearLinksForSource:
    @pytest.mark.asyncio
    async def test_clear_deletes_existing_rows(self):
        linker = ImageLinker()
        session = _mock_session()
        img_id = _uuid()

        delete_result = MagicMock()
        delete_result.rowcount = 3

        session.execute.side_effect = [
            _make_execute_result([(img_id,)]),
            delete_result,
        ]

        deleted = await linker.clear_links_for_source("donaldson", session)

        assert deleted == 3
        session.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_clear_no_images_returns_zero(self):
        linker = ImageLinker()
        session = _mock_session()

        session.execute.side_effect = [
            _make_execute_result([]),
        ]

        deleted = await linker.clear_links_for_source("donaldson", session)

        assert deleted == 0
        session.flush.assert_not_called()

    @pytest.mark.asyncio
    async def test_clear_only_affects_given_source(self):
        linker = ImageLinker()
        session = _mock_session()
        img_id = _uuid()

        delete_result = MagicMock()
        delete_result.rowcount = 2

        session.execute.side_effect = [
            _make_execute_result([(img_id,)]),
            delete_result,
        ]

        deleted = await linker.clear_links_for_source("triola", session)

        assert deleted == 2


# ---------------------------------------------------------------------------
# Edge-cases and multiple images/chunks
# ---------------------------------------------------------------------------


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_multiple_figures_in_single_chunk(self):
        linker = ImageLinker()
        session = _mock_session()
        img1_id = _uuid()
        img2_id = _uuid()
        chunk_id = _uuid()

        session.execute.side_effect = [
            _make_execute_result([(chunk_id, "See Figure 1.1 and Figure 2.2.")]),
            _make_execute_result([(img1_id, "1.1"), (img2_id, "2.2")]),
            _make_execute_result([]),
            _make_execute_result([(img1_id, 4, None), (img2_id, 9, None)]),
            _make_execute_result([(chunk_id, 4, None)]),
            _make_execute_result([]),
        ]

        count = await linker.link_images_to_chunks("donaldson", session)

        assert count >= 2

    @pytest.mark.asyncio
    async def test_no_chunks_returns_zero(self):
        linker = ImageLinker()
        session = _mock_session()

        session.execute.side_effect = [
            _make_execute_result([]),
            _make_execute_result([]),
            _make_execute_result([]),
            _make_execute_result([]),
            _make_execute_result([]),
            _make_execute_result([]),
        ]

        count = await linker.link_images_to_chunks("empty_source", session)

        assert count == 0

    @pytest.mark.asyncio
    async def test_no_images_returns_zero(self):
        linker = ImageLinker()
        session = _mock_session()
        chunk_id = _uuid()

        session.execute.side_effect = [
            _make_execute_result([(chunk_id, "Figure 1.1 mentioned here.")]),
            _make_execute_result([]),
            _make_execute_result([]),
            _make_execute_result([]),
            _make_execute_result([]),
            _make_execute_result([]),
        ]

        count = await linker.link_images_to_chunks("donaldson", session)

        assert count == 0

    @pytest.mark.asyncio
    async def test_flush_called_when_rows_added(self):
        linker = ImageLinker()
        session = _mock_session()
        img_id = _uuid()
        chunk_id = _uuid()

        session.execute.side_effect = [
            _make_execute_result([(chunk_id, "Figure 3.0 here.")]),
            _make_execute_result([(img_id, "3.0")]),
            _make_execute_result([]),
            _make_execute_result([(img_id, 2, None)]),
            _make_execute_result([(chunk_id, 99, None)]),
            _make_execute_result([]),
        ]

        await linker.link_images_to_chunks("donaldson", session)

        session.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_flush_when_no_rows(self):
        linker = ImageLinker()
        session = _mock_session()

        session.execute.side_effect = [
            _make_execute_result([]),
            _make_execute_result([]),
            _make_execute_result([]),
            _make_execute_result([]),
            _make_execute_result([]),
            _make_execute_result([]),
        ]

        await linker.link_images_to_chunks("empty_source", session)

        session.flush.assert_not_called()


# ---------------------------------------------------------------------------
# Semantic linkage (#2063)
# ---------------------------------------------------------------------------


class TestSemanticLinkage:
    """The semantic matcher uses pgvector cosine similarity. Tests here mock
    the count-probe + lateral-join SQL results returned by ``session.execute``.
    """

    @pytest.mark.asyncio
    async def test_short_circuits_when_no_embedded_images(self):
        """When source_images.embedding count is 0, the lateral join
        must not run — verified by checking flush was called with no
        semantic rows."""
        linker = ImageLinker()
        session = _mock_session()

        # Empty explicit + contextual + count=(0, 0) → no semantic pairs
        session.execute.side_effect = [
            _make_execute_result([]),  # explicit chunks
            _make_execute_result([]),  # explicit images
            _make_execute_result([]),  # explicit existing.image_ids
            _make_execute_result([]),  # contextual images
            _make_execute_result([]),  # contextual chunks
            _make_execute_result([]),  # contextual existing.image_ids
            _make_count_result(0, 5),  # semantic count: 0 images
        ]

        count = await linker.link_images_to_chunks("empty_source", session)
        assert count == 0
        session.flush.assert_not_called()

    @pytest.mark.asyncio
    async def test_short_circuits_when_no_embedded_chunks(self):
        linker = ImageLinker()
        session = _mock_session()
        session.execute.side_effect = [
            _make_execute_result([]),
            _make_execute_result([]),
            _make_execute_result([]),
            _make_execute_result([]),
            _make_execute_result([]),
            _make_execute_result([]),
            _make_count_result(10, 0),  # semantic count: 0 chunks
        ]
        count = await linker.link_images_to_chunks("empty_chunks", session)
        assert count == 0
        session.flush.assert_not_called()

    @pytest.mark.asyncio
    async def test_semantic_pairs_inserted_with_correct_reference_type(self):
        """When the lateral join returns rows, junction rows must be
        added with ``reference_type='semantic'``."""
        linker = ImageLinker()
        session = _mock_session()
        img_id = _uuid()
        chunk_id = _uuid()

        # Lateral query returns one (image_id, chunk_id, distance) tuple.
        lateral_row = MagicMock()
        lateral_row.image_id = img_id
        lateral_row.chunk_id = chunk_id
        lateral_row.distance = 0.18
        lateral_result = MagicMock()
        lateral_result.all.return_value = [lateral_row]

        session.execute.side_effect = [
            _make_execute_result([]),  # explicit chunks
            _make_execute_result([]),  # explicit images
            _make_execute_result([]),  # explicit existing.image_ids
            _make_execute_result([]),  # contextual images
            _make_execute_result([]),  # contextual chunks
            _make_execute_result([]),  # contextual existing.image_ids
            _make_count_result(1, 1),  # semantic count: both > 0
            _make_execute_result([]),  # semantic existing.image_ids (#2106)
            lateral_result,  # lateral join result
        ]

        count = await linker.link_images_to_chunks("collection_x", session)
        assert count == 1
        added = session.add_all.call_args[0][0]
        semantic_rows = [r for r in added if r.reference_type == "semantic"]
        assert len(semantic_rows) == 1
        assert semantic_rows[0].source_image_id == img_id
        assert semantic_rows[0].document_chunk_id == chunk_id

    @pytest.mark.asyncio
    async def test_semantic_dedupes_against_explicit(self):
        """An (image, chunk) pair already present in explicit_pairs must
        NOT be re-added as semantic."""
        linker = ImageLinker()
        session = _mock_session()
        img_id = _uuid()
        chunk_id = _uuid()

        # Explicit yields the pair first
        lateral_row = MagicMock()
        lateral_row.image_id = img_id
        lateral_row.chunk_id = chunk_id
        lateral_row.distance = 0.10
        lateral_result = MagicMock()
        lateral_result.all.return_value = [lateral_row]

        session.execute.side_effect = [
            _make_execute_result([(chunk_id, "See Figure 1.3 for the diagram.")]),
            _make_execute_result([(img_id, "1.3")]),
            _make_execute_result([]),  # no pre-existing pairs
            _make_execute_result([(img_id, 5, None)]),  # contextual images
            _make_execute_result([(chunk_id, 5, None)]),  # contextual chunks
            _make_execute_result([]),
            _make_count_result(1, 1),
            _make_execute_result([]),  # semantic existing.image_ids (#2106)
            lateral_result,  # would propose the same pair as explicit
        ]

        count = await linker.link_images_to_chunks("collection_x", session)
        added = session.add_all.call_args[0][0]
        # Explicit + (deduplicated) contextual should be present, but NO
        # semantic row for the same pair.
        explicit_rows = [r for r in added if r.reference_type == "explicit"]
        semantic_rows = [r for r in added if r.reference_type == "semantic"]
        assert len(explicit_rows) == 1
        assert len(semantic_rows) == 0
        assert count == 1
