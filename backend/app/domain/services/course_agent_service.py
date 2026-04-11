"""Course content creator agent — generates full course structure via Claude API."""

import os
import uuid
from typing import Any

import structlog

from app.ai.model_registry import get_model_caps

# ── Tool-use schema for structured syllabus output ──────────────────
# Claude is forced to call this tool, ensuring every unit has an
# explicit "type" enum value.  Adults get lesson/quiz/case-study;
# kids courses also allow "scenario" (alias for case-study).
_UNIT_SCHEMA = {
    "type": "object",
    "properties": {
        "title_fr": {"type": "string"},
        "title_en": {"type": "string"},
        "type": {
            "type": "string",
            "enum": ["lesson", "quiz", "case-study", "scenario"],
        },
        "description_fr": {"type": "string"},
        "description_en": {"type": "string"},
    },
    "required": [
        "title_fr",
        "title_en",
        "type",
        "description_fr",
        "description_en",
    ],
}

_MODULE_SCHEMA = {
    "type": "object",
    "properties": {
        "module_number": {"type": "integer"},
        "title_fr": {"type": "string"},
        "title_en": {"type": "string"},
        "description_fr": {"type": "string"},
        "description_en": {"type": "string"},
        "estimated_hours": {"type": "integer"},
        "bloom_level": {
            "type": "string",
            "enum": [
                "remember",
                "understand",
                "apply",
                "analyze",
                "evaluate",
                "create",
            ],
        },
        "learning_objectives_fr": {
            "type": "array",
            "items": {"type": "string"},
        },
        "learning_objectives_en": {
            "type": "array",
            "items": {"type": "string"},
        },
        "units": {
            "type": "array",
            "items": _UNIT_SCHEMA,
        },
        "quiz_topics_fr": {
            "type": "array",
            "items": {"type": "string"},
        },
        "quiz_topics_en": {
            "type": "array",
            "items": {"type": "string"},
        },
        "flashcard_categories_fr": {
            "type": "array",
            "items": {"type": "string"},
        },
        "flashcard_categories_en": {
            "type": "array",
            "items": {"type": "string"},
        },
        "case_study_fr": {"type": "string"},
        "case_study_en": {"type": "string"},
    },
    "required": [
        "module_number",
        "title_fr",
        "title_en",
        "description_fr",
        "description_en",
        "estimated_hours",
        "bloom_level",
        "learning_objectives_fr",
        "learning_objectives_en",
        "units",
    ],
}

SYLLABUS_TOOL = {
    "name": "save_syllabus",
    "description": (
        "Save the generated course syllabus. "
        "You MUST call this tool with the complete module array."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "modules": {
                "type": "array",
                "items": _MODULE_SCHEMA,
            },
        },
        "required": ["modules"],
    },
}

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


def _try_parse_modules(raw: str) -> list[dict] | None:
    """Attempt to parse a JSON array of modules, with partial recovery on truncation."""
    import json

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    last_brace = raw.rfind("}")
    if last_brace == -1:
        return None
    candidate = raw[: last_brace + 1] + "]"
    try:
        result = json.loads(candidate)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass

    return None


