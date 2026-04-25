"""Service for AI tutor functionality with agentic tool_use and Socratic pedagogical approach."""

import asyncio
import re
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import structlog
from anthropic import AsyncAnthropic
from anthropic.types import MessageParam, ToolResultBlockParam, ToolUseBlock
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.ai.prompts.audience import detect_audience
from app.ai.prompts.tutor import (
    TutorContext,
    get_activity_suggestions,
    get_compaction_prompt,
    get_learner_block_text,
    get_persona_block_text,
    get_socratic_system_prompt,
)
from app.ai.rag.embeddings import EmbeddingService
from app.ai.rag.retriever import SemanticRetriever
from app.domain.models.content import GeneratedContent
from app.domain.models.conversation import TutorConversation, TutorMessage
from app.domain.models.module import Module
from app.domain.models.module_unit import ModuleUnit
from app.domain.models.source_image import SourceImage
from app.domain.models.user import User
from app.domain.services.analytics_service import AnalyticsService
from app.domain.services.learner_memory_service import LearnerMemoryService
from app.domain.services.platform_settings_service import SettingsCache
from app.domain.services.subscription_service import SubscriptionService
from app.domain.services.tutor_context_builder import resolve_course
from app.domain.services.tutor_tools import TOOL_DEFINITIONS, TutorToolExecutor
from app.infrastructure.config.settings import get_settings

logger = structlog.get_logger()

_sc = SettingsCache.instance
MAX_TOOL_CALLS = _sc().get("tutor-max-tool-calls", 3)
# Defaults relaxed (#1978) — compaction is now non-destructive, so we can
# afford a higher trigger and a much larger verbatim window. These fallbacks
# track ``platform_defaults.py``; the runtime values come from SettingsCache
# which reads from the platform_settings table.
COMPACT_TRIGGER = _sc().get("tutor-compaction-trigger-messages", 50)
COMPACT_KEEP_RECENT = _sc().get("tutor-compaction-keep-recent", 20)
COMPACT_SUMMARIZE_UP_TO = _sc().get("tutor-compaction-summarize-up-to", 30)

SESSION_CONTEXT_TOKEN_BUDGET = _sc().get("tutor-context-token-budget", 1500)

# Shared between the live-stream resolver and the GET-conversation resolver (#1937).
_SOURCE_IMAGE_MARKER_RE = re.compile(r"\{\{source_image:([0-9a-f-]{36})\}\}", re.IGNORECASE)


def _message_extra(msg: dict[str, Any]) -> dict[str, Any] | None:
    """Strip role/content (which live in dedicated columns of ``tutor_messages``)
    and return the rest as the row's ``extra`` JSON payload — sources,
    activity_suggestions, timestamps, etc. (#1978)."""
    extra = {k: v for k, v in msg.items() if k not in ("role", "content")}
    return extra or None


# Soft cap on the syllabus text injected into the tutor system prompt (#1979).
# At ~4 chars/token this is roughly 350 tokens — well under the existing
# SESSION_CONTEXT_TOKEN_BUDGET (1500) shared with learner memory and previous
# session compact, leaving headroom for both.
_SYLLABUS_PROMPT_CHAR_LIMIT = 1400


def _build_syllabus_for_prompt(
    syllabus_context: str | None,
    syllabus_json: dict | list | None,
) -> str | None:
    """Pick the best available syllabus representation and trim it to fit
    inside the tutor system prompt (#1979).

    Prefers the prose ``syllabus_context`` (already human-readable). Falls
    back to a flattened tree of headings extracted from ``syllabus_json``
    when only structured data is available. Returns ``None`` when neither is
    populated so course-less or pre-syllabus conversations skip the section.
    """
    text = (syllabus_context or "").strip()
    if not text and syllabus_json:
        text = _flatten_syllabus_json(syllabus_json).strip()
    if not text:
        return None
    if len(text) <= _SYLLABUS_PROMPT_CHAR_LIMIT:
        return text
    # Cut on a paragraph/line boundary close to the limit so we don't slice a
    # heading mid-word. Falls back to a hard slice if no boundary is nearby.
    cutoff = text.rfind("\n", 0, _SYLLABUS_PROMPT_CHAR_LIMIT)
    if cutoff < int(_SYLLABUS_PROMPT_CHAR_LIMIT * 0.6):
        cutoff = _SYLLABUS_PROMPT_CHAR_LIMIT
    return text[:cutoff].rstrip() + "\n…"


def _flatten_syllabus_json(node: Any, depth: int = 0) -> str:
    """Walk a structured syllabus tree and emit a markdown-ish bullet list.

    The shape isn't formally specified — different generators produce dicts
    with ``modules``/``units``/``lessons`` arrays, lists of dicts with
    ``title``/``name``/``label`` keys, or plain strings. We dig defensively
    so a bad shape just produces less text rather than a 500.
    """
    lines: list[str] = []
    indent = "  " * depth
    if isinstance(node, dict):
        title = node.get("title") or node.get("name") or node.get("label")
        if title:
            lines.append(f"{indent}- {title}")
            depth_for_children = depth + 1
        else:
            depth_for_children = depth
        for key in ("modules", "units", "lessons", "chapters", "sections", "items"):
            child = node.get(key)
            if child:
                lines.append(_flatten_syllabus_json(child, depth_for_children))
    elif isinstance(node, list):
        for item in node:
            lines.append(_flatten_syllabus_json(item, depth))
    elif isinstance(node, str):
        if node.strip():
            lines.append(f"{indent}- {node.strip()}")
    return "\n".join(line for line in lines if line)


def _excerpt_from_generated_content(content: Any, max_chars: int) -> str:
    """Extract a short, prompt-friendly excerpt from a ``GeneratedContent.content`` JSON (#1981).

    The shape varies per ``content_type`` (lesson / quiz / case): some store
    ``text``, some ``body``, some ``summary``, some nest under ``sections`` or
    ``introduction``. Prefer the most overview-friendly key, fall back to a
    stringified preview. Always trims to ``max_chars`` on a word boundary
    where possible so the prompt doesn't show half-words.
    """
    if not content:
        return ""
    text: str | None = None
    if isinstance(content, dict):
        for key in ("summary", "introduction", "intro", "text", "body", "explanation"):
            value = content.get(key)
            if isinstance(value, str) and value.strip():
                text = value.strip()
                break
        if text is None:
            # Fall back to first non-empty string value at the top level so
            # quizzes (whose top-level shape is `{"questions": [...]}`) still
            # produce *something* useful.
            for value in content.values():
                if isinstance(value, str) and value.strip():
                    text = value.strip()
                    break
        if text is None and isinstance(content.get("questions"), list) and content["questions"]:
            first_q = content["questions"][0]
            if isinstance(first_q, dict):
                text = (first_q.get("question") or first_q.get("prompt") or "").strip() or None
    elif isinstance(content, str):
        text = content.strip()
    if not text:
        return ""
    text = " ".join(text.split())  # collapse whitespace to keep prompt compact
    if len(text) <= max_chars:
        return text
    cutoff = text.rfind(" ", 0, max_chars)
    if cutoff < int(max_chars * 0.6):
        cutoff = max_chars
    return text[:cutoff].rstrip() + "…"


def _trim_text(text: str, max_chars: int, suffix: str = "…") -> str:
    """Trim ``text`` to ~``max_chars`` on a paragraph or word boundary (#1984).

    Used by the full-content renderers — when a single lesson/quiz/case body
    is unreasonably long we want to cap it without slicing mid-word or
    breaking mid-table.
    """
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    # Prefer a paragraph boundary, then a sentence end, then a word boundary.
    cutoff = text.rfind("\n\n", 0, max_chars)
    if cutoff < int(max_chars * 0.6):
        cutoff = text.rfind(". ", 0, max_chars)
    if cutoff < int(max_chars * 0.6):
        cutoff = text.rfind(" ", 0, max_chars)
    if cutoff < int(max_chars * 0.6):
        cutoff = max_chars
    return text[:cutoff].rstrip() + suffix


