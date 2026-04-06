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
