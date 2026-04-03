"""Course creation agent service.

Uses Claude API to generate a full course structure (modules, objectives)
from a domain description and uploaded source documents.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import structlog

from app.infrastructure.config.settings import get_settings

if TYPE_CHECKING:
    from app.domain.models.course import Course

logger = structlog.get_logger()

_SYSTEM_PROMPT = """You are an expert curriculum designer for public health education in West Africa.
Your role is to generate structured, pedagogically sound course outlines following Bloom's taxonomy.

Guidelines:
- Generate modules following the 4-level progression: beginner → intermediate → advanced → expert
- Each module should have clear learning objectives using Bloom's taxonomy verbs
- Content must be bilingual (French and English) and culturally relevant to ECOWAS countries
- Estimated hours per module: 10-30 hours depending on complexity
- Bloom levels: remember, understand, apply, analyze, evaluate, create
- Modules should build progressively on each other

Respond ONLY with a valid JSON array of module objects. No markdown, no explanation.
"""

_MODULE_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "required": [
            "module_number",
            "title_fr",
            "title_en",
            "description_fr",
            "description_en",
            "estimated_hours",
            "bloom_level",
        ],
        "properties": {
            "module_number": {"type": "integer"},
            "title_fr": {"type": "string"},
            "title_en": {"type": "string"},
            "description_fr": {"type": "string"},
            "description_en": {"type": "string"},
            "estimated_hours": {"type": "integer"},
            "bloom_level": {"type": "string"},
            "status": {"type": "string"},
        },
    },
}


class CourseAgentService:
    """Agent that generates a complete course structure using Claude."""

    def __init__(self) -> None:
        self.settings = get_settings()

    async def generate_course_structure(
        self,
        course: Course,
        domain: str,
        target_audience: str | None,
        languages: list[str],
        source_documents: list[str],
    ) -> list[dict[str, Any]]:
        """Generate a full course module structure for the given domain.

        Args:
            course: The Course ORM object.
            domain: Subject domain (e.g. "Nutrition communautaire").
            target_audience: Description of intended learners.
            languages: List of target languages (["fr", "en"]).
            source_documents: RAG collection IDs or source names to reference.

        Returns:
            List of module draft dicts matching ModuleDraftResponse schema.
        """
        if not self.settings.anthropic_api_key:
            logger.warning("ANTHROPIC_API_KEY not set — returning placeholder modules")
            return self._placeholder_modules(domain)

        import anthropic

        client = anthropic.AsyncAnthropic(api_key=self.settings.anthropic_api_key)

        audience_text = target_audience or "public health professionals in West Africa"
        sources_text = (
            f"Reference documents: {', '.join(source_documents)}" if source_documents else ""
        )
        languages_text = ", ".join(languages)

        user_message = f"""Generate a complete course module outline for the following:

Domain: {domain}
Target audience: {audience_text}
Languages: {languages_text}
{sources_text}

Course title (FR): {course.title_fr}
Course title (EN): {course.title_en}

Requirements:
- Generate 6-12 modules covering the full scope of the domain
- Organize into 2-4 progressive levels (beginner to expert)
- Each module must have bilingual titles and descriptions (FR/EN)
- Include bloom_level for each module (remember/understand/apply/analyze/evaluate/create)
- Set estimated_hours between 10 and 30 per module
- Set status to "draft" for all modules
- module_number should start at 1

Return ONLY a valid JSON array of module objects."""

        try:
            message = await client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=4096,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
                temperature=0.5,
            )

            raw = message.content[0].text.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

            modules = json.loads(raw)
            if not isinstance(modules, list):
                raise ValueError("Expected a JSON array")

            for i, m in enumerate(modules):
                if "status" not in m:
                    m["status"] = "draft"
                if "module_number" not in m:
                    m["module_number"] = i + 1

            logger.info(
                "Course structure generated",
                course_id=str(course.id),
                module_count=len(modules),
            )
            return modules

        except json.JSONDecodeError as e:
            logger.error("Failed to parse agent JSON response", error=str(e))
            raise ValueError(f"Agent returned invalid JSON: {e}") from e
        except Exception as e:
            logger.error("Course agent generation failed", error=str(e))
            raise

    def _placeholder_modules(self, domain: str) -> list[dict[str, Any]]:
        """Return placeholder modules when Claude API is not configured."""
        return [
            {
                "module_number": 1,
                "title_fr": f"Introduction à {domain}",
                "title_en": f"Introduction to {domain}",
                "description_fr": f"Concepts fondamentaux de {domain}",
                "description_en": f"Foundational concepts of {domain}",
                "estimated_hours": 15,
                "bloom_level": "remember",
                "status": "draft",
            },
            {
                "module_number": 2,
                "title_fr": f"Principes avancés de {domain}",
                "title_en": f"Advanced principles of {domain}",
                "description_fr": f"Application des concepts de {domain} en contexte ouest-africain",
                "description_en": f"Application of {domain} concepts in West African context",
                "estimated_hours": 20,
                "bloom_level": "apply",
                "status": "draft",
            },
        ]
