"""Quiz API schemas for request/response validation."""

from uuid import UUID

from pydantic import BaseModel, Field


class QuizQuestion(BaseModel):
    """Single quiz question with multiple choice options."""

    id: str = Field(description="Question identifier within quiz")
    question: str = Field(description="Question text")
    options: list[str] = Field(description="4 multiple choice options", min_length=4, max_length=4)
    correct_answer: int = Field(description="Index of correct option (0-3)", ge=0, le=3)
    explanation: str = Field(description="Explanation for the correct answer")
    sources_cited: list[str] = Field(
        description="Source citations for this question", default_factory=list
    )
    difficulty: str = Field(description="Question difficulty level", default="medium")


class QuizContent(BaseModel):
    """Quiz content structure matching GeneratedContent.content schema."""

    title: str = Field(description="Quiz title")
    description: str = Field(description="Quiz description/instructions")
    questions: list[QuizQuestion] = Field(
        description="List of quiz questions", min_length=1, max_length=20
    )
    time_limit_minutes: int | None = Field(
        description="Optional time limit in minutes", default=None
    )
    passing_score: float = Field(
        description="Minimum score to pass (0-100)", ge=0, le=100, default=70.0
    )


class QuizResponse(BaseModel):
    """Complete quiz response for frontend consumption."""

    id: UUID = Field(description="Quiz content ID")
    module_id: UUID = Field(description="Module this quiz belongs to")
    unit_id: str = Field(description="Unit identifier within module")
    language: str = Field(description="Content language (fr/en)")
    level: int = Field(description="Difficulty level (1-4)")
    country_context: str = Field(description="Country context for localization")
    content: QuizContent = Field(description="Quiz content and questions")
    generated_at: str = Field(description="ISO timestamp when quiz was generated")
    cached: bool = Field(description="True if retrieved from cache")

    class Config:
        json_schema_extra = {
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "module_id": "456e7890-e89b-12d3-a456-426614174001",
                "unit_id": "unit-3",
                "language": "en",
                "level": 2,
                "country_context": "senegal",
                "content": {
                    "title": "Epidemiology Fundamentals Quiz",
                    "description": "Test your understanding of basic epidemiological concepts",
                    "questions": [
                        {
                            "id": "q1",
                            "question": "What is the primary goal of epidemiology?",
                            "options": [
                                "To treat individual patients",
                                "To study disease patterns in populations",
                                "To develop vaccines",
                                "To manage healthcare facilities",
                            ],
                            "correct_answer": 1,
                            "explanation": "Epidemiology focuses on studying the distribution and determinants of health-related states in populations.",
                            "sources_cited": ["Donaldson Ch.2, p.34"],
                            "difficulty": "medium",
                        }
                    ],
                    "time_limit_minutes": 15,
                    "passing_score": 70.0,
                },
                "generated_at": "2024-01-15T10:30:00Z",
                "cached": False,
            }
        }


class QuizGenerationRequest(BaseModel):
    """Request to generate or retrieve a quiz."""

    module_id: str = Field(
        description="Module ID or module number string (e.g. 'M01') to generate quiz for"
    )
    unit_id: str = Field(description="Unit identifier within module")
    language: str = Field(description="Content language", pattern="^(fr|en)$")
    country: str = Field(description="User's country for contextualization")
    level: int = Field(description="User's learning level (1-4)", ge=1, le=4)
    num_questions: int = Field(
        description="Number of questions to generate", ge=5, le=20, default=10
    )


class SummativeAssessmentRequest(BaseModel):
    """Request to generate or retrieve a summative assessment."""

    module_id: str = Field(
        description="Module ID or module number string (e.g. 'M01') to generate assessment for"
    )
    language: str = Field(description="Content language", pattern="^(fr|en)$")
    country: str = Field(description="User's country for contextualization")
    level: int = Field(description="User's learning level (1-4)", ge=1, le=4)
    num_questions: int = Field(
        description="Number of questions (fixed at 20 for summative)", default=20, ge=20, le=20
    )


