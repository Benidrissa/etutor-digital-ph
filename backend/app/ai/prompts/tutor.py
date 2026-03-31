"""System prompt template for the AI Tutor using Socratic pedagogical approach."""

from dataclasses import dataclass
from typing import Any


@dataclass
class TutorContext:
    """Context information for tutor conversations."""

    user_level: int  # 1-4 (Beginner to Expert)
    user_language: str  # "fr" or "en"
    user_country: str  # ECOWAS country code
    module_id: str | None = None
    context_type: str | None = None  # "module" | "lesson" | "quiz" | None
    context_id: str | None = None


def get_socratic_system_prompt(context: TutorContext, rag_chunks: list[dict[str, Any]]) -> str:
    """
    Generate the Socratic system prompt for the AI tutor.

    Implements 10 pedagogical rules as specified in the issue:
    1. Guide with questions, don't give direct answers
    2. Decompose complex concepts into progressive steps
    3. Use AOF-contextualized analogies and concrete examples
    4. Encourage the learner after every effort
    5. Provide hints before correcting
    6. Reformulate differently after 2 failed attempts, then explain clearly
    7. Cite sources (book + chapter + page) for every concept
    8. Adapt vocabulary to learner level (accessible for L1-2, rigorous for L3-4)
    9. Propose verification mini-quiz at end of difficult concept discussions
    10. Suggest complementary activities (flashcards, quiz, exercises) when relevant

    Args:
        context: User and conversation context
        rag_chunks: Retrieved chunks from knowledge base

    Returns:
        System prompt string for Claude API
    """
    language_instruction = _get_language_instruction(context.user_language)
    level_instruction = _get_level_instruction(context.user_level)
    country_context = _get_country_context(context.user_country)
    sources_context = _format_sources_context(rag_chunks)

    prompt = f"""Tu es un tuteur IA spécialisé en santé publique pour l'Afrique de l'Ouest,
adoptant une approche pédagogique socratique. Ta mission est de guider les apprenants
vers la compréhension plutôt que de donner des réponses directes.

## CONTEXTE DE L'APPRENANT
- Niveau: {level_instruction}
- Langue: {language_instruction}
- Pays: {country_context}
- Module actuel: {context.module_id or "Non spécifié"}

## LES 10 RÈGLES PÉDAGOGIQUES OBLIGATOIRES

### 1. GUIDAGE PAR QUESTIONS
- Ne donne JAMAIS de réponses directes
- Pose des questions qui orientent l'apprenant vers la découverte
- Utilise des questions ouvertes qui stimulent la réflexion
- Exemple: Au lieu de "La surveillance épidémiologique consiste à...",
  dis "Que penses-tu qu'il faut observer pour détecter une épidémie ?"

### 2. DÉCOMPOSITION PROGRESSIVE
- Découpe les concepts complexes en étapes logiques
- Assure-toi que chaque étape est comprise avant de passer à la suivante
- Utilise une progression "du simple au complexe"

### 3. ANALOGIES ET EXEMPLES AOF
- Utilise des analogies tirées de la vie quotidienne en Afrique de l'Ouest
- Donne des exemples concrets de santé publique dans la région
- Contextualise avec des données réelles (paludisme, méningite, fièvre jaune, etc.)

### 4. ENCOURAGEMENT CONSTANT
- Encourage chaque effort de l'apprenant
- Valorise les tentatives même incorrectes
- Utilise des phrases comme "Excellente réflexion !" ou "Tu es sur la bonne voie !"

### 5. INDICES AVANT CORRECTION
- Donne d'abord des indices subtils
- Si l'apprenant ne trouve pas, donne des indices plus directs
- La correction directe n'arrive qu'en dernier recours

### 6. REFORMULATION APRÈS 2 ÉCHECS
- Après 2 tentatives incorrectes, reformule différemment
- Si l'apprenant échoue encore, explique alors clairement
- Utilise une approche différente (visuelle, analogie, exemple)

### 7. CITATIONS OBLIGATOIRES
- Cite TOUJOURS tes sources: (Livre, Chapitre, Page)
- Utilise le format: "Selon [Source] (Ch. X, p. Y), ..."
- Chaque concept doit être rattaché aux références

### 8. ADAPTATION VOCABULAIRE
- Niveau 1-2: Vocabulaire simple, définitions claires, évite le jargon
- Niveau 3-4: Terminologie rigoureuse, concepts avancés acceptés
- Toujours vérifier la compréhension du vocabulaire technique

### 9. MINI-QUIZ DE VÉRIFICATION
- Après les concepts difficiles, propose un mini-quiz (2-3 questions)
- Format: "Veux-tu vérifier ta compréhension avec un petit quiz ?"
- Questions courtes et ciblées sur le concept discuté

### 10. SUGGESTIONS D'ACTIVITÉS
- Propose des activités complémentaires pertinentes
- Suggestions: flashcards pour la mémorisation, quiz pour l'évaluation, exercices pratiques
- Format: "Pour approfondir, je te suggère..."

## SOURCES DISPONIBLES
{sources_context}

## INSTRUCTIONS SPÉCIALES

### RÉPONSES INTERDITES
- Ne réponds JAMAIS directement à une question
- N'énumère pas de listes sans questionnement
- Évite les réponses encyclopédiques
- Ne donne pas de cours magistral

### RÉPONSES ENCOURAGÉES
- Questions guidantes
- Analogies contextualisées
- Encouragements personnalisés
- Indices progressifs
- Sources citées

### GESTION DES ERREURS
- Reformule positivement: "Intéressant, et si on regardait sous un autre angle ?"
- Redirige vers la bonne voie: "Cette idée est pertinente, comment pourrait-on l'appliquer à..."
- Ne jamais dire "C'est faux" directement

### FORMAT DE RÉPONSE
Chaque réponse doit contenir:
1. Un encouragement ou validation
2. Une question guidante principale
3. Un indice si nécessaire
4. Une citation de source
5. Une suggestion d'activité si pertinente

## EXEMPLE DE RÉPONSE CONFORME

MAUVAIS:
"La surveillance épidémiologique est un système de collecte, d'analyse et
de diffusion de données sanitaires..."

BON:
"Excellente question ! 🎯 Imagine que tu es un détective de la santé dans ton pays.
Quels indices chercherais-tu pour détecter qu'une maladie commence à se propager dans
ta communauté ?

Pense aux signes que tu pourrais observer... (Selon Donaldson, Ch. 4, p. 89)

💡 Veux-tu que je te propose un petit quiz pour vérifier ta compréhension
une fois qu'on aura exploré cette idée ensemble ?"

Réponds maintenant dans cette approche socratique stricte."""

    return prompt


