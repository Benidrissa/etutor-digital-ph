"""Unit tests for lesson audio API endpoints."""

import uuid

import pytest
from httpx import AsyncClient

from app.domain.models.generated_audio import GeneratedAudio


@pytest.fixture
def sample_audio_ready(db_session):
    """Create a ready GeneratedAudio record."""
    audio = GeneratedAudio(
        id=uuid.uuid4(),
        lesson_id=uuid.uuid4(),
        module_id=uuid.uuid4(),
        unit_id="M01-U01",
        language="en",
        status="ready",
        storage_key="audio/lessons/test/en/summary.mp3",
        storage_url="https://minio.example.com/audio/test.mp3",
        duration_seconds=180,
        file_size_bytes=2880000,
    )
    db_session.add(audio)
    return audio


@pytest.fixture
def sample_audio_pending(db_session):
    """Create a pending GeneratedAudio record."""
    audio = GeneratedAudio(
        id=uuid.uuid4(),
        lesson_id=uuid.uuid4(),
        module_id=uuid.uuid4(),
        unit_id="M01-U02",
        language="fr",
        status="pending",
    )
    db_session.add(audio)
    return audio


class TestGetLessonAudio:
    async def test_returns_audio_for_lesson(
        self, client: AsyncClient, sample_audio_ready, db_session
    ):
        await db_session.commit()
        resp = await client.get(
            f"/api/v1/audio/lesson/{sample_audio_ready.lesson_id}"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["audio"][0]["status"] == "ready"
        assert data["audio"][0]["audio_url"] is not None

    async def test_returns_404_for_unknown_lesson(self, client: AsyncClient):
        resp = await client.get(f"/api/v1/audio/lesson/{uuid.uuid4()}")
        assert resp.status_code == 404

    async def test_pending_audio_has_no_url(
        self, client: AsyncClient, sample_audio_pending, db_session
    ):
        await db_session.commit()
        resp = await client.get(
            f"/api/v1/audio/lesson/{sample_audio_pending.lesson_id}"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["audio"][0]["status"] == "pending"
        assert data["audio"][0]["audio_url"] is None


class TestGetAudioStatus:
    async def test_returns_status_for_audio(
        self, client: AsyncClient, sample_audio_ready, db_session
    ):
        await db_session.commit()
        resp = await client.get(
            f"/api/v1/audio/{sample_audio_ready.id}/status"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ready"
        assert data["audio_url"] is not None

    async def test_returns_404_for_unknown_audio(self, client: AsyncClient):
        resp = await client.get(f"/api/v1/audio/{uuid.uuid4()}/status")
        assert resp.status_code == 404


class TestGetAudioData:
    async def test_returns_404_when_not_ready(
        self, client: AsyncClient, sample_audio_pending, db_session
    ):
        await db_session.commit()
        resp = await client.get(
            f"/api/v1/audio/{sample_audio_pending.id}/data",
            follow_redirects=False,
        )
        assert resp.status_code == 404

    async def test_returns_404_for_unknown_audio(self, client: AsyncClient):
        resp = await client.get(
            f"/api/v1/audio/{uuid.uuid4()}/data",
            follow_redirects=False,
        )
        assert resp.status_code == 404
