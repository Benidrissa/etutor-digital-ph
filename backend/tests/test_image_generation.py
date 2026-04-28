"""Tests for gpt-image-1 async image generation pipeline (issue #223, US-025)."""

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
        assert concept == "lesson concept"
        assert len(tags) > 0
        assert "style:infographic" in tags

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


def _no_existing_image_result() -> MagicMock:
    """Mock result for the dedup check — no existing image found."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    return result


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
        session.get = AsyncMock(return_value=None)
        return session

    @pytest.fixture
    def mock_claude_response(self):
        msg = MagicMock()
        content_block = MagicMock()
        content_block.text = (
            "CONCEPT: paludisme\n"
            "PROMPT: Educational poster titled Paludisme with labeled life-cycle stages and arrows\n"
            'TAGS: ["paludisme", "malaria", "aof", "épidémiologie", "style:infographic"]'
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
        existing = _make_db_image(
            ["paludisme", "malaria", "aof", "épidémiologie", "style:infographic"]
        )
        existing.reuse_count = 0

        dedup_result = _no_existing_image_result()
        reuse_result = MagicMock()
        reuse_result.scalars.return_value.all.return_value = [existing]
        mock_session.execute = AsyncMock(side_effect=[dedup_result, reuse_result])

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
        """When no matching image, gpt-image-1 must be called and image saved."""
        import base64

        dedup_result = _no_existing_image_result()
        reuse_result = MagicMock()
        reuse_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(side_effect=[dedup_result, reuse_result])

        fake_b64 = base64.b64encode(b"FAKE_PNG_DATA").decode()
        image_api_response = MagicMock()
        image_api_response.data = [MagicMock(b64_json=fake_b64)]

        with patch("anthropic.AsyncAnthropic") as mock_anthropic_cls:
            mock_client = AsyncMock()
            mock_anthropic_cls.return_value = mock_client
            mock_client.messages.create = AsyncMock(
                side_effect=[mock_claude_response, mock_alt_text_response]
            )

            with patch("openai.AsyncOpenAI") as mock_openai_cls:
                mock_openai = AsyncMock()
                mock_openai_cls.return_value = mock_openai
                mock_openai.images.generate = AsyncMock(return_value=image_api_response)

                result = await service.generate_for_lesson(
                    lesson_id=uuid.uuid4(),
                    module_id=uuid.uuid4(),
                    unit_id="u01",
                    lesson_content="Lesson about cholera surveillance.",
                    session=mock_session,
                )

            mock_openai.images.generate.assert_called_once()
            call_kwargs = mock_openai.images.generate.call_args.kwargs
            assert call_kwargs.get("model") == "gpt-image-1"
            assert call_kwargs.get("size") == "1536x1024"
            assert call_kwargs.get("quality") == "medium"
            prompt_sent = call_kwargs.get("prompt", "")
            assert "NO text" not in prompt_sent
            assert "no text, letters, numbers" not in prompt_sent.lower()

        assert result.status == "ready"
        assert result.image_url == f"/api/v1/images/{result.id}/data"
        assert result.image_data is not None
        assert len(result.image_data) > 0

    async def test_failure_handling_sets_failed_status(self, service, mock_session):
        """When DALL-E raises an exception, status must be 'failed' and lesson unaffected."""
        dedup_result = _no_existing_image_result()
        mock_session.execute = AsyncMock(return_value=dedup_result)

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
        import base64

        dedup_result = _no_existing_image_result()
        reuse_result = MagicMock()
        reuse_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(side_effect=[dedup_result, reuse_result])

        fake_b64 = base64.b64encode(b"DATA").decode()
        image_api_response = MagicMock()
        image_api_response.data = [MagicMock(b64_json=fake_b64)]

        with patch("anthropic.AsyncAnthropic") as mock_anthropic_cls:
            mock_client = AsyncMock()
            mock_anthropic_cls.return_value = mock_client
            mock_client.messages.create = AsyncMock(
                side_effect=[mock_claude_response, mock_alt_text_response]
            )

            with patch("openai.AsyncOpenAI") as mock_openai_cls:
                mock_openai = AsyncMock()
                mock_openai_cls.return_value = mock_openai
                mock_openai.images.generate = AsyncMock(return_value=image_api_response)

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
        existing = _make_db_image(
            ["paludisme", "malaria", "aof", "épidémiologie", "style:infographic"]
        )
        existing.reuse_count = 2

        dedup_result = _no_existing_image_result()
        reuse_result = MagicMock()
        reuse_result.scalars.return_value.all.return_value = [existing]
        mock_session.execute = AsyncMock(side_effect=[dedup_result, reuse_result])

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

    def test_system_prompt_requests_infographic_style(self):
        """System prompt for concept extraction must ask for an infographic with labels."""
        import inspect

        from app.domain.services import image_service

        source = inspect.getsource(image_service)
        assert "INFOGRAPHIC" in source
        assert "callout" in source.lower()
        assert "subject-agnostic" in source.lower()
        # West-Africa / public-health framing must be gone.
        assert "West African setting" not in source
        assert "public health education for West Africa" not in source

    def test_dalle_prompt_does_not_append_no_text_suffix(self):
        """The legacy NO-TEXT enforcement suffix must no longer be present."""
        import inspect

        from app.domain.services import image_service

        source = inspect.getsource(image_service)
        assert "NO text, letters, numbers, or written words" not in source

    def test_dalle_call_uses_medium_quality_landscape(self):
        """gpt-image-1 must be invoked at medium quality, 1536x1024."""
        import inspect

        from app.domain.services import image_service

        source = inspect.getsource(image_service)
        assert '"1536x1024"' in source
        assert '"medium"' in source

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
        """image_data must be stored (not NULL) after successful gpt-image-1 generation."""
        import base64

        dedup_result = _no_existing_image_result()
        reuse_result = MagicMock()
        reuse_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(side_effect=[dedup_result, reuse_result])

        fake_b64 = base64.b64encode(b"FAKE_PNG_BINARY_DATA").decode()
        image_api_response = MagicMock()
        image_api_response.data = [MagicMock(b64_json=fake_b64)]

        with patch("anthropic.AsyncAnthropic") as mock_anthropic_cls:
            mock_client = AsyncMock()
            mock_anthropic_cls.return_value = mock_client
            mock_client.messages.create = AsyncMock(
                side_effect=[mock_claude_response, mock_alt_text_response]
            )

            with patch("openai.AsyncOpenAI") as mock_openai_cls:
                mock_openai = AsyncMock()
                mock_openai_cls.return_value = mock_openai
                mock_openai.images.generate = AsyncMock(return_value=image_api_response)

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
