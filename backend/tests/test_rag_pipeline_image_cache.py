"""Unit tests for the cross-course source-image donor-clone (#2580).

When the same source PDF is reused across courses, image extraction/indexation must
be cached like text chunks are — otherwise the full PyMuPDF extraction is re-paid
every time (Gap A) and, worse, a ``file_hash``-deduped upload (no PDF on disk) gets
zero images at all (Gap B). ``_find_donor_images`` / ``_clone_source_images`` /
``clone_images_from_donor`` mirror the text donor-clone trio, keyed on ``file_hash``
(exact) with a ``content_hash`` fallback.

These are mock-session unit tests so they run without a live DB (the DB-backed
conftest can't materialize the PG enums — see project notes).
"""

import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ai.rag.pipeline import RAGPipeline


def _donor_image(**overrides):
    """A donor SourceImage stand-in carrying every field _clone_source_images reuses."""
    img = MagicMock()
    defaults = {
        "image_hash": "abc123def4567890",
        "storage_key": "source-images/donor/book/1_1_1.webp",
        "storage_url": "http://minio/donor/1_1_1.webp",
        "storage_key_fr": "source-images/donor/book/1_1_1.fr.svg",
        "storage_url_fr": "http://minio/donor/1_1_1.fr.svg",
        "embedding": [0.1, 0.2],
        "caption": "Figure 1.1",
        "caption_fr": "Figure 1.1 (fr)",
        "caption_en": "Figure 1.1 (en)",
        "alt_text_fr": "alt fr",
        "alt_text_en": "alt en",
        "figure_kind": "photo",
        "image_type": "photo",
        "width": 640,
        "height": 480,
        "file_size_bytes": 1234,
        "original_format": "png",
        "format": "webp",
        "semantic_tags": {"tags": ["x"]},
        "page_number": 3,
        "chapter": "1",
        "section": "1.1",
        "surrounding_text": "context",
        "figure_number": "1.1",
        "attribution": None,
    }
    defaults.update(overrides)
    for k, v in defaults.items():
        setattr(img, k, v)
    return img


class TestFindDonorImages:
    def setup_method(self):
        self.pipeline = RAGPipeline(AsyncMock())

    @pytest.mark.asyncio
    async def test_prefers_file_hash_over_content_hash(self):
        """An exact file_hash match wins — content_hash is never queried."""
        donor_res = uuid.uuid4()
        images = [_donor_image(), _donor_image()]

        pick = MagicMock()
        pick.scalar_one_or_none = MagicMock(return_value=donor_res)
        fetch = MagicMock()
        fetch.scalars.return_value.all.return_value = images

        session = MagicMock()
        session.execute = AsyncMock(side_effect=[pick, fetch])

        result = await self.pipeline._find_donor_images(
            "file-hash", "content-hash", uuid.uuid4(), session
        )

        assert result == images
        # Two calls only: pick-donor-by-file_hash, then fetch-its-images. The
        # content_hash pick is skipped because file_hash already matched.
        assert session.execute.await_count == 2

    @pytest.mark.asyncio
    async def test_falls_back_to_content_hash(self):
        """No file_hash donor → retry on content_hash, then fetch images."""
        donor_res = uuid.uuid4()
        images = [_donor_image()]

        miss = MagicMock()
        miss.scalar_one_or_none = MagicMock(return_value=None)
        hit = MagicMock()
        hit.scalar_one_or_none = MagicMock(return_value=donor_res)
        fetch = MagicMock()
        fetch.scalars.return_value.all.return_value = images

        session = MagicMock()
        session.execute = AsyncMock(side_effect=[miss, hit, fetch])

        result = await self.pipeline._find_donor_images(
            "file-hash", "content-hash", uuid.uuid4(), session
        )

        assert result == images
        assert session.execute.await_count == 3

    @pytest.mark.asyncio
    async def test_skips_query_for_missing_file_hash(self):
        """A falsy file_hash issues no query — goes straight to content_hash."""
        donor_res = uuid.uuid4()
        hit = MagicMock()
        hit.scalar_one_or_none = MagicMock(return_value=donor_res)
        fetch = MagicMock()
        fetch.scalars.return_value.all.return_value = [_donor_image()]

        session = MagicMock()
        session.execute = AsyncMock(side_effect=[hit, fetch])

        result = await self.pipeline._find_donor_images(None, "content-hash", uuid.uuid4(), session)

        assert len(result) == 1
        # content_hash pick + fetch — the None file_hash never hit the DB.
        assert session.execute.await_count == 2

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_donor(self):
        miss = MagicMock()
        miss.scalar_one_or_none = MagicMock(return_value=None)
        session = MagicMock()
        session.execute = AsyncMock(return_value=miss)

        result = await self.pipeline._find_donor_images(
            "file-hash", "content-hash", uuid.uuid4(), session
        )

        assert result == []
        # Both picks miss; no image fetch is issued.
        assert session.execute.await_count == 2


