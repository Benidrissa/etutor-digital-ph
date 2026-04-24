"""Unit tests for ``backfill_complex_diagram_overlays`` (issue #1883).

Exercises ``_run_overlay_backfill_with_factory`` directly with a mocked
session, httpx, Claude calls, and storage so the tests have no DB/MinIO/
network dependency.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from app.ai.translation.complex_overlay import DiagramLabel, DiagramLabels
from app.tasks import image_translation


def _make_row(
    storage_key_fr: str | None = None,
    figure_kind: str = "complex_diagram",
    storage_url: str | None = "https://minio/default.webp",
    width: int | None = 800,
    height: int | None = 600,
) -> MagicMock:
    row = MagicMock()
    row.id = uuid.uuid4()
    row.source = "biology"
    row.rag_collection_id = "course-1"
    row.figure_kind = figure_kind
    row.storage_url = storage_url
    row.storage_key_fr = storage_key_fr
    row.storage_url_fr = None
    row.figure_number = "1.1"
    row.page_number = 1
    row.width = width
    row.height = height
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


class _FakeStorage:
    def __init__(self):
        self.uploads: list[tuple[str, bytes, str]] = []

    async def upload_bytes(self, key: str, data: bytes, content_type: str) -> str:
        self.uploads.append((key, data, content_type))
        return f"https://minio/{key}"


def _patch_httpx(body: bytes = b"fake-webp"):
    upstream = MagicMock()
    upstream.content = body
    upstream.raise_for_status = MagicMock()
    http_client = MagicMock()
    http_client.get = AsyncMock(return_value=upstream)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=http_client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return patch.object(image_translation.httpx, "AsyncClient", return_value=ctx)


def _sample_labels() -> DiagramLabels:
    return DiagramLabels(
        labels=[
            DiagramLabel(id="n1", text="Noyau", x_pct=30.0, y_pct=40.0),
            DiagramLabel(id="n2", text="Membrane", x_pct=60.0, y_pct=50.0),
        ]
    )


class TestRunOverlayBackfillWithFactory:
    async def test_dry_run_counts_without_calling_claude(self):
        rows = [_make_row(), _make_row()]
        session = _FakeSession(rows)
        task = MagicMock()
        storage = _FakeStorage()

        extract = AsyncMock(return_value=_sample_labels())
        translate = AsyncMock(return_value=_sample_labels())

        with (
            _patch_httpx(),
            patch.object(image_translation, "extract_label_positions", new=extract),
            patch.object(image_translation, "translate_labels", new=translate),
        ):
            result = await image_translation._run_overlay_backfill_with_factory(
                task=task,
                rag_collection_id=None,
                limit=None,
                dry_run=True,
                session_factory=_FakeSessionFactory(session),
                storage=storage,
            )

        assert result == {
            "status": "dry_run",
            "eligible": 2,
            "rendered": 0,
            "failed": 0,
        }
        extract.assert_not_awaited()
        translate.assert_not_awaited()
        assert storage.uploads == []
        assert session.commits == 0

    async def test_renders_and_uploads_all_eligible_rows(self):
        rows = [_make_row(), _make_row()]
        session = _FakeSession(rows)
        task = MagicMock()
        storage = _FakeStorage()

        extract = AsyncMock(return_value=_sample_labels())
        translate = AsyncMock(return_value=_sample_labels())

        with (
            _patch_httpx(),
            patch.object(image_translation, "extract_label_positions", new=extract),
            patch.object(image_translation, "translate_labels", new=translate),
        ):
            result = await image_translation._run_overlay_backfill_with_factory(
                task=task,
                rag_collection_id=None,
                limit=None,
                dry_run=False,
                session_factory=_FakeSessionFactory(session),
                storage=storage,
            )

        assert result["status"] == "complete"
        assert result["rendered"] == 2
        assert result["failed"] == 0
        assert len(storage.uploads) == 2
        for key, data, content_type in storage.uploads:
            assert key.endswith(".fr.svg")
            assert content_type == "image/svg+xml"
            assert data.startswith(b"<svg")
        for row in rows:
            assert row.storage_key_fr.endswith(".fr.svg")
            assert row.storage_url_fr.startswith("https://minio/")

    async def test_extract_failure_does_not_abort_batch(self):
        # Parallel execution: drive the extract mock by call ordinal so the
        # assertion only checks counts, not per-row identity.
        rows = [_make_row(), _make_row(), _make_row()]
        session = _FakeSession(rows)
        task = MagicMock()
        storage = _FakeStorage()

        call_count = {"n": 0}

        async def _extract(*, image_bytes):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise ValueError("vision timed out")
            return _sample_labels()

        extract = AsyncMock(side_effect=_extract)
        translate = AsyncMock(return_value=_sample_labels())

        with (
            _patch_httpx(),
            patch.object(image_translation, "extract_label_positions", new=extract),
            patch.object(image_translation, "translate_labels", new=translate),
        ):
            result = await image_translation._run_overlay_backfill_with_factory(
                task=task,
                rag_collection_id=None,
                limit=None,
                dry_run=False,
                session_factory=_FakeSessionFactory(session),
                storage=storage,
            )

        assert result["rendered"] == 2
        assert result["failed"] == 1
        assert sum(1 for r in rows if r.storage_key_fr is None) == 1
        assert sum(1 for r in rows if r.storage_key_fr is not None) == 2

    async def test_empty_eligible_set_returns_noop(self):
        session = _FakeSession([])
        task = MagicMock()
        storage = _FakeStorage()

        extract = AsyncMock(return_value=_sample_labels())
        translate = AsyncMock(return_value=_sample_labels())

        with (
            _patch_httpx(),
            patch.object(image_translation, "extract_label_positions", new=extract),
            patch.object(image_translation, "translate_labels", new=translate),
        ):
            result = await image_translation._run_overlay_backfill_with_factory(
                task=task,
                rag_collection_id=None,
                limit=None,
                dry_run=False,
                session_factory=_FakeSessionFactory(session),
                storage=storage,
            )

        assert result["status"] == "noop"
        assert result["eligible"] == 0
        extract.assert_not_awaited()
