"""System prompts for lesson generation."""

import re
from collections import defaultdict
from typing import TYPE_CHECKING, Literal
from uuid import UUID

import structlog

if TYPE_CHECKING:
    from app.domain.models.course import Course

from app.domain.services.platform_settings_service import SettingsCache

logger = structlog.get_logger(__name__)

# Figures are offered to the model as short opaque tokens (⟦FIG1⟧ … ⟦FIG5⟧) rather
# than raw 36-char UUIDs. LLMs reliably copy a 4-char token but frequently *fabricate*
# a long UUID they were asked to echo verbatim (observed on staging: markers whose
# UUID exists nowhere in the DB), which silently drops the figure. The backend maps
# each token back to its real SourceImage id after generation. Keep this in sync with
# ``assign_figure_tokens`` and the extractor in ``lesson_service``.
MAX_FIGURE_TOKENS = 5
FIGURE_TOKEN_RE = re.compile(r"⟦FIG(\d+)⟧")


def assign_figure_tokens(linked_images: dict | None) -> dict[str, dict]:
    """Map short opaque tokens (⟦FIG1⟧…) to the candidate figures, deterministically.

    Flattens ``linked_images`` (chunk_id → list of image meta dicts) in iteration
    order, dedupes by image id, and caps at ``MAX_FIGURE_TOKENS``. Returns
    ``{token: image_meta}``. Because it is a pure function of ``linked_images``, the
    prompt formatter and the extractor derive the *same* mapping independently.
    """
    img_by_token: dict[str, dict] = {}
    if not linked_images:
        return img_by_token
    seen: set[str] = set()
    n = 0
    for img_list in linked_images.values():
        for img in img_list:
            img_id = str(img.get("id") or "")
            if not img_id or img_id in seen:
                continue
            n += 1
            if n > MAX_FIGURE_TOKENS:
                return img_by_token
            seen.add(img_id)
            img_by_token[f"⟦FIG{n}⟧"] = img
    return img_by_token


# Keys whose admin-editable value MUST reference {unit_title} so the
# generated content stays bound to the unit. Warn at runtime if missing.
_UNIT_BINDING_REQUIRED_KEYS = frozenset(
    {
        "ai-prompt-lesson-system",
        "ai-prompt-lesson-kids-system",
        "ai-prompt-quiz-system",
        "ai-prompt-quiz-kids-system",
        "ai-prompt-case-study-system",
        "ai-prompt-case-study-kids-system",
    }
)
_unit_binding_warned: set[str] = set()

# Mapping of country codes to French names for contextualization
COUNTRY_NAMES_FR = {
    "SN": "Sénégal",
    "ML": "Mali",
    "BF": "Burkina Faso",
    "NE": "Niger",
    "GH": "Ghana",
    "CI": "Côte d'Ivoire",
    "GN": "Guinée",
    "LR": "Libéria",
    "SL": "Sierra Leone",
    "GM": "Gambie",
    "GW": "Guinée-Bissau",
    "CV": "Cap-Vert",
    "NG": "Nigéria",
    "BJ": "Bénin",
    "TG": "Togo",
    # Catch-all options ("Other West African" / "Other") have no single country;
    # fall back to the regional name so prompts stay grammatical and on-domain.
    "OWA": "Afrique de l'Ouest",
    "OTH": "Afrique de l'Ouest",
}

COUNTRY_NAMES_EN = {
    "SN": "Senegal",
    "ML": "Mali",
    "BF": "Burkina Faso",
    "NE": "Niger",
    "GH": "Ghana",
    "CI": "Côte d'Ivoire",
    "GN": "Guinea",
    "LR": "Liberia",
    "SL": "Sierra Leone",
    "GM": "Gambia",
    "GW": "Guinea-Bissau",
    "CV": "Cape Verde",
    "NG": "Nigeria",
    "BJ": "Benin",
    "TG": "Togo",
    # Catch-all options ("Other West African" / "Other") have no single country;
    # fall back to the regional name so prompts stay grammatical and on-domain.
    "OWA": "West Africa",
    "OTH": "West Africa",
}