class TestCloneSourceImages:
    def setup_method(self):
        self.pipeline = RAGPipeline(AsyncMock())

    @pytest.mark.asyncio
    async def test_reuses_expensive_fields_and_stamps_new_identity(self):
        donor = _donor_image()
        new_resource = uuid.uuid4()
        added = []
        session = MagicMock()
        session.add = MagicMock(side_effect=added.append)
        session.commit = AsyncMock()

        cloned = await self.pipeline._clone_source_images(
            [donor], "new-src", "new-rag", new_resource, session
        )

        assert cloned == 1
        (row,) = added
        # New identity / ownership:
        assert row.source == "new-src"
        assert row.rag_collection_id == "new-rag"
        assert row.course_resource_id == new_resource
        # Expensive computed fields reused verbatim from the donor (no MinIO /
        # OpenAI / Claude work):
        assert row.storage_key == donor.storage_key
        assert row.storage_url_fr == donor.storage_url_fr
        assert row.embedding == donor.embedding
        assert row.caption_fr == donor.caption_fr
        assert row.figure_kind == donor.figure_kind
        # Positional metadata copied (same PDF ⇒ same positions):
        assert row.page_number == donor.page_number
        assert row.figure_number == donor.figure_number
        session.commit.assert_awaited_once()


class TestCloneImagesFromDonor:
    def setup_method(self):
        self.pipeline = RAGPipeline(AsyncMock())

    @pytest.mark.asyncio
    async def test_returns_none_and_skips_linker_when_no_donor(self):
        self.pipeline._find_donor_images = AsyncMock(return_value=[])
        session = MagicMock()

        with patch("app.ai.rag.pipeline.ImageLinker") as Linker:
            result = await self.pipeline.clone_images_from_donor(
                "src", "rag", uuid.uuid4(), "fh", "ch", session
            )

        assert result is None
        Linker.assert_not_called()

    @pytest.mark.asyncio
    async def test_clones_then_links(self):
        donors = [_donor_image(), _donor_image()]
        self.pipeline._find_donor_images = AsyncMock(return_value=donors)
        self.pipeline._clone_source_images = AsyncMock(return_value=2)
        session = MagicMock()
        session.commit = AsyncMock()

        linker = MagicMock()
        linker.link_images_to_chunks = AsyncMock(return_value=5)
        with (
            patch("app.ai.rag.pipeline.ImageLinker", return_value=linker),
            # Donor binaries present → clone shortcut proceeds (#2605).
            patch(
                "app.ai.rag.pipeline.S3StorageService.object_exists",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            result = await self.pipeline.clone_images_from_donor(
                "src", "rag", uuid.uuid4(), "fh", "ch", session
            )

        assert result == 2
        linker.link_images_to_chunks.assert_awaited_once_with("src", session)

    @pytest.mark.asyncio
    async def test_returns_none_when_donor_storage_missing(self):
        """Dead donor (binaries gone) → skip clone, fall back to extraction (#2605)."""
        donors = [_donor_image(), _donor_image()]
        self.pipeline._find_donor_images = AsyncMock(return_value=donors)
        self.pipeline._clone_source_images = AsyncMock(return_value=2)
        session = MagicMock()

        with (
            patch("app.ai.rag.pipeline.ImageLinker") as Linker,
            patch(
                "app.ai.rag.pipeline.S3StorageService.object_exists",
                new_callable=AsyncMock,
                return_value=False,
            ),
        ):
            result = await self.pipeline.clone_images_from_donor(
                "src", "rag", uuid.uuid4(), "fh", "ch", session
            )

        assert result is None  # caller runs full extraction instead
        self.pipeline._clone_source_images.assert_not_called()
        Linker.assert_not_called()


class TestProcessImagesShortCircuit:
    def setup_method(self):
        self.pipeline = RAGPipeline(AsyncMock())

    @pytest.mark.asyncio
    async def test_cache_hit_skips_pdf_extraction(self):
        """Gap A: a donor exists → clone and return WITHOUT opening the PDF."""
        self.pipeline.clear_resource_images = AsyncMock(return_value=0)
        self.pipeline.clone_images_from_donor = AsyncMock(return_value=4)
        session = MagicMock()

        with patch("app.ai.rag.pipeline.PDFImageExtractor") as Extractor:
            result = await self.pipeline._process_images(
                Path("book.pdf"),
                "src",
                "rag",
                session,
                None,
                course_resource_id=uuid.uuid4(),
                file_hash="fh",
                content_hash="ch",
            )

        assert result == 4
        # The whole point: no PyMuPDF extraction was constructed/run.
        Extractor.assert_not_called()
        self.pipeline.clear_resource_images.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cache_miss_falls_through_to_extraction(self):
        """No donor → clone returns None → full extraction path runs (0 images here)."""
        self.pipeline.clear_resource_images = AsyncMock(return_value=0)
        self.pipeline.clone_images_from_donor = AsyncMock(return_value=None)
        session = MagicMock()

        extractor = MagicMock()
        extractor.extract_images_from_pdf.return_value = []
        with patch("app.ai.rag.pipeline.PDFImageExtractor", return_value=extractor) as Extractor:
            result = await self.pipeline._process_images(
                Path("book.pdf"),
                "src",
                "rag",
                session,
                None,
                course_resource_id=uuid.uuid4(),
                file_hash="fh",
                content_hash="ch",
            )

        assert result == 0
        Extractor.assert_called_once()
        extractor.extract_images_from_pdf.assert_called_once()
