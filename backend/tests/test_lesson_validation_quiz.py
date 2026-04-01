"""Tests for lesson validation quiz generation (issue #219)."""

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.claude_service import ClaudeService
from app.ai.rag.retriever import SemanticRetriever
from app.api.v1.schemas.quiz import (
    LessonValidationContent,
    LessonValidationQuizRequest,
    LessonValidationQuizResponse,
)
from app.domain.models.content import GeneratedContent
from app.domain.services.quiz_service import QuizService


@pytest.fixture
def mock_claude_service():
    return AsyncMock(spec=ClaudeService)


@pytest.fixture
def mock_semantic_retriever():
    return AsyncMock(spec=SemanticRetriever)


@pytest.fixture
def quiz_service(mock_claude_service, mock_semantic_retriever):
    return QuizService(mock_claude_service, mock_semantic_retriever)


@pytest.fixture
def sample_lesson_content():
    return GeneratedContent(
        id=uuid.uuid4(),
        module_id=uuid.uuid4(),
        content_type="lesson",
        language="fr",
        level=2,
        content={
            "introduction": "Introduction à l'épidémiologie en Afrique de l'Ouest.",
            "concepts": "Les indicateurs de santé publique incluent l'incidence et la prévalence.",
            "aof_example": "Au Sénégal, la surveillance du paludisme utilise le DHIS2.",
            "synthesis": "La surveillance épidémiologique est essentielle pour la santé publique.",
            "key_points": ["Incidence", "Prévalence", "Surveillance"],
        },
        sources_cited=["Donaldson Ch.2, p.34"],
        country_context="SN",
        validated=False,
        generated_at=datetime.now(UTC),
    )


@pytest.fixture
def sample_rag_results():
    chunk = MagicMock()
    chunk.source = "donaldson"
    chunk.chapter = "3"
    chunk.page = 45
    chunk.content = "Epidemiological surveillance is the systematic collection of data..."

    result = MagicMock()
    result.chunk = chunk
    return [result]


@pytest.fixture
def sample_validation_quiz_data():
    return {
        "scenario_title": "Épidémie de méningite à Dakar",
        "scenario_context": (
            "Une épidémie de méningite bactérienne est signalée dans le district de Dakar. "
            "Le médecin chef du district reçoit des rapports de 15 cas en une semaine. "
            "Il doit décider des mesures de réponse appropriées."
        ),
        "questions": [
            {
                "id": "q1",
                "question_type": "mcq",
                "question": "Quelle est la première action à entreprendre face à cette épidémie?",
                "options": [
                    "Fermer les écoles immédiatement",
                    "Confirmer le diagnostic en laboratoire",
                    "Lancer une campagne de vaccination de masse",
                    "Informer les médias",
                ],
                "correct_answer": 1,
                "explanation": "La confirmation diagnostique est prioritaire (Donaldson Ch.3, p.45).",
                "sources_cited": ["Donaldson Ch.3, p.45"],
                "difficulty": "medium",
            },
            {
                "id": "q2",
                "question_type": "mcq",
                "question": "Quel indicateur permet de mesurer la vitesse de propagation?",
                "options": ["Prévalence", "Taux d'attaque", "Létalité", "Incidence cumulée"],
                "correct_answer": 1,
                "explanation": "Le taux d'attaque mesure la proportion de cas (Donaldson Ch.4, p.67).",
                "sources_cited": ["Donaldson Ch.4, p.67"],
                "difficulty": "medium",
            },
            {
                "id": "q3",
                "question_type": "true_false",
                "question": "La méningite bactérienne est une maladie à déclaration obligatoire au Sénégal.",
                "options": ["True", "False"],
                "correct_answer": 0,
                "explanation": "Oui, elle est à déclaration obligatoire (Scutchfield Ch.5, p.89).",
                "sources_cited": ["Scutchfield Ch.5, p.89"],
                "difficulty": "easy",
            },
            {
                "id": "q4",
                "question_type": "mcq",
                "question": "Quel seuil d'incidence déclenche une alerte épidémique pour la méningite?",
                "options": ["1 cas/100k", "5 cas/100k", "10 cas/100k", "15 cas/100k"],
                "correct_answer": 2,
                "explanation": "Le seuil OMS est 10 cas/100k habitants (WHO AFRO 2019).",
                "sources_cited": ["WHO AFRO 2019"],
                "difficulty": "hard",
            },
            {
                "id": "q5",
                "question_type": "mcq",
                "question": "Dans le DHIS2, quelle entrée documente les nouveaux cas?",
                "options": [
                    "Cas suspects confirmés en labo",
                    "Cas probables selon critères cliniques",
                    "Cas confirmés ET probables",
                    "Uniquement les décès",
                ],
                "correct_answer": 2,
                "explanation": "Le DHIS2 enregistre les cas confirmés et probables (Donaldson Ch.7, p.112).",
                "sources_cited": ["Donaldson Ch.7, p.112"],
                "difficulty": "medium",
            },
        ],
        "time_limit_minutes": 15,
        "passing_score": 70.0,
    }