def _render_lesson_full(content: dict, max_chars: int, language: str) -> str:
    """Render a generated lesson body as markdown for the system prompt (#1984).

    Lesson shape (per ``LessonContent`` schema): introduction + concepts[]
    + aof_example + synthesis + key_points[] + sources_cited[].
    Trims the assembled markdown to ``max_chars`` so a single runaway lesson
    can't consume the whole module budget.
    """
    if not isinstance(content, dict):
        return ""
    intro_label = "Introduction" if language == "en" else "Introduction"
    concepts_label = "Key concepts" if language == "en" else "Concepts clés"
    aof_label = "West African example" if language == "en" else "Exemple ouest-africain"
    synthesis_label = "Synthesis" if language == "en" else "Synthèse"
    key_points_label = "Key takeaways" if language == "en" else "Points clés"
    sources_label = "Sources" if language == "en" else "Sources"

    parts: list[str] = []
    intro = (content.get("introduction") or content.get("summary") or "").strip()
    if intro:
        parts.append(f"_{intro_label}:_ {intro}")
    concepts = content.get("concepts")
    if isinstance(concepts, list) and concepts:
        bullets = "\n".join(
            f"  - {c.strip()}" for c in concepts if isinstance(c, str) and c.strip()
        )
        if bullets:
            parts.append(f"_{concepts_label}:_\n{bullets}")
    aof = (content.get("aof_example") or "").strip()
    if aof:
        parts.append(f"_{aof_label}:_ {aof}")
    synthesis = (content.get("synthesis") or "").strip()
    if synthesis:
        parts.append(f"_{synthesis_label}:_ {synthesis}")
    key_points = content.get("key_points")
    if isinstance(key_points, list) and key_points:
        bullets = "\n".join(
            f"  - {kp.strip()}" for kp in key_points if isinstance(kp, str) and kp.strip()
        )
        if bullets:
            parts.append(f"_{key_points_label}:_\n{bullets}")
    sources = content.get("sources_cited")
    if isinstance(sources, list) and sources:
        srcs = ", ".join(s.strip() for s in sources if isinstance(s, str) and s.strip())
        if srcs:
            parts.append(f"_{sources_label}:_ {srcs}")
    return _trim_text("\n".join(parts), max_chars)


def _render_quiz_full(
    content: dict, max_chars: int, language: str, include_answers: bool = True
) -> str:
    """Render a generated quiz with questions + (optionally) correct answers (#1984).

    Including the correct answer + explanation lets the tutor *guide* a
    learner through reasoning, rather than re-deriving the answer from
    scratch on each question. Toggle via the ``tutor-include-quiz-answers``
    setting.
    """
    if not isinstance(content, dict):
        return ""
    questions = content.get("questions")
    if not isinstance(questions, list):
        return ""
    answer_label = "Correct answer" if language == "en" else "Réponse correcte"
    explain_label = "Explanation" if language == "en" else "Explication"

    rendered: list[str] = []
    for idx, q in enumerate(questions, start=1):
        if not isinstance(q, dict):
            continue
        question_text = (q.get("question") or q.get("prompt") or "").strip()
        if not question_text:
            continue
        block = [f"  Q{idx}. {question_text}"]
        options = q.get("options")
        if isinstance(options, list):
            for j, opt in enumerate(options):
                if isinstance(opt, str) and opt.strip():
                    block.append(f"    {chr(ord('A') + j)}. {opt.strip()}")
        if include_answers:
            correct_idx = q.get("correct_answer")
            if (
                isinstance(correct_idx, int)
                and isinstance(options, list)
                and 0 <= correct_idx < len(options)
            ):
                correct_letter = chr(ord("A") + correct_idx)
                block.append(f"    _{answer_label}:_ {correct_letter}")
            explanation = (q.get("explanation") or "").strip()
            if explanation:
                block.append(f"    _{explain_label}:_ {explanation}")
        rendered.append("\n".join(block))
    return _trim_text("\n\n".join(rendered), max_chars)


def _render_case_full(content: Any, max_chars: int, language: str) -> str:
    """Render a generated case study for the system prompt (#1984).

    Handles two shapes:

    * Structured ``CaseStudyContent`` (aof_context, real_data,
      guided_questions, annotated_correction, sources_cited).
    * Plain prose strings — when falling back to the legacy
      ``module.case_study_fr|en`` text columns (no row in
      ``generated_content``).
    """
    if isinstance(content, str):
        return _trim_text(content.strip(), max_chars)
    if not isinstance(content, dict):
        return ""
    context_label = "Context" if language == "en" else "Contexte"
    data_label = "Real-world data" if language == "en" else "Données réelles"
    questions_label = "Guided questions" if language == "en" else "Questions guidées"
    correction_label = "Annotated correction" if language == "en" else "Correction annotée"
    sources_label = "Sources" if language == "en" else "Sources"
    parts: list[str] = []
    aof_context = (content.get("aof_context") or content.get("body") or "").strip()
    if aof_context:
        parts.append(f"_{context_label}:_ {aof_context}")
    real_data = (content.get("real_data") or "").strip()
    if real_data:
        parts.append(f"_{data_label}:_\n{real_data}")
    guided = content.get("guided_questions")
    if isinstance(guided, list) and guided:
        bullets = "\n".join(f"  - {g.strip()}" for g in guided if isinstance(g, str) and g.strip())
        if bullets:
            parts.append(f"_{questions_label}:_\n{bullets}")
    correction = (content.get("annotated_correction") or "").strip()
    if correction:
        parts.append(f"_{correction_label}:_ {correction}")
    sources = content.get("sources_cited")
    if isinstance(sources, list) and sources:
        srcs = ", ".join(s.strip() for s in sources if isinstance(s, str) and s.strip())
        if srcs:
            parts.append(f"_{sources_label}:_ {srcs}")
    summary = (content.get("summary") or "").strip()
    if not parts and summary:
        parts.append(summary)
    return _trim_text("\n".join(parts), max_chars)


async def _build_current_module_section(
    module_obj: Module | None,
    language: str,
    session: AsyncSession,
    char_limit: int | None = None,
    excerpt_chars: int | None = None,
) -> str | None:
    """Render the current module's unit / quiz / case-study content (#1981, #1984).

    Returns ``None`` when no module is in scope (chat without a module
    context) or when the module has no units.

    Behaviour evolved with #1984: instead of 200-char excerpts, we now render
    the **full lesson body, full quiz (with answers), and full case study**
    for every generated unit in the module — bounded by per-unit and
    per-section char limits. The tutor can quote, cite, and reason from the
    actual material rather than tool-calling for every concrete question.

    Pending units (no GeneratedContent row) still show titles + a 🔒 marker
    so the tutor knows what exists but isn't yet authored.
    """
    if module_obj is None:
        return None

    char_limit = (
        char_limit
        if char_limit is not None
        else _sc().get("tutor-module-content-char-limit", 30000)
    )
    excerpt_chars = (
        excerpt_chars
        if excerpt_chars is not None
        else _sc().get("tutor-module-content-excerpt-chars", 10000)
    )
    include_quiz_answers = bool(_sc().get("tutor-include-quiz-answers", True))

    # Localised labels — keep the prompt natural in either FR or EN so the
    # tutor doesn't switch languages mid-thought.
    if language == "fr":
        generated_marker = "✓ (généré)"
        pending_marker = "🔒 (à venir)"
        case_label = "Étude de cas"
        lesson_label = "Leçon"
        quiz_label = "Quiz"
    else:
        generated_marker = "✓ (generated)"
        pending_marker = "🔒 (not yet generated)"
        case_label = "Case study"
        lesson_label = "Lesson"
        quiz_label = "Quiz"

    module_title = (
        getattr(module_obj, "title_fr", None)
        if language == "fr"
        else getattr(module_obj, "title_en", None)
    )
    module_number = getattr(module_obj, "module_number", None)
    if module_title and module_number:
        header = f"Module {module_number} — {module_title}"
    elif module_title:
        header = module_title
    else:
        header = f"Module {module_number}" if module_number else "Module"

    # Single batched lookup keyed on (module_id, language). FR and EN are
    # stored as separate rows, so we only fetch the user's effective language.
    content_index: dict[tuple[str, str], dict] = {}
    case_contents: list[dict] = []
    try:
        result = await session.execute(
            select(GeneratedContent).where(
                GeneratedContent.module_id == module_obj.id,
                GeneratedContent.language == language,
            )
        )
        for row in result.scalars().all():
            content_obj = row.content if isinstance(row.content, dict) else {}
            unit_id = str(content_obj.get("unit_id") or "").strip()
            if row.content_type == "case":
                case_contents.append(content_obj)
            elif unit_id:
                content_index[(row.content_type, unit_id)] = content_obj
    except Exception as exc:  # pragma: no cover — defensive: bad DB shouldn't 500 the tutor
        logger.warning(
            "Failed to load GeneratedContent for module section",
            module_id=str(module_obj.id),
            error=str(exc),
        )

    # Units — preserve order via order_index. ``selectinload`` should have
    # populated this; fall back to an empty list rather than triggering a
    # lazy load (which would explode in async code).
    units: list[ModuleUnit] = []
    try:
        units = sorted(
            list(getattr(module_obj, "units", []) or []),
            key=lambda u: getattr(u, "order_index", 0) or 0,
        )
    except Exception:
        units = []

    lines: list[str] = [header]

    for unit in units:
        unit_title = (
            getattr(unit, "title_fr", None) if language == "fr" else getattr(unit, "title_en", None)
        ) or ""
        unit_number = getattr(unit, "unit_number", None) or ""
        prefix = f"{unit_number} — " if unit_number else ""
        lesson = content_index.get(("lesson", unit_number))
        quiz = content_index.get(("quiz", unit_number))
        marker = generated_marker if (lesson or quiz) else pending_marker
        lines.append(f"- {prefix}{unit_title} {marker}".rstrip())
        if lesson:
            body = _render_lesson_full(lesson, excerpt_chars, language)
            if body:
                lines.append(f"  **{lesson_label}:**")
                for body_line in body.split("\n"):
                    lines.append(f"  {body_line}")
        if quiz:
            body = _render_quiz_full(quiz, excerpt_chars, language, include_quiz_answers)
            if body:
                lines.append(f"  **{quiz_label}:**")
                for body_line in body.split("\n"):
                    lines.append(f"  {body_line}")

    # Case studies — prefer GeneratedContent rows (the new flow), fall back
    # to the module-level `case_study_fr|en` text columns when no row exists.
    if case_contents:
        for case in case_contents:
            title = (case.get("title") or case_label).strip()
            body = _render_case_full(case, excerpt_chars, language)
            lines.append(f"- {title} {generated_marker}")
            if body:
                for body_line in body.split("\n"):
                    lines.append(f"  {body_line}")
    else:
        legacy_case = (
            getattr(module_obj, "case_study_fr", None)
            if language == "fr"
            else getattr(module_obj, "case_study_en", None)
        )
        if isinstance(legacy_case, str) and legacy_case.strip():
            body = _render_case_full(legacy_case, excerpt_chars, language)
            lines.append(f"- {case_label} {generated_marker}")
            if body:
                for body_line in body.split("\n"):
                    lines.append(f"  {body_line}")

    if len(lines) <= 1:
        # Header only — no units, no cases. Skip the section entirely so we
        # don't waste tokens on a content-free heading.
        return None

    rendered = "\n".join(lines)
    if len(rendered) <= char_limit:
        return rendered
    # Trim on a line boundary near the cap so we never slice mid-bullet.
    cutoff = rendered.rfind("\n", 0, char_limit)
    if cutoff < int(char_limit * 0.6):
        cutoff = char_limit
    return rendered[:cutoff].rstrip() + "\n…"


