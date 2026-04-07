"""Unit tests for the multi-pass PDF summarizer (issue #1039, #1104).

Verifies:
- _split_into_chunks handles small and large texts correctly
- _compute_defaults returns correct values for known models
- _proportional_budgets distributes budget proportionally
- summarize_pdf_for_syllabus falls back gracefully when no API key
- summarize_pdfs_sync returns one summary per input PDF
- Concurrent processing (asyncio.gather) is used for multi-chunk PDFs
- Task integration: PdfSummarizer is called instead of truncation
- Backward compat: old setting keys still read correctly
"""

import asyncio
import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ai.pdf_summarizer import (
    PdfChunkPlan,
    _compute_defaults,
    _proportional_budgets,
    _split_into_chunks,
    compute_chunk_plan,
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

    def test_three_pdfs_5m_chars_each_fits_in_one_chunk(self):
        total = 5_000_000
        pdf_sizes = [2_100_000, 1_800_000, 1_100_000]
        budget = 3_500_000
        for pdf_chars in pdf_sizes:
            plan = compute_chunk_plan(
                pdf_chars=pdf_chars,
                num_pdfs=3,
                total_pdf_chars=total,
                context_budget_chars=budget,
                model="claude-sonnet-4-6",
            )
            assert plan.chunk_count == 1, f"Expected 1 chunk for {pdf_chars} chars, got {plan.chunk_count}"

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

    def test_smaller_model_requires_more_chunks(self):
        pdf_chars = 500_000
        plan_sonnet = compute_chunk_plan(
            pdf_chars=pdf_chars,
            num_pdfs=1,
            total_pdf_chars=pdf_chars,
            context_budget_chars=3_500_000,
            model="claude-sonnet-4-6",
        )
        plan_haiku = compute_chunk_plan(
            pdf_chars=pdf_chars,
            num_pdfs=1,
            total_pdf_chars=pdf_chars,
            context_budget_chars=3_500_000,
            model="claude-haiku-4-5",
        )
        assert plan_haiku.chunk_count >= plan_sonnet.chunk_count

    def test_combine_output_tokens_within_model_max(self):
        plan = compute_chunk_plan(
            pdf_chars=1_000_000,
            num_pdfs=1,
            total_pdf_chars=1_000_000,
            context_budget_chars=3_500_000,
            model="claude-sonnet-4-6",
        )
        assert plan.combine_max_output_tokens <= 64_000

    def test_chunk_output_tokens_within_model_max(self):
        plan = compute_chunk_plan(
            pdf_chars=1_000_000,
            num_pdfs=1,
            total_pdf_chars=1_000_000,
            context_budget_chars=3_500_000,
            model="claude-sonnet-4-6",
        )
        assert plan.chunk_max_output_tokens <= 64_000

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
                summarize_pdf_for_syllabus(
                    "SmallBook", "short text", toc=None, chunk_size_chars=100_000
                )
            )

        assert result == "Summary of single chunk"
        assert mock_client.messages.create.call_count == 1

    def test_multi_chunk_uses_gather(self):
        from app.ai.pdf_summarizer import summarize_pdf_for_syllabus

        gather_calls = []
        original_gather = asyncio.gather

        async def spy_gather(*coros, **kwargs):
            gather_calls.append(len(coros))
            return await original_gather(*coros, **kwargs)

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
            patch("app.ai.pdf_summarizer.asyncio.gather", side_effect=spy_gather),
        ):
            result = asyncio.run(
                summarize_pdf_for_syllabus("LargeBook", text, toc=None, chunk_size_chars=5000)
            )

        assert len(gather_calls) >= 1, "asyncio.gather should be used for concurrent chunks"
        assert "Summary call" in result

    def test_target_chars_injects_word_limit_into_prompt(self):
        from app.ai.pdf_summarizer import summarize_pdf_for_syllabus

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
            asyncio.run(
                summarize_pdf_for_syllabus(
                    "Book", "short text", toc=None, chunk_size_chars=100_000, target_chars=5_000
                )
            )

        assert any("1000" in p for p in captured_prompts), "Word limit should appear in prompt"

    def test_target_chars_caps_max_tokens(self):
        from app.ai.pdf_summarizer import summarize_pdf_for_syllabus

        captured_max_tokens = []

        async def mock_create(**kwargs):
            captured_max_tokens.append(kwargs.get("max_tokens"))
            resp = MagicMock()
            resp.content = [MagicMock(text="ok")]
            return resp

        mock_client = MagicMock()
        mock_client.messages.create = mock_create

        with (
            patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}),
            patch("anthropic.AsyncAnthropic", return_value=mock_client),
        ):
            asyncio.run(
                summarize_pdf_for_syllabus(
                    "Book", "short text", toc=None, chunk_size_chars=100_000, target_chars=5_000
                )
            )

        assert captured_max_tokens[0] < 16_000, "max_tokens should be capped below default"

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
            asyncio.run(
                summarize_pdf_for_syllabus("Book", "content", toc=toc, chunk_size_chars=100_000)
            )

        assert any("Chapter 1" in p for p in captured_prompts)

    def test_none_params_use_computed_defaults(self):
        from app.ai.pdf_summarizer import summarize_pdf_for_syllabus

        captured_max_tokens = []

        async def mock_create(**kwargs):
            captured_max_tokens.append(kwargs.get("max_tokens"))
            resp = MagicMock()
            resp.content = [MagicMock(text="ok")]
            return resp

        mock_client = MagicMock()
        mock_client.messages.create = mock_create

        with (
            patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}),
            patch("anthropic.AsyncAnthropic", return_value=mock_client),
        ):
            asyncio.run(
                summarize_pdf_for_syllabus(
                    "Book",
                    "short text",
                    toc=None,
                    chunk_size_chars=None,
                    chunk_max_output_tokens=None,
                )
            )

        assert captured_max_tokens[0] == 16_000, "Should use computed default of 16K for sonnet-4-6"


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

    def test_budget_even_split_when_same_size(self):
        received_targets = []

        async def fake_summarize(name, text, toc=None, **kwargs):
            received_targets.append(kwargs.get("target_chars"))
            return f"summary:{name}"

        pdf_texts = [
            ("A", "aaa", []),
            ("B", "bbb", []),
            ("C", "ccc", []),
        ]

        with (
            patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}),
            patch("app.ai.pdf_summarizer.summarize_pdf_for_syllabus", side_effect=fake_summarize),
        ):
            result = summarize_pdfs_sync(pdf_texts, total_budget_chars=300_000)

        assert len(result) == 3
        assert all(t == 100_000 for t in received_targets)

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

    def test_new_param_names_forwarded(self):
        received_kwargs = []

        async def fake_summarize(name, text, toc=None, **kwargs):
            received_kwargs.append(kwargs)
            return f"summary:{name}"

        pdf_texts = [("A", "aaa", [])]

        with (
            patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}),
            patch("app.ai.pdf_summarizer.summarize_pdf_for_syllabus", side_effect=fake_summarize),
        ):
            summarize_pdfs_sync(
                pdf_texts,
                chunk_size_chars=200_000,
                chunk_max_output_tokens=8_000,
                combine_max_output_tokens=16_000,
                max_concurrent=3,
            )

        assert received_kwargs[0]["chunk_size_chars"] == 200_000
        assert received_kwargs[0]["chunk_max_output_tokens"] == 8_000
        assert received_kwargs[0]["combine_max_output_tokens"] == 16_000
        assert received_kwargs[0]["max_concurrent"] == 3