class CourseAgentService:
    """Generates course structure using Claude API, with graceful fallback."""

    def _get_admin_prompt(
        self,
        audience_type: list[str] | None = None,
        **template_vars: str,
    ) -> str | None:
        """Check if admin has customized the syllabus prompt via platform settings."""
        try:
            from app.ai.prompts.audience import KIDS_AUDIENCE_SLUGS
            from app.domain.services.platform_settings_service import SettingsCache
            from app.infrastructure.config.platform_defaults import DEFAULTS_BY_KEY

            is_kids = bool(audience_type and any(s in KIDS_AUDIENCE_SLUGS for s in audience_type))
            key = "ai-prompt-syllabus-kids-system" if is_kids else "ai-prompt-syllabus-system"
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
        description_fr: str | None = None,
        description_en: str | None = None,
        audience_type: list[str] | None = None,
    ) -> str:
        """Build the syllabus generation prompt, using admin override if available."""
        from app.ai.prompts.audience import (
            detect_audience_from_slugs,
            get_audience_guidance,
        )

        audience_ctx = detect_audience_from_slugs(audience_type, title_en, title_fr)

        age_range = f"{audience_ctx.age_min}-{audience_ctx.age_max}" if audience_ctx.is_kids else ""
        audience_guidance = (
            get_audience_guidance(audience_ctx, "en") if audience_ctx.is_kids else ""
        )

        admin = self._get_admin_prompt(
            audience_type=audience_type,
            course_title=f"{title_fr} / {title_en}",
            course_domain=domains_str,
            level=levels_str,
            estimated_hours=str(estimated_hours),
            resource_text=resource_block,
            age_range=age_range,
            audience_guidance=audience_guidance,
        )
        if admin:
            return admin

        description_block = ""
        if description_fr or description_en:
            description_block = "\n"
            if description_fr:
                description_block += f"- Description (FR): {description_fr}\n"
            if description_en:
                description_block += f"- Description (EN): {description_en}\n"

        if audience_ctx.is_kids:
            return self._build_kids_prompt(
                title_fr=title_fr,
                title_en=title_en,
                description_block=description_block,
                domains_str=domains_str,
                levels_str=levels_str,
                audience_str=audience_str,
                estimated_hours=estimated_hours,
                resource_block=resource_block,
                age_range=age_range,
                audience_guidance=audience_guidance,
            )

        return (
            "You are an expert instructional designer specializing in "
            "bilingual (FR/EN) adaptive e-learning. You design curricula "
            "using Bloom's taxonomy, Knowles' andragogy, the ADDIE model, "
            "and spiral learning.\n\n"
            f"Create a complete course syllabus for:\n"
            f"- Title FR: {title_fr}\n"
            f"- Title EN: {title_en}\n"
            f"{description_block}"
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
            "## CRITICAL — every unit MUST have a type field\n"
            'Each unit must include "type" set to exactly one of: '
            '"lesson", "quiz", or "case-study". '
            "Never omit the type field.\n\n"
            "## Conciseness rules (CRITICAL — this is a syllabus, not the course itself)\n"
            "- description_fr/en: max 2 sentences (~30 words each)\n"
            "- learning_objectives: max 3-5 bullet points per module, each ≤15 words\n"
            "- unit description_fr/en: max 1 sentence (~20 words)\n"
            "- quiz_topics: max 5 short topic names per module\n"
            "- flashcard_categories: max 5 short category names per module\n"
            "- case_study_fr/en: max 2 sentences (~40 words) — topic outline only, not the full case\n"
            "- Keep total response under 20,000 words\n\n"
            "- NEVER truncate text with '...' or ellipsis — write complete short text instead\n\n"
            "Call the save_syllabus tool with the complete module array."
        )

    def _build_kids_prompt(
        self,
        title_fr: str,
        title_en: str,
        description_block: str,
        domains_str: str,
        levels_str: str,
        audience_str: str,
        estimated_hours: int,
        resource_block: str,
        age_range: str,
        audience_guidance: str,
    ) -> str:
        """Build kids-adapted syllabus prompt with child-centered pedagogy."""
        return (
            "You are a warm, encouraging instructional designer who creates "
            "bilingual (FR/EN) course syllabi for young learners aged "
            f"{age_range} in West Africa. You apply child-centered pedagogy, "
            "Piaget's developmental stages, and play-based learning.\n\n"
            f"{audience_guidance}\n\n"
            f"Create a complete course syllabus for:\n"
            f"- Title FR: {title_fr}\n"
            f"- Title EN: {title_en}\n"
            f"{description_block}"
            f"- Domain(s): {domains_str}\n"
            f"- Level(s): {levels_str}\n"
            f"- Target audience: {audience_str} (ages {age_range})\n"
            f"- Estimated total hours: {estimated_hours}\n\n"
            f"{resource_block}\n\n"
            "## Design principles (mandatory)\n"
            "- Progressive complexity: start with discovery (remember/understand), "
            "build to exploration (apply), and for older children (ages 13+) "
            "reach basic analysis (analyze/evaluate)\n"
            "- Bloom level cap: primary school → apply; secondary school → evaluate\n"
            "- Each module must be self-contained (5-15h) with child-friendly "
            "learning objectives\n"
            "- Units are short learning sessions (5-10 min for ages 5-8, "
            "10-15 min for ages 9-15), 3-6 units per module\n"
            "- Every module includes: lessons, a formative quiz per lesson "
            "(10 questions, 60% pass — fun and encouraging), flashcards "
            "(10-20 bilingual cards with simple concrete definitions), and "
            "a story-based scenario from daily life in West Africa relatable "
            "to children\n"
            "- Module titles must be playful and adventure-themed to excite children\n"
            "- Learning objectives must use child-friendly verbs: "
            "discover, explore, create, play, build, find, learn, share\n"
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
            '"type": "lesson"|"quiz"|"scenario",\n'
            '     "description_fr": str, "description_en": str}\n'
            "  ],\n"
            '  "quiz_topics_fr": [str], '
            '"quiz_topics_en": [str],\n'
            '  "flashcard_categories_fr": [str], '
            '"flashcard_categories_en": [str],\n'
            '  "case_study_fr": str, "case_study_en": str\n'
            "}\n\n"
            "## CRITICAL — every unit MUST have a type field\n"
            'Each unit must include "type" set to exactly one of: '
            '"lesson", "quiz", or "scenario" '
            "(scenario is a story-based activity for children). "
            "Never omit the type field.\n\n"
            "## Conciseness rules (CRITICAL — this is a syllabus, not the course itself)\n"
            "- description_fr/en: max 2 short sentences (~20 words each)\n"
            "- learning_objectives: max 3-4 bullet points per module, each ≤12 words\n"
            "- unit description_fr/en: max 1 sentence (~15 words)\n"
            "- quiz_topics: max 5 short topic names per module\n"
            "- flashcard_categories: max 5 short category names per module\n"
            "- case_study_fr/en: max 2 sentences (~30 words) — a story prompt, not the full case\n"
            "- Keep total response under 20,000 words\n\n"
            "- NEVER truncate text with '...' or ellipsis — write complete short text instead\n\n"
            "Call the save_syllabus tool with the complete module array."
        )

    async def generate_course_structure(
        self,
        title_fr: str,
        title_en: str,
        course_description_fr: str | None = None,
        course_description_en: str | None = None,
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
                description_fr=course_description_fr,
                description_en=course_description_en,
                audience_type=audience_type,
            )

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
                    description_fr=course_description_fr,
                    description_en=course_description_en,
                    audience_type=audience_type,
                )

            # Use tool_use to enforce structured JSON output
            async with client.messages.stream(
                model=_model,
                max_tokens=64000,
                messages=[{"role": "user", "content": prompt}],
                tools=[SYLLABUS_TOOL],
                tool_choice={"type": "tool", "name": "save_syllabus"},
            ) as stream:
                message = await stream.get_final_message()

            # Extract modules from tool_use block
            modules_raw = None
            for block in message.content:
                if block.type == "tool_use" and block.name == "save_syllabus":
                    modules_raw = block.input.get("modules", [])
                    break

            # Fallback: if tool_use failed, try raw text parsing
            if not modules_raw:
                logger.warning(
                    "tool_use extraction failed, falling back to text",
                    course=title_en,
                    stop_reason=message.stop_reason,
                )
                for block in message.content:
                    if hasattr(block, "text") and block.text:
                        raw = block.text.strip()
                        if raw.startswith("```"):
                            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
                        modules_raw = _try_parse_modules(raw)
                        if modules_raw:
                            break

            if not modules_raw:
                raise ValueError("Failed to extract modules from tool_use or text")

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