async def _build_course_block(
    course: Any,
    module_obj: Module | None,
    language: str,
    session: AsyncSession,
    char_limit: int | None = None,
) -> str | None:
    """Render the course-level cacheable layer of the tutor prompt (#1984).

    Stable per ``(course, language)`` — eligible for prompt caching across
    every turn within a session that doesn't switch course.

    Includes:
      * Course title + domain.
      * Full ``course.syllabus_context`` (no longer trimmed at 1.4k chars).
      * Per-resource summary from ``course_resources.summary_text`` so the
        tutor can name reference materials without a tool call.
      * Cross-module map: every other module's title + a generated/pending
        status marker so the tutor knows what's discoverable elsewhere.

    Returns ``None`` when no course is in scope.
    """
    if course is None:
        return None
    char_limit = (
        char_limit if char_limit is not None else _sc().get("tutor-course-block-char-limit", 20000)
    )

    if language == "fr":
        title_label = "Cours"
        domain_label = "Domaine"
        syllabus_label = "Syllabus"
        resources_label = "Ressources de référence"
        modules_map_label = "Carte des modules"
        generated_marker = "✓"
        pending_marker = "🔒"
    else:
        title_label = "Course"
        domain_label = "Domain"
        syllabus_label = "Syllabus"
        resources_label = "Reference resources"
        modules_map_label = "Module map"
        generated_marker = "✓"
        pending_marker = "🔒"

    course_title = (
        getattr(course, "title_fr", None) if language == "fr" else getattr(course, "title_en", None)
    ) or ""
    course_domain = getattr(course, "domain", None) or course_title

    parts: list[str] = []
    if course_title:
        parts.append(f"**{title_label}:** {course_title}")
    if course_domain:
        parts.append(f"**{domain_label}:** {course_domain}")

    syllabus_text = (getattr(course, "syllabus_context", None) or "").strip()
    if not syllabus_text:
        syllabus_json = getattr(course, "syllabus_json", None)
        if syllabus_json:
            syllabus_text = _flatten_syllabus_json(syllabus_json).strip()
    if syllabus_text:
        parts.append(f"\n## {syllabus_label}\n{syllabus_text}")

    # Reference resources — opt-out via setting if needed (heavy summaries).
    try:
        from app.domain.models.course_resource import CourseResource

        result = await session.execute(
            select(CourseResource).where(CourseResource.course_id == course.id)
        )
        resources = result.scalars().all()
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning(
            "Failed to load course resources for tutor prompt",
            course_id=str(getattr(course, "id", "?")),
            error=str(exc),
        )
        resources = []
    resource_lines: list[str] = []
    for res in resources:
        title = (getattr(res, "filename", None) or getattr(res, "title", "")).strip()
        summary = (getattr(res, "summary_text", None) or "").strip()
        if not summary:
            continue
        if title:
            resource_lines.append(f"- **{title}:** {summary}")
        else:
            resource_lines.append(f"- {summary}")
    if resource_lines:
        parts.append(f"\n## {resources_label}\n" + "\n".join(resource_lines))

    # Cross-module map — gives the tutor a way to point learners across
    # modules without loading every module's full content.
    if bool(_sc().get("tutor-include-cross-module-map", True)):
        modules_map_lines: list[str] = []
        try:
            from app.domain.models.module import Module as ModuleModel

            mod_result = await session.execute(
                select(ModuleModel)
                .where(ModuleModel.course_id == course.id)
                .order_by(ModuleModel.module_number.asc())
            )
            all_modules = mod_result.scalars().all()
        except Exception:
            all_modules = []
        # Which modules have any GeneratedContent in this language? Single
        # batched query — much cheaper than per-module probes.
        generated_module_ids: set = set()
        try:
            gc_result = await session.execute(
                select(GeneratedContent.module_id)
                .where(GeneratedContent.language == language)
                .distinct()
            )
            generated_module_ids = {mid for (mid,) in gc_result.all()}
        except Exception:
            pass
        active_id = getattr(module_obj, "id", None)
        for m in all_modules:
            mtitle = (
                getattr(m, "title_fr", None) if language == "fr" else getattr(m, "title_en", None)
            ) or ""
            mnumber = getattr(m, "module_number", None) or "?"
            marker = generated_marker if m.id in generated_module_ids else pending_marker
            you_are_here = " ← " + ("vous êtes ici" if language == "fr" else "you are here")
            suffix = you_are_here if active_id is not None and m.id == active_id else ""
            modules_map_lines.append(f"- {mnumber}. {mtitle} {marker}{suffix}")
        if modules_map_lines:
            parts.append(f"\n## {modules_map_label}\n" + "\n".join(modules_map_lines))

    if not parts:
        return None
    rendered = "\n".join(parts)
    if len(rendered) <= char_limit:
        return rendered
    cutoff = rendered.rfind("\n", 0, char_limit)
    if cutoff < int(char_limit * 0.6):
        cutoff = char_limit
    return rendered[:cutoff].rstrip() + "\n…"


def _assemble_cached_system(
    persona_text: str,
    course_text: str | None,
    module_text: str | None,
    learner_text: str,
) -> list[dict[str, Any]]:
    """Build the Anthropic ``system=`` argument as a list of cacheable blocks (#1984).

    Layered most-stable-first so prompt caching hits the longest matching
    prefix on every repeat turn:

      1. Persona block — stable per (course, language, audience). Cached.
      2. Course block — stable per (course, language). Cached.
      3. Module block — stable per (module, language). Cached.
      4. Learner block — per-conversation. **NOT** cached so memory updates
         and progress changes mid-session don't bust the prefix above.

    Empty optional blocks (``course_text`` / ``module_text``) are simply
    omitted from the list, preserving the cache prefix for sessions without
    course or module context.
    """
    blocks: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": persona_text,
            "cache_control": {"type": "ephemeral"},
        },
    ]
    if course_text:
        blocks.append(
            {
                "type": "text",
                "text": course_text,
                "cache_control": {"type": "ephemeral"},
            }
        )
    if module_text:
        blocks.append(
            {
                "type": "text",
                "text": module_text,
                "cache_control": {"type": "ephemeral"},
            }
        )
    blocks.append(
        {
            "type": "text",
            "text": learner_text,
            # No cache_control — this is the only per-conversation slice and
            # changes whenever learner memory or progress updates.
        }
    )
    return blocks


