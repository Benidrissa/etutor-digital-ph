"""Default values and metadata for all platform settings.

This is the single source of truth for setting definitions.
The JSON config file only stores overrides; any missing key
falls back to the default defined here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SettingDef:
    """Definition of a single platform setting."""

    key: str
    category: str
    default: Any
    value_type: str  # integer | float | string | boolean | json
    label: str
    description: str = ""
    validation: dict | None = None
    is_sensitive: bool = False


# ── All platform settings ─────────────────────────────────────

SETTING_DEFINITIONS: list[SettingDef] = [
    # ── Quiz & Assessment ──────────────────────────────────
    SettingDef(
        "quiz.unit_questions_count", "quiz",
        10, "integer",
        "Questions per unit quiz",
        "Number of questions generated for each unit-level quiz.",
        {"min": 3, "max": 50},
    ),
    SettingDef(
        "quiz.summative_questions_count", "quiz",
        20, "integer",
        "Questions per summative assessment",
        "Number of questions in the module summative assessment.",
        {"min": 5, "max": 50},
    ),
    SettingDef(
        "quiz.passing_score", "quiz",
        80.0, "float",
        "Passing score (%)",
        "Minimum percentage required to pass a quiz or assessment.",
        {"min": 40, "max": 100},
    ),
    SettingDef(
        "quiz.time_limit_min_minutes", "quiz",
        10, "integer",
        "Minimum time limit (minutes)",
        "Floor value for the quiz time limit calculation.",
        {"min": 5, "max": 60},
    ),
    SettingDef(
        "quiz.time_limit_per_question_minutes", "quiz",
        1.5, "float",
        "Minutes per question (time limit formula)",
        "Multiplied by question count to compute quiz time limit.",
        {"min": 0.5, "max": 5.0},
    ),
    SettingDef(
        "quiz.summative_time_limit_minutes", "quiz",
        30, "integer",
        "Summative assessment time limit (minutes)",
        "Maximum time allowed for summative assessments.",
        {"min": 10, "max": 180},
    ),

    # ── Progress & Unlocking ───────────────────────────────
    SettingDef(
        "progress.unlock_threshold_pct", "progress",
        80.0, "float",
        "Module unlock — completion %",
        "Minimum completion percentage of previous module "
        "to unlock the next one.",
        {"min": 50, "max": 100},
    ),
    SettingDef(
        "progress.unlock_threshold_score", "progress",
        80.0, "float",
        "Module unlock — quiz score avg %",
        "Minimum quiz score average of previous module "
        "to unlock the next one.",
        {"min": 50, "max": 100},
    ),
    SettingDef(
        "progress.unit_pass_score", "progress",
        80.0, "float",
        "Unit pass score (%)",
        "Quiz score required to mark a unit as completed.",
        {"min": 40, "max": 100},
    ),

    # ── Flashcards (FSRS) ─────────────────────────────────
    SettingDef(
        "flashcards.new_cards_per_session", "flashcards",
        20, "integer",
        "New flashcards per session",
        "Maximum number of new flashcards per study session.",
        {"min": 5, "max": 100},
    ),
    SettingDef(
        "flashcards.review_preview_days", "flashcards",
        14, "integer",
        "Review preview window (days)",
        "How many days ahead to show upcoming reviews.",
        {"min": 7, "max": 90},
    ),
    SettingDef(
        "flashcards.min_generated_count", "flashcards",
        15, "integer",
        "Minimum flashcards per generation",
        "Warn if AI generates fewer than this many flashcards.",
        {"min": 5, "max": 50},
    ),
    SettingDef(
        "flashcards.fsrs_params", "flashcards",
        {
            "again": {"stability": 0.5, "difficulty": 1.0},
            "hard": {"stability": 0.8, "difficulty": 0.5},
            "good": {"stability": 1.2, "difficulty": -0.1},
            "easy": {
                "stability": 1.5,
                "difficulty": -0.2,
                "interval": 1.3,
            },
        },
        "json",
        "FSRS spaced-repetition parameters",
        "Stability multipliers and difficulty adjustments.",
    ),

    # ── Placement Test ─────────────────────────────────────
    SettingDef(
        "placement.level_thresholds", "placement",
        {"1": [0, 40], "2": [40, 60], "3": [60, 80], "4": [80, 101]},
        "json",
        "Score-to-level thresholds",
        "Score percentage ranges that determine assigned level.",
    ),
    SettingDef(
        "placement.retest_cooldown_days", "placement",
        90, "integer",
        "Retest cooldown (days)",
        "Minimum days before retaking the placement test.",
        {"min": 0, "max": 365},
    ),
    SettingDef(
        "placement.role_bonuses", "placement",
        {"doctor": 5, "researcher": 8, "nurse": 3, "student": -3},
        "json",
        "Professional role score adjustments (%)",
        "Score bonuses/penalties based on professional role.",
    ),
    SettingDef(
        "placement.time_adjustments", "placement",
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
        "Penalties/bonuses based on test completion time.",
    ),
    SettingDef(
        "placement.competency_threshold", "placement",
        70, "integer",
        "Competency area threshold",
        "Minimum level score to identify a competency area.",
        {"min": 40, "max": 100},
    ),

    # ── Auth & Security (sensitive) ────────────────────────
    SettingDef(
        "auth.access_token_expiry_minutes", "auth",
        15, "integer",
        "Access token expiry (minutes)",
        "JWT access token lifetime.",
        {"min": 5, "max": 120}, True,
    ),
    SettingDef(
        "auth.refresh_token_expiry_days", "auth",
        90, "integer",
        "Refresh token expiry (days)",
        "JWT refresh token lifetime.",
        {"min": 7, "max": 365}, True,
    ),
    SettingDef(
        "auth.magic_link_expiry_hours", "auth",
        1, "integer",
        "Magic link expiry (hours)",
        "How long password-reset magic links remain valid.",
        {"min": 1, "max": 48}, True,
    ),
    SettingDef(
        "auth.max_failed_totp_attempts", "auth",
        10, "integer",
        "Max failed TOTP attempts",
        "Account locks after this many failed MFA attempts.",
        {"min": 3, "max": 30}, True,
    ),
    SettingDef(
        "auth.totp_lockout_minutes", "auth",
        15, "integer",
        "TOTP lockout duration (minutes)",
        "How long account stays locked after failed MFA attempts.",
        {"min": 5, "max": 120}, True,
    ),
    SettingDef(
        "auth.otp_expiry_minutes", "auth",
        10, "integer",
        "Email OTP expiry (minutes)",
        "How long email OTP codes remain valid.",
        {"min": 5, "max": 60}, True,
    ),
    SettingDef(
        "auth.otp_max_attempts", "auth",
        5, "integer",
        "Max OTP verification attempts",
        "Maximum attempts to verify an email OTP code.",
        {"min": 3, "max": 20}, True,
    ),
    SettingDef(
        "auth.otp_rate_limit_window_seconds", "auth",
        600, "integer",
        "OTP rate limit window (seconds)",
        "Time window for OTP generation rate limiting.",
        {"min": 60, "max": 3600}, True,
    ),
    SettingDef(
        "auth.otp_max_requests_per_window", "auth",
        5, "integer",
        "Max OTP requests per window",
        "Maximum OTP requests within the rate limit window.",
        {"min": 2, "max": 20}, True,
    ),
    SettingDef(
        "auth.backup_codes_count", "auth",
        8, "integer",
        "Backup codes count",
        "Number of backup codes generated during TOTP setup.",
        {"min": 4, "max": 20}, True,
    ),

    # ── Rate Limiting ──────────────────────────────────────
    SettingDef(
        "rate_limiting.global_requests_per_minute", "rate_limiting",
        100, "integer",
        "Global rate limit (req/min)",
        "Maximum requests per minute per IP address.",
        {"min": 10, "max": 1000}, True,
    ),
    SettingDef(
        "rate_limiting.tutor_daily_limit", "rate_limiting",
        200, "integer",
        "Tutor messages daily limit",
        "Maximum tutor messages per user per day.",
        {"min": 10, "max": 1000},
    ),

    # ── AI & Content Generation ────────────────────────────
    SettingDef(
        "ai.max_tokens_content", "ai",
        64000, "integer",
        "Max tokens — content generation",
        "Maximum output tokens for Claude API calls.",
        {"min": 4000, "max": 128000},
    ),
    SettingDef(
        "ai.temperature_content", "ai",
        0.7, "float",
        "Temperature — content generation",
        "Claude temperature for general content generation.",
        {"min": 0.0, "max": 1.5},
    ),
    SettingDef(
        "ai.rag_default_top_k", "ai",
        8, "integer",
        "RAG retrieval top-k (default)",
        "Number of document chunks retrieved for content generation.",
        {"min": 3, "max": 30},
    ),
    SettingDef(
        "ai.rag_flashcard_top_k", "ai",
        12, "integer",
        "RAG retrieval top-k (flashcards)",
        "Chunks retrieved specifically for flashcard generation.",
        {"min": 3, "max": 30},
    ),

    # ── Tutor ──────────────────────────────────────────────
    SettingDef(
        "tutor.response_max_tokens", "tutor",
        1500, "integer",
        "Tutor response max tokens",
        "Maximum tokens for each tutor response.",
        {"min": 500, "max": 8000},
    ),
    SettingDef(
        "tutor.response_temperature", "tutor",
        0.7, "float",
        "Tutor response temperature",
        "Claude temperature for tutor responses.",
        {"min": 0.0, "max": 1.5},
    ),
    SettingDef(
        "tutor.compaction_trigger_messages", "tutor",
        20, "integer",
        "Compaction trigger (messages)",
        "Trigger conversation compaction after this many messages.",
        {"min": 10, "max": 100},
    ),
    SettingDef(
        "tutor.compaction_keep_recent", "tutor",
        5, "integer",
        "Compaction — keep recent messages",
        "Most recent messages to keep when compacting.",
        {"min": 2, "max": 20},
    ),
    SettingDef(
        "tutor.compaction_summarize_up_to", "tutor",
        15, "integer",
        "Compaction — summarize up to",
        "Older messages to summarize during compaction.",
        {"min": 5, "max": 50},
    ),
    SettingDef(
        "tutor.context_token_budget", "tutor",
        1500, "integer",
        "Session context token budget",
        "Maximum tokens for injected session context.",
        {"min": 500, "max": 5000},
    ),
    SettingDef(
        "tutor.max_tool_calls", "tutor",
        3, "integer",
        "Max tool calls per response",
        "Maximum Claude tool calls per tutor response.",
        {"min": 1, "max": 10},
    ),
    SettingDef(
        "tutor.compaction_max_tokens", "tutor",
        600, "integer",
        "Compaction summary max tokens",
        "Max tokens for generating the compaction summary.",
        {"min": 200, "max": 2000},
    ),
    SettingDef(
        "tutor.compaction_temperature", "tutor",
        0.3, "float",
        "Compaction temperature",
        "Lower temperature for factual compaction summaries.",
        {"min": 0.0, "max": 1.0},
    ),
    SettingDef(
        "tutor.suggestions_max_tokens", "tutor",
        800, "integer",
        "Learning suggestions max tokens",
        "Max tokens for learning activity suggestions.",
        {"min": 200, "max": 2000},
    ),
    SettingDef(
        "tutor.suggestions_temperature", "tutor",
        0.5, "float",
        "Suggestions temperature",
        "Temperature for generating learning suggestions.",
        {"min": 0.0, "max": 1.0},
    ),

    # ── Pagination ─────────────────────────────────────────
    SettingDef(
        "pagination.admin_default_limit", "pagination",
        50, "integer",
        "Admin list default page size",
        "Default items per page in admin lists.",
        {"min": 10, "max": 200},
    ),
    SettingDef(
        "pagination.admin_max_limit", "pagination",
        200, "integer",
        "Admin list max page size",
        "Maximum items per page in admin lists.",
        {"min": 50, "max": 1000},
    ),
    SettingDef(
        "pagination.conversation_history_limit", "pagination",
        20, "integer",
        "Conversation history default",
        "Default tutor conversations returned.",
        {"min": 5, "max": 100},
    ),
]


# Build lookup index
DEFAULTS_BY_KEY: dict[str, SettingDef] = {
    s.key: s for s in SETTING_DEFINITIONS
}

CATEGORIES: list[str] = sorted(
    {s.category for s in SETTING_DEFINITIONS}
)
