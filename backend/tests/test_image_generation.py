"""Tests for DALL-E 3 async image generation pipeline (US-025, FR-03.2)."""

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.image import GeneratedImage
from app.domain.services.image_service import ImageGenerationService


@pytest.fixture
def image_service():
    return ImageGenerationService()


@pytest.fixture
def sample_lesson_content():
    return (
        "La surveillance épidémiologique est essentielle pour le contrôle des maladies. "
        "En Afrique de l'Ouest, le paludisme reste la principale cause de morbidité. "
        "Les systèmes de santé doivent collecter des données de manière systématique."
    )


@pytest.fixture
def sample_image_ready():
    return GeneratedImage(
        id=uuid.uuid4(),
        lesson_id=uuid.uuid4(),
        module_id=uuid.uuid4(),
        unit_id="unit-01",
        status="ready",
        dalle_prompt="A West African health worker recording malaria data in a rural clinic",
        semantic_tags=[
            "malaria",
            "surveillance",
            "health_worker",
            "west_africa",
            "data_collection",
        ],
        key_concept="Épidémiological surveillance",
        alt_text_fr="Agent de santé enregistrant des données de paludisme dans une clinique",
        alt_text_en="Health worker recording malaria data in a rural clinic",
        reuse_count=0,
        width=512,
        height=512,
        image_data=b"fake_webp_bytes",
        generated_at=datetime.now(UTC),
    )


class TestSemanticReuse:
    """Tests for semantic tag overlap reuse logic."""

    @pytest.mark.asyncio
    async def test_reuse_image_when_overlap_above_threshold(
        self, image_service, sample_image_ready
    ):
        """Images with >= 85% tag overlap should be reused."""
        session = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [sample_image_ready]
        session.execute = AsyncMock(return_value=mock_result)

        overlapping_tags = [
            "malaria",
            "surveillance",
            "health_worker",
            "west_africa",
            "data_collection",
        ]

        result = await image_service.find_reusable_image(overlapping_tags, session)

        assert result is not None
        assert result.id == sample_image_ready.id

    @pytest.mark.asyncio
    async def test_no_reuse_when_overlap_below_threshold(self, image_service, sample_image_ready):
        """Images with < 85% tag overlap should NOT be reused."""
        session = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [sample_image_ready]
        session.execute = AsyncMock(return_value=mock_result)

        low_overlap_tags = ["nutrition", "maternal_health", "vaccination", "hiv", "tuberculosis"]

        result = await image_service.find_reusable_image(low_overlap_tags, session)

        assert result is None

    @pytest.mark.asyncio
    async def test_reuse_increments_reuse_count(self, image_service, sample_image_ready):
        """Reusing an image must increment its reuse_count."""
        module_id = uuid.uuid4()
        lesson_id = uuid.uuid4()

        session = AsyncMock(spec=AsyncSession)
        call_count = 0

        def execute_side_effect(query):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                mock_result.scalars.return_value.all.return_value = [sample_image_ready]
            else:
                mock_result.scalars.return_value.all.return_value = []
            return mock_result

        session.execute = AsyncMock(side_effect=execute_side_effect)
        session.add = MagicMock()
        session.commit = AsyncMock()

        with (
            patch.object(
                image_service,
                "extract_concept_and_tags",
                new=AsyncMock(
                    return_value=(
                        "Surveillance",
                        "A health worker in West Africa",
                        [
                            "malaria",
                            "surveillance",
                            "health_worker",
                            "west_africa",
                            "data_collection",
                        ],
                    )
                ),
            ),
            patch.object(
                image_service,
                "generate_alt_text",
                new=AsyncMock(return_value=("Texte alt FR", "Alt text EN")),
            ),
        ):
            await image_service.process_lesson_image(
                lesson_id=lesson_id,
                module_id=module_id,
                unit_id="unit-01",
                lesson_content="Surveillance du paludisme en Afrique de l'Ouest",
                session=session,
            )

        assert sample_image_ready.reuse_count == 1

    @pytest.mark.asyncio
    async def test_no_reuse_when_no_images_exist(self, image_service):
        """Should return None when generated_images is empty."""
        session = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        session.execute = AsyncMock(return_value=mock_result)

        result = await image_service.find_reusable_image(["malaria", "surveillance"], session)

        assert result is None


