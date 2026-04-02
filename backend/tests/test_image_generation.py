"""Tests for DALL-E 3 async image generation pipeline (US-025, FR-03.2)."""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.services.image_service import ImageGenerationService, _jaccard


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

LESSON_CONTENT = "Malaria is a life-threatening disease caused by Plasmodium parasites."


def _make_anthropic_response(payload: dict) -> SimpleNamespace:
    text = json.dumps(payload)
    return SimpleNamespace(content=[SimpleNamespace(text=text)])


def _make_service(anthropic_mock, openai_mock) -> ImageGenerationService:
    settings_mock = MagicMock()
    settings_mock.anthropic_api_key = "test-anthropic-key"
    settings_mock.openai_api_key = "test-openai-key"
    return ImageGenerationService(
        anthropic_client=anthropic_mock,
        openai_client=openai_mock,
        settings=settings_mock,
    )


def _concept_response():
    return _make_anthropic_response(
        {
            "concept": "malaria parasite life cycle",
            "prompt": "Educational illustration of malaria parasite life cycle in West Africa",
            "tags": ["malaria", "parasite", "epidemiology", "west africa", "mosquito"],
        }
    )


def _alt_text_response():
    return _make_anthropic_response(
        {
            "fr": "Cycle de vie du parasite du paludisme",
            "en": "Malaria parasite life cycle",
        }
    )


def _dalle_response(url: str = "https://cdn.example.com/malaria.png") -> SimpleNamespace:
    return SimpleNamespace(data=[SimpleNamespace(url=url)])


# ---------------------------------------------------------------------------
# Unit tests: Jaccard similarity
# ---------------------------------------------------------------------------


class TestJaccard:
    def test_identical_tags_return_1(self):
        tags = ["malaria", "parasite", "epidemiology"]
        assert _jaccard(tags, tags) == 1.0

    def test_disjoint_tags_return_0(self):
        assert _jaccard(["a", "b"], ["c", "d"]) == 0.0

    def test_50_percent_overlap(self):
        assert _jaccard(["a", "b"], ["b", "c"]) == pytest.approx(1 / 3)

    def test_case_insensitive(self):
        assert _jaccard(["Malaria"], ["malaria"]) == 1.0

    def test_empty_both_returns_1(self):
        assert _jaccard([], []) == 1.0

    def test_one_empty_returns_0(self):
        assert _jaccard(["malaria"], []) == 0.0


# ---------------------------------------------------------------------------
# Unit tests: _extract_concept_and_tags
# ---------------------------------------------------------------------------


class TestExtractConceptAndTags:
    async def test_returns_concept_prompt_tags(self):
        anthropic_mock = MagicMock()
        anthropic_mock.messages = MagicMock()
        anthropic_mock.messages.create = AsyncMock(return_value=_concept_response())
        openai_mock = MagicMock()

        service = _make_service(anthropic_mock, openai_mock)
        concept, prompt, tags = await service._extract_concept_and_tags(LESSON_CONTENT)

        assert concept == "malaria parasite life cycle"
        assert "malaria" in prompt.lower()
        assert isinstance(tags, list)
        assert len(tags) >= 3


# ---------------------------------------------------------------------------
# Unit tests: semantic reuse
# ---------------------------------------------------------------------------


class TestSemanticReuse:
    async def test_reuses_image_with_high_overlap(self):
        """When existing image has ≥85% tag overlap → reuse it."""
        existing_tags = ["malaria", "parasite", "epidemiology", "west africa", "mosquito"]
        new_tags = ["malaria", "parasite", "epidemiology", "west africa", "mosquito"]

        existing_image = MagicMock()
        existing_image.id = uuid.uuid4()
        existing_image.status = "ready"
        existing_image.semantic_tags = existing_tags
        existing_image.reuse_count = 0

        session = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [existing_image]
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_mock
        session.execute = AsyncMock(return_value=execute_result)
        session.commit = AsyncMock()

        service = _make_service(MagicMock(), MagicMock())
        found = await service._find_reusable_image(session, new_tags)

        assert found is not None
        assert found.id == existing_image.id

    async def test_no_reuse_with_low_overlap(self):
        """When existing image has <85% overlap → returns None."""
        existing_tags = ["diabetes", "nutrition", "obesity"]
        new_tags = ["malaria", "parasite", "epidemiology", "west africa", "mosquito"]

        existing_image = MagicMock()
        existing_image.id = uuid.uuid4()
        existing_image.status = "ready"
        existing_image.semantic_tags = existing_tags

        session = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [existing_image]
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_mock
        session.execute = AsyncMock(return_value=execute_result)

        service = _make_service(MagicMock(), MagicMock())
        found = await service._find_reusable_image(session, new_tags)

        assert found is None

    async def test_reuse_increments_reuse_count(self):
        """When reusing an image, reuse_count must be incremented."""
        tags = ["malaria", "parasite", "epidemiology", "west africa", "mosquito"]

        existing_image = MagicMock()
        existing_image.id = uuid.uuid4()
        existing_image.status = "ready"
        existing_image.semantic_tags = tags
        existing_image.reuse_count = 3
        existing_image.concept = "malaria"
        existing_image.prompt = "Test prompt"

        anthropic_mock = MagicMock()
        anthropic_mock.messages = MagicMock()
        anthropic_mock.messages.create = AsyncMock(return_value=_concept_response())

        session = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [existing_image]
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_mock
        session.execute = AsyncMock(return_value=execute_result)
        session.commit = AsyncMock()
        session.add = MagicMock()

        service = _make_service(anthropic_mock, MagicMock())
        result_id = await service.run(
            session=session,
            lesson_id=uuid.uuid4(),
            module_id=uuid.uuid4(),
            unit_id="M01-U01",
            lesson_content=LESSON_CONTENT,
        )

        assert result_id == existing_image.id
        assert existing_image.reuse_count == 4


