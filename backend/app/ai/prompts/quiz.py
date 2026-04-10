"""Claude prompts for quiz generation."""

from typing import TYPE_CHECKING

from app.ai.prompts.lesson import _apply_settings_template

if TYPE_CHECKING:
    from app.domain.models.course import Course


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
    course: "Course | None" = None,
) -> str:
    """Return quiz system prompt rendered from platform settings template."""
    from app.ai.prompts.audience import detect_audience, get_audience_guidance

    audience = detect_audience(course)
    key = "ai-prompt-quiz-kids-system" if audience.is_kids else "ai-prompt-quiz-system"
    extra: dict = {}
    if audience.is_kids:
        extra["age_range"] = f"{audience.age_min}-{audience.age_max}"
        extra["audience_guidance"] = get_audience_guidance(audience, language)
    return _apply_settings_template(
        key,
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
        **extra,
    )
