"""Service for AI-generated lesson illustrations using gpt-image-1 with semantic reuse."""

from __future__ import annotations

import io
import uuid
from datetime import datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.generated_image import GeneratedImage
from app.domain.models.source_image import SourceImage, SourceImageChunk
from app.infrastructure.config.settings import settings

logger = structlog.get_logger(__name__)

SEMANTIC_REUSE_THRESHOLD = 0.85


def _jaccard_similarity(tags_a: list[str], tags_b: list[str]) -> float:
    """Compute Jaccard coefficient between two tag lists (case-insensitive)."""
    set_a = {t.lower() for t in tags_a}
    set_b = {t.lower() for t in tags_b}
    if not set_a and not set_b:
        return 1.0
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


class ImageGenerationService:
    """Pipeline: concept extraction → semantic reuse → gpt-image-1 → WebP → bilingual alt-text."""

    async def generate_for_lesson(
        self,
        lesson_id: uuid.UUID,
        module_id: uuid.UUID,
        unit_id: str,
        lesson_content: str,
        session: AsyncSession,
    ) -> GeneratedImage:
        """Generate or reuse an image for a lesson.

        Status transitions: pending → generating → ready | failed
        """
        image_record = GeneratedImage(
            id=uuid.uuid4(),
            lesson_id=lesson_id,
            module_id=module_id,
            unit_id=unit_id,
            status="pending",
        )
        session.add(image_record)
        await session.flush()

        try:
            concept, prompt, tags = await self._extract_concept_and_tags(lesson_content)
            image_record.concept = concept
            image_record.prompt = prompt
            image_record.semantic_tags = tags

            reusable = await self._find_reusable_image(tags, session)
            if reusable is not None:
                reusable.reuse_count = (reusable.reuse_count or 0) + 1
                image_record.status = "ready"
                image_record.image_url = f"/api/v1/images/{image_record.id}/data"
                image_record.image_data = reusable.image_data
                image_record.alt_text_fr = reusable.alt_text_fr
                image_record.alt_text_en = reusable.alt_text_en
                image_record.width = reusable.width
                image_record.format = reusable.format
                image_record.file_size_bytes = reusable.file_size_bytes
                image_record.generated_at = datetime.utcnow()
                await session.commit()
                logger.info(
                    "Reused existing image",
                    reused_from=str(reusable.id),
                    lesson_id=str(lesson_id),
                )
                return image_record

            source_img = await self._find_source_image(lesson_id, session)
            if source_img is not None:
                image_record.status = "ready"
                image_record.image_url = (
                    source_img.storage_url or f"/api/v1/source-images/{source_img.id}/data"
                )
                image_record.alt_text_fr = source_img.alt_text_fr or (
                    f"Figure {source_img.figure_number}" if source_img.figure_number else concept
                )
                image_record.alt_text_en = source_img.alt_text_en or (
                    f"Figure {source_img.figure_number}" if source_img.figure_number else concept
                )
                image_record.width = source_img.width or 512
                image_record.format = source_img.format or "webp"
                image_record.file_size_bytes = source_img.file_size_bytes
                image_record.generated_at = datetime.utcnow()
                await session.commit()
                logger.info(
                    "Skipping DALL-E — source image found: Figure %s",
                    source_img.figure_number or str(source_img.id),
                    lesson_id=str(lesson_id),
                    source_image_id=str(source_img.id),
                )
                return image_record

            image_record.status = "generating"
            await session.flush()

            image_bytes, image_url = await self._call_dalle(prompt)
            webp_bytes, width = _resize_to_webp(image_bytes, max_width=512)

            alt_fr, alt_en = await self._generate_alt_text(concept)

            image_record.status = "ready"
            image_record.image_url = f"/api/v1/images/{image_record.id}/data"
            image_record.image_data = webp_bytes
            image_record.alt_text_fr = alt_fr
            image_record.alt_text_en = alt_en
            image_record.width = width
            image_record.format = "webp"
            image_record.file_size_bytes = len(webp_bytes)
            image_record.generated_at = datetime.utcnow()
            await session.commit()

            logger.info(
                "Generated new image",
                lesson_id=str(lesson_id),
                concept=concept,
                width=width,
            )
            return image_record

        except Exception as exc:
            image_record.status = "failed"
            await session.commit()
            logger.error(
                "Image generation failed",
                lesson_id=str(lesson_id),
                error=str(exc),
            )
            return image_record

    async def _extract_concept_and_tags(self, lesson_content: str) -> tuple[str, str, list[str]]:
        """Use Claude API to extract key concept, DALL-E prompt, and semantic tags."""
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key, timeout=600.0)

        system = (
            "You are an expert in public health education for West Africa. "
            "Given lesson content, extract: "
            "1) A short key concept (5 words max), "
            "2) A vivid image generation prompt that follows these STRICT rules:\n"
            "   - NEVER include any text, words, labels, numbers, letters, captions, or titles in the image\n"
            "   - Focus on visual metaphors, diagrams without text, people, scenes, objects\n"
            "   - Style: clean flat illustration, infographic style, vibrant colors, educational\n"
            "   - Context: West African setting, diverse people, health facilities\n"
            "   - Max 120 chars\n"
            "   - Examples of GOOD prompts: 'African health worker examining patient in rural clinic, stethoscope, colorful flat illustration'\n"
            "   - Examples of BAD prompts: 'Chart showing mortality rates with labels and percentages'\n"
            "3) A JSON array of 5-8 lowercase semantic tags. "
            "Reply ONLY in this exact format:\n"
            "CONCEPT: <concept>\n"
            "PROMPT: <image_prompt>\n"
            "TAGS: <json_array>"
        )

        message = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=300,
            messages=[
                {
                    "role": "user",
                    "content": f"Lesson content:\n{lesson_content[:2000]}",
                }
            ],
            system=system,
        )

        text = message.content[0].text if message.content else ""
        return _parse_concept_response(text)

    async def _find_source_image(
        self, lesson_id: uuid.UUID, session: AsyncSession
    ) -> SourceImage | None:
        """Check if any source images are explicitly linked to the lesson's document chunks.

        Returns the first SourceImage with image_type in ('diagram', 'chart', 'photo')
        that is explicitly linked to a document chunk via the lesson's generated content.
        """
        from app.domain.models.content import GeneratedContent

        lesson = await session.get(GeneratedContent, lesson_id)
        if lesson is None or not lesson.sources_cited:
            return None

        sources = [
            s.get("source") for s in lesson.sources_cited if isinstance(s, dict) and s.get("source")
        ]
        if not sources:
            return None

        result = await session.execute(
            select(SourceImage)
            .join(SourceImageChunk, SourceImageChunk.source_image_id == SourceImage.id)
            .where(
                SourceImage.source.in_(sources),
                SourceImage.image_type.in_(["diagram", "chart", "photo"]),
                SourceImageChunk.reference_type == "explicit",
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _find_reusable_image(
        self, tags: list[str], session: AsyncSession
    ) -> GeneratedImage | None:
        """Search generated_images for an existing ready image with ≥85% tag overlap."""
        result = await session.execute(
            select(GeneratedImage).where(GeneratedImage.status == "ready")
        )
        candidates = result.scalars().all()

        for candidate in candidates:
            if not candidate.semantic_tags:
                continue
            similarity = _jaccard_similarity(tags, candidate.semantic_tags)
            if similarity >= SEMANTIC_REUSE_THRESHOLD:
                return candidate
        return None

    async def _call_dalle(self, prompt: str) -> tuple[bytes, str]:
        """Call OpenAI gpt-image-1 API and return (image_bytes, image_url)."""
        import base64

        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=settings.openai_api_key)

        no_text_suffix = " I NEED this image to contain absolutely NO text, letters, numbers, or written words anywhere."
        final_prompt = prompt + no_text_suffix

        response = await client.images.generate(
            model="gpt-image-1",
            prompt=final_prompt,
            size="1024x1024",
            quality="low",
        )

        image_bytes = base64.b64decode(response.data[0].b64_json)
        image_url = f"gpt-image-1://{id(response)}"

        return image_bytes, image_url

    async def _generate_alt_text(self, concept: str) -> tuple[str, str]:
        """Generate bilingual alt-text for the image."""
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key, timeout=600.0)

        message = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=100,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Write a short accessibility alt-text for an educational illustration "
                        f"about '{concept}' for West African public health students.\n"
                        "Reply in this exact format:\n"
                        "FR: <alt text in French, max 15 words>\n"
                        "EN: <alt text in English, max 15 words>"
                    ),
                }
            ],
        )

        text = message.content[0].text if message.content else ""
        return _parse_alt_text(text, concept)


