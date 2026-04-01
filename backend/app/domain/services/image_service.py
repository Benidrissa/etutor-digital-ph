"""Service for async DALL-E 3 image generation with semantic reuse (US-025, FR-03.2)."""

import io
import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.image import GeneratedImage
from app.infrastructure.config.settings import settings

logger = structlog.get_logger(__name__)

SEMANTIC_REUSE_THRESHOLD = 0.85


class ImageGenerationService:
    """Service for generating lesson illustrations using DALL-E 3 with semantic reuse."""

    async def extract_concept_and_tags(
        self,
        lesson_content: str,
        lesson_id: uuid.UUID,
        module_id: uuid.UUID,
        unit_id: str,
    ) -> tuple[str, str, list[str]]:
        """
        Use Claude API to extract key concept, generate DALL-E prompt, and semantic tags.

        Returns:
            Tuple of (key_concept, dalle_prompt, semantic_tags)
        """
        import anthropic

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

        system_prompt = (
            "You are an expert at extracting visual concepts from public health educational content "
            "for West African learners. Your task is to:\n"
            "1. Identify the single most important visual concept in the lesson\n"
            "2. Write a DALL-E 3 prompt for an educational illustration (no text in image, "
            "culturally appropriate for West Africa, medical/health context)\n"
            "3. Generate 5-10 semantic tags describing the concept\n\n"
            "Respond ONLY with valid JSON in this exact format:\n"
            '{"key_concept": "...", "dalle_prompt": "...", "semantic_tags": ["tag1", "tag2", ...]}'
        )

        excerpt = lesson_content[:3000] if len(lesson_content) > 3000 else lesson_content
        user_message = (
            f"Extract the key visual concept from this public health lesson:\n\n{excerpt}"
        )

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=512,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )

        import json

        content_text = ""
        for block in response.content:
            if hasattr(block, "text"):
                content_text += block.text

        data = json.loads(content_text)
        return data["key_concept"], data["dalle_prompt"], data["semantic_tags"]

    async def find_reusable_image(
        self,
        semantic_tags: list[str],
        session: AsyncSession,
    ) -> GeneratedImage | None:
        """
        Search generated_images for an existing image with >= 85% semantic tag overlap.

        Returns:
            Matching GeneratedImage record or None
        """
        if not semantic_tags:
            return None

        query = select(GeneratedImage).where(
            GeneratedImage.status == "ready",
            GeneratedImage.semantic_tags.isnot(None),
        )
        result = await session.execute(query)
        candidates = result.scalars().all()

        tags_set = set(t.lower() for t in semantic_tags)

        best_match: GeneratedImage | None = None
        best_overlap = 0.0

        for candidate in candidates:
            if not candidate.semantic_tags:
                continue
            candidate_set = set(t.lower() for t in candidate.semantic_tags)
            union = tags_set | candidate_set
            if not union:
                continue
            intersection = tags_set & candidate_set
            overlap = len(intersection) / len(union)
            if overlap >= SEMANTIC_REUSE_THRESHOLD and overlap > best_overlap:
                best_overlap = overlap
                best_match = candidate

        if best_match:
            logger.info(
                "Found reusable image",
                image_id=str(best_match.id),
                overlap=best_overlap,
            )

        return best_match

    async def generate_alt_text(
        self,
        key_concept: str,
        dalle_prompt: str,
    ) -> tuple[str, str]:
        """
        Generate accessibility alt-text in French and English using Claude API.

        Returns:
            Tuple of (alt_text_fr, alt_text_en)
        """
        import json

        import anthropic

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

        system_prompt = (
            "Generate concise accessibility alt-text for an educational illustration. "
            "Respond ONLY with valid JSON:\n"
            '{"alt_text_fr": "...", "alt_text_en": "..."}\n'
            "Keep each alt-text under 125 characters."
        )
        user_message = f"Key concept: {key_concept}\nImage description: {dalle_prompt}"

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=256,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )

        content_text = ""
        for block in response.content:
            if hasattr(block, "text"):
                content_text += block.text

        data = json.loads(content_text)
        return data["alt_text_fr"], data["alt_text_en"]

    async def call_dalle_and_save(
        self,
        image_record: GeneratedImage,
        session: AsyncSession,
    ) -> GeneratedImage:
        """
        Call DALL-E 3 API, convert image to WebP (max 512px), and persist.
        Updates status: generating → ready | failed.
        """
        import openai
        from PIL import Image

        image_record.status = "generating"
        await session.commit()

        try:
            openai_client = openai.OpenAI(api_key=settings.openai_api_key)

            response = openai_client.images.generate(
                model="dall-e-3",
                prompt=image_record.dalle_prompt,
                size="1024x1024",
                quality="standard",
                response_format="url",
                n=1,
            )

            image_url = response.data[0].url

            import httpx

            async with httpx.AsyncClient(timeout=30.0) as http_client:
                img_response = await http_client.get(image_url)
                img_response.raise_for_status()
                raw_bytes = img_response.content

            img = Image.open(io.BytesIO(raw_bytes))
            if img.width > 512 or img.height > 512:
                img.thumbnail((512, 512), Image.LANCZOS)

            webp_buffer = io.BytesIO()
            img.save(webp_buffer, format="WEBP", quality=85)
            webp_bytes = webp_buffer.getvalue()

            image_record.image_data = webp_bytes
            image_record.width = img.width
            image_record.height = img.height
            image_record.status = "ready"
            image_record.generated_at = datetime.now(UTC)

            await session.commit()
            logger.info(
                "Image generated and saved",
                image_id=str(image_record.id),
                width=img.width,
                height=img.height,
            )

        except Exception as exc:
            logger.error(
                "DALL-E image generation failed",
                image_id=str(image_record.id),
                error=str(exc),
            )
            image_record.status = "failed"
            image_record.error_message = str(exc)
            await session.commit()

        return image_record

    async def process_lesson_image(
        self,
        lesson_id: uuid.UUID,
        module_id: uuid.UUID,
        unit_id: str,
        lesson_content: str,
        session: AsyncSession,
    ) -> GeneratedImage:
        """
        Full pipeline: extract concept → check reuse → generate or reuse image.

        Status flow: pending → generating → ready | failed
        """
        image_record = GeneratedImage(
            id=uuid.uuid4(),
            lesson_id=lesson_id,
            module_id=module_id,
            unit_id=unit_id,
            status="pending",
        )
        session.add(image_record)
        await session.commit()

        try:
            key_concept, dalle_prompt, semantic_tags = await self.extract_concept_and_tags(
                lesson_content=lesson_content,
                lesson_id=lesson_id,
                module_id=module_id,
                unit_id=unit_id,
            )

            image_record.key_concept = key_concept
            image_record.dalle_prompt = dalle_prompt
            image_record.semantic_tags = semantic_tags
            await session.commit()

            reusable = await self.find_reusable_image(semantic_tags, session)

            if reusable:
                alt_fr, alt_en = await self.generate_alt_text(key_concept, dalle_prompt)
                reusable.reuse_count = (reusable.reuse_count or 0) + 1
                await session.commit()

                image_record.status = "ready"
                image_record.image_data = reusable.image_data
                image_record.image_url = reusable.image_url
                image_record.alt_text_fr = alt_fr
                image_record.alt_text_en = alt_en
                image_record.width = reusable.width
                image_record.height = reusable.height
                image_record.generated_at = datetime.now(UTC)
                image_record.extra_metadata = {"reused_from": str(reusable.id)}
                await session.commit()

                logger.info(
                    "Reused existing image",
                    new_image_id=str(image_record.id),
                    source_image_id=str(reusable.id),
                )
                return image_record

            alt_fr, alt_en = await self.generate_alt_text(key_concept, dalle_prompt)
            image_record.alt_text_fr = alt_fr
            image_record.alt_text_en = alt_en
            await session.commit()

            image_record = await self.call_dalle_and_save(image_record, session)

        except Exception as exc:
            logger.error(
                "Image pipeline failed",
                image_id=str(image_record.id),
                error=str(exc),
            )
            image_record.status = "failed"
            image_record.error_message = str(exc)
            await session.commit()

        return image_record
