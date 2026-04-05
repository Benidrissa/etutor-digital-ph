"""Unit tests for ImageLinker — explicit and contextual chunk↔image linkage."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.ai.rag.image_linker import _FIGURE_RE, ImageLinker

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
            _make_execute_result([(img_id, 5)]),
            _make_execute_result([(chunk_id, 5)]),
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
    async def test_no_explicit_link_when_figure_not_in_text(self):
        linker = ImageLinker()
        session = _mock_session()
        img_id = _uuid()
        chunk_id = _uuid()

        session.execute.side_effect = [
            _make_execute_result([(chunk_id, "No figures mentioned here.")]),
            _make_execute_result([(img_id, "1.3")]),
            _make_execute_result([]),
            _make_execute_result([(img_id, 3)]),
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
            _make_execute_result([(img_id, 5)]),
            _make_execute_result([(chunk_id, 5)]),
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
            _make_execute_result([(img_id, 7)]),
            _make_execute_result([(chunk_id, 7)]),
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
    async def test_contextual_link_skipped_when_explicit_exists(self):
        linker = ImageLinker()
        session = _mock_session()
        img_id = _uuid()
        chunk_id = _uuid()

        session.execute.side_effect = [
            _make_execute_result([(chunk_id, "See Figure 2.0 here.")]),
            _make_execute_result([(img_id, "2.0")]),
            _make_execute_result([]),
            _make_execute_result([(img_id, 10)]),
            _make_execute_result([(chunk_id, 10)]),
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
            _make_execute_result([(img_id, 8)]),
            _make_execute_result([(chunk_id, 3)]),
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
            _make_execute_result([(img_id, 5)]),
            _make_execute_result([(chunk_id, 5)]),
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
            _make_execute_result([(img1_id, 4), (img2_id, 9)]),
            _make_execute_result([(chunk_id, 4)]),
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
            _make_execute_result([(img_id, 2)]),
            _make_execute_result([(chunk_id, 99)]),
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
