"""Unit tests for RAGPipeline.process_pdf_images and clear_source_images."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ai.rag.pipeline import RAGPipeline


def _uuid():
    return uuid.uuid4()


def _make_extracted_image(
    page_number: int = 1,
    figure_number: str | None = "1.1",
    caption: str | None = "A test figure",
    surrounding_text: str = "Some surrounding text",
    image_type: str = "diagram",
    width: int = 400,
    height: int = 300,
    file_size_bytes: int = 10240,
    original_format: str = "png",
):
    img = MagicMock()
    img.image_bytes = b"\x00" * 100
    img.page_number = page_number
    img.figure_number = figure_number
    img.caption = caption
    img.attribution = None
    img.surrounding_text = surrounding_text
    img.image_type = image_type
    img.width = width
    img.height = height
    img.file_size_bytes = file_size_bytes
    img.original_format = original_format
    img.chapter = None
    img.section = None
    return img


def _make_pipeline():
    embedding_service = AsyncMock()
    embedding_service.generate_embedding = AsyncMock(return_value=[0.1] * 1536)
    return RAGPipeline(embedding_service=embedding_service)


def _make_session():
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    return session


class TestProcessPdfImages:
    @pytest.mark.asyncio
    async def test_returns_zero_when_pdf_not_found(self, tmp_path):
        pipeline = _make_pipeline()
        session = _make_session()
        count = await pipeline.process_pdf_images(
            pdf_path=tmp_path / "nonexistent.pdf",
            source="donaldson",
            rag_collection_id="col-1",
            session=session,
        )
        assert count == 0

    @pytest.mark.asyncio
    async def test_returns_zero_when_extractor_raises(self, tmp_path):
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4")
        pipeline = _make_pipeline()
        session = _make_session()

        with patch(
            "app.ai.rag.pipeline.PDFImageExtractor.extract_images_from_pdf",
            side_effect=RuntimeError("extraction error"),
        ):
            count = await pipeline.process_pdf_images(
                pdf_path=pdf_path,
                source="donaldson",
                rag_collection_id="col-1",
                session=session,
            )

        assert count == 0

    @pytest.mark.asyncio
    async def test_processes_single_image(self, tmp_path):
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4")
        pipeline = _make_pipeline()
        session = _make_session()
        img = _make_extracted_image()

        with (
            patch(
                "app.ai.rag.pipeline.PDFImageExtractor.extract_images_from_pdf",
                return_value=[img],
            ),
            patch(
                "app.ai.rag.pipeline.S3StorageService.upload_bytes",
                new_callable=AsyncMock,
                return_value="https://minio/bucket/key.webp",
            ),
            patch(
                "app.ai.rag.pipeline.ImageLinker.link_images_to_chunks",
                new_callable=AsyncMock,
                return_value=1,
            ),
        ):
            count = await pipeline.process_pdf_images(
                pdf_path=pdf_path,
                source="donaldson",
                rag_collection_id="col-1",
                session=session,
            )

        assert count == 1
        session.add.assert_called_once()
        session.flush.assert_called_once()
        session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_image_when_upload_fails(self, tmp_path):
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4")
        pipeline = _make_pipeline()
        session = _make_session()
        img = _make_extracted_image()

        with (
            patch(
                "app.ai.rag.pipeline.PDFImageExtractor.extract_images_from_pdf",
                return_value=[img],
            ),
            patch(
                "app.ai.rag.pipeline.S3StorageService.upload_bytes",
                new_callable=AsyncMock,
                side_effect=RuntimeError("minio down"),
            ),
            patch(
                "app.ai.rag.pipeline.ImageLinker.link_images_to_chunks",
                new_callable=AsyncMock,
                return_value=0,
            ),
        ):
            count = await pipeline.process_pdf_images(
                pdf_path=pdf_path,
                source="donaldson",
                rag_collection_id="col-1",
                session=session,
            )

        assert count == 0
        session.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_continues_when_embedding_fails(self, tmp_path):
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4")
        pipeline = _make_pipeline()
        pipeline.embedding_service.generate_embedding = AsyncMock(
            side_effect=RuntimeError("openai error")
        )
        session = _make_session()
        img = _make_extracted_image()

        with (
            patch(
                "app.ai.rag.pipeline.PDFImageExtractor.extract_images_from_pdf",
                return_value=[img],
            ),
            patch(
                "app.ai.rag.pipeline.S3StorageService.upload_bytes",
                new_callable=AsyncMock,
                return_value="https://minio/bucket/key.webp",
            ),
            patch(
                "app.ai.rag.pipeline.ImageLinker.link_images_to_chunks",
                new_callable=AsyncMock,
                return_value=0,
            ),
        ):
            count = await pipeline.process_pdf_images(
                pdf_path=pdf_path,
                source="donaldson",
                rag_collection_id="col-1",
                session=session,
            )

        assert count == 1
        session.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_processes_multiple_images(self, tmp_path):
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4")
        pipeline = _make_pipeline()
        session = _make_session()
        images = [_make_extracted_image(page_number=i, figure_number=str(i)) for i in range(1, 4)]

        with (
            patch(
                "app.ai.rag.pipeline.PDFImageExtractor.extract_images_from_pdf",
                return_value=images,
            ),
            patch(
                "app.ai.rag.pipeline.S3StorageService.upload_bytes",
                new_callable=AsyncMock,
                return_value="https://minio/bucket/key.webp",
            ),
            patch(
                "app.ai.rag.pipeline.ImageLinker.link_images_to_chunks",
                new_callable=AsyncMock,
                return_value=3,
            ),
        ):
            count = await pipeline.process_pdf_images(
                pdf_path=pdf_path,
                source="donaldson",
                rag_collection_id="col-1",
                session=session,
            )

        assert count == 3
        assert session.add.call_count == 3

    @pytest.mark.asyncio
    async def test_storage_key_format(self, tmp_path):
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4")
        pipeline = _make_pipeline()
        session = _make_session()
        img = _make_extracted_image(page_number=5, figure_number="2.3")

        uploaded_keys = []

        async def capture_upload(key, data, content_type="application/octet-stream"):
            uploaded_keys.append(key)
            return f"https://minio/bucket/{key}"

        with (
            patch(
                "app.ai.rag.pipeline.PDFImageExtractor.extract_images_from_pdf",
                return_value=[img],
            ),
            patch(
                "app.ai.rag.pipeline.S3StorageService.upload_bytes",
                new_callable=AsyncMock,
                side_effect=capture_upload,
            ),
            patch(
                "app.ai.rag.pipeline.ImageLinker.link_images_to_chunks",
                new_callable=AsyncMock,
                return_value=1,
            ),
        ):
            await pipeline.process_pdf_images(
                pdf_path=pdf_path,
                source="donaldson",
                rag_collection_id="col-1",
                session=session,
            )

        assert len(uploaded_keys) == 1
        assert "source-images/donaldson/" in uploaded_keys[0]
        assert "p5_2.3.webp" in uploaded_keys[0]

    @pytest.mark.asyncio
    async def test_no_flush_when_no_images_stored(self, tmp_path):
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4")
        pipeline = _make_pipeline()
        session = _make_session()

        with (
            patch(
                "app.ai.rag.pipeline.PDFImageExtractor.extract_images_from_pdf",
                return_value=[],
            ),
            patch(
                "app.ai.rag.pipeline.ImageLinker.link_images_to_chunks",
                new_callable=AsyncMock,
                return_value=0,
            ),
        ):
            count = await pipeline.process_pdf_images(
                pdf_path=pdf_path,
                source="donaldson",
                rag_collection_id="col-1",
                session=session,
            )

        assert count == 0
        session.flush.assert_not_called()

    @pytest.mark.asyncio
    async def test_calls_image_linker_after_storing(self, tmp_path):
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4")
        pipeline = _make_pipeline()
        session = _make_session()
        img = _make_extracted_image()

        linker_called_with = []

        async def mock_link(source, sess):
            linker_called_with.append(source)
            return 1

        with (
            patch(
                "app.ai.rag.pipeline.PDFImageExtractor.extract_images_from_pdf",
                return_value=[img],
            ),
            patch(
                "app.ai.rag.pipeline.S3StorageService.upload_bytes",
                new_callable=AsyncMock,
                return_value="https://minio/bucket/key.webp",
            ),
            patch(
                "app.ai.rag.pipeline.ImageLinker.link_images_to_chunks",
                new_callable=AsyncMock,
                side_effect=mock_link,
            ),
        ):
            await pipeline.process_pdf_images(
                pdf_path=pdf_path,
                source="triola",
                rag_collection_id="col-2",
                session=session,
            )

        assert linker_called_with == ["triola"]


class TestClearSourceImages:
    @pytest.mark.asyncio
    async def test_returns_zero_when_no_images(self):
        pipeline = _make_pipeline()
        session = _make_session()

        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        session.execute = AsyncMock(return_value=result)

        count = await pipeline.clear_source_images(source="donaldson", session=session)

        assert count == 0
        session.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_deletes_db_records_and_minio_objects(self):
        pipeline = _make_pipeline()
        session = _make_session()

        img1 = MagicMock()
        img1.storage_key = "source-images/donaldson/p1_1.1.webp"
        img2 = MagicMock()
        img2.storage_key = "source-images/donaldson/p2_2.1.webp"

        select_result = MagicMock()
        select_result.scalars.return_value.all.return_value = [img1, img2]
        delete_result = MagicMock()

        session.execute = AsyncMock(side_effect=[select_result, delete_result])

        with patch(
            "app.ai.rag.pipeline.S3StorageService.delete_object",
            new_callable=AsyncMock,
        ) as mock_delete:
            count = await pipeline.clear_source_images(source="donaldson", session=session)

        assert count == 2
        assert mock_delete.call_count == 2
        session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_continues_when_minio_delete_fails(self):
        pipeline = _make_pipeline()
        session = _make_session()

        img = MagicMock()
        img.storage_key = "source-images/donaldson/p1_1.1.webp"

        select_result = MagicMock()
        select_result.scalars.return_value.all.return_value = [img]
        delete_result = MagicMock()

        session.execute = AsyncMock(side_effect=[select_result, delete_result])

        with patch(
            "app.ai.rag.pipeline.S3StorageService.delete_object",
            new_callable=AsyncMock,
            side_effect=RuntimeError("minio error"),
        ):
            count = await pipeline.clear_source_images(source="donaldson", session=session)

        assert count == 1
        session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_minio_delete_when_no_storage_key(self):
        pipeline = _make_pipeline()
        session = _make_session()

        img = MagicMock()
        img.storage_key = None

        select_result = MagicMock()
        select_result.scalars.return_value.all.return_value = [img]
        delete_result = MagicMock()

        session.execute = AsyncMock(side_effect=[select_result, delete_result])

        with patch(
            "app.ai.rag.pipeline.S3StorageService.delete_object",
            new_callable=AsyncMock,
        ) as mock_delete:
            count = await pipeline.clear_source_images(source="donaldson", session=session)

        assert count == 1
        mock_delete.assert_not_called()
        session.commit.assert_called_once()
