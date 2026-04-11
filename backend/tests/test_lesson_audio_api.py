"""Unit tests for lesson audio API endpoints (no-DB smoke tests)."""

import uuid

from httpx import AsyncClient


class TestGetLessonAudio:
    async def test_returns_404_for_unknown_lesson(self, client: AsyncClient):
        resp = await client.get(f"/api/v1/audio/lesson/{uuid.uuid4()}")
        assert resp.status_code == 404


class TestGetAudioStatus:
    async def test_returns_404_for_unknown_audio(self, client: AsyncClient):
        resp = await client.get(f"/api/v1/audio/{uuid.uuid4()}/status")
        assert resp.status_code == 404


class TestGetAudioData:
    async def test_returns_404_for_unknown_audio(self, client: AsyncClient):
        resp = await client.get(
            f"/api/v1/audio/{uuid.uuid4()}/data",
            follow_redirects=False,
        )
        assert resp.status_code == 404
