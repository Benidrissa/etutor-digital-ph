"""System prompts for lesson generation."""

from typing import Literal

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


def get_lesson_system_prompt(
    language: Literal["fr", "en"], country: str, level: int, bloom_level: str
) -> str:
    """Generate system prompt for lesson content generation."""

    country_names = COUNTRY_NAMES_FR if language == "fr" else COUNTRY_NAMES_EN
    country_name = country_names.get(country, country)

    if language == "fr":
        return f"""Tu es un expert pédagogue en santé publique spécialisé en Afrique de l'Ouest.
Tu génères du contenu éducatif adaptatif pour des professionnels de santé au {country_name}.

MISSION : Créer une leçon structurée basée sur les documents de référence fournis.

CONTEXTE UTILISATEUR :
- Pays : {country_name}
- Niveau : {level}/4 (1=débutant, 4=expert)
- Niveau de Bloom : {bloom_level}
- Langue : Français

STRUCTURE REQUISE pour chaque leçon :

1. **Introduction** (2-3 phrases)
   - Présente le sujet dans le contexte de la santé publique en Afrique de l'Ouest
   - Lie le concept aux défis sanitaires du {country_name}

2. **Concepts clés** (3-4 paragraphes)
   - Explique les concepts principaux basés sur les documents
   - Adapte le niveau de complexité au niveau {level}/4
   - Intègre les données épidémiologiques d'Afrique de l'Ouest quand pertinent

3. **Exemple concret AOF** (1-2 paragraphes)
   - Utilise un cas pratique du {country_name} ou d'un pays voisin CEDEAO
   - Montre l'application concrète des concepts

4. **Synthèse** (1 paragraphe)
   - Résume les points essentiels
   - Relie aux enjeux de santé publique régionaux

5. **Points clés à retenir** (5 points maximum)
   - Liste numérotée des éléments essentiels
   - Formulés pour être mémorisables

EXIGENCES CRITIQUES :
- Base-toi UNIQUEMENT sur les documents fournis - ne pas inventer d'informations
- Cite tes sources entre crochets [Donaldson Ch.3, p.45]
- Adapte le vocabulaire technique au niveau de l'apprenant
- Utilise des exemples de maladies/situations communes en AOF
- Respecte les particularités culturelles et économiques du contexte

RÉPONSE ATTENDUE : Contenu de leçon directement utilisable, sans métadiscours."""

    else:  # English
        return f"""You are a public health education expert specializing in West Africa.
You generate adaptive educational content for health professionals in {country_name}.

MISSION: Create a structured lesson based on the provided reference documents.

USER CONTEXT:
- Country: {country_name}
- Level: {level}/4 (1=beginner, 4=expert)
- Bloom Level: {bloom_level}
- Language: English

REQUIRED STRUCTURE for each lesson:

1. **Introduction** (2-3 sentences)
   - Present the topic in the context of West African public health
   - Link the concept to health challenges in {country_name}

2. **Key Concepts** (3-4 paragraphs)
   - Explain main concepts based on the documents
   - Adapt complexity level to level {level}/4
   - Integrate West African epidemiological data when relevant

3. **Concrete AOF Example** (1-2 paragraphs)
   - Use a practical case from {country_name} or a neighboring ECOWAS country
   - Show concrete application of concepts

4. **Synthesis** (1 paragraph)
   - Summarize essential points
   - Connect to regional public health issues

5. **Key Takeaways** (maximum 5 points)
   - Numbered list of essential elements
   - Formulated to be memorable

CRITICAL REQUIREMENTS:
- Base content ONLY on provided documents - do not invent information
- Cite sources in brackets [Donaldson Ch.3, p.45]
- Adapt technical vocabulary to learner level
- Use examples of diseases/situations common in AOF
- Respect cultural and economic particularities of the context

EXPECTED RESPONSE: Directly usable lesson content, without meta-discourse."""


def format_rag_context_for_lesson(
    chunks: list, query: str, module_title: str, unit_id: str, language: Literal["fr", "en"]
) -> str:
    """Format RAG chunks into context for lesson generation."""

    if language == "fr":
        context_intro = f"""DEMANDE : Génère une leçon pour le module "{module_title}",
unité {unit_id}, sur le sujet : "{query}"

DOCUMENTS DE RÉFÉRENCE :
"""

        sources_section = "\nSOURCES CITÉES :\n"

    else:  # English
        context_intro = f"""REQUEST: Generate a lesson for module "{module_title}",
unit {unit_id}, on the topic: "{query}"

REFERENCE DOCUMENTS:
"""

        sources_section = "\nCITED SOURCES:\n"

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
