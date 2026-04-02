"""Service for async DALL-E 3 image generation with semantic reuse (US-025, FR-03.2)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.generated_image import GeneratedImage
from app.infrastructure.config.settings import settings

if TYPE_CHECKING:
    pass

logger = structlog.get_logger(__name__)

_REUSE_THRESHOLD = 0.85


def _jaccard_similarity(tags_a: list, tags_b: list) -> float:
    """Compute Jaccard coefficient between two tag lists."""
    set_a = {str(t).lower() for t in tags_a}
    set_b = {str(t).lower() for t in tags_b}
    if not set_a and not set_b:
        return 1.0
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union


class ImageGenerationService:
    """Orchestrates DALL-E 3 image generation with semantic reuse."""

    async def generate_image_for_lesson(
        self,
        lesson_id: uuid.UUID,
        module_id: uuid.UUID,
        unit_id: str,
        lesson_content: str,
        session: AsyncSession,
    ) -> GeneratedImage:
        """
        Main entry point: extract concept, check reuse, generate or reuse image.

        Status transitions: pending → generating → ready | failed
        """
        record = GeneratedImage(
            id=uuid.uuid4(),
            lesson_id=lesson_id,
            module_id=module_id,
            unit_id=unit_id,
            status="pending",
        )
        session.add(record)
        await session.flush()

        try:
            record.status = "generating"
            await session.flush()

            dalle_prompt, semantic_tags, concept = await self._extract_concept_and_tags(
                lesson_content
            )
            record.prompt = dalle_prompt
            record.concept = concept
            record.semantic_tags = semantic_tags
            await session.flush()

            reusable = await self._find_reusable_image(semantic_tags, record.id, session)
            if reusable:
                reusable.reuse_count = (reusable.reuse_count or 0) + 1
                reusable.lesson_id = lesson_id
                record.status = "failed"
                await session.commit()
                logger.info(
                    "Reusing existing image",
                    reused_image_id=str(reusable.id),
                    lesson_id=str(lesson_id),
                )
                return reusable

            image_url = await self._call_dalle(dalle_prompt)

            alt_fr, alt_en = await self._generate_alt_text(dalle_prompt)

            record.image_url = image_url
            record.alt_text_fr = alt_fr
            record.alt_text_en = alt_en
            record.status = "ready"
            record.generated_at = datetime.now(tz=timezone.utc)
            await session.commit()

            logger.info(
                "Image generated successfully",
                image_id=str(record.id),
                lesson_id=str(lesson_id),
                tags=semantic_tags,
            )
            return record

        except Exception as exc:
            logger.error(
                "Image generation failed",
                lesson_id=str(lesson_id),
                error=str(exc),
            )
            record.status = "failed"
            await session.commit()
            return record

    async def _extract_concept_and_tags(
        self, lesson_content: str
    ) -> tuple[str, list, str]:
        """Use Claude to extract key concept and generate DALL-E prompt + semantic tags."""
        import json

        import anthropic

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

        system = (
            "You are an educational illustration specialist for West African public health. "
            "Given lesson content, extract the key concept and produce:\n"
            "1. A DALL-E 3 prompt (max 200 chars) for a clear, culturally appropriate illustration\n"
            "2. 5-10 semantic tags (lowercase English keywords)\n"
            "3. A short concept name (3-6 words)\n\n"
            "Respond ONLY in this exact JSON format:\n"
            '{"prompt": "...", "tags": ["tag1", "tag2", ...], "concept": "..."}'
        )
        snippet = lesson_content[:2000]
        message = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=256,
            messages=[{"role": "user", "content": f"Lesson content:\n{snippet}"}],
            system=system,
        )
        raw = message.content[0].text.strip()
        data = json.loads(raw)
        return data["prompt"], [t.lower() for t in data["tags"]], data.get("concept", "")

    async def _find_reusable_image(
        self,
        semantic_tags: list,
        exclude_id: uuid.UUID,
        session: AsyncSession,
    ) -> GeneratedImage | None:
        """Search ready images for ≥85% Jaccard overlap on semantic tags."""
        result = await session.execute(
            select(GeneratedImage).where(
                GeneratedImage.status == "ready",
                GeneratedImage.id != exclude_id,
                GeneratedImage.semantic_tags.isnot(None),
            )
        )
        candidates = result.scalars().all()
        for candidate in candidates:
            if not candidate.semantic_tags:
                continue
            similarity = _jaccard_similarity(semantic_tags, candidate.semantic_tags)
            if similarity >= _REUSE_THRESHOLD:
                return candidate
        return None

    async def _call_dalle(self, prompt: str) -> str:
        """Call DALL-E 3 API and return image URL."""
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key)
        response = client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size="1024x1024",
            quality="standard",
            n=1,
            response_format="url",
        )
        return response.data[0].url

    async def _generate_alt_text(self, dalle_prompt: str) -> tuple[str, str]:
        """Generate bilingual alt-text (FR and EN) for accessibility."""
        import json

        import anthropic

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

        system = (
            "Generate concise alt-text descriptions for a public health illustration. "
            "Respond ONLY in this exact JSON format:\n"
            '{"alt_fr": "...", "alt_en": "..."}'
        )
        message = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=128,
            messages=[
                {
                    "role": "user",
                    "content": f"DALL-E prompt: {dalle_prompt}",
                }
            ],
            system=system,
        )
        raw = message.content[0].text.strip()
        data = json.loads(raw)
        return data["alt_fr"], data["alt_en"]
