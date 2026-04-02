"""Tests for DALL-E 3 async image generation pipeline (US-025, FR-03.2)."""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.generated_image import GeneratedImage
from app.domain.services.image_service import ImageGenerationService, _jaccard_similarity


def test_jaccard_similarity_identical():
    assert _jaccard_similarity(["malaria", "prevention"], ["malaria", "prevention"]) == 1.0


def test_jaccard_similarity_no_overlap():
    assert _jaccard_similarity(["malaria"], ["cholera"]) == 0.0


def test_jaccard_similarity_partial():
    result = _jaccard_similarity(["a", "b", "c"], ["b", "c", "d"])
    assert abs(result - 0.5) < 1e-9


def test_jaccard_similarity_empty_both():
    assert _jaccard_similarity([], []) == 1.0


def test_jaccard_similarity_one_empty():
    assert _jaccard_similarity([], ["malaria"]) == 0.0


def test_jaccard_similarity_case_insensitive():
    assert _jaccard_similarity(["Malaria", "Prevention"], ["malaria", "prevention"]) == 1.0


@pytest.fixture
def image_service():
    return ImageGenerationService()


@pytest.fixture
def mock_session():
    session = AsyncMock(spec=AsyncSession)
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.add = MagicMock()
    return session


def _make_anthropic_response(payload: dict) -> MagicMock:
    block = MagicMock()
    block.text = json.dumps(payload)
    msg = MagicMock()
    msg.content = [block]
    return msg


def _make_ready_image(tags: list) -> GeneratedImage:
    img = GeneratedImage(
        id=uuid.uuid4(),
        module_id=uuid.uuid4(),
        unit_id="M01-U01",
        status="ready",
        semantic_tags=tags,
        alt_text_fr="Alt FR",
        alt_text_en="Alt EN",
        reuse_count=0,
    )
    return img


@pytest.mark.asyncio
async def test_semantic_reuse_found(image_service, mock_session):
    """When an existing image has ≥85% tag overlap, it should be reused (no DALL-E call)."""
    tags = ["malaria", "prevention", "africa", "mosquito", "bed net"]
    existing = _make_ready_image(tags)

    mock_session.execute = AsyncMock(
        return_value=MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[existing])))
        )
    )

    claude_resp_concept = _make_anthropic_response(
        {"prompt": "A mosquito net over a bed in Africa", "tags": tags, "concept": "malaria prevention"}
    )

    with patch("anthropic.Anthropic") as mock_anthropic_cls:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = claude_resp_concept
        mock_anthropic_cls.return_value = mock_client

        result = await image_service.generate_image_for_lesson(
            lesson_id=uuid.uuid4(),
            module_id=uuid.uuid4(),
            unit_id="M01-U01",
            lesson_content="Malaria prevention using bed nets in Africa.",
            session=mock_session,
        )

    assert result.id == existing.id
    assert existing.reuse_count == 1


@pytest.mark.asyncio
async def test_new_generation_when_no_reusable_image(image_service, mock_session):
    """When no reusable image exists, DALL-E 3 should be called and URL saved."""
    mock_session.execute = AsyncMock(
        return_value=MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        )
    )

    tags = ["cholera", "water", "sanitation"]
    claude_resp_concept = _make_anthropic_response(
        {"prompt": "Clean water access in rural Senegal", "tags": tags, "concept": "water sanitation"}
    )
    claude_resp_alt = _make_anthropic_response(
        {"alt_fr": "Accès à l'eau potable", "alt_en": "Access to clean water"}
    )
    fake_url = "https://oaidalleapiprodscus.blob.core.windows.net/image.png"

    with (
        patch("anthropic.Anthropic") as mock_anthropic_cls,
        patch("openai.OpenAI") as mock_openai_cls,
    ):
        mock_claude = MagicMock()
        mock_claude.messages.create.side_effect = [claude_resp_concept, claude_resp_alt]
        mock_anthropic_cls.return_value = mock_claude

        mock_openai = MagicMock()
        mock_image_data = MagicMock()
        mock_image_data.url = fake_url
        mock_openai.images.generate.return_value = MagicMock(data=[mock_image_data])
        mock_openai_cls.return_value = mock_openai

        result = await image_service.generate_image_for_lesson(
            lesson_id=uuid.uuid4(),
            module_id=uuid.uuid4(),
            unit_id="M01-U01",
            lesson_content="Cholera prevention through clean water in Senegal.",
            session=mock_session,
        )

    assert result.status == "ready"
    assert result.image_url == fake_url
    assert result.alt_text_fr == "Accès à l'eau potable"
    assert result.alt_text_en == "Access to clean water"
    assert mock_openai.images.generate.called


