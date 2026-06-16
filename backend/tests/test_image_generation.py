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
    _parse_labels,
    _resize_to_webp,
)


def _provider_patch(*, responses=None, side_effect=None):
    """Patch image_service's resolve_provider with a fake provider (#2523).

    Image metadata/alt-text now route through the pluggable provider's
    ``complete()`` instead of a direct ``anthropic.AsyncAnthropic`` call. This
    adapts the existing Anthropic-style mock messages (each with
    ``.content[0].text``) into ``LLMResult`` objects. Pass ``responses`` (one
    message or a list, consumed in order) or ``side_effect`` (e.g. an exception).
    Returns ``(patch_cm, complete_mock)`` — assert on ``complete_mock.call_args``.
    """
    from app.ai.providers.base import LLMResult

    complete_mock = AsyncMock()
    if side_effect is not None:
        complete_mock.side_effect = side_effect
    elif isinstance(responses, (list, tuple)):
        complete_mock.side_effect = [LLMResult(text=r.content[0].text) for r in responses]
    else:
        complete_mock.return_value = LLMResult(text=responses.content[0].text)
    provider = MagicMock()
    provider.complete = complete_mock
    return (
        patch("app.ai.providers.resolve_provider", return_value=provider),
        complete_mock,
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
        text = (
            "CONCEPT: paludisme\n"
            "PROMPT: Malaria parasite cycle illustration, no text\n"
            "TITLE_FR: Cycle du paludisme\n"
            "TITLE_EN: Malaria cycle\n"
            'LABELS: [{"fr": "Moustique", "en": "Mosquito"}, {"fr": "Foie", "en": "Liver"}]\n'
            'TAGS: ["paludisme", "aof"]'
        )
        concept, prompt, tags, title_fr, title_en, labels = _parse_concept_response(text)
        assert concept == "paludisme"
        assert "Malaria" in prompt
        assert "paludisme" in tags
        assert title_fr == "Cycle du paludisme"
        assert title_en == "Malaria cycle"
        assert labels == [
            {"fr": "Moustique", "en": "Mosquito"},
            {"fr": "Foie", "en": "Liver"},
        ]

    def test_defaults_when_empty(self):
        concept, prompt, tags, title_fr, title_en, labels = _parse_concept_response("")
        assert concept == "lesson concept"
        assert len(tags) > 0
        assert "style:illustration" in tags
        # Title falls back to the concept so the overlay always has something.
        assert title_en == "lesson concept"
        assert title_fr == "lesson concept"
        assert labels == []

    def test_tags_lowercased(self):
        text = 'CONCEPT: Malaria\nPROMPT: Illustration\nTAGS: ["MALARIA", "AOF"]'
        _, _, tags, _, _, _ = _parse_concept_response(text)
        assert all(t == t.lower() for t in tags)

    def test_title_fr_falls_back_to_en(self):
        text = "CONCEPT: water\nPROMPT: x\nTITLE_EN: Water cycle\nTAGS: []"
        _, _, _, title_fr, title_en, _ = _parse_concept_response(text)
        assert title_en == "Water cycle"
        assert title_fr == "Water cycle"


class TestParseLabels:
    def test_parses_objects(self):
        labels = _parse_labels('[{"fr": "Eau", "en": "Water"}]')
        assert labels == [{"fr": "Eau", "en": "Water"}]

    def test_string_items_used_for_both_languages(self):
        labels = _parse_labels('["Water", "Sun"]')
        assert labels == [
            {"fr": "Water", "en": "Water"},
            {"fr": "Sun", "en": "Sun"},
        ]

    def test_malformed_returns_empty(self):
        assert _parse_labels("not json") == []
        assert _parse_labels('{"fr": "x"}') == []

    def test_missing_one_language_backfills_from_other(self):
        labels = _parse_labels('[{"en": "Water"}]')
        assert labels == [{"fr": "Water", "en": "Water"}]


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


def _empty_lesson_context_result() -> MagicMock:
    """Mock result for the lesson context load — no GeneratedContent row found.

    Falls back the service to language='en' and AudienceContext(is_kids=False).
    """
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
            "PROMPT: Clean conceptual illustration of the malaria life cycle, no text or labels\n"
            "TITLE_FR: Cycle du paludisme\n"
            "TITLE_EN: Malaria life cycle\n"
            'LABELS: [{"fr": "Moustique", "en": "Mosquito"}, {"fr": "Sang", "en": "Blood"}]\n'
            'TAGS: ["paludisme", "malaria", "aof", "épidémiologie", "style:illustration"]'
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
            ["paludisme", "malaria", "aof", "épidémiologie", "style:illustration"]
        )
        existing.reuse_count = 0

        dedup_result = _no_existing_image_result()
        reuse_result = MagicMock()
        reuse_result.scalars.return_value.all.return_value = [existing]
        mock_session.execute = AsyncMock(
            side_effect=[dedup_result, _empty_lesson_context_result(), reuse_result]
        )

        prov_patch, _ = _provider_patch(responses=mock_claude_response)
        with (
            prov_patch,
            patch("app.ai.providers.image_provider.AsyncOpenAI") as mock_openai_cls,
        ):
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
        mock_session.execute = AsyncMock(
            side_effect=[dedup_result, _empty_lesson_context_result(), reuse_result]
        )

        fake_b64 = base64.b64encode(b"FAKE_PNG_DATA").decode()
        image_api_response = MagicMock()
        image_api_response.data = [MagicMock(b64_json=fake_b64)]

        prov_patch, complete_mock = _provider_patch(
            responses=[mock_claude_response, mock_alt_text_response]
        )
        with prov_patch:
            with patch("app.ai.providers.image_provider.AsyncOpenAI") as mock_openai_cls:
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
            # The prompt passed to gpt-image-1 is the text-free prompt Claude returned.
            prompt_sent = call_kwargs.get("prompt", "")
            assert "no text" in prompt_sent.lower()

        assert result.status == "ready"
        assert result.image_url == f"/api/v1/images/{result.id}/data"
        assert result.image_data is not None
        assert len(result.image_data) > 0
        # Overlay text extracted by Claude must be persisted on the record.
        assert result.title_fr == "Cycle du paludisme"
        assert result.title_en == "Malaria life cycle"
        assert result.overlay_labels == [
            {"fr": "Moustique", "en": "Mosquito"},
            {"fr": "Sang", "en": "Blood"},
        ]

    async def test_failure_handling_sets_failed_status(self, service, mock_session):
        """When DALL-E raises an exception, status must be 'failed' and lesson unaffected."""
        dedup_result = _no_existing_image_result()
        mock_session.execute = AsyncMock(return_value=dedup_result)

        prov_patch, complete_mock = _provider_patch(side_effect=RuntimeError("Claude API error"))
        with prov_patch:
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
        mock_session.execute = AsyncMock(
            side_effect=[dedup_result, _empty_lesson_context_result(), reuse_result]
        )

        fake_b64 = base64.b64encode(b"DATA").decode()
        image_api_response = MagicMock()
        image_api_response.data = [MagicMock(b64_json=fake_b64)]

        prov_patch, _ = _provider_patch(responses=[mock_claude_response, mock_alt_text_response])
        with (
            prov_patch,
            patch("app.ai.providers.image_provider.AsyncOpenAI") as mock_openai_cls,
        ):
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
            ["paludisme", "malaria", "aof", "épidémiologie", "style:illustration"]
        )
        existing.reuse_count = 2

        dedup_result = _no_existing_image_result()
        reuse_result = MagicMock()
        reuse_result.scalars.return_value.all.return_value = [existing]
        mock_session.execute = AsyncMock(
            side_effect=[dedup_result, _empty_lesson_context_result(), reuse_result]
        )

        prov_patch, complete_mock = _provider_patch(responses=mock_claude_response)
        with prov_patch:
            await service.generate_for_lesson(
                lesson_id=uuid.uuid4(),
                module_id=uuid.uuid4(),
                unit_id="u01",
                lesson_content="Malaria lesson in West Africa.",
                session=mock_session,
            )

        assert existing.reuse_count == 3

    def test_system_prompt_requests_text_free_illustration(self):
        """System prompt must request a text-free illustration, not baked-in labels."""
        import inspect

        from app.domain.services import image_service

        source = inspect.getsource(image_service)
        # Must demand a text-free image and provide structured overlay text instead.
        assert "ABSOLUTELY NO text" in source
        assert "TITLE_FR" in source and "TITLE_EN" in source
        assert "LABELS" in source
        assert "subject-agnostic" in source.lower()
        # Legacy baked-in-text infographic framing must be gone.
        assert "labeled diagram" not in source.lower()
        assert "callout label" not in source.lower()
        # West-Africa / public-health framing must be gone.
        assert "West African setting" not in source
        assert "public health education for West Africa" not in source

    def test_dalle_prompt_does_not_append_no_text_suffix(self):
        """The legacy NO-TEXT enforcement suffix must no longer be present."""
        import inspect

        from app.domain.services import image_service

        source = inspect.getsource(image_service)
        assert "NO text, letters, numbers, or written words" not in source

    def test_openai_image_provider_uses_medium_quality_landscape(self):
        """gpt-image-1 must be invoked at medium quality; image_service requests 1536x1024."""
        import inspect

        from app.ai.providers import image_provider
        from app.domain.services import image_service

        provider_source = inspect.getsource(image_provider)
        assert '"gpt-image-1"' in provider_source or "gpt-image-1" in provider_source
        assert '"medium"' in provider_source
        # image_service requests the landscape size from whichever provider runs.
        assert '"1536x1024"' in inspect.getsource(image_service)

    async def test_extract_concept_localizes_to_lesson_language(
        self, service, mock_claude_response
    ):
        """When language='fr', the system prompt sent to Claude must request French labels."""
        from app.ai.prompts.audience import AudienceContext

        prov_patch, complete_mock = _provider_patch(responses=mock_claude_response)
        with prov_patch:
            await service._extract_concept_and_tags(
                "Lesson about photosynthesis.",
                language="fr",
                audience=AudienceContext(is_kids=False),
            )

            system_prompt = complete_mock.call_args.kwargs["system"]
            assert "French" in system_prompt
            assert "language-agnostic" in system_prompt.lower()

    async def test_extract_concept_default_english(self, service, mock_claude_response):
        """Default language='en' must request English labels in the system prompt."""
        from app.ai.prompts.audience import AudienceContext

        prov_patch, complete_mock = _provider_patch(responses=mock_claude_response)
        with prov_patch:
            await service._extract_concept_and_tags(
                "Lesson about photosynthesis.",
                language="en",
                audience=AudienceContext(is_kids=False),
            )

            system_prompt = complete_mock.call_args.kwargs["system"]
            assert "English" in system_prompt

    async def test_extract_concept_kids_audience_branches_style(
        self, service, mock_claude_response
    ):
        """When audience.is_kids=True, the prompt must request kid-friendly cartoon style."""
        from app.ai.prompts.audience import AudienceContext

        prov_patch, complete_mock = _provider_patch(responses=mock_claude_response)
        with prov_patch:
            await service._extract_concept_and_tags(
                "Counting from 1 to 10.",
                language="en",
                audience=AudienceContext(is_kids=True, age_min=6, age_max=10),
            )

            system_prompt = complete_mock.call_args.kwargs["system"]
            # Kids style markers (cartoon, primary colors, mascot) must appear.
            assert "cartoon" in system_prompt.lower()
            assert "children" in system_prompt.lower() or "child" in system_prompt.lower()
            # Adult-default style markers must NOT appear in the kids branch.
            assert "muted palette" not in system_prompt.lower()

    async def test_extract_concept_allows_humans(self, service, mock_claude_response):
        """The system prompt must explicitly allow human figures in the infographic."""
        from app.ai.prompts.audience import AudienceContext

        prov_patch, complete_mock = _provider_patch(responses=mock_claude_response)
        with prov_patch:
            await service._extract_concept_and_tags(
                "Some lesson.",
                language="en",
                audience=AudienceContext(is_kids=False),
            )

            system_prompt = complete_mock.call_args.kwargs["system"]
            # Humans must be explicitly allowed (not forbidden).
            assert "Human figures" in system_prompt or "human figures" in system_prompt
            assert "allowed" in system_prompt.lower()
            # Pre-#2088 NO-PEOPLE markers must be gone.
            assert "no people" not in system_prompt.lower()
            assert "no human" not in system_prompt.lower()

    async def test_extract_concept_injects_style_and_audience_tags(
        self, service, mock_claude_response
    ):
        """style: and audience: discriminators are injected; lang: deliberately is NOT.

        Text-free illustrations are language agnostic, so one image is reused across
        FR and EN — no lang discriminator is added.
        """
        from app.ai.prompts.audience import AudienceContext

        prov_patch, complete_mock = _provider_patch(responses=mock_claude_response)
        with prov_patch:
            _, _, tags, _, _, _ = await service._extract_concept_and_tags(
                "Counting lesson.",
                language="fr",
                audience=AudienceContext(is_kids=True, age_min=6, age_max=10),
            )

            tags_lower = {t.lower() for t in tags}
            assert "audience:kids" in tags_lower
            assert "style:illustration" in tags_lower
            assert not any(t.startswith("lang:") for t in tags_lower)

    async def test_find_reusable_image_reuses_across_languages(self, service, mock_session):
        """A text-free illustration (no lang tag) is reused regardless of lesson language."""
        existing = _make_db_image(
            ["paludisme", "malaria", "aof", "épidémiologie", "style:illustration"]
        )

        reuse_result = MagicMock()
        reuse_result.scalars.return_value.all.return_value = [existing]
        mock_session.execute = AsyncMock(return_value=reuse_result)

        new_tags = ["paludisme", "malaria", "aof", "épidémiologie", "style:illustration"]
        result = await service._find_reusable_image(new_tags, mock_session)
        assert result is existing

    async def test_find_reusable_image_blocks_cross_style_reuse(self, service, mock_session):
        """A legacy baked-text infographic must NOT be reused for a new text-free illustration."""
        legacy = _make_db_image(
            ["paludisme", "malaria", "aof", "épidémiologie", "style:infographic"]
        )

        reuse_result = MagicMock()
        reuse_result.scalars.return_value.all.return_value = [legacy]
        mock_session.execute = AsyncMock(return_value=reuse_result)

        new_tags = ["paludisme", "malaria", "aof", "épidémiologie", "style:illustration"]
        result = await service._find_reusable_image(new_tags, mock_session)
        assert result is None

    async def test_find_reusable_image_blocks_cross_audience_reuse(self, service, mock_session):
        """An adult illustration must NOT be reused for a kids lesson."""
        adult = _make_db_image(
            ["paludisme", "malaria", "aof", "épidémiologie", "style:illustration"]
        )

        reuse_result = MagicMock()
        reuse_result.scalars.return_value.all.return_value = [adult]
        mock_session.execute = AsyncMock(return_value=reuse_result)

        # New (kids) generation carries the audience:kids discriminator the adult lacks.
        new_tags = [
            "paludisme",
            "malaria",
            "aof",
            "épidémiologie",
            "style:illustration",
            "audience:kids",
        ]
        result = await service._find_reusable_image(new_tags, mock_session)
        assert result is None

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
        mock_session.execute = AsyncMock(
            side_effect=[dedup_result, _empty_lesson_context_result(), reuse_result]
        )

        fake_b64 = base64.b64encode(b"FAKE_PNG_BINARY_DATA").decode()
        image_api_response = MagicMock()
        image_api_response.data = [MagicMock(b64_json=fake_b64)]

        prov_patch, _ = _provider_patch(responses=[mock_claude_response, mock_alt_text_response])
        with (
            prov_patch,
            patch("app.ai.providers.image_provider.AsyncOpenAI") as mock_openai_cls,
        ):
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
