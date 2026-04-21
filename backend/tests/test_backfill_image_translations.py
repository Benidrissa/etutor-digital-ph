"""Unit tests for the ``backfill_image_translations`` Celery task (issue #1820).

The task's logic lives in ``_run_backfill``. We exercise it directly with a
mocked session factory and a mocked translator so the test stays fast and
has no DB dependency.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from app.ai.translation.figure_translator import FigureTranslation
from app.tasks import image_translation


def _make_row(
    caption: str | None = "A figure",
    caption_fr: str | None = None,
    caption_en: str | None = None,
    alt_text_fr: str | None = None,
    alt_text_en: str | None = None,
    rag_collection_id: str | None = "course-1",
    image_type: str = "diagram",
    figure_number: str | None = "1.1",
) -> MagicMock:
    row = MagicMock()
    row.id = uuid.uuid4()
    row.caption = caption
    row.caption_fr = caption_fr
    row.caption_en = caption_en
    row.alt_text_fr = alt_text_fr
    row.alt_text_en = alt_text_en
    row.rag_collection_id = rag_collection_id
    row.image_type = image_type
    row.figure_number = figure_number
    return row


class _FakeSession:
    """Minimal async-session double that returns pre-set rows from ``execute``."""

    def __init__(self, rows: list[MagicMock]):
        self._rows = rows
        self.added: list[MagicMock] = []
        self.commits = 0

    async def execute(self, stmt):
        result = MagicMock()
        scalars = MagicMock()
        scalars.all = MagicMock(return_value=list(self._rows))
        result.scalars = MagicMock(return_value=scalars)
        return result

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits += 1


def _patch_session_factory(session: _FakeSession):
    @asynccontextmanager
    async def _factory():
        yield session

    return patch.object(image_translation, "async_session_factory", _factory)


def _translation(fr: str = "fr", en: str = "en") -> FigureTranslation:
    return FigureTranslation(
        caption_fr=f"caption_{fr}",
        caption_en=f"caption_{en}",
        alt_text_fr=f"alt_{fr}",
        alt_text_en=f"alt_{en}",
    )


class TestRunBackfill:
    async def test_dry_run_counts_without_calling_translator(self):
        rows = [_make_row(), _make_row()]
        session = _FakeSession(rows)
        task = MagicMock()
        with (
            _patch_session_factory(session),
            patch.object(
                image_translation,
                "translate_figure_caption",
                new=AsyncMock(return_value=_translation()),
            ) as mock_tx,
        ):
            result = await image_translation._run_backfill(
                task=task, rag_collection_id=None, limit=None, dry_run=True
            )
        assert result == {
            "status": "dry_run",
            "eligible": 2,
            "translated": 0,
            "failed": 0,
        }
        mock_tx.assert_not_awaited()
        assert session.commits == 0

    async def test_translates_all_eligible_rows_and_writes_all_four_fields(self):
        rows = [_make_row(), _make_row()]
        session = _FakeSession(rows)
        task = MagicMock()
        with (
            _patch_session_factory(session),
            patch.object(
                image_translation,
                "translate_figure_caption",
                new=AsyncMock(return_value=_translation()),
            ) as mock_tx,
        ):
            result = await image_translation._run_backfill(
                task=task, rag_collection_id=None, limit=None, dry_run=False
            )
        assert result["status"] == "complete"
        assert result["eligible"] == 2
        assert result["translated"] == 2
        assert result["failed"] == 0
        assert mock_tx.await_count == 2
        for row in rows:
            assert row.caption_fr == "caption_fr"
            assert row.caption_en == "caption_en"
            assert row.alt_text_fr == "alt_fr"
            assert row.alt_text_en == "alt_en"
        assert session.commits >= 1

    async def test_translator_failure_does_not_abort_batch(self):
        rows = [_make_row(), _make_row(), _make_row()]
        session = _FakeSession(rows)
        task = MagicMock()

        side_effects = [
            _translation(),
            ValueError("transient"),
            _translation(),
        ]
        mock_tx = AsyncMock(side_effect=side_effects)

        with (
            _patch_session_factory(session),
            patch.object(image_translation, "translate_figure_caption", new=mock_tx),
        ):
            result = await image_translation._run_backfill(
                task=task, rag_collection_id=None, limit=None, dry_run=False
            )
        assert result == {
            "status": "complete",
            "eligible": 3,
            "translated": 2,
            "failed": 1,
        }
        assert rows[1].caption_fr is None
        assert rows[0].caption_fr == "caption_fr"
        assert rows[2].caption_fr == "caption_fr"

    async def test_empty_eligible_set_returns_noop(self):
        session = _FakeSession([])
        task = MagicMock()
        with (
            _patch_session_factory(session),
            patch.object(
                image_translation,
                "translate_figure_caption",
                new=AsyncMock(return_value=_translation()),
            ) as mock_tx,
        ):
            result = await image_translation._run_backfill(
                task=task, rag_collection_id=None, limit=None, dry_run=False
            )
        assert result["status"] == "noop"
        assert result["eligible"] == 0
        mock_tx.assert_not_awaited()
