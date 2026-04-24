"""Unit tests for the ``backfill_image_translations`` Celery task (issue #1820).

The task's real work lives in ``_run_backfill_with_factory``. We exercise
that directly with an injected session factory and a mocked translator so
the tests stay fast and have no DB dependency.
"""

from __future__ import annotations

import uuid
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


class _FakeSessionFactory:
    """Callable returning an async-context manager that yields a fake session."""

    def __init__(self, session: _FakeSession):
        self._session = session

    def __call__(self):
        session = self._session

        class _Ctx:
            async def __aenter__(self):
                return session

            async def __aexit__(self, exc_type, exc, tb):
                return False

        return _Ctx()


def _translation(fr: str = "fr", en: str = "en") -> FigureTranslation:
    return FigureTranslation(
        caption_fr=f"caption_{fr}",
        caption_en=f"caption_{en}",
        alt_text_fr=f"alt_{fr}",
        alt_text_en=f"alt_{en}",
    )


class TestRunBackfillWithFactory:
    async def test_dry_run_counts_without_calling_translator(self):
        rows = [_make_row(), _make_row()]
        session = _FakeSession(rows)
        task = MagicMock()
        with patch.object(
            image_translation,
            "translate_figure_caption",
            new=AsyncMock(return_value=_translation()),
        ) as mock_tx:
            result = await image_translation._run_backfill_with_factory(
                task=task,
                rag_collection_id=None,
                limit=None,
                dry_run=True,
                session_factory=_FakeSessionFactory(session),
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
        with patch.object(
            image_translation,
            "translate_figure_caption",
            new=AsyncMock(return_value=_translation()),
        ) as mock_tx:
            result = await image_translation._run_backfill_with_factory(
                task=task,
                rag_collection_id=None,
                limit=None,
                dry_run=False,
                session_factory=_FakeSessionFactory(session),
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
        # With parallel execution, side_effect list order is non-deterministic.
        # Mark one row as "should fail" and have the mock side_effect branch
        # on the input caption — that keeps the assertion order-independent.
        rows = [
            _make_row(caption="ok-1"),
            _make_row(caption="FAIL"),
            _make_row(caption="ok-2"),
        ]
        session = _FakeSession(rows)
        task = MagicMock()

        async def _side_effect(*, caption, **_):
            if caption == "FAIL":
                raise ValueError("transient")
            return _translation()

        mock_tx = AsyncMock(side_effect=_side_effect)
        with patch.object(image_translation, "translate_figure_caption", new=mock_tx):
            result = await image_translation._run_backfill_with_factory(
                task=task,
                rag_collection_id=None,
                limit=None,
                dry_run=False,
                session_factory=_FakeSessionFactory(session),
            )
        assert result == {
            "status": "complete",
            "eligible": 3,
            "translated": 2,
            "failed": 1,
        }
        # The FAIL row never gets caption_fr assigned; the other two do.
        fail_row = next(r for r in rows if r.caption == "FAIL")
        ok_rows = [r for r in rows if r.caption != "FAIL"]
        assert fail_row.caption_fr is None
        for row in ok_rows:
            assert row.caption_fr == "caption_fr"

    async def test_empty_eligible_set_returns_noop(self):
        session = _FakeSession([])
        task = MagicMock()
        with patch.object(
            image_translation,
            "translate_figure_caption",
            new=AsyncMock(return_value=_translation()),
        ) as mock_tx:
            result = await image_translation._run_backfill_with_factory(
                task=task,
                rag_collection_id=None,
                limit=None,
                dry_run=False,
                session_factory=_FakeSessionFactory(session),
            )
        assert result["status"] == "noop"
        assert result["eligible"] == 0
        mock_tx.assert_not_awaited()
