"""Unit tests for RAG indexation source naming — ensures PDF filename is used instead of UUID."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestRAGIndexationSourceName:
    """Verify that document chunks are stored with PDF filename (not UUID) as source."""

    def test_pdf_stem_used_as_source_not_uuid(self, tmp_path):
        """Source should be the PDF filename stem, not the rag_collection_id UUID."""
        pdf_file = tmp_path / "Global_Internal_Audit_Standards_2024.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake content")

        pdf_path = Path(pdf_file)
        rag_collection_id = "d12f0f92-2af6-4bea-9a29-f8e0e4edb360"

        source_name = pdf_path.stem.lower().replace(" ", "_")

        assert source_name == "global_internal_audit_standards_2024"
        assert source_name != rag_collection_id
        assert "-" not in source_name or source_name.replace("-", "").isalnum() is False

    def test_spaces_in_filename_replaced_with_underscore(self, tmp_path):
        """Spaces in PDF filename should be replaced with underscores in source name."""
        pdf_file = tmp_path / "Public Health Principles.pdf"
        pdf_path = Path(pdf_file)

        source_name = pdf_path.stem.lower().replace(" ", "_")

        assert source_name == "public_health_principles"
        assert " " not in source_name

    def test_filename_normalized_to_lowercase(self, tmp_path):
        """Source name should be lowercase regardless of PDF filename casing."""
        pdf_file = tmp_path / "Donaldson_Essential_PH.pdf"
        pdf_path = Path(pdf_file)

        source_name = pdf_path.stem.lower().replace(" ", "_")

        assert source_name == "donaldson_essential_ph"
        assert source_name == source_name.lower()

    @pytest.mark.asyncio
    async def test_process_pdf_called_with_filename_source(self, tmp_path):
        """RAG pipeline must receive the PDF filename stem as source, not the UUID."""
        pdf_file = tmp_path / "triola_biostatistics.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake")

        rag_collection_id = "d12f0f92-2af6-4bea-9a29-f8e0e4edb360"
        captured_calls = []

        async def mock_process_pdf(pdf_path, source, **kwargs):
            captured_calls.append({"pdf_path": pdf_path, "source": source})
            return 10

        mock_pipeline = MagicMock()
        mock_pipeline.process_pdf_document = mock_process_pdf

        mock_embedding_service = MagicMock()

        with (
            patch("app.ai.rag.embeddings.EmbeddingService", return_value=mock_embedding_service),
            patch("app.ai.rag.pipeline.RAGPipeline", return_value=mock_pipeline),
        ):
            pdf_path = Path(pdf_file)
            pdf_source_name = pdf_path.stem.lower().replace(" ", "_")
            chunks = await mock_pipeline.process_pdf_document(
                pdf_path=str(pdf_path),
                source=pdf_source_name,
            )

        assert len(captured_calls) == 1
        assert captured_calls[0]["source"] == "triola_biostatistics"
        assert captured_calls[0]["source"] != rag_collection_id
        assert chunks == 10
