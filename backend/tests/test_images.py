"""Tests for image status endpoints (issue #224, US-025)."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

LESSON_ID = str(uuid.uuid4())
IMAGE_READY_ID = str(uuid.uuid4())
IMAGE_PENDING_ID = str(uuid.uuid4())
IMAGE_GENERATING_ID = str(uuid.uuid4())
IMAGE_FAILED_ID = str(uuid.uuid4())
UNKNOWN_LESSON_ID = str(uuid.uuid4())
UNKNOWN_IMAGE_ID = str(uuid.uuid4())

_SEED_IMAGES = {
    IMAGE_READY_ID: {
        "image_id": IMAGE_READY_ID,
        "lesson_id": LESSON_ID,
        "status": "ready",
        "image_url": "https://cdn.example.com/images/ready.webp",
        "alt_text": "Illustration de la leçon",
        "format": "webp",
        "width": 800,
    },
    IMAGE_PENDING_ID: {
        "image_id": IMAGE_PENDING_ID,
        "lesson_id": LESSON_ID,
        "status": "pending",
        "image_url": None,
        "alt_text": "Illustration de la leçon",
        "format": "webp",
        "width": 800,
    },
    IMAGE_GENERATING_ID: {
        "image_id": IMAGE_GENERATING_ID,
        "lesson_id": LESSON_ID,
        "status": "generating",
        "image_url": None,
        "alt_text": "Lesson illustration",
        "format": "webp",
        "width": 800,
    },
    IMAGE_FAILED_ID: {
        "image_id": IMAGE_FAILED_ID,
        "lesson_id": LESSON_ID,
        "status": "failed",
        "image_url": None,
        "alt_text": "Illustration de la leçon",
        "format": "webp",
        "width": 800,
    },
}


@pytest.fixture(autouse=True)
def seed_mock_images():
    """Seed the in-memory image store for each test and clean up after."""
    from app.api.v1 import images as images_module

    images_module._MOCK_IMAGES.update(_SEED_IMAGES)
    yield
    images_module._MOCK_IMAGES.clear()


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
        response = await client.get(f"/api/v1/images/lesson/{LESSON_ID}")
        assert response.status_code == 200
        data = response.json()
        assert data["lesson_id"] == LESSON_ID
        assert data["total"] == 4
        assert len(data["images"]) == 4

    async def test_ready_image_includes_url(self, client: AsyncClient, allow_rate_limit) -> None:
        response = await client.get(f"/api/v1/images/lesson/{LESSON_ID}")
        assert response.status_code == 200
        images = {img["image_id"]: img for img in response.json()["images"]}
        ready = images[IMAGE_READY_ID]
        assert ready["status"] == "ready"
        assert ready["image_url"] == "https://cdn.example.com/images/ready.webp"

    async def test_pending_image_has_null_url(self, client: AsyncClient, allow_rate_limit) -> None:
        response = await client.get(f"/api/v1/images/lesson/{LESSON_ID}")
        images = {img["image_id"]: img for img in response.json()["images"]}
        assert images[IMAGE_PENDING_ID]["image_url"] is None
        assert images[IMAGE_PENDING_ID]["status"] == "pending"

    async def test_generating_image_has_null_url(
        self, client: AsyncClient, allow_rate_limit
    ) -> None:
        response = await client.get(f"/api/v1/images/lesson/{LESSON_ID}")
        images = {img["image_id"]: img for img in response.json()["images"]}
        assert images[IMAGE_GENERATING_ID]["image_url"] is None
        assert images[IMAGE_GENERATING_ID]["status"] == "generating"

    async def test_failed_image_has_null_url(self, client: AsyncClient, allow_rate_limit) -> None:
        response = await client.get(f"/api/v1/images/lesson/{LESSON_ID}")
        images = {img["image_id"]: img for img in response.json()["images"]}
        assert images[IMAGE_FAILED_ID]["image_url"] is None
        assert images[IMAGE_FAILED_ID]["status"] == "failed"

    async def test_returns_404_for_unknown_lesson(
        self, client: AsyncClient, allow_rate_limit
    ) -> None:
        response = await client.get(f"/api/v1/images/lesson/{UNKNOWN_LESSON_ID}")
        assert response.status_code == 404
        assert "lesson_not_found" in response.json()["detail"]["error"]

    async def test_alt_text_in_french(self, client: AsyncClient, allow_rate_limit) -> None:
        response = await client.get(f"/api/v1/images/lesson/{LESSON_ID}?lang=fr")
        assert response.status_code == 200
        images = response.json()["images"]
        fr_image = next(img for img in images if img["image_id"] == IMAGE_READY_ID)
        assert "leçon" in fr_image["alt_text"].lower() or fr_image["alt_text"] != ""

    async def test_alt_text_in_english(self, client: AsyncClient, allow_rate_limit) -> None:
        response = await client.get(f"/api/v1/images/lesson/{LESSON_ID}?lang=en")
        assert response.status_code == 200
        images = response.json()["images"]
        en_image = next(img for img in images if img["image_id"] == IMAGE_GENERATING_ID)
        assert en_image["alt_text"] == "Lesson illustration"

    async def test_response_includes_format_and_width(
        self, client: AsyncClient, allow_rate_limit
    ) -> None:
        response = await client.get(f"/api/v1/images/lesson/{LESSON_ID}")
        image = response.json()["images"][0]
        assert image["format"] == "webp"
        assert image["width"] == 800


class TestGetImageStatus:
    async def test_ready_image_returns_url(self, client: AsyncClient, allow_rate_limit) -> None:
        response = await client.get(f"/api/v1/images/{IMAGE_READY_ID}/status")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
        assert data["image_url"] == "https://cdn.example.com/images/ready.webp"

    async def test_pending_image_returns_null_url(
        self, client: AsyncClient, allow_rate_limit
    ) -> None:
        response = await client.get(f"/api/v1/images/{IMAGE_PENDING_ID}/status")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "pending"
        assert data["image_url"] is None

    async def test_unknown_image_returns_404(self, client: AsyncClient, allow_rate_limit) -> None:
        response = await client.get(f"/api/v1/images/{UNKNOWN_IMAGE_ID}/status")
        assert response.status_code == 404
        assert "image_not_found" in response.json()["detail"]["error"]

    async def test_rate_limit_returns_429(self, client: AsyncClient, deny_rate_limit) -> None:
        response = await client.get(f"/api/v1/images/{IMAGE_READY_ID}/status")
        assert response.status_code == 429
        data = response.json()
        assert "rate_limit_exceeded" in data["detail"]["error"]
        assert response.headers["retry-after"] == "2"

    async def test_image_id_in_response(self, client: AsyncClient, allow_rate_limit) -> None:
        response = await client.get(f"/api/v1/images/{IMAGE_PENDING_ID}/status")
        assert response.status_code == 200
        assert response.json()["image_id"] == IMAGE_PENDING_ID
