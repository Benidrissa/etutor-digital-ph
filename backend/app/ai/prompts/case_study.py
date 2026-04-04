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
    language: Literal["fr", "en"],
    country: str,
    level: int,
    bloom_level: str,
    course_title: str | None = None,
    course_description: str | None = None,
) -> str:
    """Generate system prompt for case study content generation."""

    country_names = COUNTRY_NAMES_FR if language == "fr" else COUNTRY_NAMES_EN
    country_name = country_names.get(country, country)

    if language == "fr":
        if course_title:
            expert_role = f"Tu es un expert pédagogue en {course_title} spécialisé pour le contexte d'Afrique de l'Ouest."
            audience_line = f"Tu génères des études de cas éducatives adaptatives pour des professionnels au {country_name} dans le domaine : {course_title}."
            mission_line = f"Créer une étude de cas structurée basée sur une situation réelle liée à {course_title} en AOF."
            context_section = (
                f"   - Présente la situation géographique, économique et organisationnelle\n"
                f"   - Décrit le contexte institutionnel du pays concerné\n"
                f"   - Fournit les indicateurs pertinents pour {course_title} avant l'événement"
            )
            data_sources = "   - Sources : organisations professionnelles, rapports institutionnels, données du secteur"
            conclusion_line = f"   - Relie les conclusions aux pratiques de {course_title} en AOF"
        else:
            expert_role = (
                "Tu es un expert pédagogue en santé publique spécialisé en Afrique de l'Ouest."
            )
            audience_line = f"Tu génères des études de cas éducatives adaptatives pour des professionnels de santé au {country_name}."
            mission_line = "Créer une étude de cas structurée basée sur un événement de santé publique réel en AOF."
            context_section = (
                "   - Présente la situation géographique, économique et sanitaire\n"
                "   - Décrit le système de santé du pays concerné\n"
                "   - Fournit les indicateurs de santé pertinents avant l'événement"
            )
            data_sources = "   - Sources : DHIS2, OMS AFRO, MSF, ministère de la santé"
            conclusion_line = "   - Relie les conclusions aux pratiques de santé publique en AOF"

        return f"""{expert_role}
{audience_line}

MISSION : {mission_line}

CONTEXTE UTILISATEUR :
- Pays : {country_name}
- Niveau : {level}/4 (1=débutant, 4=expert)
- Niveau de Bloom : {bloom_level}
- Langue : Français

STRUCTURE REQUISE pour l'étude de cas :

1. **Contexte AOF** (2-3 paragraphes)
{context_section}

2. **Données réelles** (tableaux ou listes structurées)
   - Données quantitatives : chiffres clés, indicateurs mesurables
   - Données temporelles : chronologie de l'événement
   - Données géographiques ou organisationnelles : distribution des faits
{data_sources}

3. **Questions guidées** (4-6 questions progressives)
   - Niveau débutant : questions d'identification et de description
   - Niveau intermédiaire : questions d'analyse et de comparaison
   - Niveau avancé : questions de synthèse et de recommandation
   - Chaque question doit relier les données présentées aux concepts du module

4. **Correction annotée** (réponses détaillées avec justifications)
   - Répond à chaque question guidée avec une explication complète
   - Cite les références bibliographiques utilisées
   - Propose des leçons apprises et recommandations
{conclusion_line}

EXIGENCES CRITIQUES :
- Base-toi UNIQUEMENT sur les documents fournis - ne pas inventer d'informations
- Cite tes sources entre crochets [Donaldson Ch.3, p.45]
- Utilise des données réelles ou réalistes pour le contexte AOF
- Adapte la complexité des questions au niveau {level}/4
- Inclure au moins une donnée chiffrée vérifiable

RÉPONSE ATTENDUE : Étude de cas directement utilisable, structurée en 4 sections numérotées."""

    else:
        if course_title:
            expert_role = f"You are an expert educator in {course_title} specializing in the West African context."
            audience_line = f"You generate adaptive educational case studies for professionals in {country_name} in the domain: {course_title}."
            mission_line = f"Create a structured case study based on a real situation related to {course_title} in West Africa."
            context_section = (
                f"   - Present the geographic, economic and organizational situation\n"
                f"   - Describe the institutional context of the country concerned\n"
                f"   - Provide relevant indicators for {course_title} before the event"
            )
            data_sources = (
                "   - Sources: professional organizations, institutional reports, sector data"
            )
            conclusion_line = f"   - Links conclusions to {course_title} practices in West Africa"
        else:
            expert_role = "You are a public health education expert specializing in West Africa."
            audience_line = f"You generate adaptive educational case studies for health professionals in {country_name}."
            mission_line = (
                "Create a structured case study based on a real public health event in West Africa."
            )
            context_section = (
                "   - Present the geographic, economic and health situation\n"
                "   - Describe the health system of the country concerned\n"
                "   - Provide relevant health indicators before the event"
            )
            data_sources = "   - Sources: DHIS2, WHO AFRO, MSF, Ministry of Health"
            conclusion_line = "   - Links conclusions to public health practices in West Africa"

        return f"""{expert_role}
{audience_line}

MISSION: {mission_line}

USER CONTEXT:
- Country: {country_name}
- Level: {level}/4 (1=beginner, 4=expert)
- Bloom Level: {bloom_level}
- Language: English

REQUIRED STRUCTURE for the case study:

1. **AOF Context** (2-3 paragraphs)
{context_section}

2. **Real Data** (tables or structured lists)
   - Quantitative data: key figures, measurable indicators
   - Temporal data: event timeline
   - Geographic or organizational data: distribution of facts
{data_sources}

3. **Guided Questions** (4-6 progressive questions)
   - Beginner level: identification and description questions
   - Intermediate level: analysis and comparison questions
   - Advanced level: synthesis and recommendation questions
   - Each question must link the presented data to module concepts

4. **Annotated Correction** (detailed answers with justifications)
   - Answers each guided question with full explanation
   - Cites used bibliographic references
   - Proposes lessons learned and recommendations
{conclusion_line}

CRITICAL REQUIREMENTS:
- Base content ONLY on provided documents - do not invent information
- Cite sources in brackets [Donaldson Ch.3, p.45]
- Use real or realistic data for West African context
- Adapt question complexity to level {level}/4
- Include at least one verifiable numeric data point

EXPECTED RESPONSE: Directly usable case study, structured in 4 numbered sections."""


def _get_case_study_topic(
    module_id: str | None,
    language: Literal["fr", "en"],
    syllabus_json: dict | None = None,
) -> str | None:
    """Resolve case study topic from syllabus_json or fallback to CASE_STUDY_TOPICS."""
    if syllabus_json:
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
