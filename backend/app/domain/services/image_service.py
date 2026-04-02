"""Service for DALL-E 3 async image generation with semantic reuse (US-025, FR-03.2)."""

from __future__ import annotations

import io
import uuid
from datetime import datetime

import structlog

logger = structlog.get_logger(__name__)

_JACCARD_REUSE_THRESHOLD = 0.85


def _jaccard(tags_a: list[str], tags_b: list[str]) -> float:
    """Compute Jaccard similarity between two tag lists (lowercased)."""
    set_a = {t.lower() for t in tags_a}
    set_b = {t.lower() for t in tags_b}
    if not set_a and not set_b:
        return 1.0
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


class ImageGenerationService:
    """Pipeline: Claude concept extraction → semantic reuse → DALL-E 3 → WebP → alt-text."""

    def __init__(self, anthropic_client, openai_client, settings):
        self._anthropic = anthropic_client
        self._openai = openai_client
        self._settings = settings

    async def run(
        self,
        session,
        lesson_id: uuid.UUID | None,
        module_id: uuid.UUID | None,
        unit_id: str | None,
        lesson_content: str,
    ) -> uuid.UUID:
        """
        Full image generation pipeline.

        Returns the UUID of the GeneratedImage record (new or reused).
        """
        from app.domain.models.generated_image import GeneratedImage
        from sqlalchemy import select

        concept, prompt, tags = await self._extract_concept_and_tags(lesson_content)

        logger.info(
            "Extracted concept for image generation",
            concept=concept,
            tags=tags,
            lesson_id=str(lesson_id) if lesson_id else None,
        )

        existing = await self._find_reusable_image(session, tags)
        if existing is not None:
            existing.reuse_count = (existing.reuse_count or 0) + 1
            await session.commit()
            logger.info(
                "Reusing existing image",
                image_id=str(existing.id),
                reuse_count=existing.reuse_count,
            )
            return existing.id

        record = GeneratedImage(
            id=uuid.uuid4(),
            lesson_id=lesson_id,
            module_id=module_id,
            unit_id=unit_id,
            concept=concept,
            prompt=prompt,
            semantic_tags=tags,
            status="generating",
        )
        session.add(record)
        await session.commit()

        try:
            image_url, file_size = await self._generate_dalle_image(prompt)
            alt_fr, alt_en = await self._generate_alt_text(concept, tags)

            record.image_url = image_url
            record.alt_text_fr = alt_fr
            record.alt_text_en = alt_en
            record.file_size_bytes = file_size
            record.status = "ready"
            record.generated_at = datetime.utcnow()
        except Exception as exc:
            logger.error(
                "DALL-E generation failed",
                error=str(exc),
                image_id=str(record.id),
            )
            record.status = "failed"

        await session.commit()
        return record.id

    async def _extract_concept_and_tags(
        self, lesson_content: str
    ) -> tuple[str, str, list[str]]:
        """Use Claude to extract the key concept and generate DALL-E prompt + semantic tags."""
        truncated = lesson_content[:3000]
        response = await self._anthropic.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=512,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "From the following public health lesson extract:\n"
                        "1. The single most important visual concept (≤8 words)\n"
                        "2. A DALL-E image prompt (1 sentence, educational illustration, West African context)\n"
                        "3. 5-8 semantic tags (single lowercase words or short phrases)\n\n"
                        "Reply ONLY as JSON: "
                        '{"concept": "...", "prompt": "...", "tags": ["tag1", "tag2", ...]}\n\n'
                        f"Lesson content:\n{truncated}"
                    ),
                }
            ],
        )
        import json

        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        data = json.loads(text)
        concept = str(data.get("concept", "public health concept"))
        prompt = str(data.get("prompt", f"Educational illustration of {concept}"))
        tags = [str(t) for t in data.get("tags", [])]
        return concept, prompt, tags

    async def _find_reusable_image(self, session, tags: list[str]):
        """Search generated_images for a record with ≥85% Jaccard tag overlap."""
        from app.domain.models.generated_image import GeneratedImage
        from sqlalchemy import select

        result = await session.execute(
            select(GeneratedImage).where(GeneratedImage.status == "ready")
        )
        candidates = result.scalars().all()

        for img in candidates:
            if not img.semantic_tags:
                continue
            similarity = _jaccard(tags, img.semantic_tags)
            if similarity >= _JACCARD_REUSE_THRESHOLD:
                logger.info(
                    "Semantic reuse candidate found",
                    image_id=str(img.id),
                    similarity=round(similarity, 3),
                )
                return img
        return None

    async def _generate_dalle_image(self, prompt: str) -> tuple[str, int]:
        """Call DALL-E 3 API and return (image_url, file_size_bytes)."""
        response = await self._openai.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size="512x512",
            quality="standard",
            n=1,
            response_format="url",
        )
        image_url = response.data[0].url
        file_size = 0
        return image_url, file_size

    async def _generate_alt_text(
        self, concept: str, tags: list[str]
    ) -> tuple[str, str]:
        """Generate bilingual alt-text for accessibility."""
        tags_str = ", ".join(tags[:5])
        response = await self._anthropic.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=200,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f'Generate short alt-text (≤15 words each) for a medical illustration of "{concept}" '
                        f"(tags: {tags_str}).\n"
                        'Reply ONLY as JSON: {"fr": "...", "en": "..."}'
                    ),
                }
            ],
        )
        import json

        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        data = json.loads(text)
        return str(data.get("fr", concept)), str(data.get("en", concept))
