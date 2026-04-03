"""Tests for image status endpoints (issue #457, US-025)."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

LESSON_ID = uuid.uuid4()
IMAGE_READY_ID = uuid.uuid4()
IMAGE_PENDING_ID = uuid.uuid4()
IMAGE_GENERATING_ID = uuid.uuid4()
IMAGE_FAILED_ID = uuid.uuid4()
UNKNOWN_LESSON_ID = uuid.uuid4()
UNKNOWN_IMAGE_ID = uuid.uuid4()


def _make_image(
    image_id,
    lesson_id,
    img_status,
    image_url=None,
    alt_text_fr=None,
    alt_text_en=None,
    image_data=None,
):
    img = MagicMock()
    img.id = image_id
    img.lesson_id = lesson_id
    img.status = img_status
    img.image_url = image_url
    img.image_data = image_data
    img.alt_text_fr = alt_text_fr
    img.alt_text_en = alt_text_en
    img.format = "webp"
    img.width = 800
    return img


_READY_IMAGE = _make_image(
    IMAGE_READY_ID,
    LESSON_ID,
    "ready",
    image_url=f"/api/v1/images/{IMAGE_READY_ID}/data",
    alt_text_fr="Illustration de la leçon",
    alt_text_en="Lesson illustration",
)
_PENDING_IMAGE = _make_image(
    IMAGE_PENDING_ID,
    LESSON_ID,
    "pending",
    alt_text_fr="Illustration de la leçon",
)
_GENERATING_IMAGE = _make_image(
    IMAGE_GENERATING_ID,
    LESSON_ID,
    "generating",
    alt_text_en="Lesson illustration",
)
_FAILED_IMAGE = _make_image(
    IMAGE_FAILED_ID,
    LESSON_ID,
    "failed",
    alt_text_fr="Illustration de la leçon",
)

_ALL_LESSON_IMAGES = [_READY_IMAGE, _PENDING_IMAGE, _GENERATING_IMAGE, _FAILED_IMAGE]

_IMAGE_BY_ID = {
    IMAGE_READY_ID: _READY_IMAGE,
    IMAGE_PENDING_ID: _PENDING_IMAGE,
    IMAGE_GENERATING_ID: _GENERATING_IMAGE,
    IMAGE_FAILED_ID: _FAILED_IMAGE,
}


def _make_db_scalars(images):
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = images
    result_mock = MagicMock()
    result_mock.scalars.return_value = scalars_mock
    return result_mock


def _make_db_scalar_one_or_none(image):
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = image
    return result_mock


@pytest.fixture
def allow_rate_limit():
    """Patch rate limiting to always allow requests."""
    with patch(
        "app.api.v1.images._check_rate_limit",
        new_callable=AsyncMock,
        return_value=True,
    ):
        yield


@pytest.fixture
def deny_rate_limit():
    """Patch rate limiting to always deny requests."""
    with patch(
        "app.api.v1.images._check_rate_limit",
        new_callable=AsyncMock,
        return_value=False,
    ):
        yield


class TestGetLessonImages:
    async def test_returns_200_with_images(self, client: AsyncClient, allow_rate_limit) -> None:
        db_mock = AsyncMock()
        db_mock.execute.return_value = _make_db_scalars(_ALL_LESSON_IMAGES)
        with patch("app.api.v1.images.get_db_session", return_value=db_mock):
            from app.api.deps import get_db_session
            from app.main import app

            async def override():
                yield db_mock

            app.dependency_overrides[get_db_session] = override
            try:
                response = await client.get(f"/api/v1/images/lesson/{LESSON_ID}")
                assert response.status_code == 200
                data = response.json()
                assert data["lesson_id"] == str(LESSON_ID)
                assert data["total"] == 4
                assert len(data["images"]) == 4
            finally:
                app.dependency_overrides.pop(get_db_session, None)

    async def test_ready_image_includes_url(self, client: AsyncClient, allow_rate_limit) -> None:
        db_mock = AsyncMock()
        db_mock.execute.return_value = _make_db_scalars(_ALL_LESSON_IMAGES)
        from app.api.deps import get_db_session
        from app.main import app

        async def override():
            yield db_mock

        app.dependency_overrides[get_db_session] = override
        try:
            response = await client.get(f"/api/v1/images/lesson/{LESSON_ID}")
            assert response.status_code == 200
            images = {img["image_id"]: img for img in response.json()["images"]}
            ready = images[str(IMAGE_READY_ID)]
            assert ready["status"] == "ready"
            assert ready["image_url"] == f"/api/v1/images/{IMAGE_READY_ID}/data"
        finally:
            app.dependency_overrides.pop(get_db_session, None)

    async def test_azure_url_overridden_with_own_endpoint(
        self, client: AsyncClient, allow_rate_limit
    ) -> None:
        azure_image = _make_image(
            IMAGE_READY_ID,
            LESSON_ID,
            "ready",
            image_url="https://oaidalleapiprodscus.blob.core.windows.net/expired-url",
            alt_text_fr="Illustration de la leçon",
        )
        db_mock = AsyncMock()
        db_mock.execute.return_value = _make_db_scalars([azure_image])
        from app.api.deps import get_db_session
        from app.main import app

        async def override():
            yield db_mock

        app.dependency_overrides[get_db_session] = override
        try:
            response = await client.get(f"/api/v1/images/lesson/{LESSON_ID}")
            assert response.status_code == 200
            images = response.json()["images"]
            assert len(images) == 1
            assert images[0]["image_url"] == f"/api/v1/images/{IMAGE_READY_ID}/data"
            assert "blob.core.windows.net" not in (images[0]["image_url"] or "")
        finally:
            app.dependency_overrides.pop(get_db_session, None)

    async def test_pending_image_has_null_url(self, client: AsyncClient, allow_rate_limit) -> None:
        db_mock = AsyncMock()
        db_mock.execute.return_value = _make_db_scalars(_ALL_LESSON_IMAGES)
        from app.api.deps import get_db_session
        from app.main import app

        async def override():
            yield db_mock

        app.dependency_overrides[get_db_session] = override
        try:
            response = await client.get(f"/api/v1/images/lesson/{LESSON_ID}")
            images = {img["image_id"]: img for img in response.json()["images"]}
            assert images[str(IMAGE_PENDING_ID)]["image_url"] is None
            assert images[str(IMAGE_PENDING_ID)]["status"] == "pending"
        finally:
            app.dependency_overrides.pop(get_db_session, None)

    async def test_generating_image_has_null_url(
        self, client: AsyncClient, allow_rate_limit
    ) -> None:
        db_mock = AsyncMock()
        db_mock.execute.return_value = _make_db_scalars(_ALL_LESSON_IMAGES)
        from app.api.deps import get_db_session
        from app.main import app

        async def override():
            yield db_mock

        app.dependency_overrides[get_db_session] = override
        try:
            response = await client.get(f"/api/v1/images/lesson/{LESSON_ID}")
            images = {img["image_id"]: img for img in response.json()["images"]}
            assert images[str(IMAGE_GENERATING_ID)]["image_url"] is None
            assert images[str(IMAGE_GENERATING_ID)]["status"] == "generating"
        finally:
            app.dependency_overrides.pop(get_db_session, None)

    async def test_failed_image_has_null_url(self, client: AsyncClient, allow_rate_limit) -> None:
        db_mock = AsyncMock()
        db_mock.execute.return_value = _make_db_scalars(_ALL_LESSON_IMAGES)
        from app.api.deps import get_db_session
        from app.main import app

        async def override():
            yield db_mock

        app.dependency_overrides[get_db_session] = override
        try:
            response = await client.get(f"/api/v1/images/lesson/{LESSON_ID}")
            images = {img["image_id"]: img for img in response.json()["images"]}
            assert images[str(IMAGE_FAILED_ID)]["image_url"] is None
            assert images[str(IMAGE_FAILED_ID)]["status"] == "failed"
        finally:
            app.dependency_overrides.pop(get_db_session, None)

    async def test_returns_404_for_unknown_lesson(
        self, client: AsyncClient, allow_rate_limit
    ) -> None:
        db_mock = AsyncMock()
        db_mock.execute.return_value = _make_db_scalars([])
        from app.api.deps import get_db_session
        from app.main import app

        async def override():
            yield db_mock

        app.dependency_overrides[get_db_session] = override
        try:
            response = await client.get(f"/api/v1/images/lesson/{UNKNOWN_LESSON_ID}")
            assert response.status_code == 404
            assert "lesson_not_found" in response.json()["detail"]["error"]
        finally:
            app.dependency_overrides.pop(get_db_session, None)

    async def test_alt_text_in_french(self, client: AsyncClient, allow_rate_limit) -> None:
        db_mock = AsyncMock()
        db_mock.execute.return_value = _make_db_scalars(_ALL_LESSON_IMAGES)
        from app.api.deps import get_db_session
        from app.main import app

        async def override():
            yield db_mock

        app.dependency_overrides[get_db_session] = override
        try:
            response = await client.get(f"/api/v1/images/lesson/{LESSON_ID}?lang=fr")
            assert response.status_code == 200
            images = response.json()["images"]
            fr_image = next(img for img in images if img["image_id"] == str(IMAGE_READY_ID))
            assert fr_image["alt_text"] != ""
        finally:
            app.dependency_overrides.pop(get_db_session, None)

    async def test_alt_text_in_english(self, client: AsyncClient, allow_rate_limit) -> None:
        db_mock = AsyncMock()
        db_mock.execute.return_value = _make_db_scalars(_ALL_LESSON_IMAGES)
        from app.api.deps import get_db_session
        from app.main import app

        async def override():
            yield db_mock

        app.dependency_overrides[get_db_session] = override
        try:
            response = await client.get(f"/api/v1/images/lesson/{LESSON_ID}?lang=en")
            assert response.status_code == 200
            images = response.json()["images"]
            en_image = next(img for img in images if img["image_id"] == str(IMAGE_GENERATING_ID))
            assert en_image["alt_text"] == "Lesson illustration"
        finally:
            app.dependency_overrides.pop(get_db_session, None)

    async def test_response_includes_format_and_width(
        self, client: AsyncClient, allow_rate_limit
    ) -> None:
        db_mock = AsyncMock()
        db_mock.execute.return_value = _make_db_scalars(_ALL_LESSON_IMAGES)
        from app.api.deps import get_db_session
        from app.main import app

        async def override():
            yield db_mock

        app.dependency_overrides[get_db_session] = override
        try:
            response = await client.get(f"/api/v1/images/lesson/{LESSON_ID}")
            image = response.json()["images"][0]
            assert image["format"] == "webp"
            assert image["width"] == 800
        finally:
            app.dependency_overrides.pop(get_db_session, None)


class TestGetImageStatus:
    async def test_ready_image_returns_url(self, client: AsyncClient, allow_rate_limit) -> None:
        db_mock = AsyncMock()
        db_mock.execute.return_value = _make_db_scalar_one_or_none(_READY_IMAGE)
        from app.api.deps import get_db_session
        from app.main import app

        async def override():
            yield db_mock

        app.dependency_overrides[get_db_session] = override
        try:
            response = await client.get(f"/api/v1/images/{IMAGE_READY_ID}/status")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ready"
            assert data["image_url"] == f"/api/v1/images/{IMAGE_READY_ID}/data"
        finally:
            app.dependency_overrides.pop(get_db_session, None)

    async def test_pending_image_returns_null_url(
        self, client: AsyncClient, allow_rate_limit
    ) -> None:
        db_mock = AsyncMock()
        db_mock.execute.return_value = _make_db_scalar_one_or_none(_PENDING_IMAGE)
        from app.api.deps import get_db_session
        from app.main import app

        async def override():
            yield db_mock

        app.dependency_overrides[get_db_session] = override
        try:
            response = await client.get(f"/api/v1/images/{IMAGE_PENDING_ID}/status")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "pending"
            assert data["image_url"] is None
        finally:
            app.dependency_overrides.pop(get_db_session, None)

    async def test_unknown_image_returns_404(self, client: AsyncClient, allow_rate_limit) -> None:
        db_mock = AsyncMock()
        db_mock.execute.return_value = _make_db_scalar_one_or_none(None)
        from app.api.deps import get_db_session
        from app.main import app

        async def override():
            yield db_mock

        app.dependency_overrides[get_db_session] = override
        try:
            response = await client.get(f"/api/v1/images/{UNKNOWN_IMAGE_ID}/status")
            assert response.status_code == 404
            assert "image_not_found" in response.json()["detail"]["error"]
        finally:
            app.dependency_overrides.pop(get_db_session, None)

    async def test_rate_limit_returns_429(self, client: AsyncClient, deny_rate_limit) -> None:
        response = await client.get(f"/api/v1/images/{IMAGE_READY_ID}/status")
        assert response.status_code == 429
        data = response.json()
        assert "rate_limit_exceeded" in data["detail"]["error"]
        assert response.headers["retry-after"] == "2"

    async def test_image_id_in_response(self, client: AsyncClient, allow_rate_limit) -> None:
        db_mock = AsyncMock()
        db_mock.execute.return_value = _make_db_scalar_one_or_none(_PENDING_IMAGE)
        from app.api.deps import get_db_session
        from app.main import app

        async def override():
            yield db_mock

        app.dependency_overrides[get_db_session] = override
        try:
            response = await client.get(f"/api/v1/images/{IMAGE_PENDING_ID}/status")
            assert response.status_code == 200
            assert response.json()["image_id"] == str(IMAGE_PENDING_ID)
        finally:
            app.dependency_overrides.pop(get_db_session, None)


class TestGetImageData:
    async def test_ready_image_serves_binary_data(self, client: AsyncClient) -> None:
        ready_with_data = _make_image(
            IMAGE_READY_ID,
            LESSON_ID,
            "ready",
            image_data=b"fake-webp-bytes",
        )
        db_mock = AsyncMock()
        db_mock.execute.return_value = _make_db_scalar_one_or_none(ready_with_data)
        from app.api.deps import get_db_session
        from app.main import app

        async def override():
            yield db_mock

        app.dependency_overrides[get_db_session] = override
        try:
            response = await client.get(
                f"/api/v1/images/{IMAGE_READY_ID}/data", follow_redirects=False
            )
            assert response.status_code == 200
            assert response.headers["content-type"] == "image/webp"
            assert response.content == b"fake-webp-bytes"
        finally:
            app.dependency_overrides.pop(get_db_session, None)

    async def test_ready_image_with_no_binary_data_returns_404(self, client: AsyncClient) -> None:
        ready_no_data = _make_image(
            IMAGE_READY_ID,
            LESSON_ID,
            "ready",
            image_url=None,
            image_data=None,
        )
        db_mock = AsyncMock()
        db_mock.execute.return_value = _make_db_scalar_one_or_none(ready_no_data)
        from app.api.deps import get_db_session
        from app.main import app

        async def override():
            yield db_mock

        app.dependency_overrides[get_db_session] = override
        try:
            response = await client.get(
                f"/api/v1/images/{IMAGE_READY_ID}/data", follow_redirects=False
            )
            assert response.status_code == 404
            assert "image_data_unavailable" in response.json()["detail"]["error"]
        finally:
            app.dependency_overrides.pop(get_db_session, None)

    async def test_pending_image_returns_404(self, client: AsyncClient) -> None:
        db_mock = AsyncMock()
        db_mock.execute.return_value = _make_db_scalar_one_or_none(_PENDING_IMAGE)
        from app.api.deps import get_db_session
        from app.main import app

        async def override():
            yield db_mock

        app.dependency_overrides[get_db_session] = override
        try:
            response = await client.get(
                f"/api/v1/images/{IMAGE_PENDING_ID}/data", follow_redirects=False
            )
            assert response.status_code == 404
            assert "image_not_ready" in response.json()["detail"]["error"]
        finally:
            app.dependency_overrides.pop(get_db_session, None)

    async def test_unknown_image_returns_404(self, client: AsyncClient) -> None:
        db_mock = AsyncMock()
        db_mock.execute.return_value = _make_db_scalar_one_or_none(None)
        from app.api.deps import get_db_session
        from app.main import app

        async def override():
            yield db_mock

        app.dependency_overrides[get_db_session] = override
        try:
            response = await client.get(
                f"/api/v1/images/{UNKNOWN_IMAGE_ID}/data", follow_redirects=False
            )
            assert response.status_code == 404
            assert "image_not_found" in response.json()["detail"]["error"]
        finally:
            app.dependency_overrides.pop(get_db_session, None)
