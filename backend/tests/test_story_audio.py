"""Story read-aloud with OpenAI TTS (#2704): cache key, synthesis, routes.

Sessions, OpenAI and MinIO are mocked (the db_session fixture is blocked on
#554, as in test_tutor_audio_service.py).
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_db_session
from app.api.deps_local_auth import get_current_user
from app.api.v1 import story_audio as api
from app.domain.services import story_audio_service as svc
from app.domain.services.story_audio_service import (
    VOICE_PROFILES,
    StoryAudioError,
    StoryAudioService,
    line_hash,
    normalize_line,
    tts_instructions,
)
from app.main import app

USER_ID = "4f1c9a7e-0000-4000-8000-000000000001"


def _user():
    return SimpleNamespace(id=USER_ID, email="kid@example.org", role="user")


def _session(scalar=None):
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=scalar)
    result.scalar_one = MagicMock(return_value=scalar)
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()
    session.get = AsyncMock()
    return session


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


def _signed_in(session):
    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db_session] = lambda: session


class TestCacheKey:
    def test_whitespace_does_not_change_the_clip(self):
        assert line_hash(" Bonjour,\n  Awa ! ", "fr", "girl", "m") == line_hash(
            "Bonjour, Awa !", "fr", "girl", "m"
        )

    @pytest.mark.parametrize(
        "other",
        [
            ("Bonjour, Awa !", "en", "girl", "m"),
            ("Bonjour, Awa !", "fr", "boy", "m"),
            ("Bonjour, Awa !", "fr", "girl", "m2"),
            ("Bonjour, Moussa !", "fr", "girl", "m"),
        ],
    )
    def test_anything_that_changes_the_sound_changes_the_key(self, other):
        assert line_hash("Bonjour, Awa !", "fr", "girl", "m") != line_hash(*other)

    def test_the_voice_version_is_part_of_the_key(self):
        before = line_hash("Hi", "en", "narrator", "m")
        with patch.object(svc, "VOICE_VERSION", svc.VOICE_VERSION + 1):
            assert line_hash("Hi", "en", "narrator", "m") != before

    def test_normalize(self):
        assert normalize_line("  a \n\t b  ") == "a b"
        assert normalize_line("") == ""


class TestProfiles:
    def test_every_api_voice_has_a_profile(self):
        from typing import get_args

        from app.api.v1.schemas.story_audio import StoryVoice

        assert set(get_args(StoryVoice)) == set(VOICE_PROFILES)

    def test_instructions_name_the_language_and_the_character(self):
        text = tts_instructions("tutor", "fr")
        assert "French" in text and "gecko" in text


class TestSynthesize:
    async def test_stores_the_clip_and_records_usage(self):
        storage = MagicMock()
        storage.upload_bytes = AsyncMock(return_value="http://minio/x")
        clip_id = uuid.uuid4()
        session = _session(scalar=clip_id)
        record = SimpleNamespace(id=clip_id)
        session.get = AsyncMock(return_value=record)

        speech = MagicMock()
        speech.create = AsyncMock(return_value=SimpleNamespace(content=b"OggS-audio"))
        openai_client = SimpleNamespace(audio=SimpleNamespace(speech=speech))

        with (
            patch.object(svc, "AsyncOpenAI", return_value=openai_client),
            patch.object(svc.settings, "openai_tts_model", "gpt-4o-mini-tts"),
            patch(
                "app.infrastructure.config.settings.Settings.openai_api_key",
                new="sk-test",
            ),
            patch("app.domain.services.ai_usage_service.record_ai_usage", AsyncMock()) as usage,
        ):
            out = await StoryAudioService(storage=storage).synthesize(
                "  Salut  Awa ", "fr", "girl", session
            )

        assert out is record
        kwargs = speech.create.await_args.kwargs
        assert kwargs["input"] == "Salut Awa"
        assert kwargs["voice"] == VOICE_PROFILES["girl"].voice
        assert kwargs["response_format"] == "opus"
        key = storage.upload_bytes.await_args.kwargs["key"]
        digest = line_hash("Salut Awa", "fr", "girl", "gpt-4o-mini-tts")
        assert key == f"story-audio/{digest[:2]}/{digest}.opus"
        assert usage.await_args.kwargs["feature"] == "story_tts"
        session.commit.assert_awaited_once()

    async def test_a_tts_failure_raises_and_stores_nothing(self):
        storage = MagicMock()
        storage.upload_bytes = AsyncMock()
        session = _session()
        speech = MagicMock()
        speech.create = AsyncMock(side_effect=RuntimeError("boom"))
        openai_client = SimpleNamespace(audio=SimpleNamespace(speech=speech))

        with (
            patch.object(svc, "AsyncOpenAI", return_value=openai_client),
            patch(
                "app.infrastructure.config.settings.Settings.openai_api_key",
                new="sk-test",
            ),
            patch("app.domain.services.ai_usage_service.record_ai_usage", AsyncMock()),
            pytest.raises(StoryAudioError),
        ):
            await StoryAudioService(storage=storage).synthesize("Salut", "fr", "girl", session)

        storage.upload_bytes.assert_not_awaited()
        session.execute.assert_not_awaited()


class TestRoutes:
    async def test_a_cached_line_is_served_without_tts(self, client):
        clip = SimpleNamespace(id=uuid.uuid4())
        _signed_in(_session(scalar=clip))
        with (
            patch.object(api, "_take_new_line_quota", AsyncMock()) as quota,
            patch.object(api.StoryAudioService, "synthesize", AsyncMock()) as synth,
        ):
            resp = await client.post(
                "/api/v1/story-audio", json={"text": "Bonjour", "language": "fr", "voice": "man"}
            )
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"id": str(clip.id), "url": f"/api/v1/story-audio/{clip.id}/data"}
        quota.assert_not_awaited()
        synth.assert_not_awaited()

    async def test_a_new_line_is_synthesized(self, client):
        clip = SimpleNamespace(id=uuid.uuid4())
        _signed_in(_session(scalar=None))
        with (
            patch(
                "app.infrastructure.config.settings.Settings.openai_api_key",
                new="sk-test",
            ),
            patch.object(api, "_take_new_line_quota", AsyncMock(return_value=True)),
            patch.object(
                api.StoryAudioService, "synthesize", AsyncMock(return_value=clip)
            ) as synth,
        ):
            resp = await client.post(
                "/api/v1/story-audio", json={"text": "Bonjour", "language": "fr", "voice": "tutor"}
            )
        assert resp.status_code == 200, resp.text
        assert resp.json()["url"] == f"/api/v1/story-audio/{clip.id}/data"
        assert synth.await_args.args[:3] == ("Bonjour", "fr", "tutor")
        assert synth.await_args.kwargs["user_id"] == uuid.UUID(USER_ID)

    async def test_past_the_daily_cap_is_429(self, client):
        _signed_in(_session(scalar=None))
        with (
            patch(
                "app.infrastructure.config.settings.Settings.openai_api_key",
                new="sk-test",
            ),
            patch.object(api, "_take_new_line_quota", AsyncMock(return_value=False)),
            patch.object(api.StoryAudioService, "synthesize", AsyncMock()) as synth,
        ):
            resp = await client.post(
                "/api/v1/story-audio", json={"text": "Bonjour", "language": "fr"}
            )
        assert resp.status_code == 429
        synth.assert_not_awaited()

    async def test_a_tts_failure_is_502(self, client):
        _signed_in(_session(scalar=None))
        with (
            patch(
                "app.infrastructure.config.settings.Settings.openai_api_key",
                new="sk-test",
            ),
            patch.object(api, "_take_new_line_quota", AsyncMock(return_value=True)),
            patch.object(
                api.StoryAudioService, "synthesize", AsyncMock(side_effect=StoryAudioError("x"))
            ),
        ):
            resp = await client.post(
                "/api/v1/story-audio", json={"text": "Bonjour", "language": "en"}
            )
        assert resp.status_code == 502

    @pytest.mark.parametrize(
        "body",
        [
            {"text": "x" * 601, "language": "fr"},
            {"text": "Bonjour", "language": "de"},
            {"text": "Bonjour", "language": "fr", "voice": "alloy"},
            {"text": "   ", "language": "fr"},
        ],
    )
    async def test_bad_requests_are_422(self, client, body):
        _signed_in(_session(scalar=None))
        resp = await client.post("/api/v1/story-audio", json=body)
        assert resp.status_code == 422

    async def test_signed_out_is_rejected(self, client):
        resp = await client.post("/api/v1/story-audio", json={"text": "Hi", "language": "en"})
        assert resp.status_code in (401, 403)

    async def test_data_serves_the_clip_as_immutable(self, client):
        app.dependency_overrides[get_db_session] = lambda: _session(scalar="story-audio/ab/ab.opus")
        storage = MagicMock()
        storage.download_bytes = AsyncMock(return_value=b"OggS")
        with patch.object(api, "S3StorageService", return_value=storage):
            resp = await client.get(f"/api/v1/story-audio/{uuid.uuid4()}/data")
        assert resp.status_code == 200
        assert resp.content == b"OggS"
        assert resp.headers["content-type"] == "audio/ogg"
        assert "immutable" in resp.headers["cache-control"]

    async def test_data_of_an_unknown_clip_is_404(self, client):
        app.dependency_overrides[get_db_session] = lambda: _session(scalar=None)
        resp = await client.get(f"/api/v1/story-audio/{uuid.uuid4()}/data")
        assert resp.status_code == 404


class TestQuota:
    async def test_counts_up_to_the_cap(self):
        fake = MagicMock()
        fake.incr = AsyncMock(side_effect=[1, 2, 3])
        fake.expire = AsyncMock()
        with patch.object(api, "redis_client", fake):
            assert await api._take_new_line_quota("u", 2) is True
            assert await api._take_new_line_quota("u", 2) is True
            assert await api._take_new_line_quota("u", 2) is False
        fake.expire.assert_awaited_once()

    async def test_redis_down_never_blocks(self):
        fake = MagicMock()
        fake.incr = AsyncMock(side_effect=ConnectionError("down"))
        with patch.object(api, "redis_client", fake):
            assert await api._take_new_line_quota("u", 2) is True
