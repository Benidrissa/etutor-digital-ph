"""Tests for file upload endpoint and file processor service."""

import io
import os
import struct
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.services.file_processor import FileProcessor, _extract_pdf_text, _parse_csv_text
from app.infrastructure.config.settings import get_settings


class TestFileProcessor:
    """Unit tests for FileProcessor."""

    def setup_method(self):
        self.processor = FileProcessor()

    def _make_tiny_png(self) -> bytes:
        """Return a minimal valid 1x1 PNG."""
        return (
            b"\x89PNG\r\n\x1a\n"
            b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
            b"\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N"
            b"\x00\x00\x00\x00IEND\xaeB`\x82"
        )

    def test_validate_accepts_valid_png(self):
        data = self._make_tiny_png()
        self.processor.validate_file("test.png", "image/png", len(data), data)

    def test_validate_rejects_oversized_file(self):
        large_data = b"x" * (11 * 1024 * 1024)
        with pytest.raises(ValueError, match="exceeds maximum size"):
            self.processor.validate_file("big.png", "image/png", len(large_data), large_data)

    def test_validate_rejects_disallowed_mime_type(self):
        data = b"fake"
        with pytest.raises(ValueError, match="not allowed"):
            self.processor.validate_file("script.py", "text/x-python", len(data), data)

    def test_validate_rejects_executable_extension(self):
        data = b"fake binary"
        with pytest.raises(ValueError, match="not allowed"):
            self.processor.validate_file("malware.exe", "image/png", len(data), data)

    def test_validate_rejects_pe_magic_bytes(self):
        data = b"MZ\x90\x00" + b"\x00" * 100
        with pytest.raises(ValueError, match="pe_executable"):
            self.processor.validate_file("bad.png", "image/png", len(data), data)

    def test_validate_rejects_elf_magic_bytes(self):
        data = b"\x7fELF" + b"\x00" * 100
        with pytest.raises(ValueError, match="elf_executable"):
            self.processor.validate_file("bad.png", "image/png", len(data), data)

    def test_validate_rejects_shell_script(self):
        data = b"#!/bin/bash\necho hi"
        with pytest.raises(ValueError, match="shell_script"):
            self.processor.validate_file("script.png", "image/png", len(data), data)

    def test_parse_csv_returns_summary(self):
        csv_data = b"country,cases,deaths\nSenegal,100,5\nGhana,200,8\n"
        result = _parse_csv_text(csv_data, 20)
        assert "country" in result
        assert "cases" in result
        assert "Senegal" in result

    def test_image_blocks_contain_base64(self):
        data = self._make_tiny_png()
        blocks = self.processor._image_blocks("image/png", data)
        assert len(blocks) == 1
        assert blocks[0]["type"] == "image"
        assert blocks[0]["source"]["type"] == "base64"
        assert blocks[0]["source"]["media_type"] == "image/png"
        assert len(blocks[0]["source"]["data"]) > 0

    def test_text_blocks_contain_content(self):
        data = b"Hello world text content"
        blocks = self.processor._text_blocks(data)
        assert len(blocks) == 1
        assert blocks[0]["type"] == "text"
        assert "Hello world" in blocks[0]["text"]

    def test_csv_blocks_contain_content(self):
        csv_data = b"col1,col2\nval1,val2\n"
        blocks = self.processor._csv_blocks("text/csv", csv_data)
        assert len(blocks) == 1
        assert blocks[0]["type"] == "text"
        assert "col1" in blocks[0]["text"]

    async def test_process_stores_file_and_returns_metadata(self, tmp_path):
        with patch.object(self.processor, "prepare_temp_dir", return_value=tmp_path):
            data = self._make_tiny_png()
            user_id = uuid.uuid4()
            result = await self.processor.process("photo.png", "image/png", data, user_id)

        assert result.file_id
        assert result.original_name == "photo.png"
        assert result.mime_type == "image/png"
        assert result.size_bytes == len(data)
        assert result.content_for_claude
        assert Path(result.file_path).exists()

    def test_cleanup_expired_files_deletes_old_files(self, tmp_path):
        with patch.object(self.processor.settings, "upload_temp_dir", str(tmp_path)):
            old_file = tmp_path / "old_upload.png"
            old_file.write_bytes(b"old")
            import time
            old_time = time.time() - (25 * 3600)
            os.utime(old_file, (old_time, old_time))

            new_file = tmp_path / "new_upload.png"
            new_file.write_bytes(b"new")

            deleted = self.processor.cleanup_expired_files()

        assert deleted == 1
        assert not old_file.exists()
        assert new_file.exists()