class TestSyllabusTaskWithSummarization:
    """Integration tests for the Celery task's PDF summarization path."""

    def _run_task(self, course_id, estimated_hours):
        from app.tasks.syllabus_generation import generate_course_syllabus

        with patch.object(generate_course_syllabus, "update_state", MagicMock()):
            return generate_course_syllabus.run(course_id, estimated_hours)

    def test_pdf_dir_exists_calls_summarizer_not_truncate(self, sample_module_dicts):
        """When PDF directory exists and text exceeds budget, task must call summarize_pdfs_sync."""
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
        mock_page = MagicMock()
        mock_page.get_text.return_value = large_text
        mock_doc = MagicMock()
        mock_doc.get_toc.return_value = []
        mock_doc.__iter__ = MagicMock(return_value=iter([mock_page]))
        mock_doc.close = MagicMock()

        mock_summarize = MagicMock(return_value=["Structured summary of book"])

        mock_cache = MagicMock()
        mock_cache.get.side_effect = lambda key, default=None: default

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
            patch(
                "app.domain.services.platform_settings_service.SettingsCache.instance",
                return_value=mock_cache,
            ),
        ):
            result = self._run_task(course_id, 20)

        mock_summarize.assert_called_once()
        assert result["status"] == "complete"

    def test_new_param_names_passed_to_summarizer(self, sample_module_dicts):
        """Task must pass new parameter names (chunk_size_chars, etc.) to summarize_pdfs_sync."""
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
        mock_page = MagicMock()
        mock_page.get_text.return_value = large_text
        mock_doc = MagicMock()
        mock_doc.get_toc.return_value = []
        mock_doc.__iter__ = MagicMock(return_value=iter([mock_page]))
        mock_doc.close = MagicMock()

        captured_kwargs = {}

        def capture_summarize(pdf_full_texts, **kwargs):
            captured_kwargs.update(kwargs)
            return ["Proper summary without truncation"] * len(pdf_full_texts)

        mock_cache = MagicMock()
        mock_cache.get.side_effect = lambda key, default=None: default

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
            patch(
                "app.domain.services.platform_settings_service.SettingsCache.instance",
                return_value=mock_cache,
            ),
        ):
            result = self._run_task(course_id, 30)

        assert result["status"] == "complete"
        assert "chunk_size_chars" in captured_kwargs
        assert "chunk_max_output_tokens" in captured_kwargs
        assert "combine_max_output_tokens" in captured_kwargs
        assert "max_concurrent" in captured_kwargs

    def test_backward_compat_old_setting_keys(self, sample_module_dicts):
        """Old DB setting keys (syllabus-combine-chunk-size, etc.) must still work."""
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
        mock_page = MagicMock()
        mock_page.get_text.return_value = large_text
        mock_doc = MagicMock()
        mock_doc.get_toc.return_value = []
        mock_doc.__iter__ = MagicMock(return_value=iter([mock_page]))
        mock_doc.close = MagicMock()

        captured_kwargs = {}

        def capture_summarize(pdf_full_texts, **kwargs):
            captured_kwargs.update(kwargs)
            return ["Summary"] * len(pdf_full_texts)

        old_key_values = {
            "syllabus-combine-chunk-size": 75_000,
            "syllabus-chunk-max-tokens": 5_000,
            "syllabus-combine-max-tokens": 10_000,
        }

        def mock_cache_get(key, default=None):
            return old_key_values.get(key, default)

        mock_cache = MagicMock()
        mock_cache.get.side_effect = mock_cache_get

        with (
            patch("asyncio.run", side_effect=mock_run),
            patch("pathlib.Path.exists", return_value=True),
            patch(
                "pathlib.Path.glob",
                return_value=[MagicMock(stem="textbook", __str__=lambda s: "textbook.pdf")],
            ),
            patch("fitz.open", return_value=mock_doc),
            patch("app.ai.pdf_summarizer.summarize_pdfs_sync", side_effect=capture_summarize),
            patch("sqlalchemy.create_engine", return_value=mock_sync_engine),
            patch("sqlalchemy.orm.Session", return_value=mock_session),
            patch(
                "app.domain.services.platform_settings_service.SettingsCache.instance",
                return_value=mock_cache,
            ),
        ):
            result = self._run_task(course_id, 20)

        assert result["status"] == "complete"
        assert captured_kwargs.get("combine_chunk_size_chars") == 75_000
        assert captured_kwargs.get("chunk_max_output_tokens") == 5_000
        assert captured_kwargs.get("combine_max_output_tokens") == 10_000


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