async def _resolve_source_images_by_uuid(
    uuids: set[str],
    session: AsyncSession,
) -> dict[str, dict[str, Any]]:
    """Fetch ``SourceImage`` rows for the given UUID strings and return a map
    keyed on UUID string whose values have the exact shape the frontend
    expects in ``sourceImageRefs`` entries.

    Silent on missing UUIDs (returns only what was found) and on DB errors
    (returns an empty map after logging). Keeps the live stream and the
    history GET path from diverging in shape. See #1937.
    """
    if not uuids:
        return {}
    try:
        result = await session.execute(
            select(SourceImage).where(SourceImage.id.in_([uuid.UUID(u) for u in uuids]))
        )
    except Exception as exc:
        logger.warning("Failed to resolve source image UUIDs", error=str(exc))
        return {}

    resolved: dict[str, dict[str, Any]] = {}
    for img in result.scalars().all():
        meta = img.to_meta_dict()
        resolved[str(img.id)] = {
            "id": str(img.id),
            "figure_number": meta.get("figure_number"),
            "caption": meta.get("caption"),
            "caption_fr": meta.get("caption_fr") or meta.get("caption"),
            "caption_en": meta.get("caption_en") or meta.get("caption"),
            "attribution": meta.get("attribution"),
            "image_type": meta.get("image_type", "unknown"),
            "storage_url": meta.get("storage_url"),
            "storage_url_fr": meta.get("storage_url_fr"),
            "alt_text_fr": meta.get("alt_text_fr"),
            "alt_text_en": meta.get("alt_text_en"),
        }
    return resolved


async def _attach_source_image_refs(
    messages: list[dict[str, Any]],
    session: AsyncSession,
) -> list[dict[str, Any]]:
    """Return ``messages`` with ``source_image_refs`` added to each assistant
    entry that contains ``{{source_image:UUID}}`` markers.

    User messages are left untouched (listen/image rendering is assistant-only).
    Missing UUIDs are silently dropped — same contract as the live-stream
    resolver. Markers in a message are returned in first-appearance order so
    the frontend's ``splitWithSourceImageMarkers`` renders correctly.
    """
    # First pass — collect the union of UUIDs across all assistant messages.
    all_uuids: set[str] = set()
    per_message_uuids: list[list[str]] = []
    for msg in messages:
        if msg.get("role") != "assistant":
            per_message_uuids.append([])
            continue
        content = msg.get("content") or ""
        uuids_in_order: list[str] = []
        seen_local: set[str] = set()
        for m in _SOURCE_IMAGE_MARKER_RE.finditer(content):
            uid = m.group(1).lower()
            if uid not in seen_local:
                seen_local.add(uid)
                uuids_in_order.append(uid)
        per_message_uuids.append(uuids_in_order)
        all_uuids.update(uuids_in_order)

    resolved = await _resolve_source_images_by_uuid(all_uuids, session)

    # Second pass — build each message's refs list without mutating input.
    out: list[dict[str, Any]] = []
    for msg, uuids_in_order in zip(messages, per_message_uuids, strict=False):
        if not uuids_in_order:
            out.append(msg)
            continue
        refs = [resolved[u] for u in uuids_in_order if u in resolved]
        # Shallow-copy so existing callers that retain a reference to the
        # conversation's stored messages (e.g. in-process tests) aren't
        # surprised by a mutation.
        enriched = dict(msg)
        enriched["source_image_refs"] = refs
        out.append(enriched)
    return out


@dataclass
class SessionContext:
    """Composed session context for a tutor conversation."""

    learner_memory: str = ""
    previous_compact: str = ""
    current_compact: str = ""
    progress_snapshot: str = ""
    is_new_conversation: bool = True

    @property
    def has_prior_context(self) -> bool:
        """Return True if any prior context was loaded."""
        return bool(self.learner_memory or self.previous_compact or self.current_compact)

    def total_text(self) -> str:
        """Return concatenated context text for token estimation."""
        parts = [
            self.learner_memory,
            self.previous_compact,
            self.current_compact,
            self.progress_snapshot,
        ]
        return "\n".join(p for p in parts if p)

    def estimated_tokens(self) -> int:
        """Rough estimate: ~4 chars per token."""
        return len(self.total_text()) // 4


class SessionManager:
    """Composes full session context for a tutor conversation.

    Loads learner memory + compacted history + progress snapshot and enforces
    the SESSION_CONTEXT_TOKEN_BUDGET so injected context stays ≤1500 tokens.
    """

    def __init__(self, learner_memory_service: LearnerMemoryService) -> None:
        self.learner_memory_service = learner_memory_service

    async def build_session_context(
        self,
        user: User,
        conversation: TutorConversation,
        is_new_conversation: bool,
        session: AsyncSession,
    ) -> SessionContext:
        """Build full session context respecting the token budget.

        For a new conversation: loads learner_memory + last conversation's compacted_context.
        For a continuing conversation: loads learner_memory + current compacted_context.
        Progress snapshot is derived from the User model (level, country).
        """
        ctx = SessionContext(is_new_conversation=is_new_conversation)

        ctx.learner_memory = await self.learner_memory_service.format_for_prompt(user.id, session)

        if is_new_conversation:
            prior = await self._get_previous_compact(user.id, conversation.id, session)
            if prior:
                ctx.previous_compact = prior
        else:
            if conversation.compacted_context:
                ctx.current_compact = conversation.compacted_context

        ctx.progress_snapshot = _build_progress_snapshot(user)

        ctx = _trim_to_budget(ctx)

        logger.info(
            "Session context built",
            user_id=str(user.id),
            conversation_id=str(conversation.id),
            is_new=is_new_conversation,
            estimated_tokens=ctx.estimated_tokens(),
            has_prior_context=ctx.has_prior_context,
        )

        return ctx

    async def _get_previous_compact(
        self,
        user_id: uuid.UUID,
        current_conversation_id: uuid.UUID,
        session: AsyncSession,
    ) -> str | None:
        """Return compacted_context from the most recent prior conversation."""
        result = await session.execute(
            select(TutorConversation)
            .where(
                TutorConversation.user_id == user_id,
                TutorConversation.id != current_conversation_id,
                TutorConversation.compacted_context.isnot(None),
            )
            .order_by(TutorConversation.created_at.desc())
            .limit(1)
        )
        prev = result.scalar_one_or_none()
        return prev.compacted_context if prev else None


def _build_progress_snapshot(user: User) -> str:
    """Build a short progress snapshot from the user model."""
    level_labels = {
        1: "Beginner (L1)",
        2: "Intermediate (L2)",
        3: "Advanced (L3)",
        4: "Expert (L4)",
    }
    level_label = level_labels.get(user.current_level, f"Level {user.current_level}")
    parts = [f"Level: {level_label}", f"Country: {user.country or 'CI'}"]
    if hasattr(user, "streak_days") and user.streak_days:
        parts.append(f"Streak: {user.streak_days} days")
    return ", ".join(parts)


def _trim_to_budget(ctx: SessionContext) -> SessionContext:
    """Trim context fields to stay within SESSION_CONTEXT_TOKEN_BUDGET.

    Priority order (least to most likely trimmed):
    progress_snapshot > learner_memory > previous_compact/current_compact
    """
    if ctx.estimated_tokens() <= SESSION_CONTEXT_TOKEN_BUDGET:
        return ctx

    budget_chars = SESSION_CONTEXT_TOKEN_BUDGET * 4

    if ctx.previous_compact:
        available = budget_chars - len(ctx.learner_memory) - len(ctx.progress_snapshot)
        if available < len(ctx.previous_compact):
            ctx.previous_compact = ctx.previous_compact[: max(0, available)]

    if ctx.current_compact:
        available = budget_chars - len(ctx.learner_memory) - len(ctx.progress_snapshot)
        if available < len(ctx.current_compact):
            ctx.current_compact = ctx.current_compact[: max(0, available)]

    if ctx.estimated_tokens() > SESSION_CONTEXT_TOKEN_BUDGET:
        available = budget_chars - len(ctx.progress_snapshot)
        if available < len(ctx.learner_memory):
            ctx.learner_memory = ctx.learner_memory[: max(0, available)]

    return ctx


