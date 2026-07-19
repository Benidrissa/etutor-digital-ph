"""Unit tests for NUL-byte sanitization in PDF resource extraction (#2642).

Some PDFs' embedded fonts/CID maps make PyMuPDF emit NUL (0x00) characters in
extracted page text and TOC titles. PostgreSQL rejects NUL in text and jsonb
columns, so unsanitized text crashed extract_course_resource at commit time and
blocked course creation with a 400 no_source_summary.
"""

from app.tasks.resource_extraction import _sanitize_pdf_text


def test_strips_nul_characters():
    assert _sanitize_pdf_text("Chap\x00itre 1\x00") == "Chapitre 1"


def test_preserves_text_without_nul():
    text = "Table des matières\n\nContenu accentué: é à ç — 100%"
    assert _sanitize_pdf_text(text) == text


def test_nul_only_string_becomes_empty():
    assert _sanitize_pdf_text("\x00\x00") == ""


def test_preserves_other_control_characters():
    # Only NUL is rejected by PostgreSQL; keep newlines/tabs used for layout.
    assert _sanitize_pdf_text("line1\nline2\tend") == "line1\nline2\tend"
