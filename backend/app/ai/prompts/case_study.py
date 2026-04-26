"""System prompts for case study generation."""

from typing import TYPE_CHECKING, Literal

import structlog

from app.ai.prompts.lesson import _apply_settings_template

if TYPE_CHECKING:
    from app.domain.models.course import Course

logger = structlog.get_logger(__name__)


def get_case_study_system_prompt(
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
    """Generate system prompt for case study content generation."""
    from app.ai.prompts.audience import detect_audience, get_audience_guidance

    audience = detect_audience(course)
    key = "ai-prompt-case-study-kids-system" if audience.is_kids else "ai-prompt-case-study-system"
    logger.debug(
        "get_case_study_system_prompt called",
        setting_key=key,
        language=language,
        country=country,
        level=level,
        bloom_level=bloom_level,
        is_kids=audience.is_kids,
    )
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


def format_rag_context_for_case_study(
    chunks: list,
    query: str,
    module_title: str,
    unit_id: str,
    language: Literal["fr", "en"],
    module_id: str | None = None,  # noqa: ARG001  (kept for backwards-compat callers)
    syllabus_json: dict | None = None,  # noqa: ARG001
    unit_title: str = "",
    unit_description: str | None = None,
) -> str:
    """Format RAG chunks into context for case study generation.

    Args:
        chunks: RAG search result chunks.
        query: Search query used for RAG.
        module_title: Title of the parent module.
        unit_id: Unit identifier (e.g. "1.9").
        language: Content language (fr/en).
        module_id, syllabus_json: kept for backwards compatibility; no longer used —
            unit_title + unit_description are the authoritative topic source.
        unit_title: Declared title of the case-study unit. Anchors generation.
        unit_description: Declared description of the case-study unit.
    """

    if language == "fr":
        unit_block = f"UNITÉ CIBLE : {unit_id} — « {unit_title} »\n" if unit_title else ""
        if unit_description:
            unit_block += f"DESCRIPTION DE L'UNITÉ : {unit_description}\n"
        constraint = (
            "CONTRAINTE STRICTE : L'étude de cas doit traiter EXCLUSIVEMENT du "
            "sujet de l'unité ci-dessus.\n\n"
            if unit_title
            else ""
        )
        context_intro = f"""DEMANDE : Génère une étude de cas pour le module "{module_title}".
{unit_block}{constraint}Thème de recherche : "{query}"

DOCUMENTS DE RÉFÉRENCE :
"""
        sources_section = "\nSOURCES CITÉES :\n"

    else:
        unit_block = f'TARGET UNIT: {unit_id} — "{unit_title}"\n' if unit_title else ""
        if unit_description:
            unit_block += f"UNIT DESCRIPTION: {unit_description}\n"
        constraint = (
            "STRICT CONSTRAINT: The case study must address EXCLUSIVELY the topic "
            "of the unit above.\n\n"
            if unit_title
            else ""
        )
        context_intro = f"""REQUEST: Generate a case study for module "{module_title}".
{unit_block}{constraint}Search theme: "{query}"

REFERENCE DOCUMENTS:
"""
        sources_section = "\nCITED SOURCES:\n"

    formatted_chunks = []
    sources = set()

    for i, chunk in enumerate(chunks, 1):
        if hasattr(chunk, "chunk"):
            content = chunk.chunk.content
            source = chunk.chunk.source
            chapter = getattr(chunk.chunk, "chapter", None)
            page = getattr(chunk.chunk, "page", None)
        else:
            content = chunk.content
            source = chunk.source
            chapter = getattr(chunk, "chapter", None)
            page = getattr(chunk, "page", None)

        source_ref = source.title()
        if chapter:
            source_ref += f" Ch.{chapter}"
        if page:
            source_ref += f", p.{page}"

        formatted_chunks.append(f"[Extrait {i} - {source_ref}]\n{content}\n")
        sources.add(source_ref)

    full_context = context_intro
    full_context += "\n".join(formatted_chunks)
    full_context += sources_section
    full_context += "\n".join(f"- {source}" for source in sorted(sources))

    return full_context
