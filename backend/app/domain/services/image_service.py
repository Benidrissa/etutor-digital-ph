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

logger = structlog.get_logger(__name__)

SEMANTIC_REUSE_THRESHOLD = 0.85
# Text-free illustrations are a distinct style from the legacy baked-in-text
# "infographic" images, so they carry their own style discriminator. This keeps
# the reuse cache from serving an old garbled-text image for a new lesson.
STYLE_TAG = "style:illustration"

# Sira serves West African learners. The Claude-authored prompt is asked to depict
# Black West African people, but image models drift toward their (white/European)
# training bias, so we also append this literal constraint to every prompt we send
# to the image backend — belt-and-suspenders, since the model follows literal text.
PEOPLE_CONSTRAINT = (
    " Important: any human figures must be Black African people from West Africa, "
    "with West African skin tones, hair textures and facial features. Never depict "
    "white, Caucasian, European, Asian or other non-African people."
)


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
            (
                concept,
                prompt,
                tags,
                title_fr,
                title_en,
                labels,
            ) = await self._extract_concept_and_tags(lesson_content, language, audience)
            image_record.concept = concept
            image_record.prompt = prompt
            image_record.semantic_tags = tags
            # Title/labels are this lesson's overlay text; they stay on this record
            # even when the underlying illustration is reused from another lesson.
            image_record.title_fr = title_fr
            image_record.title_en = title_en
            image_record.overlay_labels = labels

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

            image_bytes, image_url = await self._generate_image(prompt)
            # Keep the provider's native width (~1536) — downscaling blurs fine detail.
            webp_bytes, width = _resize_to_webp(image_bytes, max_width=1536)

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
    ) -> tuple[str, str, list[str], str, str, list[dict[str, str]]]:
        """Use Claude to extract the concept, a text-free image prompt, semantic tags,
        a bilingual title, and bilingual component labels for the DOM overlay.

        Returns ``(concept, prompt, tags, title_fr, title_en, labels)`` where ``labels``
        is a list of ``{"fr": ..., "en": ...}`` dicts.
        """
        from app.ai.providers import resolve_provider
        from app.domain.services.platform_settings_service import SettingsCache

        model = SettingsCache.instance().get("ai-model-image-metadata", "claude-haiku-4-5")
        provider = resolve_provider(model)

        if audience.is_kids:
            style_block = (
                "STYLE for a children's audience: bright friendly cartoon-style flat "
                "illustration, primary colors, rounded shapes, simple icons, optional "
                "friendly mascot character. Keep visual complexity low. Where children "
                "appear, they MUST be Black African children from West Africa."
            )
        else:
            style_block = (
                "STYLE: flat editorial illustration, hand-drawn educational poster feel, "
                "muted palette with one or two accent colors, lots of whitespace."
            )

        system = (
            "You design clean conceptual illustrations for an adaptive multi-subject learning "
            "platform. The app renders the title and labels as real text OUTSIDE the image, so "
            "the image itself MUST be completely text-free. Given lesson content, extract:\n"
            "1) A short key concept (5 words max, in English).\n"
            "2) A detailed image-generation prompt for a single clear conceptual illustration "
            "that depicts the concept at a glance. The prompt MUST:\n"
            "   - Show 3 to 5 components, objects, or steps arranged so their relationship is "
            "visually obvious (flow, hierarchy, before/after, cause/effect) through arrows, "
            "positioning, or grouping — but with NO written labels on them.\n"
            "   - Contain ABSOLUTELY NO text: no title, no caption, no labels, no letters, no "
            "words, no numbers, no writing, no signage, no UI text of any kind. Convey meaning "
            "through imagery alone.\n"
            f"   - {style_block}\n"
            "   - Human figures (learners, professionals, customers, kids, etc.) ARE allowed and "
            "even encouraged when they help convey the concept. Whenever people appear they MUST "
            "be Black African people from West Africa (West African skin tones, hair textures and "
            "facial features); NEVER depict white, Caucasian, European, Asian or other non-African "
            "people. Avoid stereotypes. People are not required if the concept is purely structural.\n"
            "   - Stay subject-agnostic about the topic: derive the visual setting from the lesson "
            "content itself (do not assume any specific profession or industry unless the lesson "
            "states it). This does NOT override the rule above — any people shown are always Black "
            "West Africans regardless of subject.\n"
            "   - 250-450 characters.\n"
            "   - GOOD example: 'Clean conceptual illustration: cross-section of a leaf showing a "
            "chloroplast, stomata and veins; arrows for CO2 entering, O2 leaving, water rising and "
            "sugar descending; flat illustration, muted greens, hand-drawn feel, absolutely no text "
            "or labels.'\n"
            "   - BAD example: 'A poster titled \"Photosynthesis\" with labeled callouts' "
            "(contains text).\n"
            "3) A short title for the illustration in BOTH French and English (natural, idiomatic, "
            "6 words max each).\n"
            "4) 3 to 4 key component labels — the things a learner should notice in the image — "
            "each in BOTH French and English (1 to 4 words each), as a JSON array of "
            '{"fr": "...", "en": "..."} objects.\n'
            "5) A JSON array of 5-8 lowercase English semantic tags describing the lesson concept. "
            f'Always include the literal tag "{STYLE_TAG}" as one of the tags. The CONCEPT, LABELS '
            "en-field and TAGS must stay in English so the cache key is language-agnostic.\n"
            "Reply ONLY in this exact format:\n"
            "CONCEPT: <concept>\n"
            "PROMPT: <image_prompt>\n"
            "TITLE_FR: <french title>\n"
            "TITLE_EN: <english title>\n"
            "LABELS: <json_array>\n"
            "TAGS: <json_array>"
        )

        result = await provider.complete(
            system=system,
            messages=[
                {
                    "role": "user",
                    "content": f"Lesson content:\n{lesson_content[:2000]}",
                }
            ],
            max_tokens=700,
            temperature=1.0,
            model=model,
        )

        text = result.text
        concept, prompt, tags, title_fr, title_en, labels = _parse_concept_response(text)

        # Inject server-side discriminator tags so the cache key always matches the
        # actual generated style/audience, regardless of what Claude returned. Note
        # there is deliberately NO lang: tag — text-free illustrations are language
        # agnostic, so one image is reused across FR and EN lessons.
        tag_set = {t.lower() for t in tags}
        if STYLE_TAG not in tag_set:
            tags.append(STYLE_TAG)
        if audience.is_kids and "audience:kids" not in tag_set:
            tags.append("audience:kids")

        return concept, prompt, tags, title_fr, title_en, labels

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
        generation — currently ``style:`` and ``audience:``. This keeps the new
        text-free ``style:illustration`` images separate from the legacy baked-in
        text images, and prevents cross-audience reuse (an adult illustration for a
        kids lesson). There is deliberately no ``lang:`` discriminator: text-free
        illustrations are language agnostic and are reused across FR and EN.
        """
        new_discriminators = {
            t.lower() for t in tags if any(t.lower().startswith(p) for p in ("style:", "audience:"))
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
                if any(t.lower().startswith(p) for p in ("style:", "audience:"))
            }
            if not new_discriminators.issubset(candidate_discriminators):
                continue
            similarity = _jaccard_similarity(tags, candidate.semantic_tags)
            if similarity >= SEMANTIC_REUSE_THRESHOLD:
                return candidate
        return None

    async def _generate_image(self, prompt: str) -> tuple[bytes, str]:
        """Generate the illustration via the configured image provider.

        The backend (``gpt-image-1`` or a Gemini image model) is selected by the
        ``ai-model-image`` platform setting and resolved by prefix. A missing
        GOOGLE_API_KEY *or* any provider runtime error (e.g. Gemini quota 429)
        transparently falls back to gpt-image-1. Returns ``(image_bytes, image_url)``
        where the URL is a backend tag (the public URL is set by the caller from the
        stored data endpoint).
        """
        from app.ai.providers.image_provider import DEFAULT_IMAGE_MODEL, generate_image
        from app.domain.services.platform_settings_service import SettingsCache

        model = SettingsCache.instance().get("ai-model-image", DEFAULT_IMAGE_MODEL)
        image_bytes, used_model = await generate_image(
            prompt + PEOPLE_CONSTRAINT, model=model, size="1536x1024"
        )
        return image_bytes, f"{used_model}://generated"

    # Backwards-compatible alias: the backfill task still calls ``_call_dalle``.
    _call_dalle = _generate_image

    async def _generate_alt_text(self, concept: str) -> tuple[str, str]:
        """Generate bilingual alt-text for the image."""
        from app.ai.providers import resolve_provider
        from app.domain.services.platform_settings_service import SettingsCache

        model = SettingsCache.instance().get("ai-model-image-metadata", "claude-haiku-4-5")
        provider = resolve_provider(model)

        result = await provider.complete(
            system="",
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
            max_tokens=100,
            temperature=1.0,
            model=model,
        )

        text = result.text
        return _parse_alt_text(text, concept)


def _parse_concept_response(
    text: str,
) -> tuple[str, str, list[str], str, str, list[dict[str, str]]]:
    """Parse Claude's structured response.

    Returns ``(concept, prompt, tags, title_fr, title_en, labels)`` where ``labels``
    is a list of ``{"fr": ..., "en": ...}`` dicts.
    """
    import json
    import re

    concept = ""
    prompt = ""
    tags: list[str] = []
    title_fr = ""
    title_en = ""
    labels: list[dict[str, str]] = []

    for line in text.splitlines():
        line = line.strip()
        if line.startswith("CONCEPT:"):
            concept = line[len("CONCEPT:") :].strip()
        elif line.startswith("PROMPT:"):
            prompt = line[len("PROMPT:") :].strip()
        elif line.startswith("TITLE_FR:"):
            title_fr = line[len("TITLE_FR:") :].strip()
        elif line.startswith("TITLE_EN:"):
            title_en = line[len("TITLE_EN:") :].strip()
        elif line.startswith("LABELS:"):
            raw = line[len("LABELS:") :].strip()
            labels = _parse_labels(raw)
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
            f"Clean conceptual illustration of {concept}: 3-5 related components arranged to "
            "show their relationship through arrows, positioning and grouping. Flat "
            "illustration, hand-drawn feel, muted palette, absolutely no text or labels."
        )
    if not tags:
        tags = [concept.lower()]
    if STYLE_TAG not in {t.lower() for t in tags}:
        tags.append(STYLE_TAG)
    # Title falls back to the concept; the overlay always needs something to show.
    if not title_en:
        title_en = concept
    if not title_fr:
        title_fr = title_en

    return concept, prompt, tags, title_fr, title_en, labels


def _parse_labels(raw: str) -> list[dict[str, str]]:
    """Parse the LABELS JSON array into a list of ``{"fr", "en"}`` dicts.

    Tolerates Claude returning plain strings instead of objects (uses the string
    for both languages) and silently drops malformed entries.
    """
    import json

    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []

    labels: list[dict[str, str]] = []
    for item in parsed:
        if isinstance(item, dict):
            fr = str(item.get("fr") or item.get("en") or "").strip()
            en = str(item.get("en") or item.get("fr") or "").strip()
        elif isinstance(item, str):
            fr = en = item.strip()
        else:
            continue
        if fr or en:
            labels.append({"fr": fr, "en": en})
    return labels


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


def _resize_to_webp(
    image_bytes: bytes, max_width: int = 1536, quality: int = 92
) -> tuple[bytes, int]:
    """Convert image bytes to WebP, downscaling only if wider than ``max_width``.

    Quality defaults to 92: text-free illustrations have soft gradients that compress
    well, and the higher quality keeps edges crisp without a large size penalty.
    """
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        if img.width > max_width:
            ratio = max_width / img.width
            new_height = int(img.height * ratio)
            img = img.resize((max_width, new_height), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="WEBP", quality=quality)
        return buf.getvalue(), img.width
    except (ImportError, Exception):
        return image_bytes, max_width