class TestNewImageGeneration:
    """Tests for new DALL-E 3 image generation."""

    @pytest.mark.asyncio
    async def test_new_image_generated_when_no_reusable(self, image_service, sample_lesson_content):
        """When no reusable image exists, DALL-E should be called and image saved."""
        module_id = uuid.uuid4()
        lesson_id = uuid.uuid4()

        session = AsyncMock(spec=AsyncSession)
        call_count = 0

        def execute_side_effect(query):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            return mock_result

        session.execute = AsyncMock(side_effect=execute_side_effect)
        session.add = MagicMock()
        session.commit = AsyncMock()

        with (
            patch.object(
                image_service,
                "extract_concept_and_tags",
                new=AsyncMock(
                    return_value=(
                        "Malaria surveillance",
                        "A West African health worker at a clinic",
                        ["malaria", "surveillance", "clinic"],
                    )
                ),
            ),
            patch.object(
                image_service,
                "generate_alt_text",
                new=AsyncMock(return_value=("Texte alt FR", "Alt text EN")),
            ),
            patch.object(
                image_service,
                "call_dalle_and_save",
                new=AsyncMock(side_effect=lambda img, sess: setattr(img, "status", "ready") or img),
            ),
        ):
            result = await image_service.process_lesson_image(
                lesson_id=lesson_id,
                module_id=module_id,
                unit_id="unit-01",
                lesson_content=sample_lesson_content,
                session=session,
            )

        assert result.status == "ready"
        assert result.dalle_prompt == "A West African health worker at a clinic"
        assert result.semantic_tags == ["malaria", "surveillance", "clinic"]
        assert result.alt_text_fr == "Texte alt FR"
        assert result.alt_text_en == "Alt text EN"

    @pytest.mark.asyncio
    async def test_dalle_called_with_generated_prompt(self, image_service):
        """DALL-E API must be called with the Claude-generated prompt."""
        module_id = uuid.uuid4()
        lesson_id = uuid.uuid4()

        session = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        session.execute = AsyncMock(return_value=mock_result)
        session.add = MagicMock()
        session.commit = AsyncMock()

        dalle_mock = AsyncMock(side_effect=lambda img, sess: setattr(img, "status", "ready") or img)

        with (
            patch.object(
                image_service,
                "extract_concept_and_tags",
                new=AsyncMock(
                    return_value=("Test concept", "Test DALL-E prompt", ["tag1", "tag2"])
                ),
            ),
            patch.object(
                image_service,
                "generate_alt_text",
                new=AsyncMock(return_value=("Alt FR", "Alt EN")),
            ),
            patch.object(image_service, "call_dalle_and_save", new=dalle_mock),
        ):
            await image_service.process_lesson_image(
                lesson_id=lesson_id,
                module_id=module_id,
                unit_id="unit-02",
                lesson_content="Public health lesson content",
                session=session,
            )

        dalle_mock.assert_called_once()
        called_image = dalle_mock.call_args[0][0]
        assert called_image.dalle_prompt == "Test DALL-E prompt"