class TestFileUploadEndpoint:
    """Integration-style tests for the upload endpoint."""

    async def test_upload_accepts_valid_png(self, client, auth_headers):
        png_data = (
            b"\x89PNG\r\n\x1a\n"
            b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
            b"\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N"
            b"\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        response = await client.post(
            "/api/v1/tutor/upload",
            headers=auth_headers,
            files={"file": ("test.png", io.BytesIO(png_data), "image/png")},
        )
        assert response.status_code == 200
        data = response.json()
        assert "file_id" in data
        assert data["mime_type"] == "image/png"
        assert data["original_name"] == "test.png"

    async def test_upload_rejects_oversized_file(self, client, auth_headers):
        large_data = b"x" * (11 * 1024 * 1024)
        response = await client.post(
            "/api/v1/tutor/upload",
            headers=auth_headers,
            files={"file": ("big.png", io.BytesIO(large_data), "image/png")},
        )
        assert response.status_code == 422

    async def test_upload_rejects_executable_file(self, client, auth_headers):
        exe_data = b"MZ\x90\x00" + b"\x00" * 100
        response = await client.post(
            "/api/v1/tutor/upload",
            headers=auth_headers,
            files={"file": ("malware.exe", io.BytesIO(exe_data), "application/octet-stream")},
        )
        assert response.status_code in (422, 400)

    async def test_upload_requires_auth(self, client):
        response = await client.post(
            "/api/v1/tutor/upload",
            files={"file": ("test.png", io.BytesIO(b"data"), "image/png")},
        )
        assert response.status_code == 401

    async def test_pdf_text_extraction_returns_content(self, tmp_path):
        settings = get_settings()
        pdf_bytes = _create_minimal_pdf()
        result = _extract_pdf_text(pdf_bytes, settings.upload_max_pdf_tokens)
        assert isinstance(result, str)

    async def test_file_ids_included_in_chat(self, client, auth_headers):
        request_body = {
            "message": "Analyse this file",
            "file_ids": ["non-existent-id"],
        }
        with patch("app.domain.services.tutor_service.TutorService.send_message") as mock_send:
            async def _fake_stream(*args, **kwargs):
                yield {"type": "content", "data": {"text": "ok"}}
                yield {"type": "finished", "data": {"remaining_messages": 49}, "finished": True}

            mock_send.return_value = _fake_stream()
            response = await client.post(
                "/api/v1/tutor/chat",
                headers=auth_headers,
                json=request_body,
            )
        assert response.status_code == 200


def _create_minimal_pdf() -> bytes:
    """Create a minimal valid PDF with some text for testing extraction."""
    return b"""%PDF-1.4
1 0 obj<</Type /Catalog /Pages 2 0 R>>endobj
2 0 obj<</Type /Pages /Kids [3 0 R] /Count 1>>endobj
3 0 obj<</Type /Page /MediaBox [0 0 612 792] /Parent 2 0 R /Contents 4 0 R /Resources<</Font<</F1<</Type /Font /Subtype /Type1 /BaseFont /Helvetica>>>>>>>>endobj
4 0 obj<</Length 44>>
stream
BT /F1 12 Tf 100 700 Td (Test PDF content) Tj ET
endstream
endobj
xref
0 5
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
0000000317 00000 n
trailer<</Size 5 /Root 1 0 R>>
startxref
413
%%EOF"""
