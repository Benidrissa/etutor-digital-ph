"""Course content creator agent — generates full course structure via Claude API."""

from __future__ import annotations

import os
import uuid
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from app.domain.services.course_management_service import CostTracker

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

    async def generate_course_structure(
        self,
        title_fr: str,
        title_en: str,
        course_domain: list[str] | None = None,
        course_level: list[str] | None = None,
        audience_type: list[str] | None = None,
        estimated_hours: int = 20,
        cost_tracker: CostTracker | None = None,
    ) -> list[dict[str, Any]]:
        """
        Generate a course module outline using Claude API.

        Returns a list of module dicts with title_fr, title_en, description,
        estimated_hours, bloom_level, and a sequential module_number.
        Falls back to 2 placeholder modules if ANTHROPIC_API_KEY is not set.

        Args:
            cost_tracker: optional CostTracker for recording AI usage costs.
                          Passed through from CourseManagementService when the
                          expert context requires cost tracking.
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

            prompt = (
                f"You are an expert instructional designer specializing in bilingual (FR/EN) "
                f"adaptive e-learning. You design curricula using Bloom's "
                f"taxonomy, Knowles' andragogy, the ADDIE model, and spiral learning.\n\n"
                f"Create a complete course syllabus for:\n"
                f"- Title FR: {title_fr}\n"
                f"- Title EN: {title_en}\n"
                f"- Domain(s): {domains_str}\n"
                f"- Level(s): {levels_str}\n"
                f"- Target audience: {audience_str}\n"
                f"- Estimated total hours: {estimated_hours}\n\n"
                f"## Design principles (mandatory)\n"
                f"- Progressive complexity: start with foundational concepts (remember/understand), "
                f"build to applied skills (apply/analyze), end with expert synthesis (evaluate/create)\n"
                f"- Each module must be self-contained (10-25h) with clear learning objectives\n"
                f"- Units are micro-learning (10-15 min each), 3-6 lessons per module\n"
                f"- Every module includes: lessons, a formative quiz per lesson, a summative "
                f"module quiz (20 questions, 80% pass), flashcards (20-40 bilingual cards), "
                f"and a practical case study contextualized to the target audience\n"
                f"- Bilingual: all text in both FR and EN\n\n"
                f"## Output format\n"
                f"Return a JSON array of modules. Each module must have:\n"
                f"{{\n"
                f'  "module_number": int,\n'
                f'  "title_fr": str, "title_en": str,\n'
                f'  "description_fr": str, "description_en": str,\n'
                f'  "estimated_hours": int,\n'
                f'  "bloom_level": "remember"|"understand"|"apply"|"analyze"|"evaluate"|"create",\n'
                f'  "learning_objectives_fr": [str], "learning_objectives_en": [str],\n'
                f'  "units": [\n'
                f'    {{"title_fr": str, "title_en": str, "type": "lesson"|"quiz"|"case-study",\n'
                f'     "description_fr": str, "description_en": str}}\n'
                f"  ],\n"
                f'  "quiz_topics_fr": [str], "quiz_topics_en": [str],\n'
                f'  "flashcard_categories_fr": [str], "flashcard_categories_en": [str],\n'
                f'  "case_study_fr": str, "case_study_en": str\n'
                f"}}\n\n"
                f"Return ONLY valid JSON, no markdown fences, no explanation."
            )

            import json

            message = await client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=64000,
                messages=[{"role": "user", "content": prompt}],
            )

            # Check for truncation
            if message.stop_reason == "max_tokens":
                logger.warning(
                    "Response truncated at max_tokens, retrying",
                    course=title_en,
                    stop_reason=message.stop_reason,
                )
                message = await client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=64000,
                    messages=[
                        {"role": "user", "content": prompt},
                        {"role": "assistant", "content": message.content[0].text},
                        {
                            "role": "user",
                            "content": "The JSON was truncated. Please complete it from where you stopped. Return ONLY the remaining JSON to complete the array.",
                        },
                    ],
                )

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
