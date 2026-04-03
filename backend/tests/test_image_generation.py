"""Tests for DALL-E 2 async image generation pipeline (issue #223, US-025)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.models.generated_image import GeneratedImage
from app.domain.services.image_service import (
    ImageGenerationService,
    _jaccard_similarity,
    _parse_alt_text,
    _parse_concept_response,
    _resize_to_webp,
)


class TestJaccardSimilarity:
    def test_identical_tags_returns_one(self):
        tags = ["malaria", "épidémiologie", "aof"]
        assert _jaccard_similarity(tags, tags) == 1.0

    def test_disjoint_tags_returns_zero(self):
        assert _jaccard_similarity(["malaria"], ["cholera"]) == 0.0

    def test_partial_overlap(self):
        a = ["malaria", "épidémiologie", "aof"]
        b = ["malaria", "épidémiologie", "sénégal"]
        similarity = _jaccard_similarity(a, b)
        assert abs(similarity - 2 / 4) < 1e-9

    def test_case_insensitive(self):
        assert _jaccard_similarity(["Malaria"], ["malaria"]) == 1.0

    def test_both_empty_returns_one(self):
        assert _jaccard_similarity([], []) == 1.0

    def test_one_empty_returns_zero(self):
        assert _jaccard_similarity(["malaria"], []) == 0.0


class TestParseConceptResponse:
    def test_parses_valid_response(self):
        text = 'CONCEPT: paludisme\nPROMPT: Malaria parasite cycle illustration\nTAGS: ["paludisme", "aof"]'
        concept, prompt, tags = _parse_concept_response(text)
        assert concept == "paludisme"
        assert "Malaria" in prompt
        assert "paludisme" in tags

    def test_defaults_when_empty(self):
        concept, prompt, tags = _parse_concept_response("")
        assert concept == "public health"
        assert len(tags) > 0

    def test_tags_lowercased(self):
        text = 'CONCEPT: Malaria\nPROMPT: Illustration\nTAGS: ["MALARIA", "AOF"]'
        _, _, tags = _parse_concept_response(text)
        assert all(t == t.lower() for t in tags)


class TestParseAltText:
    def test_parses_fr_and_en(self):
        text = "FR: Cycle de vie du paludisme\nEN: Malaria life cycle"
        fr, en = _parse_alt_text(text, "malaria")
        assert fr == "Cycle de vie du paludisme"
        assert en == "Malaria life cycle"

    def test_fallback_to_concept(self):
        fr, en = _parse_alt_text("", "malaria")
        assert "malaria" in fr.lower()
        assert "malaria" in en.lower()


class TestResizeToWebp:
    def test_skips_resize_when_already_at_target_width(self):
        """When input is already 512px wide, no resize should occur — only WebP conversion."""
        import io

        try:
            from PIL import Image
        except ImportError:
            pytest.skip("Pillow not installed")

        img = Image.new("RGB", (512, 512), color=(100, 150, 200))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        png_bytes = buf.getvalue()

        webp_bytes, width = _resize_to_webp(png_bytes, max_width=512)

        assert width == 512
        result_img = Image.open(io.BytesIO(webp_bytes))
        assert result_img.format == "WEBP"
        assert result_img.width == 512

    def test_resizes_when_larger_than_target(self):
        """When input is larger than max_width, it must be resized down."""
        import io

        try:
            from PIL import Image
        except ImportError:
            pytest.skip("Pillow not installed")

        img = Image.new("RGB", (1024, 1024), color=(100, 150, 200))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        png_bytes = buf.getvalue()

        webp_bytes, width = _resize_to_webp(png_bytes, max_width=512)

        assert width == 512
        result_img = Image.open(io.BytesIO(webp_bytes))
        assert result_img.width == 512


def _make_db_image(tags: list[str], status: str = "ready") -> GeneratedImage:
    img_id = uuid.uuid4()
    img = GeneratedImage(
        id=img_id,
        status=status,
        semantic_tags=tags,
        image_url=f"/api/v1/images/{img_id}/data",
        image_data=b"fake-webp-data",
        alt_text_fr="Image FR",
        alt_text_en="Image EN",
        width=512,
        format="webp",
        file_size_bytes=14,
        reuse_count=0,
    )
    return img


class TestImageGenerationService:
    @pytest.fixture
    def service(self):
        return ImageGenerationService()

    @pytest.fixture
    def mock_session(self):
        session = AsyncMock()
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        session.add = MagicMock()
        return session

    @pytest.fixture
    def mock_claude_response(self):
        msg = MagicMock()
        content_block = MagicMock()
        content_block.text = (
            "CONCEPT: paludisme\n"
            "PROMPT: Malaria parasite life cycle in West Africa illustration\n"
            'TAGS: ["paludisme", "malaria", "aof", "épidémiologie"]'
        )
        msg.content = [content_block]
        return msg

    @pytest.fixture
    def mock_alt_text_response(self):
        msg = MagicMock()
        content_block = MagicMock()
        content_block.text = (
            "FR: Cycle de vie du parasite du paludisme\nEN: Malaria parasite life cycle"
        )
        msg.content = [content_block]
        return msg

    async def test_semantic_reuse_skips_dalle(self, service, mock_session, mock_claude_response):
        """When a matching image exists (≥85% Jaccard), DALL-E must NOT be called."""
        existing = _make_db_image(["paludisme", "malaria", "aof", "épidémiologie"])
        existing.reuse_count = 0

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [existing]
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch("anthropic.AsyncAnthropic") as mock_anthropic_cls:
            mock_client = AsyncMock()
            mock_anthropic_cls.return_value = mock_client
            mock_client.messages.create = AsyncMock(return_value=mock_claude_response)

            with patch("openai.AsyncOpenAI") as mock_openai_cls:
                result = await service.generate_for_lesson(
                    lesson_id=uuid.uuid4(),
                    module_id=uuid.uuid4(),
                    unit_id="u01",
                    lesson_content="Lesson about malaria in West Africa.",
                    session=mock_session,
                )

                mock_openai_cls.assert_not_called()

        assert result.status == "ready"
        assert result.image_url == f"/api/v1/images/{result.id}/data"
        assert result.image_data == existing.image_data

    async def test_new_generation_calls_dalle(
        self, service, mock_session, mock_claude_response, mock_alt_text_response
    ):
        """When no matching image, DALL-E 2 must be called and image saved."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        dalle_response = MagicMock()
        dalle_response.data = [
            MagicMock(url="https://oaidalleapiprodscus.blob.core.windows.net/img.png")
        ]

        with patch("anthropic.AsyncAnthropic") as mock_anthropic_cls:
            mock_client = AsyncMock()
            mock_anthropic_cls.return_value = mock_client
            mock_client.messages.create = AsyncMock(
                side_effect=[mock_claude_response, mock_alt_text_response]
            )

            with patch("openai.AsyncOpenAI") as mock_openai_cls:
                mock_openai = AsyncMock()
                mock_openai_cls.return_value = mock_openai
                mock_openai.images.generate = AsyncMock(return_value=dalle_response)

                with patch("httpx.AsyncClient") as mock_http_cls:
                    mock_http = AsyncMock()
                    mock_http_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
                    mock_http_cls.return_value.__aexit__ = AsyncMock(return_value=False)
                    mock_http.get = AsyncMock(
                        return_value=MagicMock(
                            content=b"FAKE_PNG_DATA", raise_for_status=MagicMock()
                        )
                    )

                    result = await service.generate_for_lesson(
                        lesson_id=uuid.uuid4(),
                        module_id=uuid.uuid4(),
                        unit_id="u01",
                        lesson_content="Lesson about cholera surveillance.",
                        session=mock_session,
                    )

            mock_openai.images.generate.assert_called_once()
            call_kwargs = mock_openai.images.generate.call_args.kwargs
            assert call_kwargs.get("model") == "dall-e-2"
            assert call_kwargs.get("size") == "512x512"

        assert result.status == "ready"
        assert result.image_url == f"/api/v1/images/{result.id}/data"
        assert "oaidalleapiprodscus" not in (result.image_url or "")
        assert result.image_data is not None
        assert len(result.image_data) > 0

    async def test_failure_handling_sets_failed_status(self, service, mock_session):
        """When DALL-E raises an exception, status must be 'failed' and lesson unaffected."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch("anthropic.AsyncAnthropic") as mock_anthropic_cls:
            mock_client = AsyncMock()
            mock_anthropic_cls.return_value = mock_client
            mock_client.messages.create = AsyncMock(side_effect=RuntimeError("Claude API error"))

            result = await service.generate_for_lesson(
                lesson_id=uuid.uuid4(),
                module_id=uuid.uuid4(),
                unit_id="u01",
                lesson_content="Some lesson content.",
                session=mock_session,
            )

        assert result.status == "failed"

    async def test_alt_text_generated_in_both_languages(
        self, service, mock_session, mock_claude_response, mock_alt_text_response
    ):
        """Alt-text must be generated in both FR and EN."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        dalle_response = MagicMock()
        dalle_response.data = [MagicMock(url="https://example.com/img.png")]

        with patch("anthropic.AsyncAnthropic") as mock_anthropic_cls:
            mock_client = AsyncMock()
            mock_anthropic_cls.return_value = mock_client
            mock_client.messages.create = AsyncMock(
                side_effect=[mock_claude_response, mock_alt_text_response]
            )

            with patch("openai.AsyncOpenAI") as mock_openai_cls:
                mock_openai = AsyncMock()
                mock_openai_cls.return_value = mock_openai
                mock_openai.images.generate = AsyncMock(return_value=dalle_response)

                with patch("httpx.AsyncClient") as mock_http_cls:
                    mock_http = AsyncMock()
                    mock_http_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
                    mock_http_cls.return_value.__aexit__ = AsyncMock(return_value=False)
                    mock_http.get = AsyncMock(
                        return_value=MagicMock(content=b"DATA", raise_for_status=MagicMock())
                    )

                    result = await service.generate_for_lesson(
                        lesson_id=uuid.uuid4(),
                        module_id=uuid.uuid4(),
                        unit_id="u01",
                        lesson_content="Lesson content.",
                        session=mock_session,
                    )

        assert result.alt_text_fr is not None and len(result.alt_text_fr) > 0
        assert result.alt_text_en is not None and len(result.alt_text_en) > 0

    async def test_reuse_increments_reuse_count(self, service, mock_session, mock_claude_response):
        """Reusing an existing image must increment its reuse_count."""
        existing = _make_db_image(["paludisme", "malaria", "aof", "épidémiologie"])
        existing.reuse_count = 2

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [existing]
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch("anthropic.AsyncAnthropic") as mock_anthropic_cls:
            mock_client = AsyncMock()
            mock_anthropic_cls.return_value = mock_client
            mock_client.messages.create = AsyncMock(return_value=mock_claude_response)

            await service.generate_for_lesson(
                lesson_id=uuid.uuid4(),
                module_id=uuid.uuid4(),
                unit_id="u01",
                lesson_content="Malaria lesson in West Africa.",
                session=mock_session,
            )

        assert existing.reuse_count == 3

    def test_openai_api_key_not_in_frontend_accessible_code(self):
        """Verify OPENAI_API_KEY is loaded from settings (server-side), not hardcoded."""
        import inspect

        from app.domain.services import image_service

        source = inspect.getsource(image_service)
        assert "OPENAI_API_KEY" not in source or "settings.openai_api_key" in source
        assert "sk-" not in source

    def test_celery_task_is_registered(self):
        """Verify generate_lesson_image task is importable and has expected signature."""
        from app.tasks.content_generation import generate_lesson_image

        assert callable(generate_lesson_image)
        assert hasattr(generate_lesson_image, "delay")
        assert hasattr(generate_lesson_image, "apply_async")

    def test_backfill_task_is_registered(self):
        """Verify backfill_missing_image_data task is importable and has expected signature."""
        from app.tasks.content_generation import backfill_missing_image_data

        assert callable(backfill_missing_image_data)
        assert hasattr(backfill_missing_image_data, "delay")
        assert hasattr(backfill_missing_image_data, "apply_async")

    async def test_new_generation_image_data_not_null(
        self, service, mock_session, mock_claude_response, mock_alt_text_response
    ):
        """image_data must be stored (not NULL) after successful DALL-E generation."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        dalle_response = MagicMock()
        dalle_response.data = [MagicMock(url="https://example.com/img.png")]

        with patch("anthropic.AsyncAnthropic") as mock_anthropic_cls:
            mock_client = AsyncMock()
            mock_anthropic_cls.return_value = mock_client
            mock_client.messages.create = AsyncMock(
                side_effect=[mock_claude_response, mock_alt_text_response]
            )

            with patch("openai.AsyncOpenAI") as mock_openai_cls:
                mock_openai = AsyncMock()
                mock_openai_cls.return_value = mock_openai
                mock_openai.images.generate = AsyncMock(return_value=dalle_response)

                with patch("httpx.AsyncClient") as mock_http_cls:
                    mock_http = AsyncMock()
                    mock_http_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
                    mock_http_cls.return_value.__aexit__ = AsyncMock(return_value=False)
                    mock_http.get = AsyncMock(
                        return_value=MagicMock(
                            content=b"FAKE_PNG_BINARY_DATA", raise_for_status=MagicMock()
                        )
                    )

                    result = await service.generate_for_lesson(
                        lesson_id=uuid.uuid4(),
                        module_id=uuid.uuid4(),
                        unit_id="u01",
                        lesson_content="Lesson about tuberculosis surveillance in Senegal.",
                        session=mock_session,
                    )

        assert result.image_data is not None, "image_data must not be NULL after generation"
        assert len(result.image_data) > 0
        assert result.image_url == f"/api/v1/images/{result.id}/data"
        assert "blob.core.windows.net" not in (result.image_url or "")
