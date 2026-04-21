"""Tests for the HeyGen video-summary poller and shared finalizer.

Covers the three terminal outcomes of ``_reconcile_one`` (ready,
failed, timed_out), the "still generating" no-op path, and the
shared ``finalize_video_summary`` helper that the webhook also
delegates to. DB interactions are stubbed with an in-memory session
fake so we don't need a real Postgres.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from app.domain.models.module_media import ModuleMedia
from app.domain.services.media_summary_service import (
    finalize_video_summary,
    is_web_ready_mp4,
)
from app.infrastructure.video import VideoStatus
from app.tasks.heygen_poll import _is_timed_out, _reconcile_one

# ── Fakes ────────────────────────────────────────────────────────────


@dataclass
class _FakeSession:
    """Just enough of AsyncSession to satisfy the code under test."""

    commits: int = field(default=0)

    async def commit(self) -> None:
        self.commits += 1

    async def flush(self) -> None:
        pass


class _FakeStorage:
    def __init__(self) -> None:
        self.uploaded: list[tuple[str, bytes, str]] = []

    async def upload_bytes(self, *, key: str, data: bytes, content_type: str) -> str:
        self.uploaded.append((key, data, content_type))
        return f"https://minio.test/{key}"


class _FakeHttpResponse:
    def __init__(self, content: bytes, status_code: int = 200) -> None:
        self.content = content
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeHttpClient:
    def __init__(self, response: _FakeHttpResponse) -> None:
        self._response = response

    async def get(self, url: str) -> _FakeHttpResponse:
        return self._response


def _make_record(
    *,
    status: str = "generating",
    provider_video_id: str = "vid-abc",
    created_at: datetime | None = None,
) -> ModuleMedia:
    """Build an in-memory ModuleMedia without touching the DB."""
    record = ModuleMedia(
        id=uuid.uuid4(),
        module_id=uuid.uuid4(),
        media_type="video_summary",
        language="en",
        status=status,
    )
    record.provider_video_id = provider_video_id
    record.created_at = created_at or datetime.now(UTC)
    return record


def _mp4_bytes(size: int = 128) -> bytes:
    """Minimal ISO-BMFF MP4 payload that passes ``is_web_ready_mp4``."""
    return b"\x00\x00\x00\x18ftypisom" + b"\x00" * (size - 12)


# ── is_web_ready_mp4 ─────────────────────────────────────────────────


def test_is_web_ready_mp4_accepts_ftyp():
    assert is_web_ready_mp4(_mp4_bytes())


def test_is_web_ready_mp4_rejects_non_mp4():
    assert not is_web_ready_mp4(b"not a video")
    assert not is_web_ready_mp4(b"\x1a\x45\xdf\xa3webm" + b"\x00" * 20)


# ── finalize_video_summary ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_finalize_happy_path_sets_ready():
    record = _make_record()
    session = _FakeSession()
    storage = _FakeStorage()
    http = _FakeHttpClient(_FakeHttpResponse(_mp4_bytes(256)))

    outcome = await finalize_video_summary(
        record,
        video_url="https://heygen.test/vid.mp4",
        session=session,  # type: ignore[arg-type]
        duration_hint=173,
        storage=storage,  # type: ignore[arg-type]
        http_client=http,  # type: ignore[arg-type]
    )

    assert outcome == "ready"
    assert record.status == "ready"
    assert record.file_size_bytes == 256
    assert record.duration_seconds == 173
    assert record.storage_key.startswith("video/")
    assert record.storage_key.endswith("/summary.mp4")
    assert record.storage_url == f"https://minio.test/{record.storage_key}"
    assert record.generated_at is not None
    assert storage.uploaded[0][2] == "video/mp4"


@pytest.mark.asyncio
async def test_finalize_rejects_non_mp4_container():
    record = _make_record()
    session = _FakeSession()
    http = _FakeHttpClient(_FakeHttpResponse(b"not an mp4 file at all"))

    outcome = await finalize_video_summary(
        record,
        video_url="https://heygen.test/vid.mp4",
        session=session,  # type: ignore[arg-type]
        http_client=http,  # type: ignore[arg-type]
    )

    assert outcome == "failed"
    assert record.status == "failed"
    assert "MP4 container" in (record.error_message or "")


@pytest.mark.asyncio
async def test_finalize_surfaces_download_error():
    record = _make_record()
    session = _FakeSession()
    http = _FakeHttpClient(_FakeHttpResponse(b"", status_code=500))

    outcome = await finalize_video_summary(
        record,
        video_url="https://heygen.test/vid.mp4",
        session=session,  # type: ignore[arg-type]
        http_client=http,  # type: ignore[arg-type]
    )

    assert outcome == "failed"
    assert record.status == "failed"
    assert "download failed" in (record.error_message or "")


# ── _reconcile_one ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reconcile_completed_calls_finalize_and_returns_ready(
    monkeypatch,
):
    record = _make_record()
    session = _FakeSession()

    client = AsyncMock()
    client.get_video = AsyncMock(
        return_value=VideoStatus(
            provider_video_id="vid-abc",
            status="completed",
            video_url="https://heygen.test/vid.mp4",
        )
    )

    called: dict[str, object] = {}

    async def _fake_finalize(record, *, video_url, session, duration_hint=None):
        called["video_url"] = video_url
        record.status = "ready"
        return "ready"

    monkeypatch.setattr(
        "app.tasks.heygen_poll.finalize_video_summary",
        _fake_finalize,
    )

    outcome = await _reconcile_one(
        record=record,
        client=client,
        session=session,  # type: ignore[arg-type]
    )
    assert outcome == "ready"
    assert called["video_url"] == "https://heygen.test/vid.mp4"


@pytest.mark.asyncio
async def test_reconcile_completed_without_url_marks_failed():
    record = _make_record()
    session = _FakeSession()

    client = AsyncMock()
    client.get_video = AsyncMock(
        return_value=VideoStatus(
            provider_video_id="vid-abc",
            status="completed",
            video_url=None,
        )
    )

    outcome = await _reconcile_one(
        record=record,
        client=client,
        session=session,  # type: ignore[arg-type]
    )
    assert outcome == "failed"
    assert record.status == "failed"
    assert "without a video_url" in (record.error_message or "")


@pytest.mark.asyncio
async def test_reconcile_failed_propagates_error_message():
    record = _make_record()
    session = _FakeSession()

    client = AsyncMock()
    client.get_video = AsyncMock(
        return_value=VideoStatus(
            provider_video_id="vid-abc",
            status="failed",
            error="avatar not found",
        )
    )

    outcome = await _reconcile_one(
        record=record,
        client=client,
        session=session,  # type: ignore[arg-type]
    )
    assert outcome == "failed"
    assert record.status == "failed"
    assert record.error_message == "avatar not found"


@pytest.mark.asyncio
async def test_reconcile_still_processing_is_noop():
    record = _make_record()
    original_status = record.status
    session = _FakeSession()

    client = AsyncMock()
    client.get_video = AsyncMock(
        return_value=VideoStatus(
            provider_video_id="vid-abc",
            status="processing",
        )
    )

    outcome = await _reconcile_one(
        record=record,
        client=client,
        session=session,  # type: ignore[arg-type]
    )
    assert outcome == "still_pending"
    assert record.status == original_status
    assert session.commits == 0  # nothing to save


@pytest.mark.asyncio
async def test_reconcile_timeout_marks_failed_without_hitting_heygen():
    record = _make_record(created_at=datetime.now(UTC) - timedelta(hours=3))
    session = _FakeSession()

    client = AsyncMock()
    client.get_video = AsyncMock()

    outcome = await _reconcile_one(
        record=record,
        client=client,
        session=session,  # type: ignore[arg-type]
    )
    assert outcome == "timed_out"
    assert record.status == "failed"
    assert "timed out" in (record.error_message or "")
    client.get_video.assert_not_awaited()


# ── _is_timed_out ───────────────────────────────────────────────────


def test_is_timed_out_ignores_fresh_rows():
    assert not _is_timed_out(_make_record())


def test_is_timed_out_flags_rows_older_than_cap():
    stale = _make_record(created_at=datetime.now(UTC) - timedelta(hours=3))
    assert _is_timed_out(stale)


def test_is_timed_out_handles_naive_timestamps():
    # Some rows have a tz-naive created_at depending on how Alembic
    # seeded them; treat naive as UTC rather than crashing.
    naive = _make_record(
        created_at=datetime.utcnow() - timedelta(hours=3),
    )
    naive.created_at = naive.created_at.replace(tzinfo=None)
    assert _is_timed_out(naive)