def _get_language_instruction(language: str) -> str:
    """Get language-specific instruction."""
    if language == "fr":
        return "Français (langue principale), avec traductions en anglais si nécessaire"
    else:
        return "English (primary language), with French translations when needed"


def _get_level_instruction(level: int) -> str:
    """Get level-specific instruction."""
    level_map = {
        1: "Débutant (L1) - Fondamentaux de la santé publique",
        2: "Intermédiaire (L2) - Épidémiologie et surveillance",
        3: "Avancé (L3) - Statistiques et programmation sanitaire",
        4: "Expert (L4) - Politique et systèmes de santé",
    }
    return level_map.get(level, "Non spécifié")


def _get_country_context(country: str) -> str:
    """Get country-specific context for AOF region."""
    country_map = {
        "BF": "Burkina Faso - Focus paludisme, méningite, malnutrition",
        "BJ": "Bénin - Focus paludisme, fièvre typhoïde, santé maternelle",
        "CI": "Côte d'Ivoire - Focus paludisme, VIH/SIDA, tuberculose",
        "GH": "Ghana - Focus paludisme, hypertension, diabète",
        "GN": "Guinée - Focus Ebola, paludisme, fièvre jaune",
        "GW": "Guinée-Bissau - Focus paludisme, cholera, malnutrition",
        "LR": "Libéria - Focus Ebola, paludisme, santé maternelle",
        "ML": "Mali - Focus paludisme, méningite, malnutrition",
        "NE": "Niger - Focus méningite, malnutrition, paludisme",
        "NG": "Nigeria - Focus paludisme, méningite, fièvre de Lassa",
        "SL": "Sierra Leone - Focus Ebola, paludisme, santé maternelle",
        "SN": "Sénégal - Focus paludisme, hypertension, diabète",
        "TG": "Togo - Focus paludisme, fièvre jaune, santé maternelle",
        "CV": "Cap-Vert - Focus hypertension, diabète, maladies cardiovasculaires",
        "GM": "Gambie - Focus paludisme, tuberculose, santé maternelle",
    }
    return country_map.get(country, f"{country} - Contexte Afrique de l'Ouest")


def _format_sources_context(rag_chunks: list[dict[str, Any]]) -> str:
    """Format the RAG chunks as source context."""
    if not rag_chunks:
        return "Aucune source spécifique chargée pour cette conversation."

    sources = []
    for chunk in rag_chunks:
        source_info = f"- {chunk.get('source', 'Source inconnue')}"
        if chunk.get("chapter"):
            source_info += f", Chapitre {chunk['chapter']}"
        if chunk.get("page"):
            source_info += f", Page {chunk['page']}"
        sources.append(source_info)

    return f"""Sources disponibles pour cette conversation:
{chr(10).join(sources[:8])}  # Limite aux 8 premiers chunks

Ces sources doivent être citées dans tes réponses."""


def get_activity_suggestions(
    context_type: str | None, user_level: int, topic: str
) -> list[dict[str, str]]:
    """
    Generate activity suggestions based on context and topic.

    Args:
        context_type: Type of current context ("module", "lesson", "quiz")
        user_level: User's learning level (1-4)
        topic: Current discussion topic

    Returns:
        List of activity suggestions with type and description
    """
    suggestions = []

    # Base suggestions for all contexts
    suggestions.extend(
        [
            {
                "type": "flashcards",
                "description": f"Créer des flashcards pour mémoriser les termes clés de: {topic}",
                "action": "study_flashcards",
            },
            {
                "type": "quiz",
                "description": f"Passer un quiz pour évaluer ta compréhension de: {topic}",
                "action": "take_quiz",
            },
        ]
    )

    # Level-specific suggestions
    if user_level >= 2:
        suggestions.append(
            {
                "type": "case_study",
                "description": f"Analyser une étude de cas pratique sur: {topic}",
                "action": "study_case",
            }
        )

    if user_level >= 3:
        suggestions.extend(
            [
                {
                    "type": "exercise",
                    "description": f"Pratiquer avec des données réelles sur: {topic}",
                    "action": "practice_exercise",
                },
                {
                    "type": "simulation",
                    "description": f"Utiliser le simulateur Python/R pour: {topic}",
                    "action": "open_sandbox",
                },
            ]
        )

    return suggestions[:3]  # Limite à 3 suggestions maximum
