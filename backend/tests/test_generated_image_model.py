"""Unit tests for the GeneratedImage model (issue #222)."""

import uuid

import pytest

from app.domain.models.generated_image import GeneratedImage, ImageStatus


class TestGeneratedImageModel:
    def test_instantiation_with_minimal_fields(self):
        img = GeneratedImage(id=uuid.uuid4())
        assert img.id is not None

    def test_instantiation_with_all_fields(self):
        img = GeneratedImage(
            id=uuid.uuid4(),
            lesson_id=uuid.uuid4(),
            module_id=uuid.uuid4(),
            unit_id="1.2",
            concept="paludisme",
            prompt="Illustrate malaria transmission in West Africa",
            image_url="images/abc123.webp",
            format="webp",
            width=512,
            alt_text_fr="Cycle de transmission du paludisme",
            alt_text_en="Malaria transmission cycle",
            semantic_tags=["épidémiologie", "paludisme", "AOF"],
            reuse_count=0,
            status=ImageStatus.pending,
            file_size_bytes=40960,
        )
        assert img.concept == "paludisme"
        assert img.format == "webp"
        assert img.width == 512

    def test_status_enum_values(self):
        assert ImageStatus.pending == "pending"
        assert ImageStatus.generating == "generating"
        assert ImageStatus.ready == "ready"
        assert ImageStatus.failed == "failed"

    def test_status_field_accepts_enum(self):
        img = GeneratedImage(id=uuid.uuid4(), status=ImageStatus.ready)
        assert img.status == ImageStatus.ready

    def test_status_field_accepts_string(self):
        img = GeneratedImage(id=uuid.uuid4(), status=ImageStatus("generating"))
        assert img.status == ImageStatus.generating

    def test_semantic_tags_accepts_list_of_strings(self):
        tags = ["épidémiologie", "paludisme", "AOF", "Sénégal"]
        img = GeneratedImage(id=uuid.uuid4(), semantic_tags=tags)
        assert img.semantic_tags == tags
        assert isinstance(img.semantic_tags, list)
        assert all(isinstance(t, str) for t in img.semantic_tags)

    def test_semantic_tags_accepts_none(self):
        img = GeneratedImage(id=uuid.uuid4(), semantic_tags=None)
        assert img.semantic_tags is None

    def test_semantic_tags_accepts_empty_list(self):
        img = GeneratedImage(id=uuid.uuid4(), semantic_tags=[])
        assert img.semantic_tags == []

    def test_nullable_fk_fields(self):
        img = GeneratedImage(id=uuid.uuid4())
        assert img.lesson_id is None
        assert img.module_id is None

    def test_uuid_pk_uniqueness(self):
        ids = {GeneratedImage(id=uuid.uuid4()).id for _ in range(100)}
        assert len(ids) == 100

    def test_invalid_status_raises(self):
        with pytest.raises(ValueError):
            ImageStatus("unknown_status")