class QuizAnswerSubmission(BaseModel):
    """User's answer to a single quiz question."""

    question_id: str = Field(description="Question identifier")
    selected_option: int = Field(description="User's selected option index (0-3)", ge=0, le=3)
    time_taken_seconds: int = Field(description="Time taken to answer this question", ge=0)


class QuizAttemptRequest(BaseModel):
    """Request to submit a complete quiz attempt."""

    quiz_id: UUID = Field(description="Quiz content ID")
    answers: list[QuizAnswerSubmission] = Field(description="User's answers to all questions")
    total_time_seconds: int = Field(description="Total time taken for entire quiz", ge=0)


class QuizAttemptResult(BaseModel):
    """Result of a single question attempt."""

    question_id: str = Field(description="Question identifier")
    user_answer: int = Field(description="User's selected option index")
    correct_answer: int = Field(description="Correct option index")
    is_correct: bool = Field(description="Whether user's answer was correct")
    explanation: str = Field(description="Explanation for the correct answer")
    time_taken_seconds: int = Field(description="Time taken for this question")


class QuizAttemptResponse(BaseModel):
    """Response after submitting a quiz attempt."""

    attempt_id: UUID = Field(description="Quiz attempt ID")
    quiz_id: UUID = Field(description="Quiz content ID")
    score: float = Field(description="Final score percentage (0-100)")
    total_questions: int = Field(description="Total number of questions")
    correct_answers: int = Field(description="Number of correct answers")
    total_time_seconds: int = Field(description="Total time taken")
    passed: bool = Field(description="Whether user passed based on passing score")
    results: list[QuizAttemptResult] = Field(description="Per-question results")
    attempted_at: str = Field(description="ISO timestamp when attempt was submitted")

    class Config:
        json_schema_extra = {
            "example": {
                "attempt_id": "789e0123-e89b-12d3-a456-426614174002",
                "quiz_id": "123e4567-e89b-12d3-a456-426614174000",
                "score": 80.0,
                "total_questions": 10,
                "correct_answers": 8,
                "total_time_seconds": 420,
                "passed": True,
                "results": [
                    {
                        "question_id": "q1",
                        "user_answer": 1,
                        "correct_answer": 1,
                        "is_correct": True,
                        "explanation": "Epidemiology focuses on studying the distribution and determinants of health-related states in populations.",
                        "time_taken_seconds": 45,
                    }
                ],
                "attempted_at": "2024-01-15T11:00:00Z",
            }
        }


class SummativeAssessmentResponse(BaseModel):
    """Response after submitting a summative assessment attempt."""

    attempt_id: UUID = Field(description="Assessment attempt ID")
    assessment_id: UUID = Field(description="Assessment content ID")
    score: float = Field(description="Final score percentage (0-100)")
    total_questions: int = Field(description="Total number of questions (always 20)")
    correct_answers: int = Field(description="Number of correct answers")
    total_time_seconds: int = Field(description="Total time taken")
    passed: bool = Field(description="Whether user passed (score >= 80%)")
    results: list[QuizAttemptResult] = Field(description="Per-question results")
    domain_breakdown: dict[str, dict[str, int]] = Field(
        description="Performance breakdown by learning domain"
    )
    module_unlocked: bool = Field(description="Whether next module was unlocked")
    can_retry: bool = Field(description="Whether user can retry (false if passed or must wait)")
    next_retry_at: str | None = Field(description="ISO timestamp when retry is allowed")
    attempt_count: int = Field(description="Total number of attempts for this module")
    attempted_at: str = Field(description="ISO timestamp when attempt was submitted")


class SummativeAssessmentAttemptCheck(BaseModel):
    """Response for checking if user can attempt summative assessment."""

    can_attempt: bool = Field(description="Whether user can attempt assessment")
    last_attempt_score: float | None = Field(description="Score from last attempt if any")
    attempt_count: int = Field(description="Number of previous attempts")
    next_retry_at: str | None = Field(description="When next retry is allowed if blocked")
    reason: str | None = Field(description="Reason if cannot attempt")


class ErrorResponse(BaseModel):
    """Standard error response format."""

    error: str = Field(description="Error code")
    message: str = Field(description="Human-readable error message")
