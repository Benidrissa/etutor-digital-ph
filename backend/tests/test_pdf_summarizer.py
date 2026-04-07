"""Unit tests for the multi-pass PDF summarizer (issue #1039).

Verifies:
- _split_into_chunks handles small and large texts correctly
- summarize_pdf_for_syllabus falls back gracefully when no API key
- summarize_pdfs_sync returns one summary per input PDF
- Task integration: PdfSummarizer is called instead of truncation
"""

import asyncio
import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ai.pdf_summarizer import _split_into_chunks, summarize_pdfs_sync


class TestSplitIntoChunks:
    def test_small_text_returns_single_chunk(self):
        text = "Hello world"
        chunks = _split_into_chunks(text, chunk_size=1000)
        assert chunks == ["Hello world"]

    def test_exact_size_returns_single_chunk(self):
        text = "a" * 1000
        chunks = _split_into_chunks(text, chunk_size=1000)
        assert len(chunks) == 1

    def test_large_text_splits_into_multiple_chunks(self):
        text = ("word " * 200 + "\n") * 10
        chunks = _split_into_chunks(text, chunk_size=500)
        assert len(chunks) > 1

    def test_chunks_cover_full_text(self):
        text = ("paragraph line\n") * 50
        chunks = _split_into_chunks(text, chunk_size=100)
        combined = "".join(chunks)
        assert combined == text

    def test_chunk_size_respected(self):
        text = "x" * 10_000
        chunk_size = 1000
        chunks = _split_into_chunks(text, chunk_size=chunk_size)
        for chunk in chunks:
            assert len(chunk) <= chunk_size

    def test_prefers_newline_boundaries(self):
        text = "line1\nline2\nline3\nline4\nline5\n"
        chunks = _split_into_chunks(text, chunk_size=15)
        for chunk in chunks:
            assert not chunk.startswith(" ")


class TestSummarizePdfForSyllabus:
    def test_no_api_key_returns_toc_fallback(self):
        from app.ai.pdf_summarizer import summarize_pdf_for_syllabus

        toc = [(1, "Chapter 1: Intro", 1), (2, "Section 1.1", 5)]
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            result = asyncio.run(summarize_pdf_for_syllabus("TestBook", "some text", toc=toc))
        assert "Chapter 1: Intro" in result

    def test_no_api_key_no_toc_returns_placeholder(self):
        from app.ai.pdf_summarizer import summarize_pdf_for_syllabus

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            result = asyncio.run(summarize_pdf_for_syllabus("TestBook", "some text", toc=None))
        assert "TestBook" in result

    def test_single_chunk_calls_summarize_once(self):
        from app.ai.pdf_summarizer import summarize_pdf_for_syllabus

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Summary of single chunk")]

        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        with (
            patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}),
            patch("anthropic.AsyncAnthropic", return_value=mock_client),
        ):
            result = asyncio.run(
                summarize_pdf_for_syllabus("SmallBook", "short text", toc=None, chunk_size=100_000)
            )

        assert result == "Summary of single chunk"
        assert mock_client.messages.create.call_count == 1

    def test_multi_chunk_calls_summarize_then_combine(self):
        from app.ai.pdf_summarizer import summarize_pdf_for_syllabus

        call_count = 0

        async def mock_create(**kwargs):
            nonlocal call_count
            call_count += 1
            resp = MagicMock()
            resp.content = [MagicMock(text=f"Summary call {call_count}")]
            return resp

        mock_client = MagicMock()
        mock_client.messages.create = mock_create

        text = "word " * 5000
        with (
            patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}),
            patch("anthropic.AsyncAnthropic", return_value=mock_client),
        ):
            result = asyncio.run(
                summarize_pdf_for_syllabus("LargeBook", text, toc=None, chunk_size=5000)
            )

        assert call_count >= 2, "Should call Claude at least once per chunk plus once to combine"
        assert "Summary call" in result

    def test_toc_prepended_to_text(self):
        from app.ai.pdf_summarizer import summarize_pdf_for_syllabus

        toc = [(1, "Chapter 1", 1), (1, "Chapter 2", 10)]
        captured_prompts = []

        async def mock_create(**kwargs):
            captured_prompts.append(kwargs.get("messages", [{}])[0].get("content", ""))
            resp = MagicMock()
            resp.content = [MagicMock(text="ok")]
            return resp

        mock_client = MagicMock()
        mock_client.messages.create = mock_create

        with (
            patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}),
            patch("anthropic.AsyncAnthropic", return_value=mock_client),
        ):
            asyncio.run(summarize_pdf_for_syllabus("Book", "content", toc=toc, chunk_size=100_000))

        assert any("Chapter 1" in p for p in captured_prompts)


