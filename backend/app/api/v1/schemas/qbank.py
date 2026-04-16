"""Pydantic V2 schemas for question bank API."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class QuestionBankCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    bank_type: str = Field(default="mixed", pattern="^(exam|training|mixed)$")


class QuestionBankUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    bank_type: str | None = Field(default=None, pattern="^(exam|training|mixed)$")
    is_active: bool | None = None


class QuestionBankResponse(BaseModel):
    id: str
    organization_id: str
    title: str
    description: str | None
    bank_type: str
    is_active: bool
    created_by: str | None
    created_at: str
    updated_at: str
    question_count: int = 0


class QuestionUpdate(BaseModel):
    question_text: str | None = None
    options: list[str] | None = Field(default=None, min_length=4, max_length=4)
    correct_answer: int | None = Field(default=None, ge=0, le=3)
    explanation: str | None = None
    category: str | None = None
    difficulty: str | None = Field(default=None, pattern="^(easy|medium|hard)$")
    image_url: str | None = None
    source_ref: str | None = None
    is_active: bool | None = None


class QuestionResponse(BaseModel):
    id: str
    bank_id: str
    question_text: str
    options: list[str]
    correct_answer: int
    explanation: str | None
    category: str | None
    difficulty: str
    image_url: str | None
    source_ref: str | None
    is_active: bool
    created_at: str
    updated_at: str


class PaginatedQuestionsResponse(BaseModel):
    items: list[QuestionResponse]
    total: int
    page: int
    per_page: int
    pages: int


class TestCreate(BaseModel):
    bank_id: str
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    mode: str = Field(default="exam", pattern="^(exam|training|review)$")
    question_count: int = Field(default=20, ge=1, le=200)
    time_limit_minutes: int | None = Field(default=None, ge=1)
    passing_score: float = Field(default=70.0, ge=0.0, le=100.0)
    category_filter: str | None = None
    difficulty_filter: str | None = Field(default=None, pattern="^(easy|medium|hard)$")
    shuffle_questions: bool = True
    show_answers: bool = False


class TestUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    mode: str | None = Field(default=None, pattern="^(exam|training|review)$")
    question_count: int | None = Field(default=None, ge=1, le=200)
    time_limit_minutes: int | None = None
    passing_score: float | None = Field(default=None, ge=0.0, le=100.0)
    category_filter: str | None = None
    difficulty_filter: str | None = None
    shuffle_questions: bool | None = None
    show_answers: bool | None = None
    is_active: bool | None = None


class TestResponse(BaseModel):
    id: str
    bank_id: str
    title: str
    description: str | None
    mode: str
    question_count: int
    time_limit_minutes: int | None
    passing_score: float
    category_filter: str | None
    difficulty_filter: str | None
    shuffle_questions: bool
    show_answers: bool
    is_active: bool
    created_by: str | None
    created_at: str
    updated_at: str


class TestStartResponse(BaseModel):
    test_id: str
    mode: str
    questions: list[QuestionResponse]
    time_limit_minutes: int | None
    passing_score: float


class AnswerInput(BaseModel):
    selected: list[int] = Field(..., min_length=1)
    time_sec: int = Field(default=0, ge=0)


class TestSubmitRequest(BaseModel):
    answers: dict[str, AnswerInput]


class CategoryScore(BaseModel):
    correct: int
    total: int
    score: float


class TestAttemptResponse(BaseModel):
    attempt_id: str
    test_id: str
    user_id: str
    score: float
    total_questions: int
    correct_count: int
    passed: bool
    category_breakdown: dict[str, CategoryScore]
    time_taken_sec: int | None
    attempted_at: str


class AttemptHistoryResponse(BaseModel):
    attempts: list[TestAttemptResponse]
    total: int