class TestFailureHandling:
    """Tests for graceful failure handling."""

    @pytest.mark.asyncio
    async def test_status_set_to_failed_on_dalle_error(self, image_service):
        """If DALL-E fails, image status must be 'failed' and lesson remains usable."""
        module_id = uuid.uuid4()
        lesson_id = uuid.uuid4()

        session = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        session.execute = AsyncMock(return_value=mock_result)
        session.add = MagicMock()
        session.commit = AsyncMock()

        async def failing_dalle(img, sess):
            img.status = "failed"
            img.error_message = "DALL-E API error: rate limit exceeded"
            return img

        with (
            patch.object(
                image_service,
                "extract_concept_and_tags",
                new=AsyncMock(return_value=("Concept", "Prompt", ["tag1"])),
            ),
            patch.object(
                image_service,
                "generate_alt_text",
                new=AsyncMock(return_value=("Alt FR", "Alt EN")),
            ),
            patch.object(image_service, "call_dalle_and_save", new=failing_dalle),
        ):
            result = await image_service.process_lesson_image(
                lesson_id=lesson_id,
                module_id=module_id,
                unit_id="unit-01",
                lesson_content="Lesson content",
                session=session,
            )

        assert result.status == "failed"
        assert result.error_message is not None

    @pytest.mark.asyncio
    async def test_status_set_to_failed_on_concept_extraction_error(self, image_service):
        """If Claude concept extraction fails, image status must be 'failed'."""
        module_id = uuid.uuid4()
        lesson_id = uuid.uuid4()

        session = AsyncMock(spec=AsyncSession)
        session.add = MagicMock()
        session.commit = AsyncMock()

        with patch.object(
            image_service,
            "extract_concept_and_tags",
            new=AsyncMock(side_effect=Exception("Claude API unavailable")),
        ):
            result = await image_service.process_lesson_image(
                lesson_id=lesson_id,
                module_id=module_id,
                unit_id="unit-01",
                lesson_content="Lesson content",
                session=session,
            )

        assert result.status == "failed"
        assert "Claude API unavailable" in result.error_message


class TestAltText:
    """Tests for bilingual alt-text generation."""

    @pytest.mark.asyncio
    async def test_alt_text_generated_in_fr_and_en(self, image_service):
        """Alt-text must be generated in both French and English."""
        mock_response = MagicMock()
        mock_block = MagicMock()
        mock_block.text = json.dumps(
            {
                "alt_text_fr": "Agent de santé collectant des données de paludisme",
                "alt_text_en": "Health worker collecting malaria data",
            }
        )
        mock_response.content = [mock_block]

        with patch("anthropic.Anthropic") as mock_anthropic_cls:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response
            mock_anthropic_cls.return_value = mock_client

            alt_fr, alt_en = await image_service.generate_alt_text(
                key_concept="Surveillance du paludisme",
                dalle_prompt="A health worker in West Africa collecting malaria data",
            )

        assert alt_fr == "Agent de santé collectant des données de paludisme"
        assert alt_en == "Health worker collecting malaria data"
        assert len(alt_fr) > 0
        assert len(alt_en) > 0


class TestStatusTransitions:
    """Tests for image status state machine."""

    @pytest.mark.asyncio
    async def test_image_starts_as_pending(self, image_service):
        """New image record must start with status='pending'."""
        module_id = uuid.uuid4()
        lesson_id = uuid.uuid4()

        captured_images = []

        session = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        session.execute = AsyncMock(return_value=mock_result)
        session.commit = AsyncMock()

        initial_statuses: list[str] = []

        def capture_add(obj):
            if isinstance(obj, GeneratedImage):
                initial_statuses.append(obj.status)
                captured_images.append(obj)

        session.add = MagicMock(side_effect=capture_add)

        with (
            patch.object(
                image_service,
                "extract_concept_and_tags",
                new=AsyncMock(return_value=("Concept", "Prompt", ["tag1"])),
            ),
            patch.object(
                image_service,
                "generate_alt_text",
                new=AsyncMock(return_value=("Alt FR", "Alt EN")),
            ),
            patch.object(
                image_service,
                "call_dalle_and_save",
                new=AsyncMock(side_effect=lambda img, sess: setattr(img, "status", "ready") or img),
            ),
        ):
            await image_service.process_lesson_image(
                lesson_id=lesson_id,
                module_id=module_id,
                unit_id="unit-01",
                lesson_content="Lesson",
                session=session,
            )

        assert len(initial_statuses) == 1
        assert initial_statuses[0] == "pending"


class TestOpenAIKeyNotExposed:
    """Verify OpenAI API key is server-side only."""

    def test_openai_key_not_in_image_service_module(self):
        """The image_service module must not contain hardcoded API keys."""
        import inspect

        from app.domain.services import image_service as img_svc_module

        source = inspect.getsource(img_svc_module)
        assert "sk-" not in source, "No hardcoded OpenAI API key in image_service"

    def test_openai_key_loaded_from_settings(self):
        """OPENAI_API_KEY must be loaded from settings (env var), not hardcoded."""
        from app.infrastructure.config.settings import Settings

        settings_fields = Settings.model_fields
        assert "openai_api_key" in settings_fields