# ---------------------------------------------------------------------------
# Unit tests: new image generation
# ---------------------------------------------------------------------------


class TestNewImageGeneration:
    async def test_calls_dalle_when_no_reuse(self):
        """When no matching image exists → DALL-E API must be called."""
        anthropic_mock = MagicMock()
        anthropic_mock.messages = MagicMock()
        anthropic_mock.messages.create = AsyncMock(
            side_effect=[_concept_response(), _alt_text_response()]
        )

        openai_mock = MagicMock()
        openai_mock.images = MagicMock()
        openai_mock.images.generate = AsyncMock(return_value=_dalle_response())

        session = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_mock
        session.execute = AsyncMock(return_value=execute_result)
        session.add = MagicMock()
        session.commit = AsyncMock()

        service = _make_service(anthropic_mock, openai_mock)
        image_id = await service.run(
            session=session,
            lesson_id=uuid.uuid4(),
            module_id=uuid.uuid4(),
            unit_id="M01-U01",
            lesson_content=LESSON_CONTENT,
        )

        openai_mock.images.generate.assert_called_once()
        assert image_id is not None
        assert isinstance(image_id, uuid.UUID)

    async def test_alt_text_generated_in_fr_and_en(self):
        """Alt-text must be generated in both FR and EN."""
        anthropic_mock = MagicMock()
        anthropic_mock.messages = MagicMock()
        anthropic_mock.messages.create = AsyncMock(
            side_effect=[_concept_response(), _alt_text_response()]
        )

        openai_mock = MagicMock()
        openai_mock.images = MagicMock()
        openai_mock.images.generate = AsyncMock(return_value=_dalle_response())

        session = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_mock
        session.execute = AsyncMock(return_value=execute_result)

        added_records = []
        session.add = MagicMock(side_effect=added_records.append)
        session.commit = AsyncMock()

        service = _make_service(anthropic_mock, openai_mock)
        await service.run(
            session=session,
            lesson_id=uuid.uuid4(),
            module_id=uuid.uuid4(),
            unit_id="M01-U01",
            lesson_content=LESSON_CONTENT,
        )

        assert len(added_records) == 1
        record = added_records[0]
        assert record.alt_text_fr == "Cycle de vie du parasite du paludisme"
        assert record.alt_text_en == "Malaria parasite life cycle"


# ---------------------------------------------------------------------------
# Unit tests: failure handling
# ---------------------------------------------------------------------------


class TestFailureHandling:
    async def test_dalle_failure_sets_status_failed(self):
        """If DALL-E raises an exception → status must be 'failed', not re-raised."""
        anthropic_mock = MagicMock()
        anthropic_mock.messages = MagicMock()
        anthropic_mock.messages.create = AsyncMock(return_value=_concept_response())

        openai_mock = MagicMock()
        openai_mock.images = MagicMock()
        openai_mock.images.generate = AsyncMock(side_effect=Exception("DALL-E quota exceeded"))

        session = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_mock
        session.execute = AsyncMock(return_value=execute_result)

        added_records = []
        session.add = MagicMock(side_effect=added_records.append)
        session.commit = AsyncMock()

        service = _make_service(anthropic_mock, openai_mock)
        image_id = await service.run(
            session=session,
            lesson_id=uuid.uuid4(),
            module_id=uuid.uuid4(),
            unit_id="M01-U01",
            lesson_content=LESSON_CONTENT,
        )

        assert image_id is not None
        assert len(added_records) == 1
        assert added_records[0].status == "failed"


# ---------------------------------------------------------------------------
# Security test: OPENAI_API_KEY never in frontend-accessible code
# ---------------------------------------------------------------------------


class TestSecurityConstraints:
    def test_openai_key_not_in_frontend(self):
        """OPENAI_API_KEY must not appear in any frontend source file."""
        import os

        frontend_root = os.path.join(
            os.path.dirname(__file__), "..", "..", "frontend"
        )
        frontend_root = os.path.abspath(frontend_root)

        if not os.path.isdir(frontend_root):
            pytest.skip("Frontend directory not found")

        forbidden = "OPENAI_API_KEY"
        for dirpath, _dirnames, filenames in os.walk(frontend_root):
            for fname in filenames:
                if fname.endswith((".ts", ".tsx", ".js", ".jsx", ".json")):
                    fpath = os.path.join(dirpath, fname)
                    try:
                        with open(fpath) as f:
                            content = f.read()
                        assert forbidden not in content, (
                            f"{forbidden} found in frontend file: {fpath}"
                        )
                    except (UnicodeDecodeError, OSError):
                        pass
