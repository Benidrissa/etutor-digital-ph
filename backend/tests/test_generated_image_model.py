"""Tests for GeneratedImage model — AI-generated lesson illustrations with semantic metadata."""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from app.domain.models.generated_image import GeneratedImage


def _make_image(**kwargs) -> GeneratedImage:
    defaults = {
        "id": uuid.uuid4(),
        "lesson_id": None,
        "module_id": None,
        "unit_id": None,
        "concept": None,
        "prompt": None,
        "image_url": None,
        "format": "webp",
        "width": 512,
        "alt_text_fr": None,
        "alt_text_en": None,
        "semantic_tags": None,
        "reuse_count": 0,
        "status": "pending",
        "generated_at": None,
        "file_size_bytes": None,
    }
    defaults.update(kwargs)
    return GeneratedImage(**defaults)


class TestGeneratedImageInstantiation:
    def test_create_with_minimal_fields(self):
        image = _make_image()
        assert isinstance(image.id, uuid.UUID)
        assert image.format == "webp"
        assert image.width == 512
        assert image.reuse_count == 0
        assert image.status == "pending"

    def test_create_with_all_fields(self):
        lesson_id = uuid.uuid4()
        module_id = uuid.uuid4()
        now = datetime.utcnow()
        image = _make_image(
            lesson_id=lesson_id,
            module_id=module_id,
            unit_id="u01",
            concept="paludisme",
            prompt="Illustration du cycle de vie du parasite du paludisme en Afrique de l'Ouest",
            image_url="https://cdn.example.com/images/malaria-cycle.webp",
            format="webp",
            width=512,
            alt_text_fr="Cycle de vie du parasite du paludisme",
            alt_text_en="Malaria parasite life cycle",
            semantic_tags=["épidémiologie", "paludisme", "AOF"],
            reuse_count=3,
            status="ready",
            generated_at=now,
            file_size_bytes=48200,
        )
        assert image.lesson_id == lesson_id
        assert image.module_id == module_id
        assert image.unit_id == "u01"
        assert image.concept == "paludisme"
        assert image.image_url == "https://cdn.example.com/images/malaria-cycle.webp"
        assert image.alt_text_fr == "Cycle de vie du parasite du paludisme"
        assert image.alt_text_en == "Malaria parasite life cycle"
        assert image.reuse_count == 3
        assert image.status == "ready"
        assert image.generated_at == now
        assert image.file_size_bytes == 48200

    def test_default_format_is_webp(self):
        image = _make_image()
        assert image.format == "webp"

    def test_default_width_is_512(self):
        image = _make_image()
        assert image.width == 512

    def test_default_reuse_count_is_zero(self):
        image = _make_image()
        assert image.reuse_count == 0

    def test_default_status_is_pending(self):
        image = _make_image()
        assert image.status == "pending"


class TestSemanticTags:
    def test_semantic_tags_accepts_list_of_strings(self):
        tags = ["épidémiologie", "paludisme", "AOF", "Sénégal"]
        image = _make_image(semantic_tags=tags)
        assert image.semantic_tags == tags

    def test_semantic_tags_can_be_none(self):
        image = _make_image(semantic_tags=None)
        assert image.semantic_tags is None

    def test_semantic_tags_accepts_empty_list(self):
        image = _make_image(semantic_tags=[])
        assert image.semantic_tags == []

    def test_semantic_tags_accepts_mixed_language_tags(self):
        tags = ["épidémiologie", "epidemiology", "malaria", "paludisme"]
        image = _make_image(semantic_tags=tags)
        assert len(image.semantic_tags) == 4


class TestStatusValues:
    @pytest.mark.parametrize("status", ["pending", "generating", "ready", "failed"])
    def test_all_valid_status_values(self, status: str):
        image = _make_image(status=status)
        assert image.status == status


class TestForeignKeys:
    def test_lesson_id_can_be_none(self):
        image = _make_image(lesson_id=None)
        assert image.lesson_id is None

    def test_module_id_can_be_none(self):
        image = _make_image(module_id=None)
        assert image.module_id is None

    def test_lesson_id_accepts_uuid(self):
        lesson_id = uuid.uuid4()
        image = _make_image(lesson_id=lesson_id)
        assert image.lesson_id == lesson_id

    def test_module_id_accepts_uuid(self):
        module_id = uuid.uuid4()
        image = _make_image(module_id=module_id)
        assert image.module_id == module_id
