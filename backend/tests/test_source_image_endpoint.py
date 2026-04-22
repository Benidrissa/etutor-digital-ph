"""Tests for the ``/source-images/{id}/data`` endpoint lang fallback (issue #1834).

The endpoint streams image bytes from MinIO. Phase 2 slice 1 adds a
``?lang=fr|en`` query param: when ``lang=fr`` and the DB row has a
populated ``storage_url_fr``, we fetch from that URL; otherwise we fall
back to the default ``storage_url``. These tests exercise the routing
logic with a mocked DB session and a mocked httpx client — no real MinIO
or network.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import ASGITransport, AsyncClient

from app.api.deps import get_db
from app.domain.models.source_image import SourceImage
from app.main import app


class _FakeImageRow:
    def __init__(self, storage_url: str | None, storage_url_fr: str | None):
        self.id = uuid.uuid4()
        self.storage_url = storage_url
        self.storage_url_fr = storage_url_fr


class _FakeSession:
    def __init__(self, row: _FakeImageRow | None):
        self._row = row

    async def execute(self, stmt):
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=self._row)
        return result


@asynccontextmanager
async def _override_db(row: _FakeImageRow | None):
    async def _get_db_override():
        yield _FakeSession(row)

    app.dependency_overrides[get_db] = _get_db_override
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_db, None)


def _fake_upstream(body: bytes, content_type: str = "image/webp"):
    response = MagicMock()
    response.content = body
    response.headers = {"content-type": content_type}
    response.raise_for_status = MagicMock()
    return response


@asynccontextmanager
async def _patched_httpx(fetch_spy: MagicMock, body: bytes = b"fake-bytes"):
    async def _get(url):
        fetch_spy(url)
        return _fake_upstream(body)

    mock_client = MagicMock()
    mock_client.get = AsyncMock(side_effect=_get)
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "app.api.v1.source_images.httpx.AsyncClient",
        return_value=mock_ctx,
    ):
        yield


async def _get_data(url_suffix: str = ""):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        return await ac.get(url_suffix)


class TestDataEndpointLangFallback:
    async def test_no_lang_uses_default_storage_url(self):
        row = _FakeImageRow(
            storage_url="https://minio/default.webp",
            storage_url_fr="https://minio/fr.webp",
        )
        fetch = MagicMock()
        async with _override_db(row), _patched_httpx(fetch):
            resp = await _get_data(f"/api/v1/source-images/{row.id}/data")
        assert resp.status_code == 200
        fetch.assert_called_once_with("https://minio/default.webp")

    async def test_lang_en_uses_default_storage_url_even_when_fr_exists(self):
        row = _FakeImageRow(
            storage_url="https://minio/default.webp",
            storage_url_fr="https://minio/fr.webp",
        )
        fetch = MagicMock()
        async with _override_db(row), _patched_httpx(fetch):
            resp = await _get_data(f"/api/v1/source-images/{row.id}/data?lang=en")
        assert resp.status_code == 200
        fetch.assert_called_once_with("https://minio/default.webp")

    async def test_lang_fr_uses_french_variant_when_available(self):
        row = _FakeImageRow(
            storage_url="https://minio/default.webp",
            storage_url_fr="https://minio/fr.webp",
        )
        fetch = MagicMock()
        async with _override_db(row), _patched_httpx(fetch):
            resp = await _get_data(f"/api/v1/source-images/{row.id}/data?lang=fr")
        assert resp.status_code == 200
        fetch.assert_called_once_with("https://minio/fr.webp")

    async def test_lang_fr_falls_back_to_default_when_no_french_variant(self):
        row = _FakeImageRow(
            storage_url="https://minio/default.webp",
            storage_url_fr=None,
        )
        fetch = MagicMock()
        async with _override_db(row), _patched_httpx(fetch):
            resp = await _get_data(f"/api/v1/source-images/{row.id}/data?lang=fr")
        assert resp.status_code == 200
        fetch.assert_called_once_with("https://minio/default.webp")

    async def test_invalid_lang_rejected(self):
        row = _FakeImageRow(
            storage_url="https://minio/default.webp",
            storage_url_fr=None,
        )
        fetch = MagicMock()
        async with _override_db(row), _patched_httpx(fetch):
            resp = await _get_data(f"/api/v1/source-images/{row.id}/data?lang=de")
        assert resp.status_code == 422  # pydantic pattern validation
        fetch.assert_not_called()

    async def test_row_not_found_returns_404(self):
        fetch = MagicMock()
        some_id = uuid.uuid4()
        async with _override_db(None), _patched_httpx(fetch):
            resp = await _get_data(f"/api/v1/source-images/{some_id}/data")
        assert resp.status_code == 404
        fetch.assert_not_called()


# Defensive: make sure the real SourceImage model has the locale columns we rely
# on, so this file fails loudly if a future migration drops them.
def test_source_image_model_has_locale_storage_columns():
    columns = {c.name for c in SourceImage.__table__.columns}
    assert "storage_url_fr" in columns
    assert "storage_key_fr" in columns
