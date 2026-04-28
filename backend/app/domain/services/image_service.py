"""Service for AI-generated lesson illustrations using gpt-image-1 with semantic reuse."""

from __future__ import annotations

import io
import uuid
from datetime import datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.ai.prompts.audience import AudienceContext, detect_audience
from app.domain.models.generated_image import GeneratedImage
from app.domain.models.source_image import SourceImage, SourceImageChunk
from app.infrastructure.config.settings import settings

logger = structlog.get_logger(__name__)

SEMANTIC_REUSE_THRESHOLD = 0.85
STYLE_TAG_INFOGRAPHIC = "style:infographic"


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
        # Dedup: return existing image if one already exists for this lesson
        existing = await session.execute(
            select(GeneratedImage)
            .where(
                GeneratedImage.lesson_id == lesson_id,
                GeneratedImage.status.in_(["ready", "generating", "pending"]),
            )
            .limit(1)
        )
        existing_image = existing.scalar_one_or_none()
        if existing_image is not None:
            logger.info(
                "Image already exists for lesson — skipping generation",
                lesson_id=str(lesson_id),
                image_id=str(existing_image.id),
                status=existing_image.status,
            )
            return existing_image

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
            lesson_row, language, audience = await self._load_lesson_context(lesson_id, session)
            concept, prompt, tags = await self._extract_concept_and_tags(
                lesson_content, language, audience
            )
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

            source_img = await self._find_source_image(lesson_row, session)
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
            webp_bytes, width = _resize_to_webp(image_bytes, max_width=1024)

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

    async def _load_lesson_context(
        self, lesson_id: uuid.UUID, session: AsyncSession
    ) -> tuple[object | None, str, AudienceContext]:
        """Eager-load the lesson row plus the course audience taxonomy.

        Returns ``(lesson_row, language, audience)``. Falls back to
        ``("en", AudienceContext(is_kids=False))`` when the lesson, its module,
        or its course can't be resolved — image generation must remain best-effort.
        """
        from app.domain.models.content import GeneratedContent
        from app.domain.models.module import Module

        result = await session.execute(
            select(GeneratedContent)
            .options(
                selectinload(GeneratedContent.module).selectinload(Module.course),
            )
            .where(GeneratedContent.id == lesson_id)
        )
        lesson = result.scalar_one_or_none()
        if lesson is None:
            return None, "en", AudienceContext(is_kids=False)

        language = (getattr(lesson, "language", None) or "en").lower()
        if language not in ("fr", "en"):
            language = "en"

        course = getattr(getattr(lesson, "module", None), "course", None)
        audience = detect_audience(course)
        return lesson, language, audience

    async def _extract_concept_and_tags(
        self, lesson_content: str, language: str, audience: AudienceContext
    ) -> tuple[str, str, list[str]]:
        """Use Claude API to extract key concept, DALL-E prompt, and semantic tags."""
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key, timeout=600.0)

        language_name = "French" if language == "fr" else "English"

        if audience.is_kids:
            style_block = (
                "STYLE for a children's audience: bright friendly cartoon-style flat "
                "illustration, primary colors, rounded shapes, big readable text, simple "
                "icons, optional friendly mascot character. Keep visual complexity low; "
                "callout labels MUST be 1 to 3 words. Show diverse children where people "
                "appear."
            )
        else:
            style_block = (
                "STYLE: flat editorial illustration, hand-drawn educational poster feel, "
                "muted palette with one or two accent colors, lots of whitespace, sans-serif labels."
            )

        system = (
            "You design explanatory infographics for an adaptive multi-subject learning platform. "
            "Given lesson content, extract:\n"
            "1) A short key concept (5 words max, in English).\n"
            "2) A detailed image-generation prompt for an editorial-poster-style INFOGRAPHIC "
            "that explains the concept at a glance. The prompt MUST request:\n"
            "   - A clear short title across the top.\n"
            "   - 3 to 6 named components, objects, or steps drawn as a labeled diagram, "
            "each with a short callout label.\n"
            "   - Connector arrows or lines that show how the components relate "
            "(flow, hierarchy, before/after, cause/effect).\n"
            "   - Optional split panels when the concept has natural contrasts.\n"
            "   - An optional small legend or maturity/timeline strip at the bottom only if it fits.\n"
            f"   - {style_block}\n"
            "   - Human figures (learners, professionals, customers, kids, etc.) ARE allowed and "
            "even encouraged when they help convey the concept; depict diverse people and avoid "
            "stereotypes. They are not required if the concept is purely structural.\n"
            "   - Stay subject-agnostic: derive the visual setting from the lesson content itself "
            "(do not assume any specific country, region, profession, or industry unless the lesson states it).\n"
            f"   - LANGUAGE: write the in-image title and ALL callout labels in {language_name} "
            "(natural, idiomatic). The CONCEPT and TAGS fields below MUST stay in English so the "
            "cache key is language-agnostic.\n"
            "   - 250-450 characters.\n"
            '   - GOOD example (en): \'Educational poster titled "Photosynthesis". Cross-section of '
            "a leaf with labeled callouts in English: chloroplast, stomata, xylem, phloem. Arrows "
            "show CO2 in, O2 out, water up, sugar down. Flat illustration, muted greens, hand-drawn feel.'\n"
            "   - GOOD example (fr): 'Affiche éducative titrée « Photosynthèse ». Coupe d'une "
            "feuille avec des étiquettes en français : chloroplaste, stomate, xylème, phloème. "
            "Flèches montrant CO2 entrant, O2 sortant, eau qui monte, sucre qui descend.'\n"
            "   - BAD example: 'A green leaf in nature, vibrant colors' (no labels, no structure).\n"
            "3) A JSON array of 5-8 lowercase English semantic tags describing the lesson concept. "
            f'Always include the literal tag "{STYLE_TAG_INFOGRAPHIC}" as one of the tags.\n'
            "Reply ONLY in this exact format:\n"
            "CONCEPT: <concept>\n"
            "PROMPT: <image_prompt>\n"
            "TAGS: <json_array>"
        )

        message = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=400,
            messages=[
                {
                    "role": "user",
                    "content": f"Lesson content:\n{lesson_content[:2000]}",
                }
            ],
            system=system,
        )

        text = message.content[0].text if message.content else ""
        concept, prompt, tags = _parse_concept_response(text)

        # Inject server-side discriminator tags so the cache key always matches the
        # actual generated style/language/audience, regardless of what Claude returned.
        tag_set = {t.lower() for t in tags}
        if STYLE_TAG_INFOGRAPHIC not in tag_set:
            tags.append(STYLE_TAG_INFOGRAPHIC)
        lang_tag = f"lang:{language}"
        if lang_tag not in tag_set:
            tags.append(lang_tag)
        if audience.is_kids and "audience:kids" not in tag_set:
            tags.append("audience:kids")

        return concept, prompt, tags

    async def _find_source_image(
        self, lesson: object | None, session: AsyncSession
    ) -> SourceImage | None:
        """Check if any source images are explicitly linked to the lesson's document chunks.

        Returns the first SourceImage with image_type in ('diagram', 'chart', 'photo')
        that is explicitly linked to a document chunk via the lesson's generated content.
        """
        if lesson is None or not getattr(lesson, "sources_cited", None):
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
        """Search generated_images for an existing ready image with ≥85% tag overlap.

        A candidate must share **every** discriminator-prefixed tag from the new
        generation — currently ``style:``, ``lang:``, and ``audience:``. This
        prevents cross-language reuse (an EN infographic for an FR lesson) and
        cross-audience reuse (an adult infographic for a kids lesson). Old rows
        that pre-date a discriminator simply lack it and are skipped.
        """
        new_discriminators = {
            t.lower()
            for t in tags
            if any(t.lower().startswith(p) for p in ("style:", "lang:", "audience:"))
        }
        if not new_discriminators:
            return None

        result = await session.execute(
            select(GeneratedImage).where(GeneratedImage.status == "ready")
        )
        candidates = result.scalars().all()

        for candidate in candidates:
            if not candidate.semantic_tags:
                continue
            candidate_discriminators = {
                t.lower()
                for t in candidate.semantic_tags
                if any(t.lower().startswith(p) for p in ("style:", "lang:", "audience:"))
            }
            if not new_discriminators.issubset(candidate_discriminators):
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

        response = await client.images.generate(
            model="gpt-image-1",
            prompt=prompt,
            size="1536x1024",
            quality="medium",
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
                        f"Write a short accessibility alt-text for an explanatory infographic "
                        f"about '{concept}'. Describe the labeled components, panels, "
                        f"and relationships shown — not just the topic.\n"
                        "Reply in this exact format:\n"
                        "FR: <alt text in French, max 20 words>\n"
                        "EN: <alt text in English, max 20 words>"
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
        concept = "lesson concept"
    if not prompt:
        prompt = (
            f'Editorial-poster-style infographic titled "{concept}" with 3-5 labeled '
            "components, callouts, and connector arrows. Flat illustration, hand-drawn feel, "
            "muted palette, sans-serif labels."
        )
    if not tags:
        tags = [concept.lower()]
    if "style:infographic" not in {t.lower() for t in tags}:
        tags.append("style:infographic")

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
