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
        # Parallel execution order is non-deterministic; drive the mock by
        # the per-row storage_url so assertions don't depend on scheduling.
        rows = [
            _make_row(storage_url="https://minio/ok-1.webp"),
            _make_row(storage_url="https://minio/FAIL.webp"),
            _make_row(storage_url="https://minio/ok-2.webp"),
        ]
        session = _FakeSession(rows)
        task = MagicMock()

        upstream = MagicMock()
        upstream.content = b"bytes"
        upstream.raise_for_status = MagicMock()
        http_client = MagicMock()
        http_client.get = AsyncMock(return_value=upstream)
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=http_client)
        ctx.__aexit__ = AsyncMock(return_value=False)

        call_seq: list[bytes] = []

        async def _classifier(*, image_bytes):
            # All three rows pass the same bytes (mock returns the same body)
            # so we distinguish by call ordinal. Parallel safe because we
            # treat the 2nd scheduled call as the failure — and we assert by
            # result count, not by specific row.
            call_seq.append(image_bytes)
            if len(call_seq) == 2:
                raise ValueError("vision timeout")
            return FigureClassification(kind="photo")

        with (
            patch.object(image_translation.httpx, "AsyncClient", return_value=ctx),
            patch.object(
                image_translation, "classify_figure", new=AsyncMock(side_effect=_classifier)
            ),
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
        # Exactly one row stays NULL, exactly two rows get classified.
        assert sum(1 for r in rows if r.figure_kind is None) == 1
        assert sum(1 for r in rows if r.figure_kind == "photo") == 2

    async def test_httpx_failure_does_not_abort_batch(self):
        # Drive fetch failure by URL so the assertion is order-independent.
        rows = [
            _make_row(storage_url="https://minio/network-FAIL.webp"),
            _make_row(storage_url="https://minio/ok.webp"),
        ]
        session = _FakeSession(rows)
        task = MagicMock()

        upstream_ok = MagicMock()
        upstream_ok.content = b"ok"
        upstream_ok.raise_for_status = MagicMock()

        async def _get(url):
            if "FAIL" in url:
                raise Exception("network")
            return upstream_ok

        http_client = MagicMock()
        http_client.get = AsyncMock(side_effect=_get)
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
        fail_row = next(r for r in rows if "FAIL" in r.storage_url)
        ok_row = next(r for r in rows if "FAIL" not in r.storage_url)
        assert fail_row.figure_kind is None
        assert ok_row.figure_kind == "photo"
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

    async def test_short_circuits_when_vision_disabled(self):
        # Cost kill-switch (#1928) — flag=False should return immediately,
        # skipping any DB query and any Claude call.
        rows = [_make_row(), _make_row()]
        session = _FakeSession(rows)
        task = MagicMock()
        classifier = AsyncMock(return_value=FigureClassification(kind="photo"))

        with (
            patch.object(image_translation.settings, "enable_figure_vision", False),
            patch.object(image_translation, "classify_figure", new=classifier),
        ):
            result = await image_translation._run_kind_backfill_with_factory(
                task=task,
                rag_collection_id=None,
                limit=None,
                dry_run=False,
                session_factory=_FakeSessionFactory(session),
            )

        assert result["status"] == "disabled"
        assert result["classified"] == 0
        classifier.assert_not_awaited()
        assert session.commits == 0