@pytest.mark.asyncio
async def test_failure_handling_dalle_error(image_service, mock_session):
    """When DALL-E raises an exception, status must be set to 'failed'."""
    mock_session.execute = AsyncMock(
        return_value=MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        )
    )

    tags = ["epidemic", "outbreak"]
    claude_resp_concept = _make_anthropic_response(
        {"prompt": "Disease outbreak response team", "tags": tags, "concept": "epidemic response"}
    )

    with (
        patch("anthropic.Anthropic") as mock_anthropic_cls,
        patch("openai.OpenAI") as mock_openai_cls,
    ):
        mock_claude = MagicMock()
        mock_claude.messages.create.return_value = claude_resp_concept
        mock_anthropic_cls.return_value = mock_claude

        mock_openai = MagicMock()
        mock_openai.images.generate.side_effect = Exception("OpenAI API Error")
        mock_openai_cls.return_value = mock_openai

        result = await image_service.generate_image_for_lesson(
            lesson_id=uuid.uuid4(),
            module_id=uuid.uuid4(),
            unit_id="M01-U02",
            lesson_content="Epidemic response strategies.",
            session=mock_session,
        )

    assert result.status == "failed"
    assert mock_session.commit.called


@pytest.mark.asyncio
async def test_alt_text_generated_in_fr_and_en(image_service, mock_session):
    """Alt-text must be produced in both FR and EN."""
    mock_session.execute = AsyncMock(
        return_value=MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        )
    )

    tags = ["vaccination", "child", "health"]
    claude_resp_concept = _make_anthropic_response(
        {"prompt": "Child vaccination campaign in West Africa", "tags": tags, "concept": "child vaccination"}
    )
    claude_resp_alt = _make_anthropic_response(
        {
            "alt_fr": "Campagne de vaccination infantile en Afrique de l'Ouest",
            "alt_en": "Child vaccination campaign in West Africa",
        }
    )
    fake_url = "https://example.com/vax.png"

    with (
        patch("anthropic.Anthropic") as mock_anthropic_cls,
        patch("openai.OpenAI") as mock_openai_cls,
    ):
        mock_claude = MagicMock()
        mock_claude.messages.create.side_effect = [claude_resp_concept, claude_resp_alt]
        mock_anthropic_cls.return_value = mock_claude

        mock_openai = MagicMock()
        mock_image_data = MagicMock()
        mock_image_data.url = fake_url
        mock_openai.images.generate.return_value = MagicMock(data=[mock_image_data])
        mock_openai_cls.return_value = mock_openai

        result = await image_service.generate_image_for_lesson(
            lesson_id=uuid.uuid4(),
            module_id=uuid.uuid4(),
            unit_id="M01-U03",
            lesson_content="Child vaccination programs across ECOWAS.",
            session=mock_session,
        )

    assert result.alt_text_fr is not None
    assert result.alt_text_en is not None
    assert "vaccination" in result.alt_text_fr.lower() or "campagne" in result.alt_text_fr.lower()
    assert "vaccination" in result.alt_text_en.lower()


def test_openai_api_key_not_in_frontend():
    """OPENAI_API_KEY must not appear in any frontend-accessible code."""
    import os

    frontend_dir = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
    if not os.path.isdir(frontend_dir):
        pytest.skip("frontend directory not found")

    found_files = []
    for root, dirs, files in os.walk(frontend_dir):
        dirs[:] = [d for d in dirs if d not in ("node_modules", ".next", ".git")]
        for filename in files:
            if filename.endswith((".ts", ".tsx", ".js", ".jsx", ".json")):
                filepath = os.path.join(root, filename)
                try:
                    with open(filepath, encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    if "OPENAI_API_KEY" in content and "NEXT_PUBLIC_" not in content:
                        found_files.append(filepath)
                except OSError:
                    pass

    def _has_public_key(path: str) -> bool:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            return "NEXT_PUBLIC_OPENAI_API_KEY" in fh.read()

    client_exposing = [f for f in found_files if _has_public_key(f)]
    assert not client_exposing, f"OPENAI_API_KEY exposed to client in: {client_exposing}"
