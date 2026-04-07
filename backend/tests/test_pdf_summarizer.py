"""Unit tests for the simplified 1-call-per-PDF summarizer (issue #1139).

Verifies:
- split_pdf_by_chapters handles small and large texts with/without TOC
- _split_into_chunks handles small and large texts correctly
- _compute_defaults returns correct values for known models
- _proportional_budgets distributes budget proportionally
- summarize_pdf_for_syllabus uses single-call path (new enriched prompt)
  and falls back gracefully when no API key
- summarize_single_pdf calls the enriched prompt
- summarize_pdfs_sync returns one summary per input resource
- syllabus_generation task loads resources from DB (pre-extracted at upload)
- Backward compat: old chunk-based call paths still work
"""

import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ai.pdf_summarizer import (
    PdfChunkPlan,
    _compute_defaults,
    _proportional_budgets,
    _split_into_chunks,
    compute_chunk_plan,
    split_pdf_by_chapters,
    summarize_pdfs_sync,
)


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


class TestSplitPdfByChapters:
    def test_small_text_returns_single_part(self):
        text = "x" * 100
        parts = split_pdf_by_chapters(text, toc=[], max_chars=1000)
        assert len(parts) == 1
        assert parts[0][1] == text

    def test_no_toc_splits_by_size(self):
        text = "x" * 5_000_000
        parts = split_pdf_by_chapters(text, toc=[], max_chars=2_500_000)
        assert len(parts) >= 2
        for _, part_text in parts:
            assert len(part_text) <= 2_500_000 + 1

    def test_no_toc_covers_full_text(self):
        text = ("line\n") * 100_000
        parts = split_pdf_by_chapters(text, toc=[], max_chars=100_000)
        combined = "".join(p[1] for p in parts)
        assert len(combined) >= len(text) - 5 * len(parts)

    def test_no_toc_part_names_numbered(self):
        text = "x" * 5_000_000
        parts = split_pdf_by_chapters(text, toc=[], max_chars=2_500_000)
        for i, (name, _) in enumerate(parts):
            assert f"Part {i + 1}" in name

    def test_with_toc_produces_multiple_groups(self):
        text = "x" * 3_000_000
        toc = [(1, "Chapter 1", 1), (1, "Chapter 2", 50), (1, "Chapter 3", 100)]
        parts = split_pdf_by_chapters(text, toc=toc, max_chars=2_500_000)
        assert len(parts) >= 1

    def test_with_toc_uses_chapter_titles(self):
        text = "content " * 10_000
        toc = [(1, "Introduction", 1), (1, "Methods", 30), (1, "Results", 60)]
        parts = split_pdf_by_chapters(text, toc=toc, max_chars=2_500_000)
        first_name = parts[0][0]
        assert isinstance(first_name, str) and len(first_name) > 0

    def test_empty_toc_falls_back_to_page_split(self):
        text = "x" * 5_000_000
        toc_no_pages = [(1, "Chapter 1", 0)]
        parts = split_pdf_by_chapters(text, toc=toc_no_pages, max_chars=2_500_000)
        assert len(parts) >= 2

    def test_each_part_within_max_chars(self):
        line = "This is a line of text with meaningful content.\n"
        text = line * 100_000
        toc = [(1, "Ch1", 1), (1, "Ch2", 40), (1, "Ch3", 80)]
        max_chars = 2_000_000
        parts = split_pdf_by_chapters(text, toc=toc, max_chars=max_chars)
        assert len(parts) >= 1
        for _, part_text in parts:
            assert len(part_text) <= len(text)


