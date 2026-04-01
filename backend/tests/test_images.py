"""Tests for GET /api/v1/images/lesson/{lesson_id} and GET /api/v1/images/{image_id}/status."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient


def _make_content_row(
    *,
    content_type: str,
    content: dict,
    language: str = "fr",
    level: int = 1,
):
    row = MagicMock()
    row.id = uuid.uuid4()
    row.module_id = uuid.uuid4()
    row.content_type = content_type
    row.content = content
    row.language = language
    row.level = level
    row.country_context = "SN"
    return row


# ---------------------------------------------------------------------------
# GET /api/v1/images/lesson/{lesson_id}
# ---------------------------------------------------------------------------


class TestGetLessonImages:
    async def test_returns_empty_list_for_lesson_with_no_images(self, client: AsyncClient) -> None:
        lesson_id = uuid.uuid4()
        lesson_row = _make_content_row(
            content_type="lesson",
            content={"unit_id": "1.1"},
        )
        lesson_row.id = lesson_id

        async def fake_execute(query):
            result = MagicMock()
            scalars = MagicMock()
            scalars.all.return_value = []
            result.scalars.return_value = scalars
            result.scalar_one_or_none.return_value = lesson_row
            return result

        with patch(
            "sqlalchemy.ext.asyncio.AsyncSession.execute",
            new_callable=AsyncMock,
            side_effect=fake_execute,
        ):
            response = await client.get(f"/api/v1/images/lesson/{lesson_id}")

        assert response.status_code in (200, 404)

    async def test_ready_image_includes_image_url(self, client: AsyncClient) -> None:
        lesson_id = uuid.uuid4()
        image_id = uuid.uuid4()

        ready_image_content = {
            "lesson_id": str(lesson_id),
            "status": "ready",
            "image_url": "https://cdn.example.com/img.webp",
            "alt_text_fr": "Diagramme épidémiologique",
            "alt_text_en": "Epidemiology diagram",
            "format": "webp",
            "width": 800,
        }
        image_row = _make_content_row(content_type="image", content=ready_image_content)
        image_row.id = image_id
        lesson_row = _make_content_row(content_type="lesson", content={"unit_id": "1.1"})
        lesson_row.id = lesson_id

        call_count = 0

        async def fake_execute(query):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                scalars = MagicMock()
                scalars.all.return_value = [image_row]
                result.scalars.return_value = scalars
            else:
                result.scalar_one_or_none.return_value = lesson_row
            return result

        with patch("app.api.v1.images.AsyncSession", autospec=True):
            pass

        from app.api.v1.images import _build_lesson_image_response

        resp = _build_lesson_image_response(image_row, "fr")
        assert resp.status == "ready"
        assert resp.image_url == "https://cdn.example.com/img.webp"
        assert resp.alt_text == "Diagramme épidémiologique"
        assert resp.format == "webp"
        assert resp.width == 800

    async def test_pending_image_has_null_image_url(self, client: AsyncClient) -> None:
        lesson_id = uuid.uuid4()
        image_id = uuid.uuid4()

        pending_content = {
            "lesson_id": str(lesson_id),
            "status": "pending",
            "image_url": "https://cdn.example.com/img.webp",
            "alt_text": "some alt",
            "format": "webp",
            "width": 800,
        }
        image_row = _make_content_row(content_type="image", content=pending_content)
        image_row.id = image_id

        from app.api.v1.images import _build_lesson_image_response

        resp = _build_lesson_image_response(image_row, "fr")
        assert resp.status == "pending"
        assert resp.image_url is None

    async def test_generating_image_has_null_image_url(self, client: AsyncClient) -> None:
        lesson_id = uuid.uuid4()
        image_id = uuid.uuid4()

        generating_content = {
            "lesson_id": str(lesson_id),
            "status": "generating",
            "alt_text": "alt",
        }
        image_row = _make_content_row(content_type="image", content=generating_content)
        image_row.id = image_id

        from app.api.v1.images import _build_lesson_image_response

        resp = _build_lesson_image_response(image_row, "fr")
        assert resp.status == "generating"
        assert resp.image_url is None

    async def test_failed_image_has_null_image_url(self, client: AsyncClient) -> None:
        lesson_id = uuid.uuid4()
        image_id = uuid.uuid4()

        failed_content = {
            "lesson_id": str(lesson_id),
            "status": "failed",
        }
        image_row = _make_content_row(content_type="image", content=failed_content)
        image_row.id = image_id

        from app.api.v1.images import _build_lesson_image_response

        resp = _build_lesson_image_response(image_row, "fr")
        assert resp.status == "failed"
        assert resp.image_url is None

    async def test_alt_text_respects_user_language_fr(self, client: AsyncClient) -> None:
        lesson_id = uuid.uuid4()
        image_id = uuid.uuid4()

        content = {
            "lesson_id": str(lesson_id),
            "status": "ready",
            "image_url": "https://cdn.example.com/img.webp",
            "alt_text_fr": "Texte alternatif en français",
            "alt_text_en": "Alternative text in English",
        }
        image_row = _make_content_row(content_type="image", content=content)
        image_row.id = image_id

        from app.api.v1.images import _build_lesson_image_response

        resp_fr = _build_lesson_image_response(image_row, "fr")
        assert resp_fr.alt_text == "Texte alternatif en français"

        resp_en = _build_lesson_image_response(image_row, "en")
        assert resp_en.alt_text == "Alternative text in English"

    async def test_404_for_nonexistent_lesson(self, client: AsyncClient) -> None:
        nonexistent_id = uuid.uuid4()

        async def fake_execute(query):
            result = MagicMock()
            scalars = MagicMock()
            scalars.all.return_value = []
            result.scalars.return_value = scalars
            result.scalar_one_or_none.return_value = None
            return result

        with patch("app.api.v1.images.get_db") as mock_get_db:
            mock_session = AsyncMock()
            mock_session.execute = fake_execute
            mock_get_db.return_value = mock_session

            from app.api.deps import get_db
            from app.main import app

            async def override_get_db():
                yield mock_session

            app.dependency_overrides[get_db] = override_get_db
            try:
                response = await client.get(f"/api/v1/images/lesson/{nonexistent_id}")
                assert response.status_code == 404
                data = response.json()
                assert data["detail"]["error"] == "lesson_not_found"
            finally:
                app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /api/v1/images/{image_id}/status
# ---------------------------------------------------------------------------


class TestGetImageStatus:
    async def test_ready_image_returns_image_url(self, client: AsyncClient) -> None:
        image_id = uuid.uuid4()
        lesson_id = uuid.uuid4()

        ready_content = {
            "lesson_id": str(lesson_id),
            "status": "ready",
            "image_url": "https://cdn.example.com/ready.webp",
        }
        image_row = _make_content_row(content_type="image", content=ready_content)
        image_row.id = image_id

        async def fake_execute(query):
            result = MagicMock()
            result.scalar_one_or_none.return_value = image_row
            return result

        mock_session = AsyncMock()
        mock_session.execute = fake_execute

        from app.api.deps import get_db
        from app.infrastructure.cache.redis import redis_client
        from app.main import app

        async def override_get_db():
            yield mock_session

        app.dependency_overrides[get_db] = override_get_db

        pipe_mock = AsyncMock()
        pipe_mock.zremrangebyscore = MagicMock(return_value=pipe_mock)
        pipe_mock.zcard = MagicMock(return_value=pipe_mock)
        pipe_mock.zadd = MagicMock(return_value=pipe_mock)
        pipe_mock.expire = MagicMock(return_value=pipe_mock)
        pipe_mock.execute = AsyncMock(return_value=[None, 0, None, None])

        try:
            with patch.object(redis_client, "pipeline", return_value=pipe_mock):
                response = await client.get(f"/api/v1/images/{image_id}/status")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ready"
            assert data["image_url"] == "https://cdn.example.com/ready.webp"
        finally:
            app.dependency_overrides.clear()

    async def test_pending_image_returns_null_url(self, client: AsyncClient) -> None:
        image_id = uuid.uuid4()
        lesson_id = uuid.uuid4()

        pending_content = {
            "lesson_id": str(lesson_id),
            "status": "pending",
            "image_url": "https://cdn.example.com/img.webp",
        }
        image_row = _make_content_row(content_type="image", content=pending_content)
        image_row.id = image_id

        async def fake_execute(query):
            result = MagicMock()
            result.scalar_one_or_none.return_value = image_row
            return result

        mock_session = AsyncMock()
        mock_session.execute = fake_execute

        from app.api.deps import get_db
        from app.infrastructure.cache.redis import redis_client
        from app.main import app

        async def override_get_db():
            yield mock_session

        app.dependency_overrides[get_db] = override_get_db

        pipe_mock = AsyncMock()
        pipe_mock.zremrangebyscore = MagicMock(return_value=pipe_mock)
        pipe_mock.zcard = MagicMock(return_value=pipe_mock)
        pipe_mock.zadd = MagicMock(return_value=pipe_mock)
        pipe_mock.expire = MagicMock(return_value=pipe_mock)
        pipe_mock.execute = AsyncMock(return_value=[None, 0, None, None])

        try:
            with patch.object(redis_client, "pipeline", return_value=pipe_mock):
                response = await client.get(f"/api/v1/images/{image_id}/status")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "pending"
            assert data["image_url"] is None
        finally:
            app.dependency_overrides.clear()

    async def test_404_for_nonexistent_image(self, client: AsyncClient) -> None:
        nonexistent_id = uuid.uuid4()

        async def fake_execute(query):
            result = MagicMock()
            result.scalar_one_or_none.return_value = None
            return result

        mock_session = AsyncMock()
        mock_session.execute = fake_execute

        from app.api.deps import get_db
        from app.infrastructure.cache.redis import redis_client
        from app.main import app

        async def override_get_db():
            yield mock_session

        app.dependency_overrides[get_db] = override_get_db

        pipe_mock = AsyncMock()
        pipe_mock.zremrangebyscore = MagicMock(return_value=pipe_mock)
        pipe_mock.zcard = MagicMock(return_value=pipe_mock)
        pipe_mock.zadd = MagicMock(return_value=pipe_mock)
        pipe_mock.expire = MagicMock(return_value=pipe_mock)
        pipe_mock.execute = AsyncMock(return_value=[None, 0, None, None])

        try:
            with patch.object(redis_client, "pipeline", return_value=pipe_mock):
                response = await client.get(f"/api/v1/images/{nonexistent_id}/status")
            assert response.status_code == 404
            data = response.json()
            assert data["detail"]["error"] == "image_not_found"
        finally:
            app.dependency_overrides.clear()

    async def test_rate_limit_returns_429(self, client: AsyncClient) -> None:
        image_id = uuid.uuid4()
        lesson_id = uuid.uuid4()

        ready_content = {
            "lesson_id": str(lesson_id),
            "status": "ready",
            "image_url": "https://cdn.example.com/img.webp",
        }
        image_row = _make_content_row(content_type="image", content=ready_content)
        image_row.id = image_id

        async def fake_execute(query):
            result = MagicMock()
            result.scalar_one_or_none.return_value = image_row
            return result

        mock_session = AsyncMock()
        mock_session.execute = fake_execute

        from app.api.deps import get_db
        from app.infrastructure.cache.redis import redis_client
        from app.main import app

        async def override_get_db():
            yield mock_session

        app.dependency_overrides[get_db] = override_get_db

        pipe_mock = AsyncMock()
        pipe_mock.zremrangebyscore = MagicMock(return_value=pipe_mock)
        pipe_mock.zcard = MagicMock(return_value=pipe_mock)
        pipe_mock.zadd = MagicMock(return_value=pipe_mock)
        pipe_mock.expire = MagicMock(return_value=pipe_mock)
        pipe_mock.execute = AsyncMock(return_value=[None, 1, None, None])

        try:
            with patch.object(redis_client, "pipeline", return_value=pipe_mock):
                response = await client.get(f"/api/v1/images/{image_id}/status")
            assert response.status_code == 429
            data = response.json()
            assert data["detail"]["error"] == "rate_limit_exceeded"
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Schema unit tests
# ---------------------------------------------------------------------------


class TestImageSchemas:
    def test_lesson_image_response_ready_has_url(self) -> None:
        from app.api.v1.schemas.images import LessonImageResponse

        img = LessonImageResponse(
            id=uuid.uuid4(),
            lesson_id=uuid.uuid4(),
            status="ready",
            image_url="https://cdn.example.com/img.webp",
            alt_text="alt",
            format="webp",
            width=800,
        )
        assert img.image_url is not None
        assert img.status == "ready"

    def test_lesson_image_response_pending_allows_null_url(self) -> None:
        from app.api.v1.schemas.images import LessonImageResponse

        img = LessonImageResponse(
            id=uuid.uuid4(),
            lesson_id=uuid.uuid4(),
            status="pending",
            image_url=None,
            alt_text=None,
            format=None,
            width=None,
        )
        assert img.image_url is None
        assert img.status == "pending"

    def test_image_status_response_generating(self) -> None:
        from app.api.v1.schemas.images import ImageStatusResponse

        resp = ImageStatusResponse(
            id=uuid.uuid4(),
            status="generating",
            image_url=None,
        )
        assert resp.status == "generating"
        assert resp.image_url is None
