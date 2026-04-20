"""Question Bank API schemas."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field, model_validator

# ---------------------------------------------------------------------------
# Question Bank
# ---------------------------------------------------------------------------


class QuestionBankCreate(BaseModel):
    organization_id: UUID | None = None
    visibility: str = Field(default="org_restricted", pattern=r"^(public|org_restricted)$")
    title: str = Field(..., min_length=2, max_length=500)
    description: str | None = None
    bank_type: str = Field(..., pattern=r"^(driving|exam_prep|psychotechnic|general_culture)$")
    language: str = Field(default="fr", max_length=5)
    time_per_question_sec: int = Field(default=60, ge=5, le=120)
    passing_score: float = Field(default=80.0, ge=0, le=100)

    @model_validator(mode="after")
    def _org_required_for_org_restricted(self) -> "QuestionBankCreate":
        if self.visibility == "org_restricted" and self.organization_id is None:
            raise ValueError("organization_id is required when visibility is org_restricted")
        return self


class QuestionBankUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=500)
    description: str | None = None
    language: str | None = Field(default=None, max_length=5)
    time_per_question_sec: int | None = Field(default=None, ge=5, le=120)
    passing_score: float | None = Field(default=None, ge=0, le=100)
    status: str | None = Field(default=None, pattern=r"^(draft|published|archived)$")
    visibility: str | None = Field(default=None, pattern=r"^(public|org_restricted)$")


class QuestionBankResponse(BaseModel):
    id: str
    organization_id: str | None = None
    # ``organization_name`` + ``organization_slug`` are populated by
    # ``_bank_response`` when the org relationship is preloaded. The
    # cross-org discovery page (#1692) relies on these so the
    # frontend doesn't need to fetch every org separately.
    organization_name: str | None = None
    organization_slug: str | None = None
    visibility: str = "org_restricted"
    title: str
    description: str | None = None
    bank_type: str
    language: str
    time_per_question_sec: int
    passing_score: float
    status: str
    question_count: int = 0
    test_count: int = 0
    created_by: str
    created_at: str
    updated_at: str


# ---------------------------------------------------------------------------
# Question
# ---------------------------------------------------------------------------


class QuestionUpdate(BaseModel):
    question_text: str | None = None
    options: list[str] | None = None
    correct_answer_indices: list[int] | None = None
    explanation: str | None = None
    category: str | None = Field(default=None, max_length=100)
    difficulty: str | None = Field(default=None, pattern=r"^(easy|medium|hard)$")


class QuestionResponse(BaseModel):
    id: str
    question_bank_id: str
    order_index: int
    image_url: str | None = None
    question_text: str
    options: list[str]
    correct_answer_indices: list[int]
    explanation: str | None = None
    source_page: int | None = None
    source_pdf_name: str | None = None
    category: str | None = None
    difficulty: str
    created_at: str


class QuestionListResponse(BaseModel):
    questions: list[QuestionResponse]
    total: int
    page: int
    per_page: int


# ---------------------------------------------------------------------------
# Test Configuration
# ---------------------------------------------------------------------------


class TestCreate(BaseModel):
    question_bank_id: UUID
    title: str = Field(..., min_length=2, max_length=500)
    mode: str = Field(..., pattern=r"^(exam|training|review)$")
    question_count: int | None = Field(default=None, ge=1, le=500)
    shuffle_questions: bool = True
    time_per_question_sec: int | None = Field(default=None, ge=5, le=120)
    show_feedback: bool = False
    filter_categories: list[str] | None = None
    filter_failed_only: bool = False


class TestUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=500)
    mode: str | None = Field(default=None, pattern=r"^(exam|training|review)$")
    question_count: int | None = Field(default=None, ge=1, le=500)
    shuffle_questions: bool | None = None
    time_per_question_sec: int | None = Field(default=None, ge=5, le=120)
    show_feedback: bool | None = None
    filter_categories: list[str] | None = None
    filter_failed_only: bool | None = None


class TestResponse(BaseModel):
    id: str
    question_bank_id: str
    title: str
    mode: str
    question_count: int | None = None
    shuffle_questions: bool
    time_per_question_sec: int | None = None
    show_feedback: bool
    filter_categories: list[str] | None = None
    filter_failed_only: bool
    created_by: str
    created_at: str


class AccessibleTestResponse(BaseModel):
    """A test returned by ``/tests/accessible`` for the learner-facing
    "Tests I can take" page (#1732). Wraps ``TestResponse`` plus enough
    bank/org context so the learner page can group tests by bank
    without a second round-trip per test.
    """

    id: str
    question_bank_id: str
    title: str
    mode: str
    question_count: int | None = None
    time_per_question_sec: int | None = None
    show_feedback: bool
    created_at: str
    bank_title: str | None = None
    bank_language: str | None = None
    bank_org_name: str | None = None
    bank_org_slug: str | None = None


# ---------------------------------------------------------------------------
# Test Session (taking a test)
# ---------------------------------------------------------------------------


class TestStartQuestion(BaseModel):
    id: str
    image_url: str | None = None
    question_text: str
    options: list[str]
    category: str | None = None
    difficulty: str
    # Populated only when the test is in training mode with show_feedback=True,
    # so the client can draw a "Correct"/"Incorrect" banner without a round-trip
    # per answer. Kept None for exam mode so network-tab inspection doesn't leak
    # the answer key (#1632).
    correct_answer_indices: list[int] | None = None


class TestStartResponse(BaseModel):
    test_id: str
    title: str
    mode: str
    time_per_question_sec: int
    show_feedback: bool
    questions: list[TestStartQuestion]
    total_questions: int
    # Pre-fetched audio URLs: ``{question_id: {language: url}}``. Only
    # entries with ``status == "ready"`` are included; missing keys mean
    # the client should fall back to polling ``/questions/{id}/audio``.
    # Preloading these on the client lets the learner start hearing the
    # question within the timer window without a per-question round-trip.
    audio: dict[str, dict[str, str]] = Field(default_factory=dict)


class TestSubmitRequest(BaseModel):
    answers: dict[str, dict] = Field(
        ...,
        description='Map of question_id to {"selected": [int], "time_sec": int}',
    )


class TestAttemptResponse(BaseModel):
    id: str
    test_id: str
    score: float
    total_questions: int
    correct_answers: int
    time_taken_sec: int
    passed: bool
    category_breakdown: dict | None = None
    attempted_at: str
    attempt_number: int


class TestAttemptDetail(TestAttemptResponse):
    answers: dict


class TestReviewQuestion(BaseModel):
    id: str
    image_url: str | None = None
    question_text: str
    options: list[str]
    correct_answer_indices: list[int]
    explanation: str | None = None
    category: str | None = None
    user_selected: list[int] | None = None
    is_correct: bool | None = None


class TestReviewResponse(BaseModel):
    test_id: str
    attempt_id: str
    score: float
    passed: bool
    questions: list[TestReviewQuestion]


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------


class ScoreBucket(BaseModel):
    bucket: str
    range: list[int]
    count: int


class CategoryPassRate(BaseModel):
    category: str
    correct: int
    total: int
    pass_rate: float
    weak: bool


class AttemptsOverTimePoint(BaseModel):
    date: str
    count: int


class BankAnalyticsResponse(BaseModel):
    bank_id: str
    total_attempts: int
    unique_students: int
    average_score: float
    pass_rate: float
    average_time_per_question_sec: float
    score_distribution: list[ScoreBucket]
    category_pass_rates: list[CategoryPassRate]
    attempts_over_time: list[AttemptsOverTimePoint]


class BankStudentRow(BaseModel):
    user_id: str
    email: str | None = None
    name: str | None = None
    attempt_count: int
    average_score: float
    pass_count: int
    last_attempt_at: str | None = None


class BankStudentsResponse(BaseModel):
    bank_id: str
    students: list[BankStudentRow]


class StudentAttemptRow(BaseModel):
    id: str
    test_id: str
    score: float
    passed: bool
    attempted_at: str
    attempt_number: int
    time_taken_sec: int


class StudentProgressResponse(BaseModel):
    bank_id: str
    user_id: str
    attempt_count: int
    attempts: list[StudentAttemptRow]
    best_score: float
    latest_score: float
    trend: str
    weakest_categories: list[CategoryPassRate]


# ---------------------------------------------------------------------------
# Audio
# ---------------------------------------------------------------------------


class AudioStatusResponse(BaseModel):
    question_id: str
    language: str
    status: str
    # Browser-reachable proxy URL served by the backend — populated only when
    # status == "ready" and the audio row has bytes in MinIO. The raw
    # storage_url is never returned because MinIO is on a private network
    # (guardrail: backend/tests/test_no_minio_leaks_in_schemas.py).
    audio_url: str | None = None
    duration_seconds: int | None = None
    # ``tts`` for OpenAI/MMS-generated clips, ``manual`` for clips the
    # editor recorded or uploaded via the question-bank form (#1747).
    # Defaults to ``tts`` so existing clients continue to render the
    # TTS-only UI until they're updated.
    source: str = "tts"


class AudioGenerateResponse(BaseModel):
    task_id: str
    bank_id: str
    language: str
    status: str = "processing"


# ---------------------------------------------------------------------------
# Translations (#1696 debug view)
# ---------------------------------------------------------------------------


class TranslationResponse(BaseModel):
    question_id: str
    language: str
    question_text: str
    options: list[str]
    source_model: str
    edited_by_admin: bool
    created_at: str
    updated_at: str
