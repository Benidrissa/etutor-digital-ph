"""Default values and metadata for all platform settings.

This is the single source of truth for setting definitions.
The JSON config file only stores overrides; any missing key
falls back to the default defined here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SettingDef:
    key: str
    category: str
    default: Any
    value_type: str  # integer | float | string | boolean | json
    label: str
    description: str = ""
    validation: dict | None = None
    is_sensitive: bool = False


SETTING_DEFINITIONS: list[SettingDef] = [
    # ── Quiz & Assessment ──────────────────────────────────
    SettingDef(
        "quiz-unit-questions-count",
        "quiz",
        10,
        "integer",
        "Questions per unit quiz",
        "Number of questions for each unit-level quiz.",
        {"min": 3, "max": 50},
    ),
    SettingDef(
        "quiz-summative-questions-count",
        "quiz",
        20,
        "integer",
        "Questions per summative assessment",
        "Questions in the module summative assessment.",
        {"min": 5, "max": 50},
    ),
    SettingDef(
        "quiz-passing-score",
        "quiz",
        80.0,
        "float",
        "Passing score (%)",
        "Minimum percentage to pass a quiz or assessment.",
        {"min": 40, "max": 100},
    ),
    SettingDef(
        "quiz-time-limit-min-minutes",
        "quiz",
        10,
        "integer",
        "Minimum time limit (minutes)",
        "Floor value for quiz time limit calculation.",
        {"min": 5, "max": 60},
    ),
    SettingDef(
        "quiz-time-limit-per-question-minutes",
        "quiz",
        1.5,
        "float",
        "Minutes per question",
        "Multiplied by question count for time limit.",
        {"min": 0.5, "max": 5.0},
    ),
    SettingDef(
        "quiz-summative-time-limit-minutes",
        "quiz",
        30,
        "integer",
        "Summative time limit (minutes)",
        "Maximum time for summative assessments.",
        {"min": 10, "max": 180},
    ),
    # ── Progress & Unlocking ───────────────────────────────
    SettingDef(
        "progress-unlock-threshold-pct",
        "progress",
        80.0,
        "float",
        "Module unlock — completion %",
        "Min completion % to unlock next module.",
        {"min": 50, "max": 100},
    ),
    SettingDef(
        "progress-unlock-threshold-score",
        "progress",
        80.0,
        "float",
        "Module unlock — quiz score avg %",
        "Min quiz avg to unlock next module.",
        {"min": 50, "max": 100},
    ),
    SettingDef(
        "progress-unit-pass-score",
        "progress",
        80.0,
        "float",
        "Unit pass score (%)",
        "Quiz score to mark a unit as completed.",
        {"min": 40, "max": 100},
    ),
    # ── Flashcards (FSRS) ─────────────────────────────────
    SettingDef(
        "flashcards-new-cards-per-session",
        "flashcards",
        20,
        "integer",
        "New flashcards per session",
        "Max new flashcards per study session.",
        {"min": 5, "max": 100},
    ),
    SettingDef(
        "flashcards-review-preview-days",
        "flashcards",
        14,
        "integer",
        "Review preview window (days)",
        "Days ahead to show upcoming reviews.",
        {"min": 7, "max": 90},
    ),
    SettingDef(
        "flashcards-min-generated-count",
        "flashcards",
        15,
        "integer",
        "Min flashcards per generation",
        "Warn if AI generates fewer.",
        {"min": 5, "max": 50},
    ),
    SettingDef(
        "flashcards-fsrs-params",
        "flashcards",
        {
            "again": {"stability": 0.5, "difficulty": 1.0},
            "hard": {"stability": 0.8, "difficulty": 0.5},
            "good": {"stability": 1.2, "difficulty": -0.1},
            "easy": {"stability": 1.5, "difficulty": -0.2, "interval": 1.3},
        },
        "json",
        "FSRS spaced-repetition parameters",
        "Stability multipliers and difficulty adjustments.",
    ),
    # ── Placement Test ─────────────────────────────────────
    SettingDef(
        "placement-level-thresholds",
        "placement",
        {"1": [0, 40], "2": [40, 60], "3": [60, 80], "4": [80, 101]},
        "json",
        "Score-to-level thresholds",
        "Score ranges for level assignment.",
    ),
    SettingDef(
        "placement-retest-cooldown-days",
        "placement",
        90,
        "integer",
        "Retest cooldown (days)",
        "Min days before retaking placement test.",
        {"min": 0, "max": 365},
    ),
    SettingDef(
        "placement-role-bonuses",
        "placement",
        {"doctor": 5, "researcher": 8, "nurse": 3, "student": -3},
        "json",
        "Role score adjustments (%)",
        "Bonuses/penalties by profession.",
    ),
    SettingDef(
        "placement-time-adjustments",
        "placement",
        {
            "fast_threshold_sec": 600,
            "fast_penalty": -10,
            "slow_threshold_sec": 2400,
            "slow_penalty": -5,
            "optimal_range_sec": [900, 1800],
            "optimal_bonus": 2,
        },
        "json",
        "Time-based score adjustments",
        "Penalties/bonuses by completion time.",
    ),
    SettingDef(
        "placement-competency-threshold",
        "placement",
        70,
        "integer",
        "Competency area threshold",
        "Min level score for competency identification.",
        {"min": 40, "max": 100},
    ),
    # ── Auth & Security (sensitive) ────────────────────────
    SettingDef(
        "auth-access-token-expiry-minutes",
        "auth",
        15,
        "integer",
        "Access token expiry (minutes)",
        "JWT access token lifetime.",
        {"min": 5, "max": 120},
        True,
    ),
    SettingDef(
        "auth-refresh-token-expiry-days",
        "auth",
        90,
        "integer",
        "Refresh token expiry (days)",
        "JWT refresh token lifetime.",
        {"min": 7, "max": 365},
        True,
    ),
    SettingDef(
        "auth-magic-link-expiry-hours",
        "auth",
        1,
        "integer",
        "Magic link expiry (hours)",
        "Password-reset magic link lifetime.",
        {"min": 1, "max": 48},
        True,
    ),
    SettingDef(
        "auth-max-failed-totp-attempts",
        "auth",
        10,
        "integer",
        "Max failed TOTP attempts",
        "Lock after this many failed MFA attempts.",
        {"min": 3, "max": 30},
        True,
    ),
    SettingDef(
        "auth-totp-lockout-minutes",
        "auth",
        15,
        "integer",
        "TOTP lockout duration (minutes)",
        "Lock duration after failed MFA.",
        {"min": 5, "max": 120},
        True,
    ),
    SettingDef(
        "auth-otp-expiry-minutes",
        "auth",
        10,
        "integer",
        "Email OTP expiry (minutes)",
        "Email OTP code lifetime.",
        {"min": 5, "max": 60},
        True,
    ),
    SettingDef(
        "auth-otp-max-attempts",
        "auth",
        5,
        "integer",
        "Max OTP verification attempts",
        "Max attempts per OTP code.",
        {"min": 3, "max": 20},
        True,
    ),
    SettingDef(
        "auth-otp-rate-limit-window-seconds",
        "auth",
        600,
        "integer",
        "OTP rate limit window (seconds)",
        "Time window for OTP rate limiting.",
        {"min": 60, "max": 3600},
        True,
    ),
    SettingDef(
        "auth-otp-max-requests-per-window",
        "auth",
        5,
        "integer",
        "Max OTP requests per window",
        "Max OTP requests within rate window.",
        {"min": 2, "max": 20},
        True,
    ),
    SettingDef(
        "auth-backup-codes-count",
        "auth",
        8,
        "integer",
        "Backup codes count",
        "Backup codes generated during TOTP setup.",
        {"min": 4, "max": 20},
        True,
    ),
    # ── Rate Limiting ──────────────────────────────────────
    SettingDef(
        "rate-limiting-global-requests-per-minute",
        "rate_limiting",
        100,
        "integer",
        "Global rate limit (req/min)",
        "Max requests per minute per IP.",
        {"min": 10, "max": 1000},
        True,
    ),
    SettingDef(
        "rate-limiting-tutor-daily-limit",
        "rate_limiting",
        200,
        "integer",
        "Tutor messages daily limit",
        "Max tutor messages per user per day.",
        {"min": 10, "max": 1000},
    ),
    # ── AI & Content Generation ────────────────────────────
    SettingDef(
        "ai-max-tokens-content",
        "ai",
        64000,
        "integer",
        "Max tokens — content generation",
        "Max output tokens for Claude API calls.",
        {"min": 4000, "max": 128000},
    ),
    SettingDef(
        "ai-temperature-content",
        "ai",
        0.7,
        "float",
        "Temperature — content generation",
        "Claude temperature for content.",
        {"min": 0.0, "max": 1.5},
    ),
    SettingDef(
        "ai-rag-default-top-k",
        "ai",
        8,
        "integer",
        "RAG retrieval top-k (default)",
        "Chunks retrieved for content generation.",
        {"min": 3, "max": 30},
    ),
    SettingDef(
        "ai-rag-flashcard-top-k",
        "ai",
        12,
        "integer",
        "RAG retrieval top-k (flashcards)",
        "Chunks retrieved for flashcard generation.",
        {"min": 3, "max": 30},
    ),
    SettingDef(
        "ai-syllabus-soft-time-limit-seconds",
        "ai",
        2700,
        "integer",
        "Syllabus generation — soft time limit (seconds)",
        "Soft time limit for syllabus generation Celery task. Task receives a warning after this duration.",
        {"min": 300, "max": 7200},
    ),
    SettingDef(
        "ai-syllabus-hard-time-limit-seconds",
        "ai",
        3600,
        "integer",
        "Syllabus generation — hard time limit (seconds)",
        "Hard time limit for syllabus generation Celery task. Task is killed after this duration.",
        {"min": 600, "max": 7200},
    ),
    # ── Tutor ──────────────────────────────────────────────
    SettingDef(
        "tutor-response-max-tokens",
        "tutor",
        1500,
        "integer",
        "Tutor response max tokens",
        "Max tokens per tutor response.",
        {"min": 500, "max": 8000},
    ),
    SettingDef(
        "tutor-response-temperature",
        "tutor",
        0.7,
        "float",
        "Tutor response temperature",
        "Claude temperature for tutor.",
        {"min": 0.0, "max": 1.5},
    ),
    SettingDef(
        "tutor-compaction-trigger-messages",
        "tutor",
        20,
        "integer",
        "Compaction trigger (messages)",
        "Compact after this many messages.",
        {"min": 10, "max": 100},
    ),
    SettingDef(
        "tutor-compaction-keep-recent",
        "tutor",
        5,
        "integer",
        "Compaction — keep recent",
        "Recent messages to keep when compacting.",
        {"min": 2, "max": 20},
    ),
    SettingDef(
        "tutor-compaction-summarize-up-to",
        "tutor",
        15,
        "integer",
        "Compaction — summarize up to",
        "Older messages to summarize.",
        {"min": 5, "max": 50},
    ),
    SettingDef(
        "tutor-context-token-budget",
        "tutor",
        1500,
        "integer",
        "Session context token budget",
        "Max tokens for session context.",
        {"min": 500, "max": 5000},
    ),
    SettingDef(
        "tutor-max-tool-calls",
        "tutor",
        3,
        "integer",
        "Max tool calls per response",
        "Max Claude tool calls per response.",
        {"min": 1, "max": 10},
    ),
    SettingDef(
        "tutor-compaction-max-tokens",
        "tutor",
        600,
        "integer",
        "Compaction summary max tokens",
        "Max tokens for compaction summary.",
        {"min": 200, "max": 2000},
    ),
    SettingDef(
        "tutor-compaction-temperature",
        "tutor",
        0.3,
        "float",
        "Compaction temperature",
        "Lower temperature for factual summaries.",
        {"min": 0.0, "max": 1.0},
    ),
    SettingDef(
        "tutor-suggestions-max-tokens",
        "tutor",
        800,
        "integer",
        "Learning suggestions max tokens",
        "Max tokens for learning suggestions.",
        {"min": 200, "max": 2000},
    ),
    SettingDef(
        "tutor-suggestions-temperature",
        "tutor",
        0.5,
        "float",
        "Suggestions temperature",
        "Temperature for learning suggestions.",
        {"min": 0.0, "max": 1.0},
    ),
    # ── Marketplace & Billing ──────────────────────────────
    SettingDef(
        "marketplace-commission-pct",
        "marketplace",
        20.0,
        "float",
        "Platform commission (%)",
        "Platform commission percentage on course sales.",
        {"min": 0.0, "max": 100.0},
    ),
    SettingDef(
        "marketplace-min-course-price",
        "marketplace",
        0,
        "integer",
        "Min course price (credits)",
        "Minimum course price in credits.",
        {"min": 0, "max": 100000},
    ),
    SettingDef(
        "marketplace-max-course-price",
        "marketplace",
        500000,
        "integer",
        "Max course price (credits)",
        "Maximum course price in credits.",
        {"min": 0, "max": 10000000},
    ),
    SettingDef(
        "marketplace-enabled",
        "marketplace",
        False,
        "boolean",
        "Marketplace enabled",
        "Enable or disable the marketplace feature.",
    ),
    SettingDef(
        "credits-per-1k-input-tokens",
        "marketplace",
        1.0,
        "float",
        "Credits per 1K input tokens",
        "Credits charged per 1,000 input tokens.",
        {"min": 0.0, "max": 100.0},
    ),
    SettingDef(
        "credits-per-1k-output-tokens",
        "marketplace",
        3.0,
        "float",
        "Credits per 1K output tokens",
        "Credits charged per 1,000 output tokens.",
        {"min": 0.0, "max": 100.0},
    ),
    SettingDef(
        "credits-per-1k-embedding-tokens",
        "marketplace",
        0.1,
        "float",
        "Credits per 1K embedding tokens",
        "Credits charged per 1,000 embedding tokens.",
        {"min": 0.0, "max": 100.0},
    ),
    SettingDef(
        "free-trial-credits",
        "marketplace",
        50000,
        "integer",
        "Free trial credits",
        "Free credits granted to new accounts.",
        {"min": 0, "max": 1000000},
    ),
    SettingDef(
        "expert-activation-cost",
        "marketplace",
        10000,
        "integer",
        "Expert activation cost (credits)",
        "Credits required to activate an expert account.",
        {"min": 0, "max": 1000000},
    ),
    SettingDef(
        "offline-download-cost-per-module",
        "marketplace",
        500,
        "integer",
        "Offline download cost per module (credits)",
        "Credits charged per module offline download.",
        {"min": 0, "max": 100000},
    ),
    # ── Payments ───────────────────────────────────────────
    SettingDef(
        "payments-orange-money-number",
        "payments",
        "+221 77 000 0000",
        "string",
        "Orange Money payment number",
        "Phone number displayed to users for Orange Money transfers.",
    ),
    SettingDef(
        "payments-subscription-price-xof",
        "payments",
        2000,
        "integer",
        "Subscription price (FCFA)",
        "Monthly subscription price displayed on the subscribe page.",
        {"min": 0, "max": 100000},
    ),
    SettingDef(
        "payments-subscription-duration-days",
        "payments",
        28,
        "integer",
        "Subscription duration (days)",
        "Days of access per payment.",
        {"min": 1, "max": 365},
    ),
    # ── AI Prompts ─────────────────────────────────────────
    SettingDef(
        "ai-prompt-lesson-system",
        "ai_prompts",
        (
            "You are an expert educator in {course_title}. You design adaptive, bilingual (FR/EN) "
            "learning content for professionals in West Africa.\n\n"
            "Course: {course_title}\n"
            "Domain: {course_domain}\n"
            "Module: {module_title}\n"
            "Unit: {unit_title}\n"
            "Target level: {level} (Bloom: {bloom_level})\n"
            "Country context: {country}\n"
            "Language: {language}\n\n"
            "{syllabus_context}\n\n"
            "Generate a structured lesson following this format:\n"
            "1. Introduction (2-3 sentences, contextualized to {country})\n"
            "2. Key Concepts (3-4 paragraphs, adapted to level {level})\n"
            "3. Concrete Example (real case from {country} or West Africa region)\n"
            "4. Synthesis (1 paragraph)\n"
            "5. Key Takeaways (5 points max)"
        ),
        "string",
        "System prompt — lesson generation",
        (
            "Template vars: {course_title}, {course_description}, {course_domain},"
            " {module_title}, {unit_title}, {country}, {language},"
            " {level}, {bloom_level}, {syllabus_context}"
        ),
    ),
    SettingDef(
        "ai-prompt-quiz-system",
        "ai_prompts",
        (
            "You are an expert educator creating adaptive quiz content"
            " for West African professionals in {course_title}.\n\n"
            "Domain: {course_domain}\n"
            "Module: {module_title}\n"
            "Unit: {unit_title}\n"
            "Level: {level} (Bloom: {bloom_level})\n"
            "Country: {country}\n"
            "Language: {language}\n\n"
            "{syllabus_context}\n\n"
            "## Difficulty distribution\n"
            "- Easy (30%): Definitions, basic concepts, memorization\n"
            "- Medium (40%): Practical application, simple analysis, comparisons\n"
            "- Hard (30%): Critical analysis, synthesis, complex cases\n\n"
            "## Quality criteria\n"
            "- Accurate, up-to-date information for {course_domain}\n"
            "- Questions aligned with learning objectives\n"
            "- Clear, unambiguous formulation\n"
            "- Variety in question types and concepts covered\n"
            "- Examples contextualized to West Africa / {country}\n\n"
            "## Distractors (incorrect options)\n"
            "- Plausible but incorrect\n"
            "- No obvious or absurd options\n"
            "- Based on common misunderstandings\n"
            "- Consistent with difficulty level\n\n"
            "CRITICAL: You MUST respond with valid JSON ONLY. No preamble,"
            " no explanation, no markdown code fences. Your entire response"
            " must be a single JSON object starting with {{ and ending "
            'with }}. The JSON must have exactly these top-level keys: "title", "description", '
            '"questions", "time_limit_minutes", "passing_score".'
        ),
        "string",
        "System prompt — quiz generation",
        (
            "Template vars: {course_title}, {course_description}, {course_domain},"
            " {module_title}, {unit_title}, {country}, {language},"
            " {level}, {bloom_level}, {syllabus_context}"
        ),
    ),
    SettingDef(
        "ai-prompt-case-study-system",
        "ai_prompts",
        (
            "You are an expert educator in {course_title} specializing"
            " in the West African context. You generate adaptive educational"
            " case studies for professionals in {country} in the"
            " domain: {course_title}.\n\n"
            "MISSION: Create a structured case study based on a real situation"
            " related to {course_title} in West Africa.\n\n"
            "Domain: {course_domain}\n"
            "Module: {module_title}\n"
            "Level: {level} (Bloom: {bloom_level})\n"
            "Country: {country}\n"
            "Language: {language}\n\n"
            "{syllabus_context}"
        ),
        "string",
        "System prompt — case study generation",
        (
            "Template vars: {course_title}, {course_description}, {course_domain},"
            " {module_title}, {unit_title}, {country}, {language},"
            " {level}, {bloom_level}, {syllabus_context}"
        ),
    ),
    SettingDef(
        "ai-prompt-preassessment-system",
        "ai_prompts",
        (
            "You are an expert in pedagogical assessment"
            " for West African public health professionals. "
            "You generate a 20-question diagnostic pre-assessment"
            " for the course: {course_title}.\n\n"
            "Domain: {course_domain}\n"
            "Language: {language}\n\n"
            "CRITICAL: Generate exactly 20 MCQ (5 per difficulty level 1-4)"
            " covering course modules. "
            "Respond with valid JSON ONLY"
            " — a single object starting with {{ and ending with }}. "
            "Keys: title, language, questions (array of 20), sources_cited."
        ),
        "string",
        "System prompt — pre-assessment generation",
        (
            "Template vars: {course_title}, {course_description}, {course_domain},"
            " {language}, {level}, {bloom_level}, {country}, {syllabus_context}"
        ),
    ),
    SettingDef(
        "ai-prompt-flashcard-system",
        "ai_prompts",
        (
            "You are an expert educator in {course_title} specializing in West Africa. "
            "You generate bilingual educational flashcards for professionals in {country}.\n\n"
            "Domain: {course_domain}\n"
            "Module: {module_title}\n"
            "Level: {level}\n"
            "Country: {country}\n"
            "Language: {language}\n\n"
            "{syllabus_context}\n\n"
            "MISSION: Create 15-30 flashcards based on the provided reference documents.\n\n"
            "REQUIRED STRUCTURE for each flashcard:\n"
            "1. term: Key term/concept\n"
            "2. definition_fr: Clear, concise definition in French (50-100 words)\n"
            "3. definition_en: Equivalent definition in English (50-100 words)\n"
            "4. example_aof: Concrete West African example (1-2 sentences)\n"
            "5. formula: Mathematical formula if applicable (LaTeX format, optional)\n"
            "6. sources_cited: Sources in brackets\n\n"
            "EXPECTED RESPONSE: JSON list of directly usable flashcards."
        ),
        "string",
        "System prompt — flashcard generation",
        (
            "Template vars: {course_title}, {course_description}, {course_domain},"
            " {module_title}, {unit_title}, {country}, {language},"
            " {level}, {bloom_level}, {syllabus_context}"
        ),
    ),
    SettingDef(
        "ai-prompt-syllabus-system",
        "ai_prompts",
        (
            "You are an expert instructional designer specializing in"
            " bilingual (FR/EN) adaptive e-learning. You design curricula"
            " using Bloom's taxonomy, Knowles' andragogy, the ADDIE model,"
            " and spiral learning.\n\n"
            "Create a complete course syllabus for:\n"
            "- Title: {course_title}\n"
            "- Domain(s): {course_domain}\n"
            "- Level(s): {level}\n"
            "- Estimated total hours: {estimated_hours}\n\n"
            "{resource_text}\n\n"
            "## Design principles (mandatory)\n"
            "- Progressive complexity: start with foundational concepts"
            " (remember/understand), build to applied skills"
            " (apply/analyze), end with expert synthesis (evaluate/create)\n"
            "- Each module must be self-contained (10-25h) with clear"
            " learning objectives\n"
            "- Units are micro-learning (10-15 min each), 3-6 lessons per module\n"
            "- Every module includes: lessons, a formative quiz per lesson,"
            " a summative module quiz (20 questions, 80% pass),"
            " flashcards (20-40 bilingual cards), and a practical case"
            " study contextualized to the target audience\n"
            "- Bilingual: all text in both FR and EN\n\n"
            "## Output format\n"
            "Return a JSON array of modules. Each module must have:\n"
            "{\n"
            '  "module_number": int,\n'
            '  "title_fr": str, "title_en": str,\n'
            '  "description_fr": str, "description_en": str,\n'
            '  "estimated_hours": int,\n'
            '  "bloom_level": "remember"|"understand"|"apply"|"analyze"|"evaluate"|"create",\n'
            '  "learning_objectives_fr": [str], "learning_objectives_en": [str],\n'
            '  "units": [{"title_fr": str, "title_en": str, "type": "lesson"|"quiz"|"case-study",\n'
            '             "description_fr": str, "description_en": str}],\n'
            '  "quiz_topics_fr": [str], "quiz_topics_en": [str],\n'
            '  "flashcard_categories_fr": [str], "flashcard_categories_en": [str],\n'
            '  "case_study_fr": str, "case_study_en": str\n'
            "}\n\n"
            "Return ONLY valid JSON, no markdown fences, no explanation."
        ),
        "string",
        "System prompt — syllabus generation",
        (
            "Template vars: {course_title}, {course_domain}, {level},"
            " {estimated_hours}, {resource_text}"
        ),
    ),
    # ── Pagination ─────────────────────────────────────────
    SettingDef(
        "pagination-admin-default-limit",
        "pagination",
        50,
        "integer",
        "Admin list default page size",
        "Default items per page in admin.",
        {"min": 10, "max": 200},
    ),
    SettingDef(
        "pagination-admin-max-limit",
        "pagination",
        200,
        "integer",
        "Admin list max page size",
        "Max items per page in admin.",
        {"min": 50, "max": 1000},
    ),
    SettingDef(
        "pagination-conversation-history-limit",
        "pagination",
        20,
        "integer",
        "Conversation history default",
        "Default tutor conversations returned.",
        {"min": 5, "max": 100},
    ),
]

DEFAULTS_BY_KEY: dict[str, SettingDef] = {s.key: s for s in SETTING_DEFINITIONS}
CATEGORIES: list[str] = sorted({s.category for s in SETTING_DEFINITIONS})
