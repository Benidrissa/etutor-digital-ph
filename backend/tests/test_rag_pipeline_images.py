"""Unit tests for image extraction integration in RAGPipeline."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ai.rag.image_extractor import ExtractedImage
from app.ai.rag.image_linker import ImageLinker
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
    async def test_raises_file_not_found_for_missing_pdf(self):
        with pytest.raises(FileNotFoundError):
            await self.pipeline.process_pdf_images(
                pdf_path="/nonexistent/path.pdf",
                source="donaldson",
            )

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_images_extracted(self):
        pdf_path = Path(self.temp_dir) / "test.pdf"
        pdf_path.touch()

        with patch(
            "app.ai.rag.pipeline.PDFImageExtractor.extract_images_from_pdf",
            return_value=[],
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
    async def test_storage_key_contains_source_and_page(self):
        pdf_path = Path(self.temp_dir) / "test.pdf"
        pdf_path.touch()

        fake_image = _make_extracted_image(page_number=5, figure_number="Figure 3.2")
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.execute = AsyncMock(return_value=MagicMock())

        captured_key = {}

        async def capture_upload(key, data, content_type):
            captured_key["key"] = key
            return f"http://minio/{key}"

        with (
            patch(
                "app.ai.rag.pipeline.PDFImageExtractor.extract_images_from_pdf",
                return_value=[fake_image],
            ),
            patch(
                "app.ai.rag.pipeline.S3StorageService.upload_bytes",
                side_effect=capture_upload,
            ),
            patch.object(
                ImageLinker, "link_images_to_chunks", new_callable=AsyncMock, return_value=0
            ),
        ):
            await self.pipeline.process_pdf_images(
                pdf_path=str(pdf_path),
                source="donaldson",
                session=mock_session,
            )

        assert "source-images/donaldson" in captured_key["key"]
        assert "5_" in captured_key["key"]

    @pytest.mark.asyncio
    async def test_upload_failure_skips_image_gracefully(self):
        pdf_path = Path(self.temp_dir) / "Donaldson_test.pdf"
        pdf_path.touch()

        fake_image = _make_extracted_image()
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()

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
        assert added_image.embedding is None

    @pytest.mark.asyncio
    async def test_links_images_to_chunks_after_storing(self):
        pdf_path = Path(self.temp_dir) / "test.pdf"
        pdf_path.touch()

        fake_image = _make_extracted_image()
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.execute = AsyncMock(return_value=MagicMock())

        mock_linker = AsyncMock()
        mock_linker.link_images_to_chunks = AsyncMock(return_value=3)

        with (
            patch(
                "app.ai.rag.pipeline.PDFImageExtractor.extract_images_from_pdf",
                return_value=[fake_image],
            ),
            patch(
                "app.ai.rag.pipeline.S3StorageService.upload_bytes",
                new_callable=AsyncMock,
                return_value="http://minio/key.webp",
            ),
            patch("app.ai.rag.pipeline.ImageLinker", return_value=mock_linker),
        ):
            count = await self.pipeline.process_pdf_images(
                pdf_path=str(pdf_path),
                source="donaldson",
                session=mock_session,
            )

        assert count == 1
        mock_linker.link_images_to_chunks.assert_called_once_with("donaldson", mock_session)

    @pytest.mark.asyncio
    async def test_multiple_images_all_stored(self):
        pdf_path = Path(self.temp_dir) / "test.pdf"
        pdf_path.touch()

        images = [
            _make_extracted_image(page_number=1, figure_number="Figure 1"),
            _make_extracted_image(page_number=2, figure_number="Figure 2"),
            _make_extracted_image(page_number=3, figure_number=None),
        ]
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.execute = AsyncMock(return_value=MagicMock())

        with (
            patch(
                "app.ai.rag.pipeline.PDFImageExtractor.extract_images_from_pdf",
                return_value=images,
            ),
            patch(
                "app.ai.rag.pipeline.S3StorageService.upload_bytes",
                new_callable=AsyncMock,
                return_value="http://minio/key.webp",
            ),
            patch.object(
                ImageLinker, "link_images_to_chunks", new_callable=AsyncMock, return_value=2
            ),
        ):
            count = await self.pipeline.process_pdf_images(
                pdf_path=str(pdf_path),
                source="donaldson",
                session=mock_session,
            )

        assert count == 3
        assert mock_session.add.call_count == 3

    @pytest.mark.asyncio
    async def test_rag_collection_id_stored_in_db_record(self):
        pdf_path = Path(self.temp_dir) / "test.pdf"
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
                return_value="http://minio/key.webp",
            ),
            patch.object(
                ImageLinker, "link_images_to_chunks", new_callable=AsyncMock, return_value=0
            ),
        ):
            await self.pipeline.process_pdf_images(
                pdf_path=str(pdf_path),
                source="donaldson",
                rag_collection_id="rag-col-123",
                session=mock_session,
            )

        added_image = mock_session.add.call_args[0][0]
        assert added_image.rag_collection_id == "rag-col-123"


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

    @pytest.mark.asyncio
    async def test_image_without_storage_key_does_not_call_minio(self):
        from app.domain.models.source_image import SourceImage

        mock_img = MagicMock(spec=SourceImage)
        mock_img.storage_key = None

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
        mock_delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_deletes_multiple_images_all_from_minio(self):
        from app.domain.models.source_image import SourceImage

        mock_imgs = []
        for i in range(3):
            m = MagicMock(spec=SourceImage)
            m.storage_key = f"source-images/donaldson/{i}_Figure.webp"
            mock_imgs.append(m)

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_imgs
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()

        with patch(
            "app.ai.rag.pipeline.S3StorageService.delete_object",
            new_callable=AsyncMock,
        ) as mock_delete:
            count = await self.pipeline.clear_source_images("donaldson", session=mock_session)

        assert count == 3
        assert mock_delete.call_count == 3
