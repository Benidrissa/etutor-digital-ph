"""Unit tests for the ImageLinker class."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest  # noqa: F401

from app.ai.rag.image_linker import _FIGURE_PATTERN, ImageLinker


def _make_image(
    source: str = "donaldson",
    page_number: int = 5,
    figure_number: str | None = "Figure 1.3",
) -> MagicMock:
    img = MagicMock()
    img.id = uuid.uuid4()
    img.source = source
    img.page_number = page_number
    img.figure_number = figure_number
    return img


def _make_chunk(
    source: str = "donaldson",
    page: int | None = 5,
    content: str = "Some text mentioning Figure 1.3 in context.",
) -> MagicMock:
    chunk = MagicMock()
    chunk.id = uuid.uuid4()
    chunk.source = source
    chunk.page = page
    chunk.content = content
    return chunk


class TestFigurePattern:
    def test_matches_figure_with_decimal(self):
        matches = _FIGURE_PATTERN.findall("See Figure 1.3 for details.")
        assert matches == ["1.3"]

    def test_matches_figure_without_decimal(self):
        matches = _FIGURE_PATTERN.findall("Refer to Figure 4 above.")
        assert matches == ["4"]

    def test_case_insensitive(self):
        matches = _FIGURE_PATTERN.findall("figure 2.1 shows the trend.")
        assert matches == ["2.1"]

    def test_no_match_when_absent(self):
        matches = _FIGURE_PATTERN.findall("No figure references here.")
        assert matches == []

    def test_multiple_matches(self):
        matches = _FIGURE_PATTERN.findall("Figure 1.2 and Figure 3 are relevant.")
        assert matches == ["1.2", "3"]


class TestNormalizeFigureNumber:
    def test_extracts_decimal(self):
        assert ImageLinker._normalize_figure_number("Figure 3.1") == "3.1"

    def test_extracts_integer(self):
        assert ImageLinker._normalize_figure_number("Fig. 2") == "2"

    def test_handles_raw_number(self):
        assert ImageLinker._normalize_figure_number("1.5") == "1.5"

    def test_fallback_on_no_digit(self):
        assert ImageLinker._normalize_figure_number("NoNumber") == "NoNumber"


class TestImageLinkerExplicit:
    @pytest.fixture
    def linker(self):
        return ImageLinker()

    async def test_explicit_link_created_when_figure_matches(self, linker):
        image = _make_image(figure_number="Figure 1.3", page_number=5)
        chunk = _make_chunk(content="As shown in Figure 1.3, incidence rose sharply.", page=5)

        session = AsyncMock()
        calls = [0]

        async def mock_execute(stmt):
            result = MagicMock()
            calls[0] += 1
            if calls[0] == 1:
                result.scalars.return_value.all.return_value = [chunk]
            else:
                result.scalars.return_value.all.return_value = [image]
            return result

        session.execute = AsyncMock(side_effect=mock_execute)

        pairs = await linker._build_explicit_pairs("donaldson", session)
        assert len(pairs) == 1
        assert pairs[0] == (image.id, chunk.id)

    async def test_no_explicit_link_when_figure_not_in_chunk(self, linker):
        image = _make_image(figure_number="Figure 2.4", page_number=5)
        chunk = _make_chunk(content="No figure reference here at all.", page=5)

        session = AsyncMock()

        calls = [0]

        async def mock_execute(stmt):
            result = MagicMock()
            calls[0] += 1
            if calls[0] == 1:
                result.scalars.return_value.all.return_value = [chunk]
            else:
                result.scalars.return_value.all.return_value = [image]
            return result

        session.execute = AsyncMock(side_effect=mock_execute)
        pairs = await linker._build_explicit_pairs("donaldson", session)
        assert pairs == []

    async def test_deduplicates_same_pair(self, linker):
        image = _make_image(figure_number="Figure 1.3")
        chunk = _make_chunk(content="Figure 1.3 repeated. Figure 1.3 again.")

        session = AsyncMock()
        calls = [0]

        async def mock_execute(stmt):
            result = MagicMock()
            calls[0] += 1
            if calls[0] == 1:
                result.scalars.return_value.all.return_value = [chunk]
            else:
                result.scalars.return_value.all.return_value = [image]
            return result

        session.execute = AsyncMock(side_effect=mock_execute)
        pairs = await linker._build_explicit_pairs("donaldson", session)
        assert len(pairs) == 1


class TestImageLinkerContextual:
    @pytest.fixture
    def linker(self):
        return ImageLinker()

    async def test_contextual_link_for_same_page(self, linker):
        image = _make_image(page_number=7, figure_number=None)
        chunk = _make_chunk(page=7, content="Some public health text on page 7.")

        session = AsyncMock()
        calls = [0]

        async def mock_execute(stmt):
            result = MagicMock()
            calls[0] += 1
            if calls[0] == 1:
                result.scalars.return_value.all.return_value = [image]
            else:
                result.scalars.return_value.all.return_value = [chunk]
            return result

        session.execute = AsyncMock(side_effect=mock_execute)
        pairs = await linker._build_contextual_pairs("donaldson", session, skip_pairs=set())
        assert len(pairs) == 1
        assert pairs[0] == (image.id, chunk.id)

    async def test_contextual_skips_explicit_pairs(self, linker):
        image = _make_image(page_number=7, figure_number="Figure 1.1")
        chunk = _make_chunk(page=7, content="Figure 1.1 shows trends.")
        skip = {(image.id, chunk.id)}

        session = AsyncMock()
        calls = [0]

        async def mock_execute(stmt):
            result = MagicMock()
            calls[0] += 1
            if calls[0] == 1:
                result.scalars.return_value.all.return_value = [image]
            else:
                result.scalars.return_value.all.return_value = [chunk]
            return result

        session.execute = AsyncMock(side_effect=mock_execute)
        pairs = await linker._build_contextual_pairs("donaldson", session, skip_pairs=skip)
        assert pairs == []

    async def test_no_contextual_link_different_page(self, linker):
        image = _make_image(page_number=3, figure_number=None)
        chunk = _make_chunk(page=10, content="Text on a different page.")

        session = AsyncMock()
        calls = [0]

        async def mock_execute(stmt):
            result = MagicMock()
            calls[0] += 1
            if calls[0] == 1:
                result.scalars.return_value.all.return_value = [image]
            else:
                result.scalars.return_value.all.return_value = [chunk]
            return result

        session.execute = AsyncMock(side_effect=mock_execute)
        pairs = await linker._build_contextual_pairs("donaldson", session, skip_pairs=set())
        assert pairs == []

    async def test_chunk_without_page_excluded(self, linker):
        image = _make_image(page_number=5, figure_number=None)
        session = AsyncMock()
        calls = [0]

        async def mock_execute(stmt):
            result = MagicMock()
            calls[0] += 1
            if calls[0] == 1:
                result.scalars.return_value.all.return_value = [image]
            else:
                result.scalars.return_value.all.return_value = []
            return result

        session.execute = AsyncMock(side_effect=mock_execute)
        pairs = await linker._build_contextual_pairs("donaldson", session, skip_pairs=set())
        assert pairs == []


class TestLinkImagesToChunks:
    @pytest.fixture
    def linker(self):
        return ImageLinker()

    async def test_returns_zero_when_no_images_or_chunks(self, linker):
        session = AsyncMock()

        async def mock_execute(stmt):
            result = MagicMock()
            result.scalars.return_value.all.return_value = []
            result.all.return_value = []
            return result

        session.execute = AsyncMock(side_effect=mock_execute)

        with (
            patch.object(linker, "_build_explicit_pairs", return_value=[]),
            patch.object(linker, "_build_contextual_pairs", return_value=[]),
        ):
            total = await linker.link_images_to_chunks("donaldson", session)

        assert total == 0
        session.execute.assert_not_called()

    async def test_returns_total_link_count(self, linker):
        img_id = uuid.uuid4()
        chunk_id1 = uuid.uuid4()
        chunk_id2 = uuid.uuid4()

        session = AsyncMock()
        result = MagicMock()
        session.execute = AsyncMock(return_value=result)

        with (
            patch.object(linker, "_build_explicit_pairs", return_value=[(img_id, chunk_id1)]),
            patch.object(linker, "_build_contextual_pairs", return_value=[(img_id, chunk_id2)]),
        ):
            total = await linker.link_images_to_chunks("donaldson", session)

        assert total == 2
        session.execute.assert_called_once()
        session.commit.assert_called_once()

    async def test_calls_commit_after_insert(self, linker):
        img_id = uuid.uuid4()
        chunk_id = uuid.uuid4()

        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock())

        with (
            patch.object(linker, "_build_explicit_pairs", return_value=[(img_id, chunk_id)]),
            patch.object(linker, "_build_contextual_pairs", return_value=[]),
        ):
            await linker.link_images_to_chunks("triola", session)

        session.commit.assert_called_once()


class TestClearLinksForSource:
    @pytest.fixture
    def linker(self):
        return ImageLinker()

    async def test_returns_zero_when_no_images(self, linker):
        session = AsyncMock()

        async def mock_execute(stmt):
            result = MagicMock()
            result.all.return_value = []
            return result

        session.execute = AsyncMock(side_effect=mock_execute)
        deleted = await linker.clear_links_for_source("donaldson", session)
        assert deleted == 0

    async def test_deletes_links_for_source(self, linker):
        img_id = uuid.uuid4()
        session = AsyncMock()
        calls = [0]

        async def mock_execute(stmt):
            result = MagicMock()
            calls[0] += 1
            if calls[0] == 1:
                result.all.return_value = [(img_id,)]
            else:
                result.rowcount = 3
            return result

        session.execute = AsyncMock(side_effect=mock_execute)
        deleted = await linker.clear_links_for_source("donaldson", session)
        assert deleted == 3
        session.commit.assert_called_once()

    async def test_commit_called_after_delete(self, linker):
        img_id = uuid.uuid4()
        session = AsyncMock()
        calls = [0]

        async def mock_execute(stmt):
            result = MagicMock()
            calls[0] += 1
            if calls[0] == 1:
                result.all.return_value = [(img_id,)]
            else:
                result.rowcount = 1
            return result

        session.execute = AsyncMock(side_effect=mock_execute)
        await linker.clear_links_for_source("triola", session)
        session.commit.assert_called_once()
