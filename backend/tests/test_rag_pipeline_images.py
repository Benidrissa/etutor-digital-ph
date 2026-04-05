"""Tests for image extraction integration in RAGPipeline."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ai.rag.image_extractor import ExtractedImage
from app.ai.rag.image_linker import ImageLinker, _cosine_similarity
from app.ai.rag.pipeline import RAGPipeline


def _make_extracted_image(**kwargs) -> ExtractedImage:
    defaults = dict(
        image_bytes=b"fake_webp_data",
        width=300,
        height=200,
        original_format="png",
        file_size_bytes=14,
        page_number=1,
        figure_number="Figure 1",
        caption="Diagram of disease spread",
        attribution=None,
        image_type="diagram",
        surrounding_text="surrounding text about disease",
        chapter="Chapter 1",
        section=None,
    )
    defaults.update(kwargs)
    return ExtractedImage(**defaults)


class TestCosineSimilarity:
    def test_identical_vectors(self):
        v = [1.0, 0.0, 0.0]
        assert abs(_cosine_similarity(v, v) - 1.0) < 1e-6

    def test_orthogonal_vectors(self):
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert abs(_cosine_similarity(a, b)) < 1e-6

    def test_empty_vectors_return_zero(self):
        assert _cosine_similarity([], [1.0]) == 0.0
        assert _cosine_similarity([1.0], []) == 0.0

    def test_zero_vector_returns_zero(self):
        assert _cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0


class TestImageLinker:
    @pytest.mark.asyncio
    async def test_no_images_returns_zero(self):
        session = AsyncMock()
        session.execute = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        session.execute.return_value = mock_result

        linker = ImageLinker()
        count = await linker.link_images_to_chunks("donaldson", session)
        assert count == 0

    @pytest.mark.asyncio
    async def test_images_without_embeddings_skipped(self):
        session = AsyncMock()

        from app.domain.models.source_image import SourceImage

        img = MagicMock(spec=SourceImage)
        img.caption_embedding = None

        mock_images = MagicMock()
        mock_images.scalars.return_value.all.return_value = [img]

        mock_chunks = MagicMock()
        mock_chunks.scalars.return_value.all.return_value = []

        session.execute = AsyncMock(side_effect=[mock_images, mock_chunks])

        linker = ImageLinker()
        count = await linker.link_images_to_chunks("donaldson", session)
        assert count == 0


class TestRAGPipelineProcessPDFImages:
    def setup_method(self):
        self.embedding_service = AsyncMock()
        self.embedding_service.generate_embedding = AsyncMock(return_value=[0.1] * 1536)
        self.pipeline = RAGPipeline(self.embedding_service)
        self.temp_dir = tempfile.mkdtemp()

    def teardown_method(self):
        import shutil

        shutil.rmtree(self.temp_dir)

    @pytest.mark.asyncio
    async def test_raises_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            await self.pipeline.process_pdf_images(
                pdf_path="/nonexistent/path.pdf",
                source="donaldson",
            )

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_images(self):
        pdf_path = Path(self.temp_dir) / "test.pdf"
        pdf_path.touch()

        with (
            patch(
                "app.ai.rag.pipeline.PDFImageExtractor.extract_images_from_pdf",
                return_value=[],
            ),
        ):
            count = await self.pipeline.process_pdf_images(
                pdf_path=str(pdf_path),
                source="donaldson",
            )

        assert count == 0

    @pytest.mark.asyncio
    async def test_uploads_images_and_stores_metadata(self):
        pdf_path = Path(self.temp_dir) / "Donaldson_test.pdf"
        pdf_path.touch()

        fake_image = _make_extracted_image()
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.execute = AsyncMock(return_value=MagicMock())

        with (
            patch(
                "app.ai.rag.pipeline.PDFImageExtractor.extract_images_from_pdf",
                return_value=[fake_image],
            ),
            patch(
                "app.ai.rag.pipeline.S3StorageService.upload_bytes",
                new_callable=AsyncMock,
                return_value="http://minio/bucket/source-images/donaldson/1_Figure_1.webp",
            ),
            patch.object(
                ImageLinker, "link_images_to_chunks", new_callable=AsyncMock, return_value=1
            ),
        ):
            count = await self.pipeline.process_pdf_images(
                pdf_path=str(pdf_path),
                source="donaldson",
                session=mock_session,
            )

        assert count == 1
        mock_session.add.assert_called_once()
        mock_session.commit.assert_called()

    @pytest.mark.asyncio
    async def test_upload_failure_skips_image_gracefully(self):
        pdf_path = Path(self.temp_dir) / "Donaldson_test.pdf"
        pdf_path.touch()

        fake_image = _make_extracted_image()
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.execute = AsyncMock(return_value=MagicMock())

        with (
            patch(
                "app.ai.rag.pipeline.PDFImageExtractor.extract_images_from_pdf",
                return_value=[fake_image],
            ),
            patch(
                "app.ai.rag.pipeline.S3StorageService.upload_bytes",
                new_callable=AsyncMock,
                side_effect=ConnectionError("MinIO unreachable"),
            ),
            patch.object(
                ImageLinker, "link_images_to_chunks", new_callable=AsyncMock, return_value=0
            ),
        ):
            count = await self.pipeline.process_pdf_images(
                pdf_path=str(pdf_path),
                source="donaldson",
                session=mock_session,
            )

        assert count == 0
        mock_session.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_embedding_failure_stores_image_without_embedding(self):
        pdf_path = Path(self.temp_dir) / "Donaldson_test.pdf"
        pdf_path.touch()

        fake_image = _make_extracted_image()
        self.embedding_service.generate_embedding = AsyncMock(side_effect=Exception("OpenAI error"))
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.execute = AsyncMock(return_value=MagicMock())

        with (
            patch(
                "app.ai.rag.pipeline.PDFImageExtractor.extract_images_from_pdf",
                return_value=[fake_image],
            ),
            patch(
                "app.ai.rag.pipeline.S3StorageService.upload_bytes",
                new_callable=AsyncMock,
                return_value="http://minio/bucket/key.webp",
            ),
            patch.object(
                ImageLinker, "link_images_to_chunks", new_callable=AsyncMock, return_value=0
            ),
        ):
            count = await self.pipeline.process_pdf_images(
                pdf_path=str(pdf_path),
                source="donaldson",
                session=mock_session,
            )

        assert count == 1
        added_image = mock_session.add.call_args[0][0]
        assert added_image.caption_embedding is None


class TestRAGPipelineClearSourceImages:
    def setup_method(self):
        self.embedding_service = AsyncMock()
        self.pipeline = RAGPipeline(self.embedding_service)

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_images(self):
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        count = await self.pipeline.clear_source_images("donaldson", session=mock_session)
        assert count == 0

    @pytest.mark.asyncio
    async def test_deletes_from_db_and_minio(self):
        from app.domain.models.source_image import SourceImage

        mock_img = MagicMock(spec=SourceImage)
        mock_img.storage_key = "source-images/donaldson/1_Figure_1.webp"

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_img]
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()

        with patch(
            "app.ai.rag.pipeline.S3StorageService.delete_object",
            new_callable=AsyncMock,
        ) as mock_delete:
            count = await self.pipeline.clear_source_images("donaldson", session=mock_session)

        assert count == 1
        mock_delete.assert_called_once_with(mock_img.storage_key)
        mock_session.commit.assert_called()

    @pytest.mark.asyncio
    async def test_minio_failure_does_not_block_db_delete(self):
        from app.domain.models.source_image import SourceImage

        mock_img = MagicMock(spec=SourceImage)
        mock_img.storage_key = "source-images/donaldson/1_Figure_1.webp"

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_img]
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()

        with patch(
            "app.ai.rag.pipeline.S3StorageService.delete_object",
            new_callable=AsyncMock,
            side_effect=ConnectionError("MinIO unreachable"),
        ):
            count = await self.pipeline.clear_source_images("donaldson", session=mock_session)

        assert count == 1
        mock_session.commit.assert_called()