def _build_template_vars(
    language: str,
    country: str,
    level: int,
    bloom_level: str,
    course_title: str | None,
    course_description: str | None,
    module_title: str = "",
    unit_title: str = "",
    syllabus_context: str = "",
    course_domain: str = "",
) -> dict:
    """Build a dict of all template variables for prompt interpolation."""
    country_names = COUNTRY_NAMES_FR if language == "fr" else COUNTRY_NAMES_EN
    country_name = country_names.get(country, country)
    domain = course_title or ("santé publique" if language == "fr" else "public health")
    return {
        "course_title": course_title or ("santé publique" if language == "fr" else "public health"),
        "course_description": course_description or "",
        "course_domain": course_domain or domain,
        "module_title": module_title,
        "unit_title": unit_title,
        "country": country_name,
        "language": language,
        "level": str(level),
        "bloom_level": bloom_level,
        "syllabus_context": syllabus_context,
    }


def _apply_settings_template(
    setting_key: str,
    language: str,
    country: str,
    level: int,
    bloom_level: str,
    course_title: str | None,
    course_description: str | None,
    module_title: str = "",
    unit_title: str = "",
    syllabus_context: str = "",
    course_domain: str = "",
    **extra_vars,
) -> str:
    """Render the prompt template from platform settings.

    Always returns a rendered string. Uses the admin-overridden value
    if one exists, otherwise uses the compiled default.
    """
    from app.infrastructure.config.platform_defaults import DEFAULTS_BY_KEY

    defn = DEFAULTS_BY_KEY.get(setting_key)
    if defn is None:
        return ""
    current = SettingsCache.instance().get(setting_key)
    if not current:
        current = defn.default
    # Guard: warn once if an admin-overridden prompt drops the {unit_title}
    # placeholder. Without it, generated content drifts to module-level
    # overviews instead of the requested unit (issue #2007).
    if (
        setting_key in _UNIT_BINDING_REQUIRED_KEYS
        and "{unit_title}" not in current
        and setting_key not in _unit_binding_warned
    ):
        _unit_binding_warned.add(setting_key)
        logger.warning(
            "Prompt template missing {unit_title} placeholder — "
            "generated content may drift off-topic",
            setting_key=setting_key,
        )
    vars_map = _build_template_vars(
        language,
        country,
        level,
        bloom_level,
        course_title,
        course_description,
        module_title,
        unit_title,
        syllabus_context,
        course_domain,
    )
    vars_map.update(extra_vars)
    return current.format_map(defaultdict(str, vars_map))


def get_lesson_system_prompt(
    language: Literal["fr", "en"],
    country: str,
    level: int,
    bloom_level: str,
    course_title: str | None = None,
    course_description: str | None = None,
    module_title: str = "",
    unit_title: str = "",
    syllabus_context: str = "",
    course_domain: str = "",
    course: "Course | None" = None,
) -> str:
    """Generate system prompt for lesson content generation."""
    from app.ai.prompts.audience import detect_audience, get_audience_guidance

    audience = detect_audience(course)
    key = "ai-prompt-lesson-kids-system" if audience.is_kids else "ai-prompt-lesson-system"
    extra: dict = {}
    if audience.is_kids:
        extra["age_range"] = f"{audience.age_min}-{audience.age_max}"
        extra["audience_guidance"] = get_audience_guidance(audience, language)
    return _apply_settings_template(
        key,
        language,
        country,
        level,
        bloom_level,
        course_title,
        course_description,
        module_title,
        unit_title,
        syllabus_context,
        course_domain,
        **extra,
    )


