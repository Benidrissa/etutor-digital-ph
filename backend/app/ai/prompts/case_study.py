"""System prompts for case study generation."""

from typing import Literal

from app.ai.prompts.lesson import COUNTRY_NAMES_EN, COUNTRY_NAMES_FR

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
    language: Literal["fr", "en"], country: str, level: int, bloom_level: str
) -> str:
    """Generate system prompt for case study content generation."""

    country_names = COUNTRY_NAMES_FR if language == "fr" else COUNTRY_NAMES_EN
    country_name = country_names.get(country, country)

    if language == "fr":
        return f"""Tu es un expert pédagogue en santé publique spécialisé en Afrique de l'Ouest.
Tu génères des études de cas éducatives adaptatives pour des professionnels de santé au {country_name}.

MISSION : Créer une étude de cas structurée basée sur un événement de santé publique réel en AOF.

CONTEXTE UTILISATEUR :
- Pays : {country_name}
- Niveau : {level}/4 (1=débutant, 4=expert)
- Niveau de Bloom : {bloom_level}
- Langue : Français

STRUCTURE REQUISE pour l'étude de cas :

1. **Contexte AOF** (2-3 paragraphes)
   - Présente la situation géographique, économique et sanitaire
   - Décrit le système de santé du pays concerné
   - Fournit les indicateurs de santé pertinents avant l'événement

2. **Données réelles** (tableaux ou listes structurées)
   - Données épidémiologiques : cas confirmés, décès, taux d'attaque
   - Données temporelles : chronologie de l'événement
   - Données géographiques : distribution des cas
   - Sources : DHIS2, OMS AFRO, MSF, ministère de la santé

3. **Questions guidées** (4-6 questions progressives)
   - Niveau débutant : questions d'identification et de description
   - Niveau intermédiaire : questions d'analyse et de comparaison
   - Niveau avancé : questions de synthèse et de recommandation
   - Chaque question doit relier les données présentées aux concepts du module

4. **Correction annotée** (réponses détaillées avec justifications)
   - Répond à chaque question guidée avec une explication complète
   - Cite les références bibliographiques utilisées
   - Propose des leçons apprises et recommandations
   - Relie les conclusions aux pratiques de santé publique en AOF

EXIGENCES CRITIQUES :
- Base-toi UNIQUEMENT sur les documents fournis - ne pas inventer d'informations
- Cite tes sources entre crochets [Donaldson Ch.3, p.45]
- Utilise des données réelles ou réalistes pour le contexte AOF
- Adapte la complexité des questions au niveau {level}/4
- Inclure au moins une donnée chiffrée vérifiable

RÉPONSE ATTENDUE : Étude de cas directement utilisable, structurée en 4 sections numérotées."""

    else:
        return f"""You are a public health education expert specializing in West Africa.
You generate adaptive educational case studies for health professionals in {country_name}.

MISSION: Create a structured case study based on a real public health event in West Africa.

USER CONTEXT:
- Country: {country_name}
- Level: {level}/4 (1=beginner, 4=expert)
- Bloom Level: {bloom_level}
- Language: English

REQUIRED STRUCTURE for the case study:

1. **AOF Context** (2-3 paragraphs)
   - Present the geographic, economic and health situation
   - Describe the health system of the country concerned
   - Provide relevant health indicators before the event

2. **Real Data** (tables or structured lists)
   - Epidemiological data: confirmed cases, deaths, attack rates
   - Temporal data: event timeline
   - Geographic data: case distribution
   - Sources: DHIS2, WHO AFRO, MSF, Ministry of Health

3. **Guided Questions** (4-6 progressive questions)
   - Beginner level: identification and description questions
   - Intermediate level: analysis and comparison questions
   - Advanced level: synthesis and recommendation questions
   - Each question must link the presented data to module concepts

4. **Annotated Correction** (detailed answers with justifications)
   - Answers each guided question with full explanation
   - Cites used bibliographic references
   - Proposes lessons learned and recommendations
   - Links conclusions to public health practices in West Africa

CRITICAL REQUIREMENTS:
- Base content ONLY on provided documents - do not invent information
- Cite sources in brackets [Donaldson Ch.3, p.45]
- Use real or realistic data for AOF context
- Adapt question complexity to level {level}/4
- Include at least one verifiable numeric data point

EXPECTED RESPONSE: Directly usable case study, structured in 4 numbered sections."""


def format_rag_context_for_case_study(
    chunks: list,
    query: str,
    module_title: str,
    unit_id: str,
    language: Literal["fr", "en"],
    module_id: str | None = None,
) -> str:
    """Format RAG chunks into context for case study generation."""

    module_key = module_id.upper() if module_id else None
    topic = None
    if module_key and module_key in CASE_STUDY_TOPICS:
        topic = CASE_STUDY_TOPICS[module_key][language]

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
