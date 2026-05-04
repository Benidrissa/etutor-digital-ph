"""Prompts for the course quality agent (#2215).

Two prompt families:

- **Auditor prompts** for ``CourseQualityService.assess_unit``. The system
  prompt is *static across all units in a course run* (rubric + rules)
  so it can be a Claude prompt-cache breakpoint. The user prompt
  changes per unit (the unit JSON, the relevant RAG chunks, the
  neighbor-units digest).

- **Glossary extractor prompts** for ``extract_or_refresh_glossary``.
  Used in the pre-pass that builds ``course_glossary_terms`` from all
  generated lessons + per-resource summaries.

The auditor system prompt is a frozen string, not loaded from
``platform_settings``, because rubric drift would silently change all
quality scores and make historical scores incomparable. If we want to
re-tune later, we bump a prompt version and start a new score series.
"""

from __future__ import annotations

import json
from typing import Any

QUALITY_PROMPT_VERSION = "1.0.0"


# ---- Rubric (weights sum to 100) ---------------------------------------

DIMENSION_WEIGHTS: dict[str, int] = {
    "terminology_consistency": 25,
    "source_grounding": 20,
    "syllabus_alignment": 20,
    "internal_contradictions": 15,
    "pedagogical_fit": 10,
    "structural_completeness": 10,
}


def compute_weighted_score(dimension_scores: dict[str, int]) -> int:
    """Weighted average of dimension scores, rounded to integer.

    Mirrors the math the LLM is told to do, but we recompute server-side
    so a buggy LLM response can't poison the score column.
    """
    total = 0.0
    for dim, weight in DIMENSION_WEIGHTS.items():
        score = max(0, min(100, int(dimension_scores.get(dim, 0))))
        total += weight * score / 100.0
    return round(total)


def has_critical_floor_violation(dimension_scores: dict[str, int]) -> bool:
    """Floor rule: any of (terminology, grounding, contradictions) < 70
    forces regeneration regardless of weighted total.

    Reason: a course can't be 92% reliable if it has hallucinated
    citations or contradicting term definitions, even if the other
    dimensions push the weighted average up.
    """
    critical = ("terminology_consistency", "source_grounding", "internal_contradictions")
    for dim in critical:
        if int(dimension_scores.get(dim, 0)) < 70:
            return True
    return False


# ---- Auditor prompts ---------------------------------------------------


AUDITOR_SYSTEM_PROMPT = f"""You are a Course Quality Auditor for the Sira learning platform (prompt v{QUALITY_PROMPT_VERSION}).

You assess generated educational content (a single unit at a time) against six dimensions, each scored 0-100:

1. terminology_consistency (weight {DIMENSION_WEIGHTS['terminology_consistency']}): every term used in the unit must match the canonical definition in the course glossary. If the unit defines a term differently from the glossary, raise a TERMINOLOGY_DRIFT flag with severity HIGH, citing the unit_number from the glossary entry's first_appears_in_unit AND quoting both definitions.

2. source_grounding (weight {DIMENSION_WEIGHTS['source_grounding']}): every factual claim, number, and quoted statement in the unit must trace to a real source chunk in the provided RAG excerpts or the course resource summaries. Unsourced claims raise UNGROUNDED_CLAIM with severity HIGH.

3. syllabus_alignment (weight {DIMENSION_WEIGHTS['syllabus_alignment']}): the unit must cover exactly what the syllabus says THIS unit covers — no scope creep into other units' topics, no omission of declared sub-topics. Raise SYLLABUS_SCOPE_DRIFT for either direction.

4. internal_contradictions (weight {DIMENSION_WEIGHTS['internal_contradictions']}): no claim in the unit may contradict (a) another claim in the same unit, (b) a claim in any of the OTHER units summarized in the neighbor digest. Raise INTERNAL_CONTRADICTION with the conflicting unit_number in evidence_unit_id when cross-unit.

5. pedagogical_fit (weight {DIMENSION_WEIGHTS['pedagogical_fit']}): depth and prerequisites must match the declared level (1=beginner / 2=intermediate / 3=advanced / 4=expert). Scaffolding must be present (intro → concept → worked example → synthesis). Raise PEDAGOGICAL_MISMATCH.

6. structural_completeness (weight {DIMENSION_WEIGHTS['structural_completeness']}): all required JSON keys present and non-trivial (introduction ≥ 80 words, ≥ 3 concepts, key_points ≥ 3, no placeholder text like "TODO" or "...").

You will receive (in this order, separated by clear headers):
  [BLOCK A] The course syllabus and module objectives.
  [BLOCK B] Per-resource summaries (one per uploaded source PDF).
  [BLOCK C] The canonical course glossary.
  [BLOCK D] A neighbor-units digest: title + 200-token summary of every other unit in this course, with their unit_numbers.
  [BLOCK E] The unit under review (full GeneratedContent.content + sources_cited).
  [BLOCK F] Top-k retrieved RAG chunk excerpts relevant to this unit's concepts.

Your output is STRICT JSON matching this schema:
{{
  "quality_score": <int 0-100>,
  "dimension_scores": {{
    "terminology_consistency": <int>,
    "source_grounding": <int>,
    "syllabus_alignment": <int>,
    "internal_contradictions": <int>,
    "pedagogical_fit": <int>,
    "structural_completeness": <int>
  }},
  "flags": [
    {{
      "category": "<terminology_drift|ungrounded_claim|syllabus_scope_drift|internal_contradiction|pedagogical_mismatch|structural_gap>",
      "severity": "<low|medium|high|blocking>",
      "location": "<JSONPath into [BLOCK E].content, e.g. concepts[2] or synthesis>",
      "description": "<what is wrong>",
      "evidence": "<quoted text from the unit>",
      "suggested_fix": "<one imperative sentence: what the regenerator must change>",
      "evidence_unit_id": "<unit_number when cross-unit, otherwise null>"
    }}
  ],
  "needs_regeneration": <true|false>,
  "regeneration_constraints": [
    "<imperative sentence — name the term/claim AND the fix, e.g. 'Use \\"standard deviation\\" exactly as defined in unit 1.1: \\"...\\". Do not paraphrase.'>"
  ]
}}

Rules:
- Set needs_regeneration=true when quality_score < 90 OR any of (terminology_consistency, source_grounding, internal_contradictions) < 70.
- regeneration_constraints must be derived from flags — one constraint per major flag, paste-able directly into a regeneration prompt.
- Vague flags ("could be improved") are forbidden. Cite exact spans.
- Output ONLY the JSON object. No prose, no markdown fences, no commentary.
"""