def format_rag_context_for_lesson(
    chunks: list,
    query: str,
    module_title: str,
    unit_id: str,
    language: Literal["fr", "en"],
    linked_images: dict[UUID, list[dict]] | None = None,
    unit_title: str = "",
    unit_description: str | None = None,
) -> str:
    """Format RAG chunks into context for lesson generation.

    Args:
        chunks: RAG search result chunks
        query: Original search query
        module_title: Title of the module
        unit_id: Unit identifier (e.g. "1.3")
        language: Content language (fr/en)
        linked_images: Optional mapping of chunk_id -> list of image metadata dicts
                       (from SemanticRetriever.get_linked_images). Capped at 5 total annotations.
        unit_title: Declared title of the unit (e.g. "Mesures de morbidité et de mortalité").
                    Required for unit-level binding; empty string falls back to query-only.
        unit_description: Declared description of the unit. Reinforces topic scope.
    """
    if language == "fr":
        unit_block = f"UNITÉ CIBLE : {unit_id} — « {unit_title} »\n" if unit_title else ""
        if unit_description:
            unit_block += f"DESCRIPTION DE L'UNITÉ : {unit_description}\n"
        constraint = (
            "CONTRAINTE STRICTE : Le contenu doit traiter EXCLUSIVEMENT du sujet de "
            "l'unité ci-dessus. Ne couvre PAS les autres unités du module — chaque "
            "unité a sa propre leçon dédiée.\n\n"
            if unit_title
            else ""
        )
        context_intro = f"""DEMANDE : Génère une leçon pour le module "{module_title}".
{unit_block}{constraint}Sujet de recherche : "{query}"

DOCUMENTS DE RÉFÉRENCE :
"""
        sources_section = "\nSOURCES CITÉES :\n"
        figure_label = "FIGURE DISPONIBLE"

    else:  # English
        unit_block = f'TARGET UNIT: {unit_id} — "{unit_title}"\n' if unit_title else ""
        if unit_description:
            unit_block += f"UNIT DESCRIPTION: {unit_description}\n"
        constraint = (
            "STRICT CONSTRAINT: The content must address EXCLUSIVELY the topic of "
            "the unit above. Do NOT cover the other units in the module — each unit "
            "has its own dedicated lesson.\n\n"
            if unit_title
            else ""
        )
        context_intro = f"""REQUEST: Generate a lesson for module "{module_title}".
{unit_block}{constraint}Search topic: "{query}"

REFERENCE DOCUMENTS:
"""
        sources_section = "\nCITED SOURCES:\n"
        figure_label = "FIGURE AVAILABLE"

    formatted_chunks = []
    sources = set()
    # Offer figures as short opaque tokens (⟦FIG1⟧…) mapped back to real UUIDs by
    # the extractor. Each candidate image gets one stable token regardless of which
    # chunk surfaces it, so the model only ever copies a 4-char token.
    img_by_token = assign_figure_tokens(linked_images)
    token_by_id = {str(img.get("id") or ""): token for token, img in img_by_token.items()}

    for i, chunk in enumerate(chunks, 1):
        if hasattr(chunk, "chunk"):
            content = chunk.chunk.content
            source = chunk.chunk.source
            chapter = getattr(chunk.chunk, "chapter", None)
            page = getattr(chunk.chunk, "page", None)
            chunk_id = getattr(chunk.chunk, "id", None)
        else:
            content = chunk.content
            source = chunk.source
            chapter = getattr(chunk, "chapter", None)
            page = getattr(chunk, "page", None)
            chunk_id = getattr(chunk, "id", None)

        source_ref = source.title()
        if chapter:
            source_ref += f" Ch.{chapter}"
        if page:
            source_ref += f", p.{page}"

        chunk_text = f"[Extrait {i} - {source_ref}]\n{content}\n"

        if linked_images and chunk_id is not None and token_by_id:
            images = linked_images.get(chunk_id, [])
            for img in images:
                img_id = str(img.get("id") or "")
                token = token_by_id.get(img_id)
                if not token:
                    # Beyond MAX_FIGURE_TOKENS, or no id — not offered to the model.
                    continue
                fig_num = img.get("figure_number") or ""
                # Use the lesson-language caption so Claude reasons over (and
                # may echo) the translated figure text, not the raw English the
                # PyMuPDF extractor pulled from the PDF (#2502). The translated
                # variants are produced at indexation time and carried through
                # SourceImage.to_meta_dict(); fall back across locales then the
                # raw caption.
                if language == "fr":
                    caption = (
                        img.get("caption_fr") or img.get("caption") or img.get("caption_en") or ""
                    )
                else:
                    caption = (
                        img.get("caption_en") or img.get("caption") or img.get("caption_fr") or ""
                    )
                img_type = img.get("image_type") or "unknown"
                label_parts = []
                if fig_num:
                    label_parts.append(f"Figure {fig_num}")
                if caption:
                    label_parts.append(f'"{caption}"')
                if img_type != "unknown":
                    label_parts.append(f"({img_type})")
                label = " — ".join(label_parts) if label_parts else caption or img_type
                # The model cites the figure by copying the token verbatim.
                chunk_text += f"[{figure_label}: {label} — cite as {token}]\n"

        formatted_chunks.append(chunk_text)
        sources.add(source_ref)

    full_context = context_intro
    full_context += "\n".join(formatted_chunks)
    full_context += sources_section
    full_context += "\n".join(f"- {source}" for source in sorted(sources))

    return full_context
