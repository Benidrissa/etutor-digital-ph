"""Claude prompts for pre-assessment generation."""

from app.ai.prompts.lesson import _apply_settings_template


def get_preassessment_system_prompt(
    language: str,
    course_title: str,
    course_description: str | None = None,
    course_domain: str = "",
    module_titles: list[str] | None = None,
) -> str:
    """Return system prompt for pre-assessment generation."""
    module_list = ""
    if module_titles:
        module_list = "\n".join(f"- {t}" for t in module_titles)
    return _apply_settings_template(
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
        module_list=module_list,
    )


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