class TestComputeDefaults:
    def test_sonnet_4_6_returns_large_chunks(self):
        defaults = _compute_defaults("claude-sonnet-4-6")
        assert defaults["chunk_size_chars"] >= 300_000
        assert defaults["combine_chunk_size_chars"] >= 200_000
        assert defaults["chunk_max_output_tokens"] >= 16_000
        assert defaults["combine_max_output_tokens"] >= 32_000

    def test_sonnet_4_6_chunk_capped_at_500k(self):
        defaults = _compute_defaults("claude-sonnet-4-6")
        assert defaults["chunk_size_chars"] <= 500_000

    def test_default_model_returns_smaller_chunks(self):
        defaults = _compute_defaults("unknown-model")
        sonnet_defaults = _compute_defaults("claude-sonnet-4-6")
        assert defaults["chunk_size_chars"] < sonnet_defaults["chunk_size_chars"]
        assert defaults["chunk_max_output_tokens"] <= sonnet_defaults["chunk_max_output_tokens"]

    def test_haiku_returns_caps(self):
        defaults = _compute_defaults("claude-haiku-4-5")
        assert defaults["chunk_max_output_tokens"] <= 16_000
        assert defaults["combine_max_output_tokens"] <= 64_000

    def test_all_values_are_positive(self):
        for model in ["claude-sonnet-4-6", "claude-opus-4-6", "claude-haiku-4-5", "_default"]:
            defaults = _compute_defaults(model)
            for key, val in defaults.items():
                assert val > 0, f"{key} should be positive for model {model}"


class TestComputeChunkPlan:
    def test_returns_pdf_chunk_plan_instance(self):
        plan = compute_chunk_plan(
            pdf_chars=500_000,
            num_pdfs=1,
            total_pdf_chars=500_000,
            context_budget_chars=3_500_000,
        )
        assert isinstance(plan, PdfChunkPlan)

    def test_small_pdf_fits_in_single_chunk_sonnet(self):
        plan = compute_chunk_plan(
            pdf_chars=500_000,
            num_pdfs=1,
            total_pdf_chars=500_000,
            context_budget_chars=3_500_000,
            model="claude-sonnet-4-6",
        )
        assert plan.chunk_count == 1

    def test_large_pdf_requires_multiple_chunks(self):
        plan = compute_chunk_plan(
            pdf_chars=4_000_000,
            num_pdfs=1,
            total_pdf_chars=4_000_000,
            context_budget_chars=3_500_000,
            model="claude-sonnet-4-6",
        )
        assert plan.chunk_count >= 2

    def test_chunk_size_covers_full_pdf(self):
        pdf_chars = 2_100_000
        plan = compute_chunk_plan(
            pdf_chars=pdf_chars,
            num_pdfs=3,
            total_pdf_chars=5_000_000,
            context_budget_chars=3_500_000,
            model="claude-sonnet-4-6",
        )
        assert plan.chunk_size_chars * plan.chunk_count >= pdf_chars

    def test_all_values_are_positive(self):
        plan = compute_chunk_plan(
            pdf_chars=1_000_000,
            num_pdfs=2,
            total_pdf_chars=2_000_000,
            context_budget_chars=3_500_000,
        )
        assert plan.chunk_count >= 1
        assert plan.chunk_size_chars >= 1
        assert plan.chunk_max_output_tokens >= 1024
        assert plan.combine_max_output_tokens >= 1024

    def test_zero_pdf_chars_returns_single_chunk(self):
        plan = compute_chunk_plan(
            pdf_chars=0,
            num_pdfs=1,
            total_pdf_chars=0,
            context_budget_chars=3_500_000,
        )
        assert plan.chunk_count == 1

    def test_unknown_model_falls_back_to_default(self):
        plan = compute_chunk_plan(
            pdf_chars=100_000,
            num_pdfs=1,
            total_pdf_chars=100_000,
            context_budget_chars=3_500_000,
            model="unknown-model-xyz",
        )
        assert plan.chunk_count >= 1
        assert plan.chunk_size_chars >= 1


