"""Course content creator agent — generates full course structure via Claude API."""

import os
import uuid
from typing import Any

import structlog

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
        domain: str | None,
        target_audience: str | None,
        estimated_hours: int,
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

            prompt = (
                f"You are an expert instructional designer specializing in bilingual (FR/EN) "
                f"adaptive e-learning for professionals. You design curricula using Bloom's "
                f"taxonomy, Knowles' andragogy, the ADDIE model, and spiral learning.\n\n"
                f"Create a complete course syllabus for:\n"
                f"- Title FR: {title_fr}\n"
                f"- Title EN: {title_en}\n"
                f"- Domain: {domain or 'General'}\n"
                f"- Target audience: {target_audience or 'Professionals'}\n"
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

            message = await client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=8192,
                messages=[{"role": "user", "content": prompt}],
            )

            import json

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
