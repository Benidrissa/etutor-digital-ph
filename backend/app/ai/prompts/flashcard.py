"""System prompts for flashcard generation."""

from typing import TYPE_CHECKING, Literal

from app.ai.prompts.lesson import _apply_settings_template

if TYPE_CHECKING:
    from app.domain.models.course import Course

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


def get_flashcard_system_prompt(
    language: Literal["fr", "en"],
    country: str,
    level: int,
    course_title: str | None = None,
    course_description: str | None = None,
    module_title: str = "",
    syllabus_context: str = "",
    course_domain: str = "",
    course: "Course | None" = None,
) -> str:
    """Generate system prompt for flashcard content generation."""
    from app.ai.prompts.audience import detect_audience, get_audience_guidance

    audience = detect_audience(course)
    key = "ai-prompt-flashcard-kids-system" if audience.is_kids else "ai-prompt-flashcard-system"
    extra: dict = {}
    if audience.is_kids:
        extra["age_range"] = f"{audience.age_min}-{audience.age_max}"
        extra["audience_guidance"] = get_audience_guidance(audience, language)
    return _apply_settings_template(
        key,
        language,
        country,
        level,
        "",
        course_title,
        course_description,
        module_title,
        "",
        syllabus_context,
        course_domain,
        **extra,
    )


def format_rag_context_for_flashcards(
    chunks: list, module_title: str, language: Literal["fr", "en"]
) -> str:
    """Format RAG chunks into context for flashcard generation."""

    if language == "fr":
        context_intro = f"""DEMANDE : Génère des flashcards pour le module "{module_title}"

DOCUMENTS DE RÉFÉRENCE pour extraction des concepts :
"""

        sources_section = "\nSOURCES DISPONIBLES :\n"

    else:  # English
        context_intro = f"""REQUEST: Generate flashcards for module "{module_title}"

REFERENCE DOCUMENTS for concept extraction:
"""

        sources_section = "\nAVAILABLE SOURCES:\n"

    # Format chunks
    formatted_chunks = []
    sources = set()

    for i, chunk in enumerate(chunks, 1):
        if hasattr(chunk, "chunk"):
            # SearchResult object
            content = chunk.chunk.content
            source = chunk.chunk.source
            chapter = getattr(chunk.chunk, "chapter", None)
            page = getattr(chunk.chunk, "page", None)
        else:
            # Direct chunk object
            content = chunk.content
            source = chunk.source
            chapter = getattr(chunk, "chapter", None)
            page = getattr(chunk, "page", None)

        # Format source reference
        source_ref = source.title()
        if chapter:
            source_ref += f" Ch.{chapter}"
        if page:
            source_ref += f", p.{page}"

        formatted_chunks.append(f"[Extrait {i} - {source_ref}]\n{content}\n")
        sources.add(source_ref)

    # Build full context
    full_context = context_intro
    full_context += "\n".join(formatted_chunks)
    full_context += sources_section
    full_context += "\n".join(f"- {source}" for source in sorted(sources))

    return full_context