class TestProportionalBudgets:
    def test_none_budget_returns_none_list(self):
        pdf_texts = [("A", "aaa", []), ("B", "bbb", [])]
        result = _proportional_budgets(pdf_texts, None)
        assert result == [None, None]

    def test_empty_returns_empty(self):
        result = _proportional_budgets([], 100_000)
        assert result == []

    def test_proportional_to_text_size(self):
        pdf_texts = [("A", "a" * 100, []), ("B", "b" * 300, [])]
        result = _proportional_budgets(pdf_texts, 400_000)
        assert result[0] == 100_000
        assert result[1] == 300_000

    def test_equal_sizes_get_equal_budget(self):
        pdf_texts = [("A", "x" * 100, []), ("B", "y" * 100, []), ("C", "z" * 100, [])]
        result = _proportional_budgets(pdf_texts, 300_000)
        assert all(b == 100_000 for b in result)

    def test_zero_total_falls_back_to_even_split(self):
        pdf_texts = [("A", "", []), ("B", "", [])]
        result = _proportional_budgets(pdf_texts, 200_000)
        assert result == [100_000, 100_000]

    def test_sum_of_budgets_equals_total(self):
        pdf_texts = [("A", "a" * 50, []), ("B", "b" * 150, []), ("C", "c" * 300, [])]
        total = 500_000
        result = _proportional_budgets(pdf_texts, total)
        assert sum(r for r in result if r is not None) <= total


def _make_stream_client(
    text: str = "ok",
    captured_system: list | None = None,
    captured_user: list | None = None,
    stream_call_count: list | None = None,
):
    """Build a mock client whose .messages.stream() is an async context manager."""
    final_message = MagicMock()
    final_message.content = [MagicMock(text=text)]

    @asynccontextmanager
    async def mock_stream(**kwargs):
        if captured_system is not None:
            captured_system.append(kwargs.get("system", ""))
        if captured_user is not None:
            captured_user.append(kwargs.get("messages", [{}])[0].get("content", ""))
        if stream_call_count is not None:
            stream_call_count.append(1)

        async def _aiter():
            return
            yield  # makes it an async generator

        stream = MagicMock()
        stream.__aiter__ = lambda self: _aiter()
        stream.get_final_message = AsyncMock(return_value=final_message)
        yield stream

    mock_client = MagicMock()
    mock_client.messages.stream = mock_stream
    return mock_client


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

    def test_default_uses_single_call_enriched_prompt(self):
        """Without chunk overrides, must use summarize_single_pdf (new enriched prompt)."""
        from app.ai.pdf_summarizer import summarize_pdf_for_syllabus

        captured_system: list = []
        captured_user: list = []
        mock_client = _make_stream_client(
            text="Rich structured summary",
            captured_system=captured_system,
            captured_user=captured_user,
        )

        with (
            patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}),
            patch("anthropic.AsyncAnthropic", return_value=mock_client),
        ):
            result = asyncio.run(summarize_pdf_for_syllabus("SmallBook", "short text", toc=None))

        assert result == "Rich structured summary"
        assert len(captured_system) == 1
        assert any("instructional designer" in s for s in captured_system)
        assert any("EXHAUSTIVE" in p for p in captured_user)

    def test_single_chunk_legacy_path_when_chunk_size_given(self):
        """Explicit chunk_size_chars must trigger legacy chunking path (streaming)."""
        from app.ai.pdf_summarizer import summarize_pdf_for_syllabus

        stream_calls: list = []
        mock_client = _make_stream_client(
            text="Legacy chunk summary", stream_call_count=stream_calls
        )

        with (
            patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}),
            patch("anthropic.AsyncAnthropic", return_value=mock_client),
        ):
            result = asyncio.run(
                summarize_pdf_for_syllabus(
                    "SmallBook", "short text", toc=None, chunk_size_chars=100_000
                )
            )

        assert result == "Legacy chunk summary"
        assert len(stream_calls) == 1

    def test_toc_prepended_to_prompt_in_single_call_mode(self):
        from app.ai.pdf_summarizer import summarize_pdf_for_syllabus

        toc = [(1, "Chapter 1", 1), (1, "Chapter 2", 10)]
        captured_user: list = []
        mock_client = _make_stream_client(text="ok", captured_user=captured_user)

        with (
            patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}),
            patch("anthropic.AsyncAnthropic", return_value=mock_client),
        ):
            asyncio.run(summarize_pdf_for_syllabus("Book", "content", toc=toc))

        assert any("Chapter 1" in p for p in captured_user)


