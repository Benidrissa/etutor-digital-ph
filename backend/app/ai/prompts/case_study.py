"""System prompts for case study generation."""

from typing import TYPE_CHECKING, Literal

import structlog

from app.ai.prompts.lesson import _apply_settings_template

if TYPE_CHECKING:
    from app.domain.models.course import Course

logger = structlog.get_logger(__name__)

CASE_STUDY_TOPICS = {
    "M01": {
        "fr": "Épidémie Ebola en Guinée 2014",
        "en": "Ebola Epidemic in Guinea 2014",
    },
    "M02": {
        "fr": "Système de surveillance du paludisme au Burkina Faso",
        "en": "Malaria Surveillance System in Burkina Faso",
    },
    "M03": {
        "fr": "Réforme du système de santé au Ghana",
        "en": "Health System Reform in Ghana",
    },
    "M04": {
        "fr": "Enquête épidémiologique sur le choléra au Niger",
        "en": "Cholera Epidemiological Investigation in Niger",
    },
    "M05": {
        "fr": "Surveillance de la méningite en zone sahélienne",
        "en": "Meningitis Surveillance in the Sahel Belt",
    },
    "M06": {
        "fr": "Implémentation DHIS2 au Sénégal",
        "en": "DHIS2 Implementation in Senegal",
    },
    "M07": {
        "fr": "Analyse biostatistique de la mortalité infantile au Mali",
        "en": "Biostatistical Analysis of Infant Mortality in Mali",
    },
}


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


def _get_case_study_topic(
    module_id: str | None,
    language: Literal["fr", "en"],
    syllabus_json: dict | None = None,
) -> str | None:
    """Resolve case study topic from syllabus_json or fallback to CASE_STUDY_TOPICS."""
    if syllabus_json and isinstance(syllabus_json, dict):
        case_study_topics = syllabus_json.get("case_study_topics") or syllabus_json.get(
            "case_studies"
        )
        if isinstance(case_study_topics, list) and case_study_topics:
            first = case_study_topics[0]
            if isinstance(first, dict):
                return first.get(language) or first.get("fr") or first.get("en") or str(first)
            return str(first)
        if isinstance(case_study_topics, dict):
            return case_study_topics.get(language) or case_study_topics.get("fr")

    module_key = module_id.upper() if module_id else None
    if module_key and module_key in CASE_STUDY_TOPICS:
        return CASE_STUDY_TOPICS[module_key][language]

    return None


def format_rag_context_for_case_study(
    chunks: list,
    query: str,
    module_title: str,
    unit_id: str,
    language: Literal["fr", "en"],
    module_id: str | None = None,
    syllabus_json: dict | None = None,
) -> str:
    """Format RAG chunks into context for case study generation."""

    topic = _get_case_study_topic(module_id, language, syllabus_json)

    if language == "fr":
        topic_line = f'Sujet recommandé : "{topic}"\n' if topic else ""
        context_intro = f"""DEMANDE : Génère une étude de cas pour le module "{module_title}",
unité {unit_id}.
{topic_line}Thème : "{query}"

DOCUMENTS DE RÉFÉRENCE :
"""
        sources_section = "\nSOURCES CITÉES :\n"

    else:
        topic_line = f'Recommended topic: "{topic}"\n' if topic else ""
        context_intro = f"""REQUEST: Generate a case study for module "{module_title}",
unit {unit_id}.
{topic_line}Theme: "{query}"

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
