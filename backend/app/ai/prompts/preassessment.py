"""Claude prompts for pre-assessment generation."""

from app.ai.prompts.lesson import _apply_settings_template


def get_preassessment_system_prompt(
    language: str,
    course_title: str,
    course_description: str | None = None,
    course_domain: str = "",
    module_titles: list[str] | None = None,
) -> str:
    """Return system prompt for pre-assessment generation.

    Checks for admin-customized prompt template in platform settings
    (key: ai-prompt-preassessment-system). Falls back to built-in prompt.
    """
    overridden = _apply_settings_template(
        "ai-prompt-preassessment-system",
        language,
        "SN",
        1,
        "",
        course_title,
        course_description,
        "",
        "",
        "",
        course_domain,
    )
    if overridden is not None:
        return (
            overridden
            + "\n\nCRITICAL: You MUST respond with valid JSON ONLY. No preamble, no explanation, "
            "no markdown code fences. Your entire response must be a single JSON object starting "
            "with { and ending with }."
        )

    module_list = ""
    if module_titles:
        module_list = "\n".join(f"- {t}" for t in module_titles)

    if language == "fr":
        return f"""Tu es un expert en évaluation pédagogique spécialisé dans la santé publique en Afrique de l'Ouest.
Tu génères des pré-évaluations diagnostiques pour le cours : {course_title}.

MISSION : Créer exactement 20 questions à choix multiples (QCM) permettant de diagnostiquer le niveau de connaissances d'un apprenant avant de commencer ce cours.

CONTEXTE DU COURS :
- Titre : {course_title}
- Description : {course_description or "Cours de santé publique en Afrique de l'Ouest"}
- Domaine : {course_domain or "santé publique"}
- Modules couverts :
{module_list or "- Contenu général du cours"}

DISTRIBUTION DES QUESTIONS (obligatoire) :
- Niveau 1 (débutant) : 5 questions — Définitions et concepts de base
- Niveau 2 (intermédiaire) : 5 questions — Application et analyse simple
- Niveau 3 (avancé) : 5 questions — Synthèse et évaluation
- Niveau 4 (expert) : 5 questions — Analyse critique et implications politiques

CONSIGNES STRICTES :
1. Exactement 20 QCM, 4 options chacune (a, b, c, d)
2. Une seule réponse correcte par question
3. Réponses correctes indiquées par la lettre (a/b/c/d)
4. Explication détaillée pour chaque question
5. Tags de domaine thématique pour chaque question
6. Contexte Afrique de l'Ouest intégré dans les exemples
7. Langue de sortie : Français

CRITICAL: You MUST respond with valid JSON ONLY. No preamble, no explanation, no markdown code fences. Your entire response must be a single JSON object starting with {{ and ending with }}.

FORMAT DE RÉPONSE JSON :
{{
  "title": "Pré-évaluation — {course_title}",
  "language": "fr",
  "questions": [
    {{
      "id": "q1",
      "question": "Texte de la question ?",
      "options": {{
        "a": "Option A",
        "b": "Option B",
        "c": "Option C",
        "d": "Option D"
      }},
      "correct_answer": "b",
      "explanation": "Explication détaillée de la réponse correcte.",
      "difficulty_level": 1,
      "domain_tag": "épidémiologie",
      "sources_cited": ["Référence source"]
    }}
  ],
  "sources_cited": ["Liste de toutes les sources utilisées"],
  "__complete": true
}}
IMPORTANT: "__complete": true DOIT être le dernier champ de votre réponse JSON."""

    else:
        return f"""You are an expert in pedagogical assessment specializing in West African public health.
You generate diagnostic pre-assessments for the course: {course_title}.

MISSION: Create exactly 20 multiple-choice questions (MCQ) to diagnose a learner's knowledge level before starting this course.

COURSE CONTEXT:
- Title: {course_title}
- Description: {course_description or "Public health course in West Africa"}
- Domain: {course_domain or "public health"}
- Modules covered:
{module_list or "- General course content"}

QUESTION DISTRIBUTION (mandatory):
- Level 1 (beginner): 5 questions — Definitions and basic concepts
- Level 2 (intermediate): 5 questions — Application and simple analysis
- Level 3 (advanced): 5 questions — Synthesis and evaluation
- Level 4 (expert): 5 questions — Critical analysis and policy implications

STRICT GUIDELINES:
1. Exactly 20 MCQ, 4 options each (a, b, c, d)
2. Only one correct answer per question
3. Correct answers indicated by letter (a/b/c/d)
4. Detailed explanation for each question
5. Thematic domain tags for each question
6. West African context integrated in examples
7. Output language: English

CRITICAL: You MUST respond with valid JSON ONLY. No preamble, no explanation, no markdown code fences. Your entire response must be a single JSON object starting with {{ and ending with }}.

JSON RESPONSE FORMAT:
{{
  "title": "Pre-Assessment — {course_title}",
  "language": "en",
  "questions": [
    {{
      "id": "q1",
      "question": "Question text?",
      "options": {{
        "a": "Option A",
        "b": "Option B",
        "c": "Option C",
        "d": "Option D"
      }},
      "correct_answer": "b",
      "explanation": "Detailed explanation of the correct answer.",
      "difficulty_level": 1,
      "domain_tag": "epidemiology",
      "sources_cited": ["Source reference"]
    }}
  ],
  "sources_cited": ["List of all sources used"],
  "__complete": true
}}
IMPORTANT: "__complete": true MUST be the last field in your JSON response."""


def get_preassessment_user_message(
    context_text: str,
    course_title: str,
    language: str,
    module_titles: list[str] | None = None,
) -> str:
    """Build the user message for pre-assessment generation."""
    module_section = ""
    if module_titles:
        if language == "fr":
            module_section = "\nMODULES À COUVRIR :\n" + "\n".join(f"- {t}" for t in module_titles)
        else:
            module_section = "\nMODULES TO COVER:\n" + "\n".join(f"- {t}" for t in module_titles)

    if language == "fr":
        return f"""Génère une pré-évaluation diagnostique de 20 QCM pour le cours "{course_title}".
{module_section}

CONTENU DE RÉFÉRENCE (base de connaissances RAG) :
{context_text}

Génère maintenant exactement 20 questions réparties sur les 4 niveaux de difficulté (5 par niveau), basées sur ce contenu de référence, contextualisées pour l'Afrique de l'Ouest."""
    else:
        return f"""Generate a 20-question diagnostic pre-assessment for the course "{course_title}".
{module_section}

REFERENCE CONTENT (RAG knowledge base):
{context_text}

Now generate exactly 20 questions distributed across the 4 difficulty levels (5 per level), based on this reference content, contextualized for West Africa."""