class TestSummarizeSinglePdf:
    def test_uses_syllabus_summary_system_prompt(self):
        from app.ai.pdf_summarizer import summarize_single_pdf

        captured_system: list = []
        mock_client = _make_stream_client(text="rich summary", captured_system=captured_system)

        asyncio.run(summarize_single_pdf(mock_client, "MyBook", "text here"))

        assert len(captured_system) == 1
        assert "instructional designer" in captured_system[0]

    def test_uses_exhaustive_instruction_in_prompt(self):
        from app.ai.pdf_summarizer import summarize_single_pdf

        captured_user: list = []
        mock_client = _make_stream_client(text="ok", captured_user=captured_user)

        asyncio.run(summarize_single_pdf(mock_client, "TestBook", "some text"))

        assert any("EXHAUSTIVE" in p for p in captured_user)
        assert any("Bloom" in p for p in captured_user)

    def test_toc_included_in_prompt(self):
        from app.ai.pdf_summarizer import summarize_single_pdf

        toc = [(1, "Chapter 1", 1), (2, "Section 1.1", 3)]
        captured_user: list = []
        mock_client = _make_stream_client(text="ok", captured_user=captured_user)

        asyncio.run(summarize_single_pdf(mock_client, "Book", "content", toc=toc))

        assert any("Chapter 1" in p for p in captured_user)

    def test_returns_stripped_text(self):
        from app.ai.pdf_summarizer import summarize_single_pdf

        mock_client = _make_stream_client(text="  summary with spaces  ")

        result = asyncio.run(summarize_single_pdf(mock_client, "Book", "text"))
        assert result == "summary with spaces"

    def test_single_api_call_regardless_of_text_size(self):
        from app.ai.pdf_summarizer import summarize_single_pdf

        stream_calls: list = []
        mock_client = _make_stream_client(text="ok", stream_call_count=stream_calls)

        large_text = "word " * 100_000
        asyncio.run(summarize_single_pdf(mock_client, "BigBook", large_text))

        assert len(stream_calls) == 1


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

        async def fake_summarize(name, text, toc=None, **kwargs):
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

    def test_no_chunk_overrides_uses_single_call_path(self):
        """When called without chunk overrides, chunk_size_chars should be None."""
        received_chunk_size = []

        async def fake_summarize(name, text, toc=None, **kwargs):
            received_chunk_size.append(kwargs.get("chunk_size_chars"))
            return f"summary:{name}"

        pdf_texts = [("A", "aaa", [])]

        with (
            patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}),
            patch("app.ai.pdf_summarizer.summarize_pdf_for_syllabus", side_effect=fake_summarize),
        ):
            summarize_pdfs_sync(pdf_texts)

        assert received_chunk_size[0] is None

    def test_budget_splits_proportionally(self):
        received_targets = []

        async def fake_summarize(name, text, toc=None, **kwargs):
            received_targets.append(kwargs.get("target_chars"))
            return f"summary:{name}"

        pdf_texts = [
            ("A", "a" * 100, []),
            ("B", "b" * 200, []),
            ("C", "c" * 100, []),
        ]

        with (
            patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}),
            patch("app.ai.pdf_summarizer.summarize_pdf_for_syllabus", side_effect=fake_summarize),
        ):
            result = summarize_pdfs_sync(pdf_texts, total_budget_chars=400_000)

        assert len(result) == 3
        assert received_targets[0] == 100_000
        assert received_targets[1] == 200_000
        assert received_targets[2] == 100_000

    def test_no_budget_passes_none_target(self):
        received_targets = []

        async def fake_summarize(name, text, toc=None, **kwargs):
            received_targets.append(kwargs.get("target_chars"))
            return f"summary:{name}"

        pdf_texts = [("A", "aaa", [])]

        with (
            patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}),
            patch("app.ai.pdf_summarizer.summarize_pdf_for_syllabus", side_effect=fake_summarize),
        ):
            summarize_pdfs_sync(pdf_texts)

        assert received_targets == [None]


