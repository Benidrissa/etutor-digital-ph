"""Unit tests for the syllabus generation Celery task (issue #876 fix).

Verifies that:
- Phase 3 DB save uses sync SQLAlchemy (no asyncio.run()) to avoid fork-pool deadlock
- Course-not-found returns a failed result dict without raising
- Successful generation returns the expected structure
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest


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


class TestSyllabusGenerationTaskUnit:
    """Unit tests for generate_course_syllabus.

    We call .run() directly (not .apply()) to avoid needing a real Redis backend.
    .run() is the plain Python function; .update_state is patched to a no-op.
    """

    def _run(self, course_id, estimated_hours, **patches):
        """Call the task's underlying .run() with update_state mocked out."""
        from app.tasks.syllabus_generation import generate_course_syllabus

        with patch.object(generate_course_syllabus, "update_state", MagicMock()):
            return generate_course_syllabus.run(course_id, estimated_hours)

    def test_course_not_found_returns_failed_dict(self):
        """When asyncio.run returns None (course not found), task returns failed dict."""
        course_id = str(uuid.uuid4())
        mock_cache = MagicMock()
        mock_cache.get.side_effect = lambda key, default=None: default

        with (
            patch("asyncio.run", return_value=None),
            patch(
                "app.domain.services.platform_settings_service.SettingsCache.instance",
                return_value=mock_cache,
            ),
        ):
            result = self._run(course_id, 20)

        assert result["status"] == "failed"
        assert "not found" in result["error"].lower()
        assert result["modules_count"] == 0
        assert result["modules"] == []

    def test_phase3_uses_sync_db_not_asyncio(self, sample_module_dicts):
        """Phase 3 DB save must use sqlalchemy.create_engine (sync), not asyncio.run.

        asyncio.run() must be called exactly twice:
          1. _fetch_course  — async read course metadata
          2. _call_claude   — async Claude API call
        NOT a third time for the DB write phase.
        """
        course_id = str(uuid.uuid4())
        course_data = {
            "title_fr": "Santé Publique",
            "title_en": "Public Health",
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
        mock_sync_engine.dispose = MagicMock()

        asyncio_run_calls = []

        def track_asyncio_run(coro):
            asyncio_run_calls.append(getattr(coro, "__name__", repr(coro)))
            if len(asyncio_run_calls) == 1:
                return course_data
            return sample_module_dicts

        mock_cache = MagicMock()
        mock_cache.get.side_effect = lambda key, default=None: default

        with (
            patch("asyncio.run", side_effect=track_asyncio_run),
            patch("pathlib.Path.exists", return_value=False),
            patch("sqlalchemy.create_engine", return_value=mock_sync_engine) as mock_ce,
            patch("sqlalchemy.orm.Session", return_value=mock_session),
            patch(
                "app.domain.services.platform_settings_service.SettingsCache.instance",
                return_value=mock_cache,
            ),
        ):
            result = self._run(course_id, 20)

        assert result["status"] == "complete"
        assert result["modules_count"] == 1

        assert mock_ce.call_count >= 1
        for call in mock_ce.call_args_list:
            engine_url_arg = call[0][0]
            assert "postgresql" in engine_url_arg
            assert "asyncpg" not in engine_url_arg, (
                "All create_engine calls must use the sync DB URL — no asyncpg driver"
            )
        assert mock_sync_engine.dispose.call_count >= 1

        assert len(asyncio_run_calls) == 2, (
            "asyncio.run should be called exactly twice (_fetch_course + _call_claude), "
            f"but was called {len(asyncio_run_calls)} time(s): {asyncio_run_calls}"
        )

    def test_saved_modules_match_claude_output(self, sample_module_dicts):
        """Result modules list must mirror Claude's module_dicts output."""
        course_id = str(uuid.uuid4())
        course_data = {
            "title_fr": "Épidémiologie",
            "title_en": "Epidemiology",
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
            return course_data if call_count == 1 else sample_module_dicts

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
            result = self._run(course_id, 30)

        assert result["status"] == "complete"
        assert result["modules_count"] == len(sample_module_dicts)
        assert len(result["modules"]) == len(sample_module_dicts)
        assert result["modules"][0]["title_fr"] == sample_module_dicts[0]["title_fr"]
        assert result["modules"][0]["title_en"] == sample_module_dicts[0]["title_en"]
        assert result["modules"][0]["units_count"] == len(sample_module_dicts[0]["units"])

    def test_small_pdfs_bypass_summarization(self, sample_module_dicts):
        """PDFs under _CONTEXT_BUDGET_CHARS use raw text — summarize_pdfs_sync is NOT called."""
        course_id = str(uuid.uuid4())
        course_data = {
            "title_fr": "Test",
            "title_en": "Test",
            "course_hours": 10,
            "rag_collection_id": None,
            "domain_slugs": [],
            "level_slugs": [],
            "audience_slugs": [],
        }

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.execute.return_value.scalars.return_value.all.return_value = []
        mock_sync_engine = MagicMock()

        small_pdf_text = "x" * 1000
        mock_fitz_doc = MagicMock()
        mock_fitz_doc.get_toc.return_value = []
        mock_fitz_doc.__iter__ = MagicMock(
            return_value=iter([MagicMock(get_text=MagicMock(return_value=small_pdf_text))])
        )
        mock_fitz_doc.close = MagicMock()

        call_count = 0

        def mock_run(coro):
            nonlocal call_count
            call_count += 1
            return course_data if call_count == 1 else sample_module_dicts

        mock_cache = MagicMock()
        mock_cache.get.side_effect = lambda key, default=None: default

        with (
            patch("asyncio.run", side_effect=mock_run),
            patch("pathlib.Path.exists", return_value=True),
            patch(
                "pathlib.Path.glob",
                return_value=[MagicMock(stem="test_pdf", __str__=lambda s: "test.pdf")],
            ),
            patch("fitz.open", return_value=mock_fitz_doc),
            patch("app.ai.pdf_summarizer.summarize_pdfs_sync") as mock_summarize,
            patch("sqlalchemy.create_engine", return_value=mock_sync_engine),
            patch("sqlalchemy.orm.Session", return_value=mock_session),
            patch(
                "app.domain.services.platform_settings_service.SettingsCache.instance",
                return_value=mock_cache,
            ),
        ):
            result = self._run(course_id, 10)

        mock_summarize.assert_not_called()
        assert result["status"] == "complete"

    def test_large_pdfs_use_summarization(self, sample_module_dicts):
        """PDFs over context budget trigger summarize_pdfs_sync."""
        _CONTEXT_BUDGET_CHARS = 400_000

        course_id = str(uuid.uuid4())
        course_data = {
            "title_fr": "Test",
            "title_en": "Test",
            "course_hours": 10,
            "rag_collection_id": None,
            "domain_slugs": [],
            "level_slugs": [],
            "audience_slugs": [],
        }

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        # Return empty list for existing resources AND None for dedup lookup
        mock_session.execute.return_value.scalars.return_value.all.return_value = []
        mock_session.execute.return_value.scalar_one_or_none.return_value = None
        mock_sync_engine = MagicMock()

        large_pdf_text = "x" * (_CONTEXT_BUDGET_CHARS + 1)
        mock_fitz_doc = MagicMock()
        mock_fitz_doc.get_toc.return_value = []
        mock_fitz_doc.__iter__ = MagicMock(
            return_value=iter([MagicMock(get_text=MagicMock(return_value=large_pdf_text))])
        )
        mock_fitz_doc.close = MagicMock()

        call_count = 0

        def mock_run(coro):
            nonlocal call_count
            call_count += 1
            return course_data if call_count == 1 else sample_module_dicts

        mock_cache = MagicMock()
        mock_cache.get.side_effect = lambda key, default=None: (
            _CONTEXT_BUDGET_CHARS if key == "syllabus-context-budget-chars" else default
        )

        with (
            patch("asyncio.run", side_effect=mock_run),
            patch("pathlib.Path.exists", return_value=True),
            patch(
                "pathlib.Path.glob",
                return_value=[MagicMock(stem="large_pdf", __str__=lambda s: "large.pdf")],
            ),
            patch("fitz.open", return_value=mock_fitz_doc),
            patch(
                "app.ai.pdf_summarizer.summarize_pdfs_sync", return_value=["summary text"]
            ) as mock_summarize,
            patch("sqlalchemy.create_engine", return_value=mock_sync_engine),
            patch("sqlalchemy.orm.Session", return_value=mock_session),
            patch(
                "app.domain.services.platform_settings_service.SettingsCache.instance",
                return_value=mock_cache,
            ),
        ):
            result = self._run(course_id, 10)

        mock_summarize.assert_called_once()
        assert result["status"] == "complete"

    def test_sync_engine_disposed_on_db_error(self, sample_module_dicts):
        """sync_engine.dispose() must be called even if session.commit() raises."""
        course_id = str(uuid.uuid4())
        course_data = {
            "title_fr": "Test",
            "title_en": "Test",
            "course_hours": 10,
            "rag_collection_id": None,
            "domain_slugs": [],
            "level_slugs": [],
            "audience_slugs": [],
        }

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.commit.side_effect = RuntimeError("DB commit failed")
        mock_sync_engine = MagicMock()

        call_count = 0

        def mock_run(coro):
            nonlocal call_count
            call_count += 1
            return course_data if call_count == 1 else sample_module_dicts

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
            pytest.raises(RuntimeError, match="DB commit failed"),
        ):
            self._run(course_id, 10)

        assert mock_sync_engine.dispose.call_count >= 1

    def test_summary_reused_from_same_resource(self, sample_module_dicts):
        """If a resource already has summary_text, summarize_pdfs_sync is NOT called."""
        _CONTEXT_BUDGET_CHARS = 100

        course_id = str(uuid.uuid4())
        course_data = {
            "title_fr": "Test",
            "title_en": "Test",
            "course_hours": 10,
            "rag_collection_id": None,
            "domain_slugs": [],
            "level_slugs": [],
            "audience_slugs": [],
        }

        mock_resource = MagicMock()
        mock_resource.raw_text = "x" * (_CONTEXT_BUDGET_CHARS + 1)
        mock_resource.toc_json = []
        mock_resource.filename = "existing_pdf"
        mock_resource.summary_text = "cached summary"
        mock_resource.summary_model = "claude-sonnet-4-6"
        mock_resource.content_hash = "abc123"
        mock_resource.id = uuid.uuid4()

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.execute.return_value.scalars.return_value.all.return_value = [mock_resource]
        mock_session.execute.return_value.scalar_one_or_none.return_value = None
        mock_sync_engine = MagicMock()

        call_count = 0

        def mock_run(coro):
            nonlocal call_count
            call_count += 1
            return course_data if call_count == 1 else sample_module_dicts

        mock_cache = MagicMock()
        mock_cache.get.side_effect = lambda key, default=None: (
            _CONTEXT_BUDGET_CHARS if key == "syllabus-context-budget-chars" else default
        )

        with (
            patch("asyncio.run", side_effect=mock_run),
            patch("pathlib.Path.exists", return_value=False),
            patch("app.ai.pdf_summarizer.summarize_pdfs_sync") as mock_summarize,
            patch("sqlalchemy.create_engine", return_value=mock_sync_engine),
            patch("sqlalchemy.orm.Session", return_value=mock_session),
            patch(
                "app.domain.services.platform_settings_service.SettingsCache.instance",
                return_value=mock_cache,
            ),
        ):
            result = self._run(course_id, 10)

        mock_summarize.assert_not_called()
        assert result["status"] == "complete"

    def test_summary_reused_from_other_course_by_hash(self, sample_module_dicts):
        """If another CourseResource with same hash has a summary, it is reused — zero API call."""
        _CONTEXT_BUDGET_CHARS = 100

        course_id = str(uuid.uuid4())
        other_course_id = uuid.uuid4()
        course_data = {
            "title_fr": "Test",
            "title_en": "Test",
            "course_hours": 10,
            "rag_collection_id": None,
            "domain_slugs": [],
            "level_slugs": [],
            "audience_slugs": [],
        }

        mock_resource = MagicMock()
        mock_resource.raw_text = "x" * (_CONTEXT_BUDGET_CHARS + 1)
        mock_resource.toc_json = []
        mock_resource.filename = "some_pdf"
        mock_resource.summary_text = None
        mock_resource.summary_model = None
        mock_resource.content_hash = "deabc123"
        mock_resource.id = uuid.uuid4()

        existing_with_summary = MagicMock()
        existing_with_summary.summary_text = "reused summary from other course"
        existing_with_summary.summary_model = "claude-sonnet-4-6"
        existing_with_summary.course_id = other_course_id

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.execute.return_value.scalars.return_value.all.return_value = [mock_resource]
        mock_session.execute.return_value.scalar_one_or_none.return_value = existing_with_summary
        mock_sync_engine = MagicMock()

        call_count = 0

        def mock_run(coro):
            nonlocal call_count
            call_count += 1
            return course_data if call_count == 1 else sample_module_dicts

        mock_cache = MagicMock()
        mock_cache.get.side_effect = lambda key, default=None: (
            _CONTEXT_BUDGET_CHARS if key == "syllabus-context-budget-chars" else default
        )

        with (
            patch("asyncio.run", side_effect=mock_run),
            patch("pathlib.Path.exists", return_value=False),
            patch("app.ai.pdf_summarizer.summarize_pdfs_sync") as mock_summarize,
            patch("sqlalchemy.create_engine", return_value=mock_sync_engine),
            patch("sqlalchemy.orm.Session", return_value=mock_session),
            patch(
                "app.domain.services.platform_settings_service.SettingsCache.instance",
                return_value=mock_cache,
            ),
        ):
            result = self._run(course_id, 10)

        mock_summarize.assert_not_called()
        assert result["status"] == "complete"