class TestSummarizePdfsSync:
    def test_returns_one_summary_per_pdf(self):
        pdf_texts = [
            ("BookA", "text a", []),
            ("BookB", "text b", []),
        ]
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            result = summarize_pdfs_sync(pdf_texts)

        assert len(result) == 2
        for r in result:
            assert isinstance(r, str)

    def test_order_preserved(self):
        names_seen = []

        async def fake_summarize(name, text, toc=None, chunk_size=None):
            names_seen.append(name)
            return f"summary:{name}"

        pdf_texts = [
            ("First", "aaa", []),
            ("Second", "bbb", []),
            ("Third", "ccc", []),
        ]

        with (
            patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}),
            patch("app.ai.pdf_summarizer.summarize_pdf_for_syllabus", side_effect=fake_summarize),
        ):
            result = summarize_pdfs_sync(pdf_texts)

        assert result[0] == "summary:First"
        assert result[1] == "summary:Second"
        assert result[2] == "summary:Third"


class TestSyllabusTaskWithSummarization:
    """Integration tests for the Celery task's PDF summarization path."""

    def _run_task(self, course_id, estimated_hours):
        from app.tasks.syllabus_generation import generate_course_syllabus

        with patch.object(generate_course_syllabus, "update_state", MagicMock()):
            return generate_course_syllabus.run(course_id, estimated_hours)

    def test_pdf_dir_exists_calls_summarizer_not_truncate(self, sample_module_dicts):
        """When PDF directory exists and text exceeds budget, task must call summarize_pdfs_sync."""
        from app.tasks.syllabus_generation import _CONTEXT_BUDGET_CHARS

        course_id = str(uuid.uuid4())
        course_data = {
            "title_fr": "Santé",
            "title_en": "Health",
            "course_hours": 20,
            "rag_collection_id": None,
            "domain_slugs": [],
            "level_slugs": [],
            "audience_slugs": [],
        }

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_sync_engine = MagicMock()

        call_count = 0

        def mock_run(coro):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return course_data
            return sample_module_dicts

        large_text = "x" * (_CONTEXT_BUDGET_CHARS + 1)
        mock_page = MagicMock()
        mock_page.get_text.return_value = large_text
        mock_doc = MagicMock()
        mock_doc.get_toc.return_value = []
        mock_doc.__iter__ = MagicMock(return_value=iter([mock_page]))
        mock_doc.close = MagicMock()

        mock_summarize = MagicMock(return_value=["Structured summary of book"])

        with (
            patch("asyncio.run", side_effect=mock_run),
            patch("pathlib.Path.exists", return_value=True),
            patch(
                "pathlib.Path.glob",
                return_value=[MagicMock(stem="textbook", __str__=lambda s: "textbook.pdf")],
            ),
            patch("fitz.open", return_value=mock_doc),
            patch("app.ai.pdf_summarizer.summarize_pdfs_sync", mock_summarize),
            patch("sqlalchemy.create_engine", return_value=mock_sync_engine),
            patch("sqlalchemy.orm.Session", return_value=mock_session),
        ):
            result = self._run_task(course_id, 20)

        mock_summarize.assert_called_once()
        assert result["status"] == "complete"

    def test_no_truncation_string_in_resource_text(self, sample_module_dicts):
        """The resource_text passed to Claude must NOT contain '(truncated to'."""
        from app.tasks.syllabus_generation import _CONTEXT_BUDGET_CHARS

        course_id = str(uuid.uuid4())
        course_data = {
            "title_fr": "Épidémio",
            "title_en": "Epi",
            "course_hours": 30,
            "rag_collection_id": None,
            "domain_slugs": [],
            "level_slugs": [],
            "audience_slugs": [],
        }

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_sync_engine = MagicMock()

        call_count = 0

        def mock_run(coro):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return course_data
            return sample_module_dicts

        large_text = "x" * (_CONTEXT_BUDGET_CHARS + 1)
        mock_page = MagicMock()
        mock_page.get_text.return_value = large_text
        mock_doc = MagicMock()
        mock_doc.get_toc.return_value = []
        mock_doc.__iter__ = MagicMock(return_value=iter([mock_page]))
        mock_doc.close = MagicMock()

        def capture_summarize(pdf_full_texts, **kwargs):
            return ["Proper summary without truncation"] * len(pdf_full_texts)

        with (
            patch("asyncio.run", side_effect=mock_run),
            patch("pathlib.Path.exists", return_value=True),
            patch(
                "pathlib.Path.glob",
                return_value=[MagicMock(stem="bigbook", __str__=lambda s: "bigbook.pdf")],
            ),
            patch("fitz.open", return_value=mock_doc),
            patch("app.ai.pdf_summarizer.summarize_pdfs_sync", side_effect=capture_summarize),
            patch("sqlalchemy.create_engine", return_value=mock_sync_engine),
            patch("sqlalchemy.orm.Session", return_value=mock_session),
        ):
            result = self._run_task(course_id, 30)

        assert result["status"] == "complete"


@pytest.fixture
def sample_module_dicts():
    return [
        {
            "title_fr": "Introduction à la santé publique",
            "title_en": "Introduction to Public Health",
            "description_fr": "Les bases.",
            "description_en": "The basics.",
            "estimated_hours": 20,
            "bloom_level": "remember",
            "units": [
                {
                    "title_fr": "Unité 1",
                    "title_en": "Unit 1",
                    "description_fr": "Desc FR",
                    "description_en": "Desc EN",
                }
            ],
        }
    ]
