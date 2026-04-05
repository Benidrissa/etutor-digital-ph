"""System prompts for lesson generation."""

from typing import Literal
from uuid import UUID

from app.domain.services.platform_settings_service import SettingsCache

from app.domain.services.platform_settings_service import SettingsCache

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
) -> str | None:
    """Try to render an admin-overridden prompt template from settings.

    Returns the rendered string if the setting has been overridden from its
    compiled default, otherwise returns None so callers fall back to the
    built-in logic.
    """
    try:
        from app.infrastructure.config.platform_defaults import DEFAULTS_BY_KEY

        defn = DEFAULTS_BY_KEY.get(setting_key)
        if defn is None:
            return None
        current = SettingsCache.instance().get(setting_key)
        if current is None or current == defn.default:
            return None
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
        return current.format_map(vars_map)
    except Exception:
        return None


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
) -> str:
    """Generate system prompt for lesson content generation.

    If an admin has customized the prompt template in platform settings, it is
    used with template variable interpolation via str.format_map(). Otherwise
    falls back to the built-in course-aware prompt logic.
    """
    overridden = _apply_settings_template(
        "ai-prompt-lesson-system",
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
    if overridden is not None:
        return overridden

    country_names = COUNTRY_NAMES_FR if language == "fr" else COUNTRY_NAMES_EN
    country_name = country_names.get(country, country)

    if language == "fr":
        if course_title:
            expert_role = f"Tu es un expert pédagogue en {course_title} spécialisé pour le contexte d'Afrique de l'Ouest."
            audience_line = f"Tu génères du contenu éducatif adaptatif pour des professionnels au {country_name} dans le domaine : {course_title}."
            intro_guidance = (
                f"Présente le sujet dans le contexte de {course_title} en Afrique de l'Ouest"
            )
            if course_description:
                intro_guidance += f" ({course_description[:150]})"
            challenge_line = f"Lie le concept aux défis de {country_name} dans ce domaine"
            data_line = (
                "Intègre des données et exemples pertinents d'Afrique de l'Ouest pour ce domaine"
            )
            example_line = f"Utilise un cas pratique du {country_name} ou d'un pays voisin CEDEAO lié à {course_title}"
            synthesis_line = f"Relie aux enjeux régionaux dans le domaine de {course_title}"
            criteria_examples = (
                f"Utilise des exemples et situations pertinents pour {course_title} en AOF"
            )
        else:
            expert_role = (
                "Tu es un expert pédagogue en santé publique spécialisé en Afrique de l'Ouest."
            )
            audience_line = f"Tu génères du contenu éducatif adaptatif pour des professionnels de santé au {country_name}."
            intro_guidance = (
                "Présente le sujet dans le contexte de la santé publique en Afrique de l'Ouest"
            )
            challenge_line = f"Lie le concept aux défis sanitaires du {country_name}"
            data_line = "Intègre les données épidémiologiques d'Afrique de l'Ouest quand pertinent"
            example_line = f"Utilise un cas pratique du {country_name} ou d'un pays voisin CEDEAO"
            synthesis_line = "Relie aux enjeux de santé publique régionaux"
            criteria_examples = "Utilise des exemples de maladies/situations communes en AOF"

        return f"""{expert_role}
{audience_line}

MISSION : Créer une leçon structurée basée sur les documents de référence fournis.

CONTEXTE UTILISATEUR :
- Pays : {country_name}
- Niveau : {level}/4 (1=débutant, 4=expert)
- Niveau de Bloom : {bloom_level}
- Langue : Français

STRUCTURE REQUISE pour chaque leçon :

1. **Introduction** (2-3 phrases)
   - {intro_guidance}
   - {challenge_line}

2. **Concepts clés** (3-4 paragraphes)
   - Explique les concepts principaux basés sur les documents
   - Adapte le niveau de complexité au niveau {level}/4
   - {data_line}

3. **Exemple concret AOF** (1-2 paragraphes)
   - {example_line}
   - Montre l'application concrète des concepts

4. **Synthèse** (1 paragraphe)
   - Résume les points essentiels
   - {synthesis_line}

5. **Points clés à retenir** (5 points maximum)
   - Liste numérotée des éléments essentiels
   - Formulés pour être mémorisables

EXIGENCES CRITIQUES :
- Base-toi UNIQUEMENT sur les documents fournis - ne pas inventer d'informations
- Cite tes sources entre crochets [Donaldson Ch.3, p.45]
- Adapte le vocabulaire technique au niveau de l'apprenant
- {criteria_examples}
- Respecte les particularités culturelles et économiques du contexte

FIGURES DE RÉFÉRENCE :
Si le contexte contient des annotations [FIGURE DISPONIBLE: ...], tu peux référencer ces figures dans ton contenu en utilisant la syntaxe {{{{source_image:UUID}}}} (remplace UUID par l'identifiant indiqué).
- Référence une figure uniquement si elle illustre directement un concept de la leçon
- Maximum 3 références de figures par leçon
- Insère la référence inline dans le texte, ex : « ... comme illustré {{{{source_image:abc123}}}} »

RÉPONSE ATTENDUE : Contenu de leçon directement utilisable, sans métadiscours."""

    else:  # English
        if course_title:
            expert_role = f"You are an expert educator in {course_title} specializing in the West African context."
            audience_line = f"You generate adaptive educational content for professionals in {country_name} in the domain: {course_title}."
            intro_guidance = f"Present the topic in the context of {course_title} in West Africa"
            if course_description:
                intro_guidance += f" ({course_description[:150]})"
            challenge_line = f"Link the concept to challenges in {country_name} in this domain"
            data_line = "Integrate relevant data and examples from West Africa for this domain"
            example_line = f"Use a practical case from {country_name} or a neighboring ECOWAS country related to {course_title}"
            synthesis_line = f"Connect to regional challenges in the domain of {course_title}"
            criteria_examples = (
                f"Use examples and situations relevant to {course_title} in West Africa"
            )
        else:
            expert_role = "You are a public health education expert specializing in West Africa."
            audience_line = f"You generate adaptive educational content for health professionals in {country_name}."
            intro_guidance = "Present the topic in the context of West African public health"
            challenge_line = f"Link the concept to health challenges in {country_name}"
            data_line = "Integrate West African epidemiological data when relevant"
            example_line = (
                f"Use a practical case from {country_name} or a neighboring ECOWAS country"
            )
            synthesis_line = "Connect to regional public health issues"
            criteria_examples = "Use examples of diseases/situations common in West Africa"

        return f"""{expert_role}
{audience_line}

MISSION: Create a structured lesson based on the provided reference documents.

USER CONTEXT:
- Country: {country_name}
- Level: {level}/4 (1=beginner, 4=expert)
- Bloom Level: {bloom_level}
- Language: English

REQUIRED STRUCTURE for each lesson:

1. **Introduction** (2-3 sentences)
   - {intro_guidance}
   - {challenge_line}

2. **Key Concepts** (3-4 paragraphs)
   - Explain main concepts based on the documents
   - Adapt complexity level to level {level}/4
   - {data_line}

3. **Concrete AOF Example** (1-2 paragraphs)
   - {example_line}
   - Show concrete application of concepts

4. **Synthesis** (1 paragraph)
   - Summarize essential points
   - {synthesis_line}

5. **Key Takeaways** (maximum 5 points)
   - Numbered list of essential elements
   - Formulated to be memorable

CRITICAL REQUIREMENTS:
- Base content ONLY on provided documents - do not invent information
- Cite sources in brackets [Donaldson Ch.3, p.45]
- Adapt technical vocabulary to learner level
- {criteria_examples}
- Respect cultural and economic particularities of the context

REFERENCE FIGURES:
If the context contains [FIGURE AVAILABLE: ...] annotations, you may reference those figures in your content using the syntax {{{{source_image:UUID}}}} (replace UUID with the identifier shown).
- Only reference a figure if it directly illustrates a concept in the lesson
- Maximum 3 figure references per lesson
- Insert the reference inline in the text, e.g. "... as illustrated {{{{source_image:abc123}}}}"

EXPECTED RESPONSE: Directly usable lesson content, without meta-discourse."""


def format_rag_context_for_lesson(
    chunks: list,
    query: str,
    module_title: str,
    unit_id: str,
    language: Literal["fr", "en"],
    linked_images: dict[UUID, list[dict]] | None = None,
) -> str:
    """Format RAG chunks into context for lesson generation.

    Args:
        chunks: RAG search result chunks
        query: Original search query
        module_title: Title of the module
        unit_id: Unit identifier
        language: Content language (fr/en)
        linked_images: Optional mapping of chunk_id -> list of image metadata dicts
                       (from SemanticRetriever.get_linked_images). Capped at 5 total annotations.
    """
    if language == "fr":
        context_intro = f"""DEMANDE : Génère une leçon pour le module "{module_title}",
unité {unit_id}, sur le sujet : "{query}"

DOCUMENTS DE RÉFÉRENCE :
"""
        sources_section = "\nSOURCES CITÉES :\n"
        figure_label = "FIGURE DISPONIBLE"

    else:  # English
        context_intro = f"""REQUEST: Generate a lesson for module "{module_title}",
unit {unit_id}, on the topic: "{query}"

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
