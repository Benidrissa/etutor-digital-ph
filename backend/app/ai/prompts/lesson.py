"""System prompts for lesson generation."""

from collections import defaultdict
from typing import TYPE_CHECKING, Literal
from uuid import UUID

import structlog

if TYPE_CHECKING:
    from app.domain.models.course import Course

from app.domain.services.platform_settings_service import SettingsCache

logger = structlog.get_logger(__name__)

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
    total_image_annotations = 0
    max_image_annotations = 5

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

        if (
            linked_images
            and chunk_id is not None
            and total_image_annotations < max_image_annotations
        ):
            images = linked_images.get(chunk_id, [])
            for img in images:
                if total_image_annotations >= max_image_annotations:
                    break
                fig_num = img.get("figure_number") or ""
                caption = img.get("caption") or ""
                img_type = img.get("image_type") or "unknown"
                img_id = img.get("id", "")
                label_parts = []
                if fig_num:
                    label_parts.append(f"Figure {fig_num}")
                if caption:
                    label_parts.append(f'"{caption}"')
                if img_type != "unknown":
                    label_parts.append(f"({img_type})")
                label = " — ".join(label_parts) if label_parts else caption or img_type
                chunk_text += f"[{figure_label}: {label} — {{{{source_image:{img_id}}}}}]\n"
                total_image_annotations += 1

        formatted_chunks.append(chunk_text)
        sources.add(source_ref)

    full_context = context_intro
    full_context += "\n".join(formatted_chunks)
    full_context += sources_section
    full_context += "\n".join(f"- {source}" for source in sorted(sources))

    return full_context