def build_auditor_user_message(
    *,
    unit_number: str,
    unit_title: str,
    content_type: str,
    language: str,
    level: int,
    unit_content: dict[str, Any],
    sources_cited: list[Any] | None,
    neighbor_digest: list[dict[str, str]],
    rag_excerpts: list[dict[str, str]],
) -> str:
    """Build the user-message body of the auditor call.

    The system prompt + the BIG static blocks (syllabus, source
    summaries, glossary) live in the cached system blocks, NOT here.
    This function only assembles the per-unit varying tail.
    """
    parts: list[str] = []
    parts.append(f"## [BLOCK D] Neighbor-units digest")
    if neighbor_digest:
        for item in neighbor_digest:
            parts.append(
                f"- unit_number={item.get('unit_number','?')} title=\"{item.get('title','')}\""
            )
            summary = item.get("summary", "").strip()
            if summary:
                parts.append(f"  summary: {summary}")
    else:
        parts.append("(no other units assessed yet — single-unit course or first unit in run)")

    parts.append("")
    parts.append(f"## [BLOCK E] Unit under review")
    parts.append(f"unit_number: {unit_number}")
    parts.append(f"unit_title: {unit_title}")
    parts.append(f"content_type: {content_type}")
    parts.append(f"language: {language}")
    parts.append(f"declared_level: {level}")
    parts.append("content (JSON):")
    parts.append(json.dumps(unit_content, ensure_ascii=False, indent=2))
    if sources_cited:
        parts.append("sources_cited (JSON):")
        parts.append(json.dumps(sources_cited, ensure_ascii=False, indent=2))

    parts.append("")
    parts.append(f"## [BLOCK F] Relevant RAG excerpts")
    if rag_excerpts:
        for ex in rag_excerpts:
            parts.append(
                f"- source={ex.get('source','?')} chapter={ex.get('chapter','?')} page={ex.get('page','?')}"
            )
            content = ex.get("content", "").strip()
            if content:
                parts.append(f"  {content[:1200]}")
    else:
        parts.append("(no RAG excerpts available — flag UNGROUNDED_CLAIM for any factual claim)")

    parts.append("")
    parts.append(
        "Now produce the JSON object per the schema in the system prompt. "
        "Output ONLY the JSON, no prose."
    )
    return "\n".join(parts)