class TestQuizServiceGenerateLessonValidationQuiz:
    """Tests for QuizService.generate_lesson_validation_quiz."""

    @pytest.mark.asyncio
    async def test_generates_quiz_with_5_to_10_questions(
        self,
        quiz_service,
        mock_claude_service,
        mock_semantic_retriever,
        sample_lesson_content,
        sample_rag_results,
        sample_validation_quiz_data,
    ):
        session = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_lesson_content
        session.execute = AsyncMock(return_value=mock_result)

        mock_semantic_retriever.search.return_value = sample_rag_results
        mock_claude_service.generate_structured_content.return_value = sample_validation_quiz_data

        result = await quiz_service.generate_lesson_validation_quiz(
            lesson_id=sample_lesson_content.id,
            module_id=sample_lesson_content.module_id,
            unit_id="unit-1",
            language="fr",
            country="SN",
            level=2,
            session=session,
        )

        assert isinstance(result, LessonValidationQuizResponse)
        assert 5 <= len(result.content.questions) <= 10
        mock_claude_service.generate_structured_content.assert_called_once()

    @pytest.mark.asyncio
    async def test_response_never_cached(
        self,
        quiz_service,
        mock_claude_service,
        mock_semantic_retriever,
        sample_lesson_content,
        sample_rag_results,
        sample_validation_quiz_data,
    ):
        """Quiz is always freshly generated — no cached flag in response."""
        session = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_lesson_content
        session.execute = AsyncMock(return_value=mock_result)

        mock_semantic_retriever.search.return_value = sample_rag_results
        mock_claude_service.generate_structured_content.return_value = sample_validation_quiz_data

        result1 = await quiz_service.generate_lesson_validation_quiz(
            lesson_id=sample_lesson_content.id,
            module_id=sample_lesson_content.module_id,
            unit_id="unit-1",
            language="fr",
            country="SN",
            level=2,
            session=session,
        )
        result2 = await quiz_service.generate_lesson_validation_quiz(
            lesson_id=sample_lesson_content.id,
            module_id=sample_lesson_content.module_id,
            unit_id="unit-1",
            language="fr",
            country="SN",
            level=2,
            session=session,
        )

        assert result1.id != result2.id
        assert mock_claude_service.generate_structured_content.call_count == 2

    @pytest.mark.asyncio
    async def test_country_context_included_in_response(
        self,
        quiz_service,
        mock_claude_service,
        mock_semantic_retriever,
        sample_lesson_content,
        sample_rag_results,
        sample_validation_quiz_data,
    ):
        session = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_lesson_content
        session.execute = AsyncMock(return_value=mock_result)

        mock_semantic_retriever.search.return_value = sample_rag_results
        mock_claude_service.generate_structured_content.return_value = sample_validation_quiz_data

        result = await quiz_service.generate_lesson_validation_quiz(
            lesson_id=sample_lesson_content.id,
            module_id=sample_lesson_content.module_id,
            unit_id="unit-1",
            language="fr",
            country="SN",
            level=2,
            session=session,
        )

        assert result.country_context == "SN"

    @pytest.mark.asyncio
    async def test_each_question_has_explanation_and_source(
        self,
        quiz_service,
        mock_claude_service,
        mock_semantic_retriever,
        sample_lesson_content,
        sample_rag_results,
        sample_validation_quiz_data,
    ):
        session = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_lesson_content
        session.execute = AsyncMock(return_value=mock_result)

        mock_semantic_retriever.search.return_value = sample_rag_results
        mock_claude_service.generate_structured_content.return_value = sample_validation_quiz_data

        result = await quiz_service.generate_lesson_validation_quiz(
            lesson_id=sample_lesson_content.id,
            module_id=sample_lesson_content.module_id,
            unit_id="unit-1",
            language="fr",
            country="SN",
            level=2,
            session=session,
        )

        for question in result.content.questions:
            assert question.explanation, f"Question {question.id} has no explanation"
            assert isinstance(question.sources_cited, list)

    @pytest.mark.asyncio
    async def test_raises_value_error_when_lesson_not_found(
        self,
        quiz_service,
        mock_semantic_retriever,
    ):
        session = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(ValueError, match="not found"):
            await quiz_service.generate_lesson_validation_quiz(
                lesson_id=uuid.uuid4(),
                module_id=uuid.uuid4(),
                unit_id="unit-1",
                language="fr",
                country="SN",
                level=2,
                session=session,
            )

    @pytest.mark.asyncio
    async def test_raises_on_too_few_questions(
        self,
        quiz_service,
        mock_claude_service,
        mock_semantic_retriever,
        sample_lesson_content,
        sample_rag_results,
    ):
        session = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_lesson_content
        session.execute = AsyncMock(return_value=mock_result)

        mock_semantic_retriever.search.return_value = sample_rag_results
        mock_claude_service.generate_structured_content.return_value = {
            "scenario_title": "Test",
            "scenario_context": "Context",
            "questions": [
                {
                    "id": "q1",
                    "question_type": "mcq",
                    "question": "Q?",
                    "options": ["A", "B", "C", "D"],
                    "correct_answer": 0,
                    "explanation": "Exp",
                    "sources_cited": [],
                    "difficulty": "easy",
                }
            ],
            "time_limit_minutes": 10,
            "passing_score": 70.0,
        }

        with pytest.raises(ValueError, match="5-10 questions"):
            await quiz_service.generate_lesson_validation_quiz(
                lesson_id=sample_lesson_content.id,
                module_id=sample_lesson_content.module_id,
                unit_id="unit-1",
                language="fr",
                country="SN",
                level=2,
                session=session,
            )

    @pytest.mark.asyncio
    async def test_rag_retrieval_called(
        self,
        quiz_service,
        mock_claude_service,
        mock_semantic_retriever,
        sample_lesson_content,
        sample_rag_results,
        sample_validation_quiz_data,
    ):
        session = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_lesson_content
        session.execute = AsyncMock(return_value=mock_result)

        mock_semantic_retriever.search.return_value = sample_rag_results
        mock_claude_service.generate_structured_content.return_value = sample_validation_quiz_data

        await quiz_service.generate_lesson_validation_quiz(
            lesson_id=sample_lesson_content.id,
            module_id=sample_lesson_content.module_id,
            unit_id="unit-1",
            language="en",
            country="GH",
            level=3,
            session=session,
        )

        mock_semantic_retriever.search.assert_called_once()

    @pytest.mark.asyncio
    async def test_response_includes_scenario_context(
        self,
        quiz_service,
        mock_claude_service,
        mock_semantic_retriever,
        sample_lesson_content,
        sample_rag_results,
        sample_validation_quiz_data,
    ):
        session = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_lesson_content
        session.execute = AsyncMock(return_value=mock_result)

        mock_semantic_retriever.search.return_value = sample_rag_results
        mock_claude_service.generate_structured_content.return_value = sample_validation_quiz_data

        result = await quiz_service.generate_lesson_validation_quiz(
            lesson_id=sample_lesson_content.id,
            module_id=sample_lesson_content.module_id,
            unit_id="unit-1",
            language="fr",
            country="SN",
            level=2,
            session=session,
        )

        assert result.content.scenario_title
        assert result.content.scenario_context
        assert len(result.content.scenario_context) > 50