class TutorService:
    """Service for managing AI tutor conversations with agentic tool_use and Socratic approach."""

    def __init__(
        self,
        anthropic_client: AsyncAnthropic,
        semantic_retriever: SemanticRetriever,
        embedding_service: EmbeddingService,
        learner_memory_service: LearnerMemoryService | None = None,
    ):
        self.anthropic = anthropic_client
        self.retriever = semantic_retriever
        self.embedding_service = embedding_service
        self.learner_memory_service = learner_memory_service or LearnerMemoryService()
        self.session_manager = SessionManager(self.learner_memory_service)
        self.settings = get_settings()

    async def send_message(
        self,
        user_id: str | uuid.UUID,
        message: str,
        session: AsyncSession,
        module_id: uuid.UUID | None = None,
        context_type: str | None = None,
        context_id: uuid.UUID | None = None,
        conversation_id: uuid.UUID | None = None,
        tutor_mode: str = "socratic",
        file_content_blocks: list[dict[str, Any]] | None = None,
        course_id: uuid.UUID | None = None,
        locale: str | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        Send a message to the AI tutor and stream the response using agentic tool_use.

        Claude autonomously decides when to call tools (RAG search, progress lookup, etc.)
        The tool loop runs server-side; only text chunks are streamed to the client.

        Args:
            user_id: User ID
            message: User message
            session: Database session
            module_id: Optional module context
            context_type: Optional context type ("module", "lesson", "quiz")
            context_id: Optional context-specific ID
            conversation_id: Optional existing conversation ID
            file_content_blocks: Optional list of Claude API content blocks (images/text) from uploads
            course_id: Optional course ID (derived from enrollment if absent)

        Yields:
            Stream chunks with tutor response data
        """
        if isinstance(user_id, str):
            user_id = uuid.UUID(user_id)

        subscription = await SubscriptionService().get_active_subscription(user_id, session)
        messages_used = await self._check_daily_limit(user_id, session)
        if subscription:
            effective_limit = subscription.daily_message_limit + subscription.message_credits
        else:
            effective_limit = 5
        if messages_used >= effective_limit:
            yield {
                "type": "error",
                "data": {
                    "code": "limit_reached",
                    "message": "Daily message limit reached. Try again tomorrow.",
                    "limit_reached": True,
                },
            }
            return

        user = await session.get(User, user_id)
        if not user:
            yield {"type": "error", "data": {"message": "User not found"}}
            return

        try:
            is_new_conversation = conversation_id is None
            conversation = await self._get_or_create_conversation(
                user_id, module_id, conversation_id, session
            )

            session_ctx = await self.session_manager.build_session_context(
                user=user,
                conversation=conversation,
                is_new_conversation=is_new_conversation,
                session=session,
            )

            if (
                is_new_conversation
                and session_ctx.previous_compact
                and not conversation.compacted_context
            ):
                conversation.compacted_context = session_ctx.previous_compact
                session.add(conversation)
                # Commit here too so the compacted_context is visible to the
                # follow-up GET the frontend fires on the yielded id (#1625).
                await session.commit()

            yield {
                "type": "conversation_id",
                "data": {"conversation_id": str(conversation.id)},
            }

            effective_language = locale if locale in ("fr", "en") else user.preferred_language

            if locale in ("fr", "en") and user.preferred_language != locale:
                user.preferred_language = locale
                session.add(user)

            # Resolve module title for human-readable system prompt. Eager-
            # load ``units`` so we can render the within-module structure for
            # the tutor (#1981) without a separate round-trip.
            from sqlalchemy.orm import selectinload

            module_title = None
            module_number = None
            module_obj = None
            if module_id:
                result = await session.execute(
                    select(Module).where(Module.id == module_id).options(selectinload(Module.units))
                )
                module_obj = result.scalar_one_or_none()
                if module_obj:
                    module_title = (
                        module_obj.title_fr if effective_language == "fr" else module_obj.title_en
                    )
                    module_number = module_obj.module_number

            # Build the per-module unit/quiz/case-study detail (#1981). Returns
            # None when no module is in scope, in which case the section is
            # omitted from the prompt.
            current_module_content = await _build_current_module_section(
                module_obj, effective_language, session
            )

            # Resolve course context: explicit > from module > from enrollment
            course = await self._resolve_course(course_id, module_id, module_obj, user_id, session)
            course_title = None
            course_domain = None
            course_syllabus = None
            rag_collection_id = None
            if course:
                course_title = course.title_fr if effective_language == "fr" else course.title_en
                course_domain = course_domain or course_title
                rag_collection_id = course.rag_collection_id
                # Syllabus injected into the system prompt so the tutor can
                # situate concepts within the course progression (#1979).
                course_syllabus = _build_syllabus_for_prompt(
                    course.syllabus_context, course.syllabus_json
                )

                # Touch course interaction for recent-courses ranking
                try:
                    from app.domain.services.progress_service import touch_course_interaction

                    await touch_course_interaction(session, uuid.UUID(str(user_id)), course.id)
                except Exception:
                    pass  # non-fatal

            audience = detect_audience(course)

            # Build the cacheable course-level block (#1984). Stable per
            # (course, language) — eligible for prompt caching across every
            # turn within a session.
            course_block_text = await _build_course_block(
                course, module_obj, effective_language, session
            )

            context = TutorContext(
                user_level=user.current_level,
                user_language=effective_language,
                user_country=user.country or "CI",
                module_id=str(module_id) if module_id else None,
                module_title=module_title,
                module_number=module_number,
                context_type=context_type,
                tutor_mode=tutor_mode,
                context_id=str(context_id) if context_id else None,
                course_title=course_title,
                course_domain=course_domain,
                course_syllabus=course_syllabus,
                current_module_content=current_module_content,
                learner_memory=session_ctx.learner_memory,
                previous_session_context=session_ctx.previous_compact,
                progress_snapshot=session_ctx.progress_snapshot,
                is_kids=audience.is_kids,
                age_min=audience.age_min,
                age_max=audience.age_max,
            )

            # Layered, cacheable system prompt (#1984). Falls back to the
            # legacy single-string path when caching is killed via setting.
            caching_enabled = bool(_sc().get("tutor-context-caching-enabled", True))
            if caching_enabled:
                persona_block_text = get_persona_block_text(context)
                learner_block_text = get_learner_block_text(context)
                system_prompt: Any = _assemble_cached_system(
                    persona_text=persona_block_text,
                    course_text=course_block_text,
                    module_text=current_module_content,
                    learner_text=learner_block_text,
                )
            else:
                system_prompt = get_socratic_system_prompt(context, [])

            conversation_history = await self._prepare_conversation_history(conversation)

            user_msg_stored = {
                "role": "user",
                "content": message,
                "timestamp": datetime.utcnow().isoformat(),
                "has_files": bool(file_content_blocks),
            }

            # Persist the user's message before the LLM loop runs (#1975).
            # Stream interruptions between here and end-of-stream then lose
            # only the assistant reply — recoverable — instead of both sides.
            await self._persist_user_message(conversation, user_msg_stored, session)

            if file_content_blocks:
                user_content: list[Any] = [*file_content_blocks, {"type": "text", "text": message}]
                conversation_history.append({"role": "user", "content": user_content})
            else:
                conversation_history.append({"role": "user", "content": message})

            tool_executor = TutorToolExecutor(
                retriever=self.retriever,
                anthropic_client=self.anthropic,
                user_id=user_id,
                user_level=user.current_level,
                user_language=effective_language,
                rag_collection_id=rag_collection_id,
            )

            tool_call_count = 0
            full_response = ""
            all_tool_calls: list[dict[str, Any]] = []
            sources_cited: list[dict[str, Any]] = []
            source_image_refs: list[dict[str, Any]] = []
            api_messages: list[MessageParam] = list(conversation_history)

            while tool_call_count <= MAX_TOOL_CALLS:
                response = await self.anthropic.messages.create(
                    model="claude-sonnet-4-6",
                    system=system_prompt,
                    messages=api_messages,
                    tools=TOOL_DEFINITIONS,
                    max_tokens=_sc().get("tutor-response-max-tokens", 1500),
                    temperature=_sc().get("tutor-response-temperature", 0.7),
                )

                # Prompt-caching telemetry (#1984). Anthropic returns
                # ``cache_read_input_tokens`` (cache hit) and
                # ``cache_creation_input_tokens`` (cache write). Watching
                # cache_read on turn 2+ tells us caching is actually working.
                try:
                    usage = getattr(response, "usage", None)
                    if usage is not None:
                        logger.info(
                            "tutor_claude_call",
                            model="claude-sonnet-4-6",
                            input_tokens=getattr(usage, "input_tokens", None),
                            output_tokens=getattr(usage, "output_tokens", None),
                            cache_read=getattr(usage, "cache_read_input_tokens", None),
                            cache_creation=getattr(usage, "cache_creation_input_tokens", None),
                            user_id=str(user_id),
                            tool_call_count=tool_call_count,
                        )
                except Exception:  # pragma: no cover — telemetry must never break the tutor
                    pass

                tool_use_blocks = [
                    block for block in response.content if isinstance(block, ToolUseBlock)
                ]

                if not tool_use_blocks:
                    text_parts = [
                        block.text
                        for block in response.content
                        if hasattr(block, "text") and block.text
                    ]
                    full_response = "".join(text_parts)

                    for chunk_text in _split_into_chunks(full_response):
                        yield {
                            "type": "content",
                            "data": {"text": chunk_text},
                            "conversation_id": str(conversation.id),
                        }
                    break

                if tool_call_count >= MAX_TOOL_CALLS:
                    logger.warning(
                        "Max tool calls reached, forcing final response",
                        user_id=str(user_id),
                        tool_call_count=tool_call_count,
                    )
                    text_parts = [
                        block.text
                        for block in response.content
                        if hasattr(block, "text") and block.text
                    ]
                    full_response = "".join(text_parts)
                    if full_response:
                        for chunk_text in _split_into_chunks(full_response):
                            yield {
                                "type": "content",
                                "data": {"text": chunk_text},
                                "conversation_id": str(conversation.id),
                            }
                    break

                assistant_content: list[Any] = list(response.content)
                api_messages.append({"role": "assistant", "content": assistant_content})

                tool_results: list[ToolResultBlockParam] = []
                for tool_block in tool_use_blocks:
                    tool_call_count += 1

                    logger.info(
                        "Tutor tool call",
                        tool_name=tool_block.name,
                        tool_id=tool_block.id,
                        user_id=str(user_id),
                        call_number=tool_call_count,
                    )

                    yield {
                        "type": "tool_call",
                        "data": {
                            "tool_name": tool_block.name,
                            "call_number": tool_call_count,
                        },
                        "conversation_id": str(conversation.id),
                    }

                    tool_result_str = await tool_executor.execute(
                        tool_name=tool_block.name,
                        tool_input=tool_block.input,
                        session=session,
                    )

                    all_tool_calls.append(
                        {
                            "tool_name": tool_block.name,
                            "tool_id": tool_block.id,
                            "input": tool_block.input,
                            "result_preview": tool_result_str[:200],
                        }
                    )

                    if tool_block.name == "search_knowledge_base":
                        import json

                        try:
                            rag_result = json.loads(tool_result_str)
                            for chunk in rag_result.get("results", []):
                                source_info: dict[str, Any] = {
                                    "source": chunk.get("source", ""),
                                    "content_preview": chunk.get("content", "")[:100] + "...",
                                    "similarity_score": chunk.get("similarity", 0),
                                }
                                if chunk.get("chapter"):
                                    source_info["chapter"] = chunk["chapter"]
                                if chunk.get("page"):
                                    source_info["page"] = chunk["page"]
                                sources_cited.append(source_info)
                        except Exception:
                            pass

                    elif tool_block.name == "search_source_images":
                        try:
                            import json as _json

                            img_result = _json.loads(tool_result_str)
                            prefix = "{{source_image:"
                            img_ids_to_fetch: list[str] = []
                            for fig in img_result.get("figures", []):
                                ref: str = fig.get("ref", "")
                                if ref.startswith(prefix) and ref.endswith("}}"):
                                    img_ids_to_fetch.append(ref[len(prefix) : -2])

                            if img_ids_to_fetch:
                                try:
                                    db_imgs = await session.execute(
                                        select(SourceImage).where(
                                            SourceImage.id.in_(
                                                [uuid.UUID(i) for i in img_ids_to_fetch]
                                            )
                                        )
                                    )
                                    db_img_map = {str(r.id): r for r in db_imgs.scalars().all()}
                                except Exception:
                                    db_img_map = {}

                                seen_img_ids: set[str] = {r["id"] for r in source_image_refs}
                                for img_id in img_ids_to_fetch:
                                    if img_id in seen_img_ids:
                                        continue
                                    seen_img_ids.add(img_id)
                                    db_img = db_img_map.get(img_id)
                                    if db_img:
                                        meta = db_img.to_meta_dict()
                                        source_image_refs.append(
                                            {
                                                "id": img_id,
                                                "figure_number": meta.get("figure_number"),
                                                "caption": meta.get("caption"),
                                                "caption_fr": meta.get("caption_fr")
                                                or meta.get("caption"),
                                                "caption_en": meta.get("caption_en")
                                                or meta.get("caption"),
                                                "attribution": meta.get("attribution"),
                                                "image_type": meta.get("image_type", "unknown"),
                                                "storage_url": meta.get("storage_url"),
                                                "storage_url_fr": meta.get("storage_url_fr"),
                                                "alt_text_fr": meta.get("alt_text_fr"),
                                                "alt_text_en": meta.get("alt_text_en"),
                                            }
                                        )
                        except Exception:
                            pass

                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_block.id,
                            "content": tool_result_str,
                        }
                    )

                api_messages.append({"role": "user", "content": tool_results})

            unique_sources = _deduplicate_sources(sources_cited)

            activity_suggestions = self._extract_activity_suggestions(
                full_response, context_type, user.current_level
            )

            assistant_msg_stored = {
                "role": "assistant",
                "content": full_response,
                "sources": unique_sources,
                "timestamp": datetime.utcnow().isoformat(),
                "activity_suggestions": activity_suggestions,
                "tool_calls_count": tool_call_count,
            }

            # User message was already committed before the LLM loop (#1975);
            # this commit only adds the assistant reply on top of it.
            assistant_position = conversation.total_messages or 0
            updated_messages = conversation.messages + [assistant_msg_stored]
            conversation.messages = updated_messages
            conversation.message_count = len(updated_messages)
            conversation.total_messages = assistant_position + 1
            # Index of the just-persisted assistant reply — the frontend needs
            # this to hit /tutor/conversations/{id}/messages/{index}/audio for
            # the listen button (#1932). Messages are positional, so the
            # assistant reply is the last entry in the updated list.
            assistant_message_index = len(updated_messages) - 1
            session.add(conversation)
            session.add(
                TutorMessage(
                    conversation_id=conversation.id,
                    position=assistant_position,
                    role="assistant",
                    content=full_response or "",
                    extra=_message_extra(assistant_msg_stored),
                )
            )

            if (
                subscription
                and messages_used >= subscription.daily_message_limit
                and subscription.message_credits > 0
            ):
                subscription.message_credits -= 1
                session.add(subscription)

            await session.commit()

            try:
                analytics_svc = AnalyticsService(session)
                await analytics_svc.ingest_event(
                    event_name="tutor_message_sent",
                    properties={
                        "module_id": str(module_id) if module_id else None,
                        "language": effective_language,
                    },
                    user_id=uuid.UUID(str(user_id)),
                    session_id=None,
                )
            except Exception as analytics_err:
                logger.warning("Analytics event failed (non-fatal)", error=str(analytics_err))

            if conversation.message_count > COMPACT_TRIGGER:
                asyncio.ensure_future(
                    self._compact_conversation_async(
                        conversation_id=conversation.id,
                        user_language=user.preferred_language,
                    )
                )

            yield {
                "type": "sources_retrieved",
                "data": {
                    "chunk_count": len(unique_sources),
                    "sources": [s.get("source", "") for s in unique_sources],
                },
                "conversation_id": str(conversation.id),
            }

            yield {
                "type": "sources_cited",
                "data": {"sources": unique_sources},
                "conversation_id": str(conversation.id),
            }

            # Resolve any {{source_image:UUID}} markers in the response that
            # weren't captured via tool calls (e.g. from conversation history).
            # Shares the resolver with get_conversation() so the shape stays
            # identical between live stream and history GET (#1937).
            seen_ids = {r["id"].lower() for r in source_image_refs}
            extra_ids = {
                m.group(1).lower()
                for m in _SOURCE_IMAGE_MARKER_RE.finditer(full_response)
                if m.group(1).lower() not in seen_ids
            }
            if extra_ids:
                resolved = await _resolve_source_images_by_uuid(extra_ids, session)
                source_image_refs.extend(resolved.values())

            if source_image_refs:
                yield {
                    "type": "source_image_refs",
                    "data": {"refs": source_image_refs},
                    "conversation_id": str(conversation.id),
                }

            yield {
                "type": "activity_suggestions",
                "data": {"suggestions": activity_suggestions},
                "conversation_id": str(conversation.id),
            }

            # Carries the persisted message index so the frontend can render
            # a listen-button wired to /tutor/conversations/{id}/messages/{N}
            # /audio without re-fetching the whole conversation (#1932).
            yield {
                "type": "message_complete",
                "data": {"message_index": assistant_message_index},
                "conversation_id": str(conversation.id),
            }

            credits_after = subscription.message_credits if subscription else 0
            yield {
                "type": "finished",
                "data": {
                    "remaining_messages": max(0, effective_limit - messages_used - 1),
                    "message_credits": credits_after,
                    "conversation_id": str(conversation.id),
                    "tool_calls_made": tool_call_count,
                },
                "finished": True,
            }

        except Exception as e:
            logger.error("Error in tutor chat", error=str(e), user_id=str(user_id))
            yield {
                "type": "error",
                "data": {"code": "tutor_error", "message": "An error occurred. Please try again."},
            }

    async def get_conversation(
        self, user_id: str | uuid.UUID, conversation_id: uuid.UUID, session: AsyncSession
    ) -> dict[str, Any] | None:
        """Get a specific conversation.

        Assistant messages containing ``{{source_image:UUID}}`` markers have
        ``source_image_refs`` attached with resolved figure metadata, so the
        frontend can render images identically to the live-stream path (#1937).
        """
        if isinstance(user_id, str):
            user_id = uuid.UUID(user_id)

        query = select(TutorConversation).where(
            TutorConversation.id == conversation_id, TutorConversation.user_id == user_id
        )
        result = await session.execute(query)
        conversation = result.scalar_one_or_none()

        if not conversation:
            return None

        # Prefer the durable per-message store so the user can scroll back to
        # the very first message even after several compaction passes (#1978).
        # Fall back to the legacy JSON array for conversations that pre-date
        # the migration's backfill (defence-in-depth).
        messages_query = (
            select(TutorMessage)
            .where(TutorMessage.conversation_id == conversation_id)
            .order_by(TutorMessage.position.asc())
        )
        rows = (await session.execute(messages_query)).scalars().all()
        if rows:
            # Spread ``extra`` first so role/content from the dedicated columns
            # always win — guards against a future caller stuffing ``role`` or
            # ``content`` into the JSON ``extra`` payload.
            messages_full = [
                {
                    **(row.extra or {}),
                    "role": row.role,
                    "content": row.content,
                }
                for row in rows
            ]
        else:
            messages_full = conversation.messages or []

        messages_out = await _attach_source_image_refs(messages_full, session)

        return {
            "id": conversation.id,
            "module_id": conversation.module_id,
            "messages": messages_out,
            "created_at": conversation.created_at,
        }

    async def list_conversations(
        self, user_id: str | uuid.UUID, session: AsyncSession, limit: int = 20, offset: int = 0
    ) -> dict[str, Any]:
        """List user's tutor conversations."""
        if isinstance(user_id, str):
            user_id = uuid.UUID(user_id)

        query = (
            select(TutorConversation)
            .where(TutorConversation.user_id == user_id)
            .order_by(TutorConversation.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(query)
        conversations = result.scalars().all()

        count_query = select(func.count(TutorConversation.id)).where(
            TutorConversation.user_id == user_id
        )
        count_result = await session.execute(count_query)
        total = count_result.scalar() or 0

        summaries = []
        for conv in conversations:
            preview = ""
            if conv.messages and len(conv.messages) > 0:
                first_user_msg = next(
                    (msg for msg in conv.messages if msg.get("role") == "user"), None
                )
                if first_user_msg:
                    preview = first_user_msg.get("content", "")[:50] + "..."

            last_message_at = conv.created_at
            if conv.messages:
                try:
                    last_ts = conv.messages[-1].get("timestamp")
                    if last_ts:
                        last_message_at = datetime.fromisoformat(last_ts)
                except (ValueError, TypeError):
                    pass

            summaries.append(
                {
                    "id": conv.id,
                    "module_id": conv.module_id,
                    # Read the increment-only counter so the sidebar count
                    # stays monotonic per conversation across compaction
                    # passes (#1978). Falls back to the JSON length only if
                    # the counter is somehow unset (legacy backfill safety).
                    "message_count": conv.total_messages or len(conv.messages or []),
                    "last_message_at": last_message_at,
                    "preview": preview,
                    "has_context": bool(conv.compacted_context),
                }
            )

        return {"conversations": summaries, "total": total}

    async def delete_conversation(
        self,
        user_id: str | uuid.UUID,
        conversation_id: uuid.UUID,
        session: AsyncSession,
    ) -> bool:
        """Delete a specific conversation. Returns True if deleted."""
        if isinstance(user_id, str):
            user_id = uuid.UUID(user_id)

        query = select(TutorConversation).where(
            TutorConversation.id == conversation_id,
            TutorConversation.user_id == user_id,
        )
        result = await session.execute(query)
        conversation = result.scalar_one_or_none()

        if not conversation:
            return False

        await session.delete(conversation)
        await session.commit()

        logger.info(
            "Conversation deleted",
            user_id=str(user_id),
            conversation_id=str(conversation_id),
            message_count=len(conversation.messages) if conversation.messages else 0,
        )
        return True

    async def delete_all_conversations(
        self,
        user_id: str | uuid.UUID,
        session: AsyncSession,
    ) -> int:
        """Delete all conversations for a user. Returns count deleted."""
        if isinstance(user_id, str):
            user_id = uuid.UUID(user_id)

        query = select(TutorConversation).where(
            TutorConversation.user_id == user_id,
        )
        result = await session.execute(query)
        conversations = result.scalars().all()

        count = len(conversations)
        for conv in conversations:
            await session.delete(conv)

        if count:
            await session.commit()
            logger.info(
                "All conversations deleted",
                user_id=str(user_id),
                deleted_count=count,
            )

        return count

    async def get_last_touched_module(
        self, user_id: str | uuid.UUID, session: AsyncSession
    ) -> dict[str, Any] | None:
        """Return the user's most recently accessed module (#1988).

        Used by the standalone ``/tutor`` page to anchor the chat in a
        concrete module by default — without this the prompt's module block
        is empty and the tutor can't cite specific units (the user-reported
        symptom that prompted #1988).

        Sources the recency from ``UserModuleProgress.last_accessed`` (the
        same field ``progress_service.touch_course_interaction_by_module``
        already updates on every learner action). Returns ``None`` when the
        user has no recorded module activity yet.
        """
        from app.domain.models.course import Course
        from app.domain.models.progress import UserModuleProgress

        if isinstance(user_id, str):
            user_id = uuid.UUID(user_id)

        user = await session.get(User, user_id)
        language = (user.preferred_language if user else "fr") or "fr"

        result = await session.execute(
            select(UserModuleProgress)
            .where(
                UserModuleProgress.user_id == user_id,
                UserModuleProgress.last_accessed.is_not(None),
            )
            .order_by(UserModuleProgress.last_accessed.desc())
            .limit(1)
        )
        progress = result.scalar_one_or_none()
        if progress is None:
            return None

        module = await session.get(Module, progress.module_id)
        if module is None:
            # Defensive: progress row pointing at a deleted module. Skip.
            return None
        course = (
            await session.get(Course, module.course_id)
            if getattr(module, "course_id", None)
            else None
        )

        module_title = (module.title_fr if language == "fr" else module.title_en) or ""
        course_title = None
        if course is not None:
            course_title = (course.title_fr if language == "fr" else course.title_en) or None

        return {
            "module_id": module.id,
            "module_number": getattr(module, "module_number", None),
            "module_title": module_title,
            "course_id": getattr(module, "course_id", None),
            "course_title": course_title,
            "last_accessed": progress.last_accessed,
        }

    async def get_tutor_stats(
        self, user_id: str | uuid.UUID, session: AsyncSession
    ) -> dict[str, Any]:
        """Get tutor usage statistics for a user."""
        if isinstance(user_id, str):
            user_id = uuid.UUID(user_id)

        daily_messages = await self._check_daily_limit(user_id, session)

        subscription = await SubscriptionService().get_active_subscription(user_id, session)
        if subscription:
            limit = subscription.daily_message_limit + subscription.message_credits
            message_credits = subscription.message_credits
        else:
            limit = 5
            message_credits = 0

        count_query = select(func.count(TutorConversation.id)).where(
            TutorConversation.user_id == user_id
        )
        count_result = await session.execute(count_query)
        total_conversations = count_result.scalar() or 0

        most_discussed_topics: list[Any] = []

        return {
            "daily_messages_used": daily_messages,
            "daily_messages_limit": limit,
            "message_credits": message_credits,
            "total_conversations": total_conversations,
            "most_discussed_topics": most_discussed_topics,
        }

    async def _check_daily_limit(self, user_id: str | uuid.UUID, session: AsyncSession) -> int:
        """How many user messages were sent today.

        Sums the increment-only ``user_messages_sent`` column (#1978). The
        previous implementation counted ``role == "user"`` rows inside the
        ``messages`` JSON array, which shrank whenever async compaction
        truncated the array — making the daily counter oscillate. The dedicated
        column is never decremented and never touched by compaction, so the
        result is monotonic within a UTC day.
        """
        if isinstance(user_id, str):
            user_id = uuid.UUID(user_id)

        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

        query = select(func.coalesce(func.sum(TutorConversation.user_messages_sent), 0)).where(
            TutorConversation.user_id == user_id,
            TutorConversation.created_at >= today_start,
        )
        result = await session.execute(query)
        return int(result.scalar_one() or 0)

    async def _get_or_create_conversation(
        self,
        user_id: str | uuid.UUID,
        module_id: uuid.UUID | None,
        conversation_id: uuid.UUID | None,
        session: AsyncSession,
    ) -> TutorConversation:
        """Get existing conversation or create a new one.

        Newly-created conversations are committed before the helper returns
        so that the streaming endpoint can safely yield the `conversation_id`
        to the client without racing a follow-up GET on a different session
        (#1625). `expire_on_commit=False` on the session factory keeps the
        Python object usable after commit.
        """
        if isinstance(user_id, str):
            user_id = uuid.UUID(user_id)

        if conversation_id:
            query = select(TutorConversation).where(
                TutorConversation.id == conversation_id,
                TutorConversation.user_id == user_id,
            )
            result = await session.execute(query)
            conversation = result.scalar_one_or_none()
            if conversation:
                return conversation

        conversation = TutorConversation(
            id=uuid.uuid4(),
            user_id=user_id,
            module_id=module_id,
            messages=[],
            created_at=datetime.utcnow(),
        )
        session.add(conversation)
        await session.commit()

        return conversation

    async def _resolve_course(
        self,
        course_id: uuid.UUID | None,
        module_id: uuid.UUID | None,
        module_obj: Module | None,
        user_id: uuid.UUID,
        session: AsyncSession,
    ):
        """Thin wrapper around the module-level :func:`resolve_course` helper.

        Kept so existing tests that ``patch.object(TutorService, '_resolve_course')``
        continue to work. New code should call ``resolve_course`` directly.
        """
        return await resolve_course(course_id, module_id, module_obj, user_id, session)

    async def _retrieve_relevant_context(
        self, query: str, user: User, module_id: uuid.UUID | None, session: AsyncSession
    ) -> list[Any]:
        """Retrieve relevant context using RAG (kept for backward compatibility)."""
        books_sources = None
        if module_id:
            from sqlalchemy.orm import selectinload

            result = await session.execute(
                select(Module).where(Module.id == module_id).options(selectinload(Module.course))
            )
            module = result.scalar_one_or_none()
            if module:
                course = module.course
                if course and course.rag_collection_id:
                    books_sources = {course.rag_collection_id: []}
                elif module.books_sources:
                    books_sources = module.books_sources

        search_results = await self.retriever.search_for_module(
            query=query,
            user_level=user.current_level,
            user_language=user.preferred_language,
            books_sources=books_sources,
            top_k=_sc().get("ai-rag-default-top-k", 8),
            session=session,
        )

        logger.info(
            "RAG retrieval completed",
            user_id=str(user.id),
            query_length=len(query),
            results_count=len(search_results),
            module_id=str(module_id) if module_id else None,
        )

        return search_results

    async def _prepare_conversation_history(
        self, conversation: TutorConversation
    ) -> list[dict[str, str]]:
        """Prepare conversation history for Claude API.

        Compaction is non-destructive (#1978): the full ordered ``messages``
        array stays intact, and ``compacted_through_position`` marks where the
        summary in ``compacted_context`` ends. We send the summary (if any)
        followed by every message past that high-water mark so Claude sees
        complete continuity without re-paying the token cost of the summarised
        prefix. When nothing has been compacted yet we cap at the last
        ``COMPACT_KEEP_RECENT * 2`` turns so the prompt stays bounded for very
        long pre-compaction conversations.
        """
        all_messages = conversation.messages or []
        compacted_through = conversation.compacted_through_position or 0

        claude_messages: list[dict[str, str]] = []

        if conversation.compacted_context:
            claude_messages.append({"role": "user", "content": conversation.compacted_context})
            claude_messages.append(
                {
                    "role": "assistant",
                    "content": "Compris. Je vais tenir compte de ce contexte pour la suite.",
                }
            )
            recent_messages = all_messages[compacted_through:]
        else:
            cap = max(10, COMPACT_KEEP_RECENT * 2)
            recent_messages = all_messages[-cap:] if len(all_messages) > cap else all_messages

        for msg in recent_messages:
            content = (msg.get("content") or "").strip()
            if msg.get("role") and content:
                claude_messages.append(
                    {
                        "role": msg["role"],
                        "content": content,
                    }
                )

        return claude_messages

    async def _persist_user_message(
        self,
        conversation: TutorConversation,
        user_msg: dict[str, Any],
        session: AsyncSession,
    ) -> None:
        """Append the user's message to the conversation and commit immediately.

        Splitting this from the assistant-reply commit is the durability fix for
        #1975: a stream interruption (mobile dropout, AbortController, container
        restart) between message receipt and end-of-stream used to lose both
        sides of the exchange because they shared a single commit. With this
        helper called before the LLM loop, only the assistant reply is at risk
        — and the user can see their message persisted on reload and retry.

        Also writes a durable row to ``tutor_messages`` and increments the
        increment-only counters (#1978) — the JSON array stays the working set
        for Claude, but billing/display counts no longer depend on its length.
        """
        # Counters can be None on a freshly-constructed instance that hasn't
        # been flushed yet (server defaults haven't fired) — coerce to 0.
        position = conversation.total_messages or 0
        conversation.messages = conversation.messages + [user_msg]
        conversation.message_count = len(conversation.messages)
        conversation.user_messages_sent = (conversation.user_messages_sent or 0) + 1
        conversation.total_messages = position + 1
        session.add(conversation)
        session.add(
            TutorMessage(
                conversation_id=conversation.id,
                position=position,
                role="user",
                content=user_msg.get("content", "") or "",
                extra=_message_extra(user_msg),
            )
        )
        await session.commit()

    async def _compact_conversation_async(
        self,
        conversation_id: uuid.UUID,
        user_language: str,
    ) -> None:
        """Summarize old messages into ``compacted_context`` non-destructively (#1978).

        Runs asynchronously (fire-and-forget) so it never blocks the response
        stream. Produces a Claude-generated summary covering messages
        ``[compacted_through_position : compacted_through_position + N]`` where
        ``N = COMPACT_SUMMARIZE_UP_TO``, then advances
        ``compacted_through_position`` past the summarised slice. The
        ``messages`` JSON array and the increment-only counters
        (``user_messages_sent``, ``total_messages``) are **not** mutated — so
        the daily limit stays accurate and the sidebar count never shrinks.

        The summary is what gets sent to Claude on the next call (see
        ``_prepare_conversation_history``); the durable per-message store in
        ``tutor_messages`` keeps the originals available for scroll-back.
        """
        try:
            engine = create_async_engine(self.settings.database_url, echo=False)
            session_factory = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )
            async with session_factory() as session:
                result = await session.execute(
                    select(TutorConversation).where(TutorConversation.id == conversation_id)
                )
                conversation = result.scalar_one_or_none()
                if not conversation:
                    return

                start = conversation.compacted_through_position or 0
                end = start + COMPACT_SUMMARIZE_UP_TO
                messages_to_compact = (conversation.messages or [])[start:end]

                if not messages_to_compact:
                    return

                prompt = get_compaction_prompt(
                    messages=messages_to_compact,
                    existing_compact=conversation.compacted_context,
                    language=user_language,
                )

                compact_response = await self.anthropic.messages.create(
                    model="claude-sonnet-4-6",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=_sc().get("tutor-compaction-max-tokens", 600),
                    temperature=_sc().get("tutor-compaction-temperature", 0.3),
                )

                compact_text_parts = [
                    block.text
                    for block in compact_response.content
                    if hasattr(block, "text") and block.text
                ]
                new_compact = "".join(compact_text_parts).strip()

                conversation.compacted_context = new_compact
                conversation.compacted_at = datetime.utcnow()
                # Advance by the actual slice length, not the constant. Otherwise
                # a partial slice (when end > len(messages)) would mark unread
                # messages as "summarised" and the next pass would skip them.
                conversation.compacted_through_position = start + len(messages_to_compact)
                # Intentionally NOT mutating conversation.messages,
                # message_count, user_messages_sent, or total_messages — those
                # are the source of truth for billing and the UI.
                session.add(conversation)
                await session.commit()

                logger.info(
                    "Conversation compacted",
                    conversation_id=str(conversation_id),
                    messages_summarized=len(messages_to_compact),
                    compacted_through_position=end,
                    compact_length=len(new_compact),
                )
        except Exception:
            logger.exception("Failed to compact conversation", conversation_id=str(conversation_id))
        finally:
            import contextlib

            async with contextlib.AsyncExitStack():
                with contextlib.suppress(Exception):
                    await engine.dispose()

    async def _get_previous_compact(
        self, user_id: uuid.UUID, current_conversation_id: uuid.UUID, session: AsyncSession
    ) -> str | None:
        """Return the compacted_context from the most recent prior conversation (cross-session)."""
        result = await session.execute(
            select(TutorConversation)
            .where(
                TutorConversation.user_id == user_id,
                TutorConversation.id != current_conversation_id,
                TutorConversation.compacted_context.isnot(None),
            )
            .order_by(TutorConversation.created_at.desc())
            .limit(1)
        )
        prev = result.scalar_one_or_none()
        return prev.compacted_context if prev else None

    def _extract_activity_suggestions(
        self, response: str, context_type: str | None, user_level: int
    ) -> list[dict[str, str]]:
        """Extract activity suggestions from the response or generate them."""
        health_topics = [
            "surveillance",
            "épidémiologie",
            "biostatistics",
            "paludisme",
            "santé publique",
            "vaccination",
            "nutrition",
            "hygiène",
        ]

        topic = "santé publique"
        for health_topic in health_topics:
            if health_topic in response.lower():
                topic = health_topic
                break

        return get_activity_suggestions(context_type, user_level, topic)


def _split_into_chunks(text: str, chunk_size: int = 50) -> list[str]:
    """Split text into smaller chunks for streaming simulation."""
    if not text:
        return []
    chunks = []
    for i in range(0, len(text), chunk_size):
        chunks.append(text[i : i + chunk_size])
    return chunks


def _deduplicate_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove duplicate sources by source+chapter+page."""
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for source in sources:
        key = f"{source.get('source', '')}-{source.get('chapter', '')}-{source.get('page', '')}"
        if key not in seen:
            seen.add(key)
            unique.append(source)
    return unique[:5]
