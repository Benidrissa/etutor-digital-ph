"""Unit tests for the ``backfill_figure_kinds`` Celery task (issue #1844).

Exercises ``_run_kind_backfill_with_factory`` directly with an injected
session factory, a mocked classifier, and a mocked httpx client so the
test has no DB, no MinIO, and no network dependency.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from app.ai.translation.figure_classifier import FigureClassification
from app.tasks import image_translation


def _make_row(
    figure_kind: str | None = None,
    storage_url: str | None = "https://minio/default.webp",
    rag_collection_id: str | None = "course-1",
) -> MagicMock:
    row = MagicMock()
    row.id = uuid.uuid4()
    row.figure_kind = figure_kind
    row.storage_url = storage_url
    row.rag_collection_id = rag_collection_id
    row.figure_number = "1.1"
    return row


class _FakeSession:
    def __init__(self, rows):
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


def _patch_httpx(response_bytes: bytes = b"fake-webp-bytes"):
    """Patch httpx.AsyncClient used by _run_kind_backfill_with_factory."""
    upstream = MagicMock()
    upstream.content = response_bytes
    upstream.raise_for_status = MagicMock()

    http_client = MagicMock()
    http_client.get = AsyncMock(return_value=upstream)

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=http_client)
    ctx.__aexit__ = AsyncMock(return_value=False)

    return patch.object(
        image_translation.httpx,
        "AsyncClient",
        return_value=ctx,
    ), http_client


class TestRunKindBackfillWithFactory:
    async def test_dry_run_counts_without_calling_classifier(self):
        rows = [_make_row(), _make_row()]
        session = _FakeSession(rows)
        task = MagicMock()
        httpx_patch, _ = _patch_httpx()
        classifier = AsyncMock(return_value=FigureClassification(kind="chart"))

        with (
            httpx_patch,
            patch.object(image_translation, "classify_figure", new=classifier),
        ):
            result = await image_translation._run_kind_backfill_with_factory(
                task=task,
                rag_collection_id=None,
                limit=None,
                dry_run=True,
                session_factory=_FakeSessionFactory(session),
            )

        assert result == {
            "status": "dry_run",
            "eligible": 2,
            "classified": 0,
            "failed": 0,
        }
        classifier.assert_not_awaited()
        assert session.commits == 0

    async def test_classifies_all_eligible_rows(self):
        rows = [_make_row(), _make_row(), _make_row()]
        session = _FakeSession(rows)
        task = MagicMock()
        httpx_patch, _ = _patch_httpx()
        classifier = AsyncMock(return_value=FigureClassification(kind="clean_flowchart"))

        with (
            httpx_patch,
            patch.object(image_translation, "classify_figure", new=classifier),
        ):
            result = await image_translation._run_kind_backfill_with_factory(
                task=task,
                rag_collection_id=None,
                limit=None,
                dry_run=False,
                session_factory=_FakeSessionFactory(session),
            )

        assert result["status"] == "complete"
        assert result["classified"] == 3
        assert result["failed"] == 0
        for row in rows:
            assert row.figure_kind == "clean_flowchart"
        assert classifier.await_count == 3
        assert session.commits >= 1

    async def test_classifier_failure_does_not_abort_batch(self):
        rows = [_make_row(), _make_row(), _make_row()]
        session = _FakeSession(rows)
        task = MagicMock()
        httpx_patch, _ = _patch_httpx()
        classifier = AsyncMock(
            side_effect=[
                FigureClassification(kind="chart"),
                ValueError("vision timeout"),
                FigureClassification(kind="photo"),
            ]
        )

        with (
            httpx_patch,
            patch.object(image_translation, "classify_figure", new=classifier),
        ):
            result = await image_translation._run_kind_backfill_with_factory(
                task=task,
                rag_collection_id=None,
                limit=None,
                dry_run=False,
                session_factory=_FakeSessionFactory(session),
            )

        assert result["classified"] == 2
        assert result["failed"] == 1
        assert rows[0].figure_kind == "chart"
        assert rows[1].figure_kind is None
        assert rows[2].figure_kind == "photo"

    async def test_httpx_failure_does_not_abort_batch(self):
        rows = [_make_row(), _make_row()]
        session = _FakeSession(rows)
        task = MagicMock()

        upstream_ok = MagicMock()
        upstream_ok.content = b"ok"
        upstream_ok.raise_for_status = MagicMock()
        http_client = MagicMock()
        http_client.get = AsyncMock(side_effect=[Exception("network"), upstream_ok])
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=http_client)
        ctx.__aexit__ = AsyncMock(return_value=False)

        classifier = AsyncMock(return_value=FigureClassification(kind="photo"))

        with (
            patch.object(image_translation.httpx, "AsyncClient", return_value=ctx),
            patch.object(image_translation, "classify_figure", new=classifier),
        ):
            result = await image_translation._run_kind_backfill_with_factory(
                task=task,
                rag_collection_id=None,
                limit=None,
                dry_run=False,
                session_factory=_FakeSessionFactory(session),
            )

        assert result["classified"] == 1
        assert result["failed"] == 1
        assert rows[0].figure_kind is None
        assert rows[1].figure_kind == "photo"
        classifier.assert_awaited_once()

    async def test_empty_eligible_set_returns_noop(self):
        session = _FakeSession([])
        task = MagicMock()
        httpx_patch, _ = _patch_httpx()
        classifier = AsyncMock(return_value=FigureClassification(kind="chart"))

        with (
            httpx_patch,
            patch.object(image_translation, "classify_figure", new=classifier),
        ):
            result = await image_translation._run_kind_backfill_with_factory(
                task=task,
                rag_collection_id=None,
                limit=None,
                dry_run=False,
                session_factory=_FakeSessionFactory(session),
            )

        assert result["status"] == "noop"
        assert result["eligible"] == 0
        classifier.assert_not_awaited()
