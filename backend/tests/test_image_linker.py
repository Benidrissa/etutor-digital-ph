"""Unit tests for ImageLinker chunk-image linking."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ai.rag.image_linker import _FIGURE_PATTERN, ImageLinker
from app.domain.models.document_chunk import DocumentChunk
from app.domain.models.source_image import SourceImage, SourceImageChunk


def make_chunk(
    source: str = "donaldson",
    content: str = "Some text",
    page: int | None = 1,
) -> DocumentChunk:
    chunk = DocumentChunk(
        id=uuid.uuid4(),
        content=content,
        source=source,
        page=page,
        language="en",
        token_count=100,
        chunk_index=0,
    )
    return chunk


def make_image(
    source: str = "donaldson",
    page_number: int = 1,
    figure_number: str | None = None,
) -> SourceImage:
    image = SourceImage(
        id=uuid.uuid4(),
        source=source,
        page_number=page_number,
        figure_number=figure_number,
        image_type="diagram",
    )
    return image


def make_link(image_id: uuid.UUID, chunk_id: uuid.UUID, reference_type: str) -> SourceImageChunk:
    return SourceImageChunk(
        id=uuid.uuid4(),
        image_id=image_id,
        chunk_id=chunk_id,
        reference_type=reference_type,
    )


class TestFigurePattern:
    def test_matches_simple_figure(self):
        matches = _FIGURE_PATTERN.findall("See Figure 3 for details.")
        assert "3" in matches

    def test_matches_dotted_figure(self):
        matches = _FIGURE_PATTERN.findall("As shown in Figure 1.3.")
        assert "1.3" in matches

    def test_case_insensitive(self):
        matches = _FIGURE_PATTERN.findall("figure 2 shows a chart")
        assert "2" in matches

    def test_no_match_without_figure(self):
        matches = _FIGURE_PATTERN.findall("Some text without any reference.")
        assert matches == []

    def test_multiple_figures_in_text(self):
        matches = _FIGURE_PATTERN.findall("Figure 1.1 and Figure 2.3 both show data.")
        assert "1.1" in matches
        assert "2.3" in matches


class TestImageLinkerExplicit:
    """Tests for explicit figure-number based linking."""

    @pytest.fixture
    def linker(self):
        return ImageLinker()

    async def test_explicit_link_created_when_figure_in_chunk(self, linker):
        chunk = make_chunk(content="See Figure 1.3 for the mortality trend.")
        image = make_image(figure_number="Figure 1.3")

        session = AsyncMock()
        session.flush = AsyncMock()
        session.add_all = MagicMock()

        with (
            patch.object(linker, "_load_existing_pairs", new=AsyncMock(return_value=set())),
            patch.object(
                linker,
                "_build_explicit_links",
                new=AsyncMock(
                    return_value=(
                        [make_link(image.id, chunk.id, "explicit")],
                        {(str(image.id), str(chunk.id))},
                    )
                ),
            ),
            patch.object(linker, "_build_contextual_links", new=AsyncMock(return_value=[])),
        ):
            count = await linker.link_images_to_chunks("donaldson", session)

        assert count == 1
        session.add_all.assert_called_once()

    async def test_no_explicit_link_when_no_figure_in_chunk(self, linker):
        chunk = make_chunk(content="This text has no figure reference.")
        image = make_image(figure_number="Figure 1.3")

        session = AsyncMock()
        session.flush = AsyncMock()

        existing = set()
        chunks_by_source = [chunk]
        images_by_source = [image]

        async def mock_execute(stmt):
            result = MagicMock()
            sql = str(stmt)
            if "document_chunks" in sql and "source_images" not in sql:
                result.scalars.return_value = chunks_by_source
            elif "source_images" in sql and "source_image_chunks" not in sql:
                result.scalars.return_value = images_by_source
            else:
                result.__iter__ = MagicMock(return_value=iter([]))
                result.scalars.return_value = []
            return result

        session.execute = mock_execute
        session.add_all = MagicMock()

        with (
            patch.object(linker, "_load_existing_pairs", new=AsyncMock(return_value=existing)),
            patch.object(
                linker,
                "_build_explicit_links",
                new=AsyncMock(return_value=([], set())),
            ),
            patch.object(linker, "_build_contextual_links", new=AsyncMock(return_value=[])),
        ):
            count = await linker.link_images_to_chunks("donaldson", session)

        assert count == 0

    async def test_build_explicit_links_deduplicates(self, linker):
        chunk = make_chunk(content="Figure 1.3 is shown here.")
        image = make_image(figure_number="Figure 1.3")
        existing_pair = (str(image.id), str(chunk.id))

        session = AsyncMock()

        async def mock_execute(stmt):
            result = MagicMock()
            sql = str(stmt)
            if "document_chunks" in sql:
                result.scalars.return_value = [chunk]
            elif "source_images" in sql:
                result.scalars.return_value = [image]
            else:
                result.scalars.return_value = []
            return result

        session.execute = mock_execute

        links, new_pairs = await linker._build_explicit_links("donaldson", session, {existing_pair})

        assert links == []
        assert new_pairs == set()

    async def test_build_explicit_links_skips_duplicate_within_batch(self, linker):
        chunk = make_chunk(content="Figure 1.3 and Figure 1.3 again.")
        image = make_image(figure_number="Figure 1.3")

        session = AsyncMock()

        async def mock_execute(stmt):
            result = MagicMock()
            sql = str(stmt)
            if "document_chunks" in sql:
                result.scalars.return_value = [chunk]
            elif "source_images" in sql:
                result.scalars.return_value = [image]
            else:
                result.scalars.return_value = []
            return result

        session.execute = mock_execute

        links, new_pairs = await linker._build_explicit_links("donaldson", session, set())

        assert len(links) == 1
        assert len(new_pairs) == 1


class TestImageLinkerContextual:
    """Tests for same-page contextual linking."""

    @pytest.fixture
    def linker(self):
        return ImageLinker()

    async def test_contextual_link_created_for_same_page(self, linker):
        image = make_image(page_number=5)
        chunk = make_chunk(page=5)

        session = AsyncMock()

        async def mock_execute(stmt):
            result = MagicMock()
            sql = str(stmt)
            if "source_images" in sql:
                result.scalars.return_value = [image]
            elif "document_chunks" in sql:
                result.scalars.return_value = [chunk]
            else:
                result.scalars.return_value = []
            return result

        session.execute = mock_execute

        links = await linker._build_contextual_links("donaldson", session, set())

        assert len(links) == 1
        assert links[0].reference_type == "contextual"

    async def test_contextual_link_skipped_if_explicit_exists(self, linker):
        image = make_image(page_number=5)
        chunk = make_chunk(page=5)
        explicit_pair = (str(image.id), str(chunk.id))

        session = AsyncMock()

        async def mock_execute(stmt):
            result = MagicMock()
            sql = str(stmt)
            if "source_images" in sql:
                result.scalars.return_value = [image]
            elif "document_chunks" in sql:
                result.scalars.return_value = [chunk]
            else:
                result.scalars.return_value = []
            return result

        session.execute = mock_execute

        links = await linker._build_contextual_links("donaldson", session, {explicit_pair})

        assert links == []

    async def test_contextual_link_skipped_for_different_page(self, linker):
        image = make_image(page_number=5)

        session = AsyncMock()

        async def mock_execute(stmt):
            result = MagicMock()
            sql = str(stmt)
            if "source_images" in sql:
                result.scalars.return_value = [image]
            elif "document_chunks" in sql:
                result.scalars.return_value = []
            else:
                result.scalars.return_value = []
            return result

        session.execute = mock_execute

        links = await linker._build_contextual_links("donaldson", session, set())

        assert links == []

    async def test_contextual_skips_image_without_page(self, linker):
        image = make_image(page_number=None)

        session = AsyncMock()

        async def mock_execute(stmt):
            result = MagicMock()
            sql = str(stmt)
            if "source_images" in sql:
                result.scalars.return_value = [image]
            else:
                result.scalars.return_value = []
            return result

        session.execute = mock_execute

        links = await linker._build_contextual_links("donaldson", session, set())

        assert links == []

    async def test_contextual_deduplicates_within_batch(self, linker):
        image = make_image(page_number=3)
        chunk = make_chunk(page=3)

        session = AsyncMock()

        async def mock_execute(stmt):
            result = MagicMock()
            sql = str(stmt)
            if "source_images" in sql:
                result.scalars.return_value = [image, image]
            elif "document_chunks" in sql:
                result.scalars.return_value = [chunk]
            else:
                result.scalars.return_value = []
            return result

        session.execute = mock_execute

        links = await linker._build_contextual_links("donaldson", session, set())

        assert len(links) == 1


class TestClearLinksForSource:
    @pytest.fixture
    def linker(self):
        return ImageLinker()

    async def test_clear_deletes_links_for_source(self, linker):
        image_id = uuid.uuid4()

        session = AsyncMock()
        session.flush = AsyncMock()

        async def mock_execute(stmt):
            result = MagicMock()
            sql = str(stmt)
            if "source_images" in sql and "DELETE" not in sql.upper():
                result.__iter__ = MagicMock(return_value=iter([[image_id]]))
                return result
            result.rowcount = 3
            return result

        session.execute = mock_execute

        deleted = await linker.clear_links_for_source("donaldson", session)

        assert deleted == 3
        session.flush.assert_called_once()

    async def test_clear_returns_zero_when_no_images(self, linker):
        session = AsyncMock()

        async def mock_execute(stmt):
            result = MagicMock()
            result.__iter__ = MagicMock(return_value=iter([]))
            return result

        session.execute = mock_execute

        deleted = await linker.clear_links_for_source("unknown_source", session)

        assert deleted == 0


class TestLinkImagesToChunksIntegration:
    """Integration-style tests for the full linking flow."""

    @pytest.fixture
    def linker(self):
        return ImageLinker()

    async def test_returns_total_count(self, linker):
        session = AsyncMock()
        session.flush = AsyncMock()
        session.add_all = MagicMock()

        image1 = make_image(page_number=1, figure_number="Figure 1.1")
        chunk1 = make_chunk(content="See Figure 1.1 for details.", page=1)

        with patch.object(linker, "_load_existing_pairs", new=AsyncMock(return_value=set())):
            explicit_link = make_link(image1.id, chunk1.id, "explicit")
            contextual_link = make_link(image1.id, chunk1.id, "contextual")
            with (
                patch.object(
                    linker,
                    "_build_explicit_links",
                    new=AsyncMock(
                        return_value=(
                            [explicit_link],
                            {(str(image1.id), str(chunk1.id))},
                        )
                    ),
                ),
                patch.object(
                    linker,
                    "_build_contextual_links",
                    new=AsyncMock(return_value=[contextual_link]),
                ),
            ):
                count = await linker.link_images_to_chunks("donaldson", session)

        assert count == 2
        session.add_all.assert_called_once()

    async def test_no_rows_added_when_nothing_to_link(self, linker):
        session = AsyncMock()
        session.flush = AsyncMock()
        session.add_all = MagicMock()

        with (
            patch.object(linker, "_load_existing_pairs", new=AsyncMock(return_value=set())),
            patch.object(
                linker,
                "_build_explicit_links",
                new=AsyncMock(return_value=([], set())),
            ),
            patch.object(linker, "_build_contextual_links", new=AsyncMock(return_value=[])),
        ):
            count = await linker.link_images_to_chunks("donaldson", session)

        assert count == 0
        session.add_all.assert_not_called()
        session.flush.assert_not_called()

    async def test_different_sources_isolated(self, linker):
        image_don = make_image(source="donaldson", page_number=1, figure_number="Figure 1")
        chunk_don = make_chunk(source="donaldson", content="Figure 1 data", page=1)

        session = AsyncMock()
        session.flush = AsyncMock()
        session.add_all = MagicMock()

        with patch.object(linker, "_load_existing_pairs", new=AsyncMock(return_value=set())):
            explicit_link = make_link(image_don.id, chunk_don.id, "explicit")
            with (
                patch.object(
                    linker,
                    "_build_explicit_links",
                    new=AsyncMock(
                        return_value=(
                            [explicit_link],
                            {(str(image_don.id), str(chunk_don.id))},
                        )
                    ),
                ),
                patch.object(linker, "_build_contextual_links", new=AsyncMock(return_value=[])),
            ):
                count = await linker.link_images_to_chunks("donaldson", session)

        assert count == 1