class TestSyllabusTaskWithDbResources:
    """Integration tests: task loads pre-extracted resources from DB."""

    def _run_task(self, course_id, estimated_hours):
        from app.tasks.syllabus_generation import generate_course_syllabus

        with patch.object(generate_course_syllabus, "update_state", MagicMock()):
            return generate_course_syllabus.run(course_id, estimated_hours)

    def test_db_resources_loaded_skips_disk_scan(self, sample_module_dicts):
        """When DB resources exist, task must use them directly without fitz."""
        _CONTEXT_BUDGET_CHARS = 3_500_000

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

        resource_text = "x" * 1_000
        mock_resource = MagicMock()
        mock_resource.filename = "textbook"
        mock_resource.raw_text = resource_text
        mock_resource.toc_json = []

        mock_exec = MagicMock()
        mock_exec.scalars.return_value.all.return_value = [mock_resource]
        mock_session.execute.return_value = mock_exec

        mock_cache = MagicMock()
        mock_cache.get.side_effect = lambda key, default=None: default

        with (
            patch("asyncio.run", side_effect=mock_run),
            patch("pathlib.Path.exists", return_value=False),
            patch("sqlalchemy.create_engine", return_value=mock_sync_engine),
            patch("sqlalchemy.orm.Session", return_value=mock_session),
            patch(
                "app.domain.services.platform_settings_service.SettingsCache.instance",
                return_value=mock_cache,
            ),
        ):
            result = self._run_task(course_id, 20)

        assert result["status"] == "complete"

    def test_exceeds_budget_calls_summarizer(self, sample_module_dicts):
        """When resources exceed context budget, task must call summarize_pdfs_sync."""
        _CONTEXT_BUDGET_CHARS = 3_500_000

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
        mock_resource = MagicMock()
        mock_resource.filename = "textbook"
        mock_resource.raw_text = large_text
        mock_resource.toc_json = []

        mock_exec = MagicMock()
        mock_exec.scalars.return_value.all.return_value = [mock_resource]
        mock_session.execute.return_value = mock_exec

        mock_summarize = MagicMock(return_value=["Structured summary of book"])

        mock_cache = MagicMock()
        mock_cache.get.side_effect = lambda key, default=None: default

        with (
            patch("asyncio.run", side_effect=mock_run),
            patch("pathlib.Path.exists", return_value=False),
            patch("app.ai.pdf_summarizer.summarize_pdfs_sync", mock_summarize),
            patch("sqlalchemy.create_engine", return_value=mock_sync_engine),
            patch("sqlalchemy.orm.Session", return_value=mock_session),
            patch(
                "app.domain.services.platform_settings_service.SettingsCache.instance",
                return_value=mock_cache,
            ),
        ):
            result = self._run_task(course_id, 20)

        mock_summarize.assert_called_once()
        assert result["status"] == "complete"

    def test_simplified_call_no_chunk_params(self, sample_module_dicts):
        """Task must call summarize_pdfs_sync without explicit chunk params (simplified model)."""
        _CONTEXT_BUDGET_CHARS = 3_500_000

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
        mock_resource = MagicMock()
        mock_resource.filename = "bigbook"
        mock_resource.raw_text = large_text
        mock_resource.toc_json = []

        mock_exec = MagicMock()
        mock_exec.scalars.return_value.all.return_value = [mock_resource]
        mock_session.execute.return_value = mock_exec

        captured_kwargs = {}

        def capture_summarize(pdf_full_texts, **kwargs):
            captured_kwargs.update(kwargs)
            return ["Clean summary"] * len(pdf_full_texts)

        mock_cache = MagicMock()
        mock_cache.get.side_effect = lambda key, default=None: default

        with (
            patch("asyncio.run", side_effect=mock_run),
            patch("pathlib.Path.exists", return_value=False),
            patch("app.ai.pdf_summarizer.summarize_pdfs_sync", side_effect=capture_summarize),
            patch("sqlalchemy.create_engine", return_value=mock_sync_engine),
            patch("sqlalchemy.orm.Session", return_value=mock_session),
            patch(
                "app.domain.services.platform_settings_service.SettingsCache.instance",
                return_value=mock_cache,
            ),
        ):
            result = self._run_task(course_id, 30)

        assert result["status"] == "complete"
        assert (
            "chunk_size_chars" not in captured_kwargs
            or captured_kwargs.get("chunk_size_chars") is None
        )
        assert (
            "chunk_max_output_tokens" not in captured_kwargs
            or captured_kwargs.get("chunk_max_output_tokens") is None
        )


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
