"""Tests for the quiz generation service."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.services.quiz_service import QuizService

SAMPLE_QUIZ_DICT = {
    "title": "Public Health Foundations Quiz",
    "description": "Test your knowledge of public health fundamentals.",
    "questions": [
        {
            "id": f"q{i}",
            "question": f"Sample question {i}?",
            "options": ["Option A", "Option B", "Option C", "Option D"],
            "correct_answer": 0,
            "explanation": f"Explanation {i}.",
            "sources_cited": ["Donaldson Ch.1, p.10"],
            "difficulty": "medium",
        }
        for i in range(1, 11)
    ],
    "time_limit_minutes": 15,
    "passing_score": 80.0,
}


@pytest.fixture
def mock_claude_service():
    service = AsyncMock()
    service.generate_structured_content = AsyncMock(return_value=SAMPLE_QUIZ_DICT)
    return service


@pytest.fixture
def mock_retriever():
    retriever = AsyncMock()
    chunk = MagicMock()
    chunk.source = "Donaldson Ch.1"
    chunk.content = "Public health content chunk."
    search_result = MagicMock()
    search_result.chunk = chunk
    search_result.similarity_score = 0.9
    retriever.search_for_module = AsyncMock(return_value=[search_result])
    return retriever


@pytest.fixture
def quiz_service(mock_claude_service, mock_retriever):
    return QuizService(mock_claude_service, mock_retriever)


class TestValidateAndNormalizeQuiz:
    def test_validates_valid_dict(self, quiz_service):
        result = quiz_service._validate_and_normalize_quiz(
            dict(SAMPLE_QUIZ_DICT), "M01-U04", 10
        )
        assert result["title"] == "Public Health Foundations Quiz"
        assert len(result["questions"]) == 10
        assert result["unit_id"] == "M01-U04"

    def test_raises_on_missing_title_field(self, quiz_service):
        data = dict(SAMPLE_QUIZ_DICT)
        del data["title"]
        with pytest.raises(ValueError, match="Missing required field"):
            quiz_service._validate_and_normalize_quiz(data, "M01-U04", 10)

    def test_raises_on_empty_questions_list(self, quiz_service):
        data = {**SAMPLE_QUIZ_DICT, "questions": []}
        with pytest.raises(ValueError, match="at least one question"):
            quiz_service._validate_and_normalize_quiz(data, "M01-U04", 10)

    def test_sets_default_passing_score_to_80(self, quiz_service):
        data = {k: v for k, v in SAMPLE_QUIZ_DICT.items() if k != "passing_score"}
        result = quiz_service._validate_and_normalize_quiz(data, "M01-U04", 10)
        assert result["passing_score"] == 80.0

    def test_enforces_minimum_passing_score_of_80(self, quiz_service):
        data = {**SAMPLE_QUIZ_DICT, "passing_score": 60.0}
        result = quiz_service._validate_and_normalize_quiz(data, "M01-U04", 10)
        assert result["passing_score"] == 80.0

    def test_accepts_slightly_fewer_questions_than_requested(self, quiz_service):
        data = {**SAMPLE_QUIZ_DICT, "questions": SAMPLE_QUIZ_DICT["questions"][:8]}
        result = quiz_service._validate_and_normalize_quiz(data, "M01-U04", 10)
        assert len(result["questions"]) == 8

    def test_unit_id_added_to_result(self, quiz_service):
        result = quiz_service._validate_and_normalize_quiz(
            dict(SAMPLE_QUIZ_DICT), "M01-U04", 10
        )
        assert result["unit_id"] == "M01-U04"


class TestValidateQuestion:
    def test_valid_question_passes(self, quiz_service):
        question = {
            "id": "q1",
            "question": "What is epidemiology?",
            "options": ["A", "B", "C", "D"],
            "correct_answer": 0,
            "explanation": "Epidemiology studies disease distribution.",
        }
        quiz_service._validate_question(question, "q1")

    def test_raises_on_missing_id(self, quiz_service):
        question = {
            "question": "What is epidemiology?",
            "options": ["A", "B", "C", "D"],
            "correct_answer": 0,
            "explanation": "Explanation.",
        }
        with pytest.raises(ValueError, match="Missing required field 'id'"):
            quiz_service._validate_question(question, "q1")

    def test_raises_on_wrong_option_count(self, quiz_service):
        question = {
            "id": "q1",
            "question": "What is epidemiology?",
            "options": ["A", "B", "C"],
            "correct_answer": 0,
            "explanation": "Explanation.",
        }
        with pytest.raises(ValueError, match="exactly 4 options"):
            quiz_service._validate_question(question, "q1")

    def test_raises_on_invalid_correct_answer(self, quiz_service):
        question = {
            "id": "q1",
            "question": "What is epidemiology?",
            "options": ["A", "B", "C", "D"],
            "correct_answer": 5,
            "explanation": "Explanation.",
        }
        with pytest.raises(ValueError, match="correct_answer must be 0, 1, 2, or 3"):
            quiz_service._validate_question(question, "q1")

    def test_sets_default_sources_and_difficulty(self, quiz_service):
        question = {
            "id": "q1",
            "question": "Test?",
            "options": ["A", "B", "C", "D"],
            "correct_answer": 1,
            "explanation": "Explanation.",
        }
        quiz_service._validate_question(question, "q1")
        assert question["sources_cited"] == []
        assert question["difficulty"] == "medium"


class TestExtractSourcesFromQuiz:
    def test_extracts_unique_sources(self, quiz_service):
        from app.api.v1.schemas.quiz import QuizContent, QuizQuestion

        questions = [
            QuizQuestion(
                id="q1",
                question="Q1?",
                options=["A", "B", "C", "D"],
                correct_answer=0,
                explanation="Exp.",
                sources_cited=["Source A", "Source B"],
            ),
            QuizQuestion(
                id="q2",
                question="Q2?",
                options=["A", "B", "C", "D"],
                correct_answer=1,
                explanation="Exp.",
                sources_cited=["Source B", "Source C"],
            ),
        ]
        content = QuizContent(
            title="Test",
            description="Desc",
            questions=questions,
            passing_score=80.0,
        )
        sources = quiz_service._extract_sources_from_quiz(content)
        assert set(sources) == {"Source A", "Source B", "Source C"}

    def test_returns_empty_list_when_no_sources(self, quiz_service):
        from app.api.v1.schemas.quiz import QuizContent, QuizQuestion

        question = QuizQuestion(
            id="q1",
            question="Q1?",
            options=["A", "B", "C", "D"],
            correct_answer=0,
            explanation="Exp.",
            sources_cited=[],
        )
        content = QuizContent(
            title="Test",
            description="Desc",
            questions=[question],
            passing_score=80.0,
        )
        sources = quiz_service._extract_sources_from_quiz(content)
        assert sources == []


class TestGenerateQuizContent:
    async def test_calls_retriever_and_claude(
        self, quiz_service, mock_retriever, mock_claude_service
    ):
        module_id = uuid.uuid4()
        result = await quiz_service._generate_quiz_content(
            module_id=module_id,
            unit_id="M01-U04",
            language="fr",
            country="senegal",
            level=1,
            num_questions=10,
        )
        mock_retriever.search_for_module.assert_called_once()
        mock_claude_service.generate_structured_content.assert_called_once()
        assert len(result.questions) == 10

    async def test_generated_content_has_passing_score_80(self, quiz_service, mock_claude_service):
        module_id = uuid.uuid4()
        result = await quiz_service._generate_quiz_content(
            module_id=module_id,
            unit_id="M01-U04",
            language="fr",
            country="senegal",
            level=1,
            num_questions=10,
        )
        assert result.passing_score == 80.0

    async def test_raises_on_claude_error(self, quiz_service, mock_claude_service):
        mock_claude_service.generate_structured_content.side_effect = Exception("API error")
        module_id = uuid.uuid4()
        with pytest.raises(Exception, match="API error"):
            await quiz_service._generate_quiz_content(
                module_id=module_id,
                unit_id="M01-U04",
                language="fr",
                country="senegal",
                level=1,
                num_questions=10,
            )


class TestBuildQuizPrompt:
    def test_prompt_contains_unit_id(self, quiz_service):
        system_prompt, user_message = quiz_service._build_quiz_prompt(
            context="Some context",
            unit_id="M01-U04",
            language="fr",
            country="senegal",
            level=1,
            num_questions=10,
        )
        assert "M01-U04" in user_message

    def test_prompt_uses_french_instruction(self, quiz_service):
        system_prompt, user_message = quiz_service._build_quiz_prompt(
            context="context",
            unit_id="M01-U04",
            language="fr",
            country="senegal",
            level=1,
            num_questions=5,
        )
        assert "in French" in user_message

    def test_prompt_uses_english_instruction(self, quiz_service):
        system_prompt, user_message = quiz_service._build_quiz_prompt(
            context="context",
            unit_id="M01-U04",
            language="en",
            country="ghana",
            level=2,
            num_questions=5,
        )
        assert "in English" in user_message

    def test_prompt_includes_passing_score_80(self, quiz_service):
        system_prompt, user_message = quiz_service._build_quiz_prompt(
            context="context",
            unit_id="M01-U04",
            language="fr",
            country="senegal",
            level=1,
            num_questions=10,
        )
        assert "80.0" in user_message

    def test_returns_tuple_of_system_and_user(self, quiz_service):
        result = quiz_service._build_quiz_prompt(
            context="context",
            unit_id="M01-U04",
            language="fr",
            country="senegal",
            level=1,
            num_questions=5,
        )
        assert isinstance(result, tuple)
        assert len(result) == 2