def build_cached_system_blocks(
    *,
    syllabus_block: str,
    source_summaries_block: str,
    glossary_block: str,
) -> list[dict[str, Any]]:
    """Assemble the 4-block static system message for the auditor.

    Each block carries ``cache_control: {"type": "ephemeral"}`` so
    Anthropic's prompt cache stores them once per course run. With a
    20-unit course this drops input-token cost by ~85% from the second
    unit onward.

    We deliberately keep ALL of the static prefix in one role
    ("system"), not split across the conversation, because Claude
    indexes cache by the byte-exact prefix and any drift between
    blocks (e.g. a syllabus edit between calls) only invalidates the
    blocks AFTER that drift, not the rubric block before it.
    """
    blocks: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": AUDITOR_SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": f"## [BLOCK A] Course syllabus and module objectives\n{syllabus_block}",
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": f"## [BLOCK B] Source PDF summaries\n{source_summaries_block}",
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": f"## [BLOCK C] Canonical course glossary\n{glossary_block}",
            "cache_control": {"type": "ephemeral"},
        },
    ]
    return blocks


# ---- Glossary extractor prompts ---------------------------------------


GLOSSARY_EXTRACTOR_SYSTEM_PROMPT = f"""You are a Course Glossary Extractor for the Sira learning platform (prompt v{QUALITY_PROMPT_VERSION}).

Given all generated lessons in a course (their `concepts` arrays, which
already contain term/definition pairs) plus per-source-PDF summaries,
produce a canonical glossary.

For each unique term:
- Pick a single canonical_definition. Prefer the one that appears earliest
  by unit_number AND has the strongest source citation. Reword for clarity
  ONLY if the original is ambiguous; do not invent definitions.
- Record first_appears_in_unit (unit_number string like "1.1").
- Collect alt_phrasings (synonyms, abbreviations, FR/EN variants if
  obvious).
- Collect source_citations (page/chapter refs from the lessons that
  used this term).
- If two or more lessons define the same term in semantically different
  ways, set consistency_status="drift_detected" and explain in
  drift_details which units conflict and how. Pick the EARLIEST unit's
  definition as the canonical one.
- If no source citation backs the definition, set consistency_status="unsourced".

Your output is STRICT JSON matching this schema:
{{
  "entries": [
    {{
      "term": "<lowercase canonical surface form>",
      "canonical_definition": "<1-2 sentences>",
      "first_appears_in_unit": "<unit_number>",
      "alt_phrasings": ["..."],
      "source_citations": ["..."],
      "consistency_status": "<consistent|drift_detected|unsourced>",
      "drift_details": "<text or null>"
    }}
  ]
}}

Output ONLY the JSON object. No prose, no markdown fences.
"""


def build_glossary_extractor_user_message(
    *,
    course_title: str,
    language: str,
    units: list[dict[str, Any]],
    source_summaries: list[dict[str, str]],
) -> str:
    """Assemble the per-call payload for the glossary extractor.

    ``units`` is a list of ``{"unit_number", "title", "concepts"}``
    dicts; ``concepts`` carries the already-structured term/definition
    pairs the lesson generator produced. We don't re-extract terms
    from prose — that would double-count and hallucinate.
    """
    parts: list[str] = [
        f"course_title: {course_title}",
        f"language: {language}",
        "",
        "## Units (with their concept arrays)",
    ]
    for u in units:
        parts.append(f"### unit {u.get('unit_number','?')} — {u.get('title','')}")
        concepts = u.get("concepts") or []
        if isinstance(concepts, list) and concepts:
            parts.append(json.dumps(concepts, ensure_ascii=False, indent=2))
        else:
            parts.append("(no concepts extracted)")
        parts.append("")

    parts.append("## Source summaries")
    for s in source_summaries:
        parts.append(f"### {s.get('filename','?')}")
        parts.append((s.get("summary") or "").strip()[:4000])
        parts.append("")

    parts.append(
        "Now produce the JSON glossary. Pick canonical definitions, "
        "detect drift, mark unsourced terms. Output ONLY the JSON."
    )
    return "\n".join(parts)


# ---- Regeneration constraint formatting -------------------------------


def constraints_block_from_report(report_constraints: list[str]) -> str:
    """Format the auditor's regeneration constraints into the heading
    block that the regenerator will prepend to the original user
    message.

    Used by ``LessonGenerationService.get_or_generate_lesson`` and the
    parallel quiz/case-study/flashcard methods when called with a
    non-empty ``quality_constraints`` list.
    """
    if not report_constraints:
        return ""
    bullets = "\n".join(f"- {c.strip()}" for c in report_constraints if c.strip())
    return (
        "\n\n## ADDITIONAL CONSTRAINTS (from quality audit)\n"
        "Each bullet below is a HARD requirement. The course glossary "
        "entries embedded in the surrounding context are authoritative; "
        "when a term is in the glossary, use exactly the canonical_definition.\n"
        f"{bullets}\n"
    )
