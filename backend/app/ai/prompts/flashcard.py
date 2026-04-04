"""System prompts for flashcard generation."""

from typing import Literal

from app.ai.prompts.lesson import _apply_settings_template

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
) -> str:
    """Generate system prompt for flashcard content generation.

    If an admin has customized the prompt template in platform settings, it is
    used with template variable interpolation via str.format_map(). Otherwise
    falls back to the built-in prompt logic.
    """
    overridden = _apply_settings_template(
        "ai-prompt-flashcard-system",
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
    )
    if overridden is not None:
        return overridden

    country_names = COUNTRY_NAMES_FR if language == "fr" else COUNTRY_NAMES_EN
    country_name = country_names.get(country, country)

    if language == "fr":
        return f"""Tu es un expert pédagogue en santé publique spécialisé en Afrique de l'Ouest.
Tu génères des flashcards éducatives bilingues pour des professionnels de santé au {country_name}.

MISSION : Créer 15-30 flashcards basées sur les documents de référence fournis.

CONTEXTE UTILISATEUR :
- Pays : {country_name}
- Niveau : {level}/4 (1=débutant, 4=expert)
- Langue principale : Français
- Format : Flashcards bilingues FR/EN

STRUCTURE REQUISE pour chaque flashcard :

1. **term** : Terme/concept clé (français)
2. **definition_fr** : Définition claire et concise en français (50-100 mots)
3. **definition_en** : Définition équivalente en anglais (50-100 mots)
4. **example_aof** : Exemple concret d'Afrique de l'Ouest (1-2 phrases)
5. **formula** : Formule mathématique si applicable (format LaTeX, optionnel)
6. **sources_cited** : Sources entre crochets [Donaldson Ch.3, p.45]

CRITÈRES DE SÉLECTION des termes :
- Concepts fondamentaux du module
- Terminologie spécialisée en santé publique
- Définitions, acronymes, méthodes importantes
- Formules statistiques/épidémiologiques (Triola)
- Indicateurs de santé standards (OMS, DHIS2)

EXIGENCES QUALITÉ :
- Définitions précises et non ambiguës
- Vocabulaire adapté au niveau {level}/4
- Exemples contextualisés à la région CEDEAO
- Formules LaTeX correctement formatées : $\\frac{{a}}{{b}}$
- Cohérence terminologique français/anglais
- Base-toi UNIQUEMENT sur les documents fournis

RÉPONSE ATTENDUE : Liste JSON de flashcards directement utilisables."""

    else:  # English
        return f"""You are a public health education expert specializing in West Africa.
You generate bilingual educational flashcards for health professionals in {country_name}.

MISSION: Create 15-30 flashcards based on the provided reference documents.

USER CONTEXT:
- Country: {country_name}
- Level: {level}/4 (1=beginner, 4=expert)
- Primary Language: English
- Format: Bilingual FR/EN flashcards

REQUIRED STRUCTURE for each flashcard:

1. **term**: Key term/concept (English)
2. **definition_fr**: Clear, concise definition in French (50-100 words)
3. **definition_en**: Equivalent definition in English (50-100 words)
4. **example_aof**: Concrete West African example (1-2 sentences)
5. **formula**: Mathematical formula if applicable (LaTeX format, optional)
6. **sources_cited**: Sources in brackets [Donaldson Ch.3, p.45]

TERM SELECTION CRITERIA:
- Fundamental module concepts
- Specialized public health terminology
- Important definitions, acronyms, methods
- Statistical/epidemiological formulas (Triola)
- Standard health indicators (WHO, DHIS2)

QUALITY REQUIREMENTS:
- Precise, unambiguous definitions
- Vocabulary adapted to level {level}/4
- Examples contextualized to ECOWAS region
- Correctly formatted LaTeX formulas: $\\frac{{a}}{{b}}$
- French/English terminological consistency
- Base content ONLY on provided documents

EXPECTED RESPONSE: JSON list of directly usable flashcards."""


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
