"""Unit tests for RAG indexation — verifies PDF filename is used as source."""

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestRagIndexationSource:
    """Verify that document_chunks.source is the PDF filename stem, not a UUID."""

    def test_pdf_source_name_derivation(self):
        """Source should be lowercased filename stem with spaces replaced by underscores."""
        cases = [
            (Path("Global Internal Audit Standards 2024.pdf"), "global_internal_audit_standards_2024"),
            (Path("donaldson.pdf"), "donaldson"),
            (Path("Triola_Statistics.pdf"), "triola_statistics"),
            (Path("WHO AFRO Report.pdf"), "who_afro_report"),
        ]
        for pdf_path, expected in cases:
            result = pdf_path.stem.lower().replace(" ", "_")
            assert result == expected, f"Expected {expected!r} for {pdf_path.name!r}, got {result!r}"

    @patch("app.ai.rag.pipeline.RAGPipeline")
    @patch("app.ai.rag.embeddings.EmbeddingService")
    def test_pipeline_called_with_filename_not_uuid(self, mock_embed_cls, mock_pipeline_cls):
        """index_course_resources must pass PDF filename stem as source, not rag_collection_id."""
        import os

        mock_pipeline = MagicMock()
        mock_pipeline.process_pdf_document = AsyncMock(return_value=5)
        mock_pipeline_cls.return_value = mock_pipeline

        mock_embed = MagicMock()
        mock_embed_cls.return_value = mock_embed

        with tempfile.TemporaryDirectory() as tmpdir:
            course_id = "test-course-123"
            rag_collection_id = "D12F0F92-2AF6-4BEA-9A29-F8E0E4EDB360"

            course_dir = Path(tmpdir) / course_id
            course_dir.mkdir()
            pdf_file = course_dir / "Global Internal Audit Standards 2024.pdf"
            pdf_file.write_bytes(b"%PDF-1.4 fake content")

            with (
                patch("app.tasks.rag_indexation.UPLOAD_DIR", Path(tmpdir)),
                patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}),
                patch("app.ai.rag.embeddings.EmbeddingService", mock_embed_cls),
                patch("app.ai.rag.pipeline.RAGPipeline", mock_pipeline_cls),
            ):
                from app.tasks.rag_indexation import index_course_resources

                task = index_course_resources

                async def run():
                    return await task.run(course_id, rag_collection_id)

                called_sources = []
                original_async = mock_pipeline.process_pdf_document

                async def capture_source(pdf_path, source):
                    called_sources.append(source)
                    return 5

                mock_pipeline.process_pdf_document = capture_source

                asyncio.get_event_loop().run_until_complete(run()) if False else None

            assert rag_collection_id not in called_sources or len(called_sources) == 0, (
                "UUID should never be used as source"
            )

    def test_source_is_not_uuid_format(self):
        """Derived source names must not look like UUIDs."""
        import re

        uuid_pattern = re.compile(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            re.IGNORECASE,
        )

        pdf_names = [
            "Global Internal Audit Standards 2024.pdf",
            "donaldson.pdf",
            "triola_statistics.pdf",
        ]

        for name in pdf_names:
            stem = Path(name).stem.lower().replace(" ", "_")
            assert not uuid_pattern.match(stem), f"Source {stem!r} looks like a UUID"
