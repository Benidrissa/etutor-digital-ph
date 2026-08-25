"""Unit tests for admin supplementary instructions in syllabus prompts (#2572).

The course creator can provide free-text guidance on the wizard's generate step;
it must appear as a delimited priority-guidance block in both the adult and kids
prompts, and survive admin prompt overrides (substituted when the template has
the {syllabus_instructions} placeholder, appended when it doesn't).
"""

from unittest.mock import MagicMock, patch

from app.domain.services.course_agent_service import CourseAgentService

BLOCK_HEADER = "PRIORITY GUIDANCE FROM THE COURSE CREATOR"
OPEN_TAG = "<creator_instructions>"
CLOSE_TAG = "</creator_instructions>"


def _build(svc: CourseAgentService, **overrides) -> str:
    kwargs = {
        "title_fr": "Épidémiologie",
        "title_en": "Epidemiology",
        "domains_str": "Public Health",
        "levels_str": "intermediate",
        "audience_str": "Professionals",
        "estimated_hours": 40,
        "resource_block": "",
        "audience_type": ["professionals"],
    }
    kwargs.update(overrides)
    return svc._build_prompt(**kwargs)


class TestInstructionsBlockDefaultPrompts:
    def test_adult_prompt_contains_delimited_block(self):
        svc = CourseAgentService()
        prompt = _build(svc, syllabus_instructions="Structurer autour de la méthodologie RDQA")

        assert BLOCK_HEADER in prompt
        assert OPEN_TAG in prompt
        assert CLOSE_TAG in prompt
        assert "Structurer autour de la méthodologie RDQA" in prompt

    def test_block_sits_between_objectives_and_resources(self):
        svc = CourseAgentService()
        prompt = _build(
            svc,
            syllabus_instructions="Focus on field examples",
            objectives_json={"fr": ["Comprendre la surveillance"]},
            resource_block="## Reference materials (full text)\nchapter one",
        )

        assert prompt.index("Course Objectives") < prompt.index(BLOCK_HEADER)
        assert prompt.index(BLOCK_HEADER) < prompt.index("Reference materials")

    def test_none_produces_no_block(self):
        svc = CourseAgentService()
        prompt = _build(svc, syllabus_instructions=None)

        assert BLOCK_HEADER not in prompt
        assert OPEN_TAG not in prompt

    def test_whitespace_only_produces_no_block(self):
        svc = CourseAgentService()
        prompt = _build(svc, syllabus_instructions="   \n\t ")

        assert BLOCK_HEADER not in prompt

    def test_instructions_are_stripped(self):
        svc = CourseAgentService()
        prompt = _build(svc, syllabus_instructions="  keep the core  ")

        assert f"{OPEN_TAG}\nkeep the core\n{CLOSE_TAG}" in prompt

    def test_kids_prompt_contains_block(self):
        svc = CourseAgentService()
        prompt = _build(
            svc,
            title_fr="Maths au Village (6-12 ans)",
            title_en="Village Math (Ages 6-12)",
            audience_str="primary_school",
            audience_type=["primary_school"],
            syllabus_instructions="Use farm animals in examples",
        )

        assert "Piaget" in prompt  # sanity: kids prompt was selected
        assert BLOCK_HEADER in prompt
        assert "Use farm animals in examples" in prompt


class TestInstructionsWithAdminOverride:
    def _patched_cache(self, template: str):
        mock_defn = MagicMock()
        mock_defn.default = "default_value"
        mock_cache = MagicMock()
        mock_cache.get.return_value = template
        return (
            patch("app.domain.services.platform_settings_service.SettingsCache"),
            patch(
                "app.infrastructure.config.platform_defaults.DEFAULTS_BY_KEY",
                {
                    "ai-prompt-syllabus-system": mock_defn,
                    "ai-prompt-syllabus-kids-system": mock_defn,
                },
            ),
            mock_cache,
        )

    def test_template_with_placeholder_gets_block_substituted(self):
        svc = CourseAgentService()
        cache_patch, defaults_patch, mock_cache = self._patched_cache(
            "Custom prompt for {course_title}.\n{syllabus_instructions}\nEnd."
        )
        with cache_patch as mock_cache_cls, defaults_patch:
            mock_cache_cls.instance.return_value = mock_cache
            prompt = _build(svc, syllabus_instructions="Prioritize RDQA")

        assert prompt.startswith("Custom prompt for")
        assert BLOCK_HEADER in prompt
        assert "Prioritize RDQA" in prompt
        assert prompt.count(BLOCK_HEADER) == 1

    def test_template_without_placeholder_gets_block_appended(self):
        svc = CourseAgentService()
        cache_patch, defaults_patch, mock_cache = self._patched_cache(
            "Custom prompt without the new placeholder for {course_title}."
        )
        with cache_patch as mock_cache_cls, defaults_patch:
            mock_cache_cls.instance.return_value = mock_cache
            prompt = _build(svc, syllabus_instructions="Prioritize RDQA")

        assert prompt.startswith("Custom prompt without the new placeholder")
        assert BLOCK_HEADER in prompt
        assert "Prioritize RDQA" in prompt

    def test_template_without_placeholder_unchanged_when_no_instructions(self):
        svc = CourseAgentService()
        cache_patch, defaults_patch, mock_cache = self._patched_cache(
            "Custom prompt without the new placeholder for {course_title}."
        )
        with cache_patch as mock_cache_cls, defaults_patch:
            mock_cache_cls.instance.return_value = mock_cache
            prompt = _build(svc, syllabus_instructions=None)

        assert BLOCK_HEADER not in prompt
        assert prompt == (
            "Custom prompt without the new placeholder for Épidémiologie / Epidemiology."
        )
