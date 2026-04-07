"""Course content creator agent — generates full course structure via Claude API."""

import os
import uuid
from typing import Any

import structlog

from app.ai.model_registry import get_model_caps

logger = structlog.get_logger(__name__)

_PLACEHOLDER_MODULES = [
    {
        "module_number": 1,
        "title_fr": "Introduction au domaine",
        "title_en": "Introduction to the field",
        "description_fr": "Les bases essentielles du domaine.",
        "description_en": "The essential foundations of the field.",
        "estimated_hours": 20,
        "bloom_level": "remember",
    },
    {
        "module_number": 2,
        "title_fr": "Concepts fondamentaux",
        "title_en": "Core concepts",
        "description_fr": "Approfondissement des concepts clés.",
        "description_en": "Deep dive into key concepts.",
        "estimated_hours": 25,
        "bloom_level": "understand",
    },
]


class CourseAgentService:
    """Generates course structure using Claude API, with graceful fallback."""

    def _get_admin_prompt(self, **template_vars: str) -> str | None:
        """Check if admin has customized the syllabus prompt via platform settings."""
        try:
            from app.domain.services.platform_settings_service import SettingsCache
            from app.infrastructure.config.platform_defaults import DEFAULTS_BY_KEY

            key = "ai-prompt-syllabus-system"
            defn = DEFAULTS_BY_KEY.get(key)
            if defn is None:
                return None

            current = SettingsCache.instance().get(key)
            if current is None or current == defn.default:
                return None

            safe_vars = {k: v or "" for k, v in template_vars.items()}
            return current.format_map(safe_vars)
        except Exception as e:
            logger.warning("Failed to apply admin syllabus prompt", error=str(e))
            return None

    def _build_prompt(
        self,
        title_fr: str,
        title_en: str,
        domains_str: str,
        levels_str: str,
        audience_str: str,
        estimated_hours: int,
        resource_block: str,
    ) -> str:
        """Build the syllabus generation prompt, using admin override if available."""
        admin = self._get_admin_prompt(
            course_title=f"{title_fr} / {title_en}",
            course_domain=domains_str,
            level=levels_str,
            estimated_hours=str(estimated_hours),
            resource_text=resource_block,
        )
        if admin:
            return admin
        return (
            "You are an expert instructional designer specializing in "
            "bilingual (FR/EN) adaptive e-learning. You design curricula "
            "using Bloom's taxonomy, Knowles' andragogy, the ADDIE model, "
            "and spiral learning.\n\n"
            f"Create a complete course syllabus for:\n"
            f"- Title FR: {title_fr}\n"
            f"- Title EN: {title_en}\n"
            f"- Domain(s): {domains_str}\n"
            f"- Level(s): {levels_str}\n"
            f"- Target audience: {audience_str}\n"
            f"- Estimated total hours: {estimated_hours}\n\n"
            f"{resource_block}\n\n"
            "## Design principles (mandatory)\n"
            "- Progressive complexity: start with foundational concepts "
            "(remember/understand), build to applied skills "
            "(apply/analyze), end with expert synthesis "
            "(evaluate/create)\n"
            "- Each module must be self-contained (10-25h) with clear "
            "learning objectives\n"
            "- Units are micro-learning (10-15 min each), 3-6 lessons "
            "per module\n"
            "- Every module includes: lessons, a formative quiz per "
            "lesson, a summative module quiz (20 questions, 80% pass), "
            "flashcards (20-40 bilingual cards), and a practical case "
            "study contextualized to the target audience\n"
            "- Bilingual: all text in both FR and EN\n\n"
            "## Output format\n"
            "Return a JSON array of modules. Each module must have:\n"
            "{\n"
            '  "module_number": int,\n'
            '  "title_fr": str, "title_en": str,\n'
            '  "description_fr": str, "description_en": str,\n'
            '  "estimated_hours": int,\n'
            '  "bloom_level": "remember"|"understand"|"apply"|'
            '"analyze"|"evaluate"|"create",\n'
            '  "learning_objectives_fr": [str], '
            '"learning_objectives_en": [str],\n'
            '  "units": [\n'
            '    {"title_fr": str, "title_en": str, '
            '"type": "lesson"|"quiz"|"case-study",\n'
            '     "description_fr": str, "description_en": str}\n'
            "  ],\n"
            '  "quiz_topics_fr": [str], '
            '"quiz_topics_en": [str],\n'
            '  "flashcard_categories_fr": [str], '
            '"flashcard_categories_en": [str],\n'
            '  "case_study_fr": str, "case_study_en": str\n'
            "}\n\n"
            "Return ONLY valid JSON, no markdown fences, "
            "no explanation."
        )

    async def generate_course_structure(
        self,
        title_fr: str,
        title_en: str,
        course_domain: list[str] | None = None,
        course_level: list[str] | None = None,
        audience_type: list[str] | None = None,
        estimated_hours: int = 20,
        resource_text: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Generate a course module outline using Claude API.

        Returns a list of module dicts with title_fr, title_en, description,
        estimated_hours, bloom_level, and a sequential module_number.
        Falls back to 2 placeholder modules if ANTHROPIC_API_KEY is not set.
        """
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            logger.warning(
                "ANTHROPIC_API_KEY not set — returning placeholder modules",
                course=title_en,
            )
            return _PLACEHOLDER_MODULES

        try:
            import anthropic

            client = anthropic.AsyncAnthropic(api_key=api_key)

            domains_str = ", ".join(course_domain) if course_domain else "General"
            levels_str = ", ".join(course_level) if course_level else "All levels"
            audience_str = ", ".join(audience_type) if audience_type else "Professionals"

            def _make_resource_block(text: str | None) -> str:
                if not text:
                    return ""
                return (
                    "## Reference materials (full text)\n"
                    "The following is the complete extracted text from the course's "
                    "reference materials. You MUST base the syllabus on this content — "
                    "every module and unit should map to actual chapters, topics, and "
                    "concepts found in these materials. Do NOT invent topics that are "
                    "not covered in the references.\n\n"
                    f"{text}"
                )

            resource_block = _make_resource_block(resource_text)
            prompt = self._build_prompt(
                title_fr,
                title_en,
                domains_str,
                levels_str,
                audience_str,
                estimated_hours,
                resource_block,
            )

            import json

            _model = "claude-sonnet-4-6"
            caps = get_model_caps(_model)
            prompt_tokens_est = len(prompt) / caps["chars_per_token"]
            available = caps["context_window_tokens"] - caps["max_output_tokens"] - 5_000
            if prompt_tokens_est > available and resource_text:
                excess_chars = int((prompt_tokens_est - available) * caps["chars_per_token"])
                resource_text = resource_text[:-excess_chars]
                logger.warning(
                    "Truncated resource_text to fit context window",
                    excess_chars=excess_chars,
                )
                resource_block = _make_resource_block(resource_text)
                prompt = self._build_prompt(
                    title_fr,
                    title_en,
                    domains_str,
                    levels_str,
                    audience_str,
                    estimated_hours,
                    resource_block,
                )

            # Use streaming to avoid timeout with large max_tokens
            async with client.messages.stream(
                model=_model,
                max_tokens=64000,
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                message = await stream.get_final_message()

            # Check for truncation
            if message.stop_reason == "max_tokens":
                logger.warning(
                    "Response truncated at max_tokens, retrying",
                    course=title_en,
                )
                async with client.messages.stream(
                    model=_model,
                    max_tokens=64000,
                    messages=[
                        {"role": "user", "content": prompt},
                        {"role": "assistant", "content": message.content[0].text},
                        {
                            "role": "user",
                            "content": "The JSON was truncated. Please complete it "
                            "from where you stopped. Return ONLY the remaining "
                            "JSON to complete the array.",
                        },
                    ],
                ) as stream:
                    message = await stream.get_final_message()

            raw = message.content[0].text.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            modules_raw: list[dict[str, Any]] = json.loads(raw)

            modules = []
            for i, m in enumerate(modules_raw, start=1):
                modules.append(
                    {
                        "module_number": i,
                        "title_fr": m.get("title_fr", f"Module {i}"),
                        "title_en": m.get("title_en", f"Module {i}"),
                        "description_fr": m.get("description_fr"),
                        "description_en": m.get("description_en"),
                        "estimated_hours": int(m.get("estimated_hours", 20)),
                        "bloom_level": m.get("bloom_level", "understand"),
                        "learning_objectives_fr": m.get("learning_objectives_fr", []),
                        "learning_objectives_en": m.get("learning_objectives_en", []),
                        "units": m.get("units", []),
                        "quiz_topics_fr": m.get("quiz_topics_fr", []),
                        "quiz_topics_en": m.get("quiz_topics_en", []),
                        "flashcard_categories_fr": m.get("flashcard_categories_fr", []),
                        "flashcard_categories_en": m.get("flashcard_categories_en", []),
                        "case_study_fr": m.get("case_study_fr"),
                        "case_study_en": m.get("case_study_en"),
                    }
                )

            logger.info(
                "Course structure generated",
                course=title_en,
                module_count=len(modules),
            )
            return modules

        except Exception as e:
            logger.error(
                "Course agent failed — returning placeholder modules",
                error=str(e),
                course=title_en,
            )
            return _PLACEHOLDER_MODULES


_DEFAULT_COURSE_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