def _parse_concept_response(text: str) -> tuple[str, str, list[str]]:
    """Parse Claude's structured response into (concept, prompt, tags)."""
    import json
    import re

    concept = ""
    prompt = ""
    tags: list[str] = []

    for line in text.splitlines():
        line = line.strip()
        if line.startswith("CONCEPT:"):
            concept = line[len("CONCEPT:") :].strip()
        elif line.startswith("PROMPT:"):
            prompt = line[len("PROMPT:") :].strip()
        elif line.startswith("TAGS:"):
            raw = line[len("TAGS:") :].strip()
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    tags = [str(t).lower() for t in parsed]
            except (json.JSONDecodeError, ValueError):
                tags = re.findall(r'"([^"]+)"', raw)

    if not concept:
        concept = "public health"
    if not prompt:
        prompt = f"Educational illustration of {concept} for West African public health"
    if not tags:
        tags = [concept.lower()]

    return concept, prompt, tags


def _parse_alt_text(text: str, concept: str) -> tuple[str, str]:
    """Parse Claude's alt-text response into (fr, en)."""
    alt_fr = f"Illustration éducative sur {concept}"
    alt_en = f"Educational illustration about {concept}"

    for line in text.splitlines():
        line = line.strip()
        if line.startswith("FR:"):
            alt_fr = line[3:].strip()
        elif line.startswith("EN:"):
            alt_en = line[3:].strip()

    return alt_fr, alt_en


def _resize_to_webp(image_bytes: bytes, max_width: int = 512) -> tuple[bytes, int]:
    """Convert image bytes to WebP format, skipping resize if already at target width."""
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        if img.width > max_width:
            ratio = max_width / img.width
            new_height = int(img.height * ratio)
            img = img.resize((max_width, new_height), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="WEBP", quality=85)
        return buf.getvalue(), img.width
    except (ImportError, Exception):
        return image_bytes, max_width