class TestLessonValidationQuizSchemas:
    """Unit tests for the new Pydantic schemas."""

    def test_request_validates_language(self):
        with pytest.raises(ValueError):
            LessonValidationQuizRequest(
                lesson_id=uuid.uuid4(),
                module_id=uuid.uuid4(),
                unit_id="unit-1",
                language="es",
                country="SN",
                level=2,
            )

    def test_request_validates_level_range(self):
        with pytest.raises(ValueError):
            LessonValidationQuizRequest(
                lesson_id=uuid.uuid4(),
                module_id=uuid.uuid4(),
                unit_id="unit-1",
                language="fr",
                country="SN",
                level=5,
            )

    def test_content_validates_question_count_minimum(self):
        with pytest.raises(ValueError):
            LessonValidationContent(
                scenario_title="Test",
                scenario_context="Context",
                questions=[],
                time_limit_minutes=10,
                passing_score=70.0,
            )

    def test_valid_request_passes_validation(self):
        req = LessonValidationQuizRequest(
            lesson_id=uuid.uuid4(),
            module_id=uuid.uuid4(),
            unit_id="unit-1",
            language="fr",
            country="SN",
            level=2,
        )
        assert req.language == "fr"
        assert req.level == 2


class TestParseResponseHelper:
    """Tests for the private parsing helper."""

    def test_parses_json_string_response(self):
        service = QuizService.__new__(QuizService)
        data = {
            "scenario_title": "Test Scenario",
            "scenario_context": "A realistic health scenario in West Africa with details.",
            "questions": [
                {
                    "id": f"q{i}",
                    "question_type": "mcq",
                    "question": f"Question {i}?",
                    "options": ["A", "B", "C", "D"],
                    "correct_answer": 0,
                    "explanation": f"Explanation {i} (Source Ch.{i}, p.{i * 10})",
                    "sources_cited": [f"Source Ch.{i}, p.{i * 10}"],
                    "difficulty": "medium",
                }
                for i in range(1, 6)
            ],
            "time_limit_minutes": 15,
            "passing_score": 70.0,
        }
        result = service._parse_lesson_validation_response(json.dumps(data), "fr")
        assert isinstance(result, LessonValidationContent)
        assert len(result.questions) == 5

    def test_parses_dict_response_directly(self):
        service = QuizService.__new__(QuizService)
        data = {
            "scenario_title": "Test",
            "scenario_context": "Realistic scenario context for public health in West Africa.",
            "questions": [
                {
                    "id": f"q{i}",
                    "question_type": "true_false" if i % 3 == 0 else "mcq",
                    "question": f"Q{i}?",
                    "options": ["True", "False"] if i % 3 == 0 else ["A", "B", "C", "D"],
                    "correct_answer": 0,
                    "explanation": f"Exp {i}",
                    "sources_cited": ["Donaldson Ch.1"],
                    "difficulty": "easy",
                }
                for i in range(1, 8)
            ],
            "time_limit_minutes": 15,
            "passing_score": 70.0,
        }
        result = service._parse_lesson_validation_response(data, "en")
        assert len(result.questions) == 7

    def test_raises_on_invalid_json(self):
        service = QuizService.__new__(QuizService)
        with pytest.raises(ValueError):
            service._parse_lesson_validation_response("not json at all", "fr")
