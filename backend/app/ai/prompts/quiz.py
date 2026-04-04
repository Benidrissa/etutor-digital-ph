"""Claude prompts for quiz generation."""

from app.ai.prompts.lesson import _apply_settings_template


def get_quiz_system_prompt(
    language: str,
    country: str,
    level: int,
    bloom_level: str,
    course_title: str | None = None,
    course_description: str | None = None,
    module_title: str = "",
    unit_title: str = "",
    syllabus_context: str = "",
    course_domain: str = "",
) -> str | None:
    """Return admin-overridden quiz system prompt or None to use built-in logic.

    When an admin has customized the quiz system prompt template in platform
    settings, returns the rendered string. Otherwise returns None so
    quiz_service._build_quiz_prompt() falls back to its built-in prompt logic.
    """
    return _apply_settings_template(
        "ai-prompt-quiz-system",
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


QUIZ_GENERATION_PROMPT = """
Tu es un expert spécialisé dans la création de contenus pédagogiques pour l'Afrique de l'Ouest
dans le domaine : {course_context}.

Tu dois créer un quiz formatif de 10 questions à choix multiples (QCM) basé sur le contenu fourni.

## Consignes strictes:

1. **Questions**: Exactement 10 QCM avec 4 options chacune
2. **Distribution de difficulté**: 3 faciles, 4 moyennes, 3 difficiles
3. **Format de réponse**: Une seule option correcte par question
4. **Explication**: Chaque question doit avoir une explication détaillée
5. **Sources**: Chaque question doit citer sa source (chapitre, page)

## Adaptation contextuelle:
- **Domaine**: {course_context}
- **Langue**: {language}
- **Niveau**: Adapté au niveau utilisateur
- **Contexte**: Inclure des exemples pertinents pour l'Afrique de l'Ouest dans le domaine {course_context}

## Types de questions à créer:
- **Faciles (3)**: Définitions, concepts de base, mémorisation
- **Moyennes (4)**: Application pratique, analyse simple, comparaisons
- **Difficiles (3)**: Analyse critique, synthèse, cas complexes

## Structure de réponse requise:

```json
{{
  "title": "Quiz - [Titre du sujet]",
  "questions": [
    {{
      "question": "Texte de la question ?",
      "options": [
        {{"text": "Option A", "is_correct": false}},
        {{"text": "Option B", "is_correct": true}},
        {{"text": "Option C", "is_correct": false}},
        {{"text": "Option D", "is_correct": false}}
      ],
      "explanation": "Explication détaillée de la réponse correcte avec justification pédagogique.",
      "difficulty": "easy|medium|hard",
      "source_reference": "Source Ch.X, p.Y"
    }}
  ],
  "estimated_duration_minutes": 15,
  "sources_cited": ["Liste de toutes les sources utilisées"]
}}
```

## Critères de qualité:

1. **Précision**: Informations exactes et à jour pour {course_context}
2. **Pertinence pédagogique**: Questions alignées sur les objectifs d'apprentissage
3. **Clarté**: Formulation claire et non ambiguë
4. **Diversité**: Variété dans les types de questions et concepts couverts
5. **Contextualisation**: Exemples adaptés à l'Afrique de l'Ouest dans le domaine {course_context}

## Distracteurs (mauvaises options):
- Plausibles mais incorrects
- Éviter les options évidentes ou absurdes
- Basés sur des malentendus communs
- Cohérents avec le niveau de difficulté

Génère maintenant le quiz basé sur ce contenu:

{content}
"""


QUIZ_GENERATION_PROMPT_EN = """
You are an expert specializing in creating educational content for West Africa
in the domain: {course_context}.

You must create a formative quiz with 10 multiple-choice questions (MCQ)
based on the provided content.

## Strict guidelines:

1. **Questions**: Exactly 10 MCQ with 4 options each
2. **Difficulty distribution**: 3 easy, 4 medium, 3 hard
3. **Answer format**: Only one correct option per question
4. **Explanation**: Each question must have a detailed explanation
5. **Sources**: Each question must cite its source (chapter, page)

## Contextual adaptation:
- **Domain**: {course_context}
- **Language**: {language}
- **Level**: Adapted to user level
- **Context**: Include relevant examples for West Africa when appropriate for {course_context}

## Types of questions to create:
- **Easy (3)**: Definitions, basic concepts, memorization
- **Medium (4)**: Practical application, simple analysis, comparisons
- **Hard (3)**: Critical analysis, synthesis, complex cases

## Required response structure:

```json
{{
  "title": "Quiz - [Subject Title]",
  "questions": [
    {{
      "question": "Question text?",
      "options": [
        {{"text": "Option A", "is_correct": false}},
        {{"text": "Option B", "is_correct": true}},
        {{"text": "Option C", "is_correct": false}},
        {{"text": "Option D", "is_correct": false}}
      ],
      "explanation": "Detailed explanation of the correct answer with pedagogical justification.",
      "difficulty": "easy|medium|hard",
      "source_reference": "Source Ch.X, p.Y"
    }}
  ],
  "estimated_duration_minutes": 15,
  "sources_cited": ["List of all sources used"]
}}
```

## Quality criteria:

1. **Accuracy**: Exact and up-to-date information for {course_context}
2. **Pedagogical relevance**: Questions aligned with learning objectives
3. **Clarity**: Clear and unambiguous formulation
4. **Diversity**: Variety in question types and concepts covered
5. **Contextualization**: Examples adapted to West Africa in the domain {course_context}

## Distractors (incorrect options):
- Plausible but incorrect
- Avoid obvious or absurd options
- Based on common misunderstandings
- Consistent with difficulty level

Now generate the quiz based on this content:

{content}
"""
