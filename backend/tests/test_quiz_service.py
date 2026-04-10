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
    "__complete": True,
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
    def test_parses_valid_dict(self, quiz_service):
        import copy

        data = copy.deepcopy(SAMPLE_QUIZ_DICT)
        result = quiz_service._validate_and_normalize_quiz(data, "M01-U04", 10)
        assert result["title"] == "Public Health Foundations Quiz"
        assert len(result["questions"]) == 10
        assert result["unit_id"] == "M01-U04"

    def test_raises_on_missing_title_field(self, quiz_service):
        import copy

        data = copy.deepcopy(SAMPLE_QUIZ_DICT)
        del data["title"]
        with pytest.raises(ValueError, match="Missing required field"):
            quiz_service._validate_and_normalize_quiz(data, "M01-U04", 10)

    def test_raises_on_empty_questions_list(self, quiz_service):
        import copy

        data = copy.deepcopy(SAMPLE_QUIZ_DICT)
        data["questions"] = []
        with pytest.raises(ValueError, match="at least one question"):
            quiz_service._validate_and_normalize_quiz(data, "M01-U04", 10)

    def test_sets_default_passing_score_to_80(self, quiz_service):
        import copy

        data = copy.deepcopy(SAMPLE_QUIZ_DICT)
        del data["passing_score"]
        result = quiz_service._validate_and_normalize_quiz(data, "M01-U04", 10)
        assert result["passing_score"] == 80.0

    def test_enforces_minimum_passing_score_of_80(self, quiz_service):
        import copy

        data = copy.deepcopy(SAMPLE_QUIZ_DICT)
        data["passing_score"] = 60.0
        result = quiz_service._validate_and_normalize_quiz(data, "M01-U04", 10)
        assert result["passing_score"] == 80.0

    def test_accepts_slightly_fewer_questions_than_requested(self, quiz_service):
        import copy

        data = copy.deepcopy(SAMPLE_QUIZ_DICT)
        data["questions"] = data["questions"][:8]
        result = quiz_service._validate_and_normalize_quiz(data, "M01-U04", 10)
        assert len(result["questions"]) == 8

    def test_unit_id_added_to_result(self, quiz_service):
        import copy

        data = copy.deepcopy(SAMPLE_QUIZ_DICT)
        result = quiz_service._validate_and_normalize_quiz(data, "M01-U04", 10)
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


class TestRawResponseFallback:
    def test_raises_on_raw_response_fallback(self, quiz_service):
        raw_fallback = {
            "content": "Here is your quiz: ...",
            "type": "quiz",
            "raw_response": True,
        }
        with pytest.raises(ValueError, match="Claude returned non-JSON text"):
            quiz_service._validate_and_normalize_quiz(raw_fallback, "M01-U04", 10)

    async def test_raises_when_claude_returns_raw_response(self, quiz_service, mock_claude_service):
        raw_fallback = {
            "content": "Here is your quiz: ...",
            "type": "quiz",
            "raw_response": True,
        }
        mock_claude_service.generate_structured_content = AsyncMock(return_value=raw_fallback)
        module_id = uuid.uuid4()
        with pytest.raises(ValueError, match="Invalid quiz format"):
            await quiz_service._generate_quiz_content(
                module_id=module_id,
                unit_id="M01-U04",
                language="fr",
                country="senegal",
                level=1,
                num_questions=10,
            )


class TestBuildQuizPrompt:
    def test_returns_tuple_of_system_and_user(self, quiz_service):
        result = quiz_service._build_quiz_prompt(
            context="Some context",
            unit_id="M01-U04",
            language="fr",
            country="senegal",
            level=1,
            num_questions=10,
        )
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_prompt_contains_unit_id(self, quiz_service):
        _system_prompt, user_message = quiz_service._build_quiz_prompt(
            context="Some context",
            unit_id="M01-U04",
            language="fr",
            country="senegal",
            level=1,
            num_questions=10,
        )
        assert "M01-U04" in user_message

    def test_prompt_uses_french_instruction(self, quiz_service):
        _system_prompt, user_message = quiz_service._build_quiz_prompt(
            context="context",
            unit_id="M01-U04",
            language="fr",
            country="senegal",
            level=1,
            num_questions=5,
        )
        assert "in French" in user_message

    def test_prompt_uses_english_instruction(self, quiz_service):
        _system_prompt, user_message = quiz_service._build_quiz_prompt(
            context="context",
            unit_id="M01-U04",
            language="en",
            country="ghana",
            level=2,
            num_questions=5,
        )
        assert "in English" in user_message

    def test_prompt_includes_passing_score_80(self, quiz_service):
        _system_prompt, user_message = quiz_service._build_quiz_prompt(
            context="context",
            unit_id="M01-U04",
            language="fr",
            country="senegal",
            level=1,
            num_questions=10,
        )
        assert "80.0" in user_message

    def test_system_prompt_enforces_json_only(self, quiz_service):
        system_prompt, _user_message = quiz_service._build_quiz_prompt(
            context="context",
            unit_id="M01-U04",
            language="fr",
            country="senegal",
            level=1,
            num_questions=10,
        )
        assert "CRITICAL" in system_prompt
        assert "JSON" in system_prompt
        assert "title" in system_prompt

    def test_unit_title_injects_topic_constraint(self, quiz_service):
        _system_prompt, user_message = quiz_service._build_quiz_prompt(
            context="context",
            unit_id="M01-U01",
            language="fr",
            country="senegal",
            level=1,
            num_questions=5,
            unit_title="Introduction à l'épidémiologie",
        )
        assert "Introduction à l'épidémiologie" in user_message
        assert "MUST be specifically about" in user_message
        assert "Do NOT include questions about other topics" in user_message

    def test_unit_description_appended_to_topic_constraint(self, quiz_service):
        _system_prompt, user_message = quiz_service._build_quiz_prompt(
            context="context",
            unit_id="M01-U01",
            language="fr",
            country="senegal",
            level=1,
            num_questions=5,
            unit_title="Épidémiologie",
            unit_description="Étude de la distribution des maladies",
        )
        assert "Étude de la distribution des maladies" in user_message

    def test_summative_injects_all_units_summary(self, quiz_service):
        _system_prompt, user_message = quiz_service._build_quiz_prompt(
            context="context",
            unit_id="summative",
            language="fr",
            country="senegal",
            level=1,
            num_questions=10,
            all_units_summary="- Unit 1: Intro\n- Unit 2: Stats",
        )
        assert "summative quiz" in user_message
        assert "Unit 1: Intro" in user_message
        assert "Distribute questions evenly" in user_message

    def test_uses_unit_title_in_requirements_section(self, quiz_service):
        _system_prompt, user_message = quiz_service._build_quiz_prompt(
            context="context",
            unit_id="M01-U01",
            language="fr",
            country="senegal",
            level=1,
            num_questions=5,
            unit_title="Épidémiologie descriptive",
        )
        assert "Épidémiologie descriptive" in user_message
        assert "M01-U01" not in user_message


class TestBuildQuizPromptKidsAware:
    def _make_kids_course(self, age_min: int = 6, age_max: int = 12) -> MagicMock:
        tc = MagicMock()
        tc.slug = "primary_school"
        tc.type = "audience"
        course = MagicMock()
        course.taxonomy_categories = [tc]
        course.title_en = f"Village Math (Ages {age_min}-{age_max})"
        course.title_fr = f"Maths au Village ({age_min}-{age_max} ans)"
        return course

    def _make_adult_course(self) -> MagicMock:
        tc = MagicMock()
        tc.slug = "professionals"
        tc.type = "audience"
        course = MagicMock()
        course.taxonomy_categories = [tc]
        course.title_en = "Internal Audit"
        course.title_fr = "Audit Interne"
        return course

    def test_kids_course_user_message_says_young_learners(self, quiz_service):
        kids_course = self._make_kids_course()
        _system, user_message = quiz_service._build_quiz_prompt(
            context="context",
            unit_id="M01-U01",
            language="en",
            country="senegal",
            level=1,
            num_questions=5,
            course_title="Village Math (Ages 6-12)",
            course=kids_course,
        )
        assert "young learners" in user_message
        assert "professionals" not in user_message

    def test_kids_course_user_message_includes_age_range(self, quiz_service):
        kids_course = self._make_kids_course(age_min=6, age_max=12)
        _system, user_message = quiz_service._build_quiz_prompt(
            context="context",
            unit_id="M01-U01",
            language="en",
            country="senegal",
            level=1,
            num_questions=5,
            course_title="Village Math (Ages 6-12)",
            course=kids_course,
        )
        assert "6-12" in user_message

    def test_kids_course_closing_note_is_fun_and_encouraging(self, quiz_service):
        kids_course = self._make_kids_course()
        _system, user_message = quiz_service._build_quiz_prompt(
            context="context",
            unit_id="M01-U01",
            language="en",
            country="senegal",
            level=1,
            num_questions=5,
            course_title="Village Math (Ages 6-12)",
            course=kids_course,
        )
        assert "fun" in user_message.lower()
        assert "encouraging" in user_message.lower()

    def test_adult_course_user_message_says_professionals(self, quiz_service):
        adult_course = self._make_adult_course()
        _system, user_message = quiz_service._build_quiz_prompt(
            context="context",
            unit_id="M01-U01",
            language="en",
            country="ghana",
            level=2,
            num_questions=5,
            course_title="Internal Audit",
            course=adult_course,
        )
        assert "professionals" in user_message
        assert "young learners" not in user_message

    def test_no_course_produces_adult_public_health_message(self, quiz_service):
        _system, user_message = quiz_service._build_quiz_prompt(
            context="context",
            unit_id="M01-U01",
            language="en",
            country="nigeria",
            level=1,
            num_questions=5,
            course=None,
        )
        assert "public health professionals" in user_message
        assert "young learners" not in user_message

    def test_kids_context_note_mentions_daily_life(self, quiz_service):
        kids_course = self._make_kids_course()
        _system, user_message = quiz_service._build_quiz_prompt(
            context="context",
            unit_id="M01-U01",
            language="en",
            country="senegal",
            level=1,
            num_questions=5,
            course_title="Village Math (Ages 6-12)",
            course=kids_course,
        )
        assert "daily life" in user_message.lower()

    def test_kids_practical_note_mentions_exciting_and_fun(self, quiz_service):
        kids_course = self._make_kids_course()
        _system, user_message = quiz_service._build_quiz_prompt(
            context="context",
            unit_id="M01-U01",
            language="en",
            country="senegal",
            level=1,
            num_questions=5,
            course_title="Village Math (Ages 6-12)",
            course=kids_course,
        )
        assert "fun" in user_message.lower()
        assert "exciting" in user_message.lower()


class TestBuildQuizSearchQuery:
    def test_returns_unit_id_when_module_is_none(self, quiz_service):
        result = quiz_service._build_quiz_search_query(None, "M01-U04", "fr")
        assert result == "unit M01-U04"

    def test_uses_module_title_fr(self, quiz_service):
        module = MagicMock()
        module.title_fr = "Fondements de la santé publique"
        module.title_en = "Foundations of Public Health"
        module.description_fr = None
        module.description_en = None
        result = quiz_service._build_quiz_search_query(module, "M01-U01", "fr")
        assert "Fondements de la santé publique" in result
        assert "M01-U01" in result

    def test_uses_module_title_en(self, quiz_service):
        module = MagicMock()
        module.title_fr = "Audit Interne"
        module.title_en = "Internal Audit"
        module.description_fr = None
        module.description_en = None
        result = quiz_service._build_quiz_search_query(module, "M01-U01", "en")
        assert "Internal Audit" in result

    def test_includes_description_up_to_200_chars(self, quiz_service):
        module = MagicMock()
        module.title_fr = "Module"
        module.title_en = "Module"
        module.description_fr = "A" * 300
        module.description_en = "A" * 300
        result = quiz_service._build_quiz_search_query(module, "M01-U01", "fr")
        assert "A" * 200 in result
        assert "A" * 201 not in result

    def test_does_not_include_public_health_hardcode(self, quiz_service):
        module = MagicMock()
        module.title_fr = "Audit Interne GIAS 2024"
        module.title_en = "Internal Audit GIAS 2024"
        module.description_fr = None
        module.description_en = None
        result = quiz_service._build_quiz_search_query(module, "M01-U01", "fr")
        assert "public health epidemiology" not in result.lower()

    def test_uses_unit_title_when_unit_provided(self, quiz_service):
        module = MagicMock()
        module.title_fr = "Module Santé"
        module.title_en = "Health Module"
        module.description_fr = None
        module.description_en = None
        unit = MagicMock()
        unit.title_fr = "Introduction à l'épidémiologie"
        unit.title_en = "Introduction to Epidemiology"
        unit.description_fr = "Bases de l'épidémiologie"
        unit.description_en = "Epidemiology basics"
        result = quiz_service._build_quiz_search_query(module, "M01-U01", "fr", unit=unit)
        assert "Introduction à l'épidémiologie" in result
        assert "Bases de l'épidémiologie" in result
        assert "Module Santé" not in result

    def test_unit_query_uses_english_when_language_en(self, quiz_service):
        module = MagicMock()
        module.title_fr = "Module Santé"
        module.title_en = "Health Module"
        module.description_fr = None
        module.description_en = None
        unit = MagicMock()
        unit.title_fr = "Introduction à l'épidémiologie"
        unit.title_en = "Introduction to Epidemiology"
        unit.description_fr = None
        unit.description_en = "Epidemiology basics"
        result = quiz_service._build_quiz_search_query(module, "M01-U01", "en", unit=unit)
        assert "Introduction to Epidemiology" in result
        assert "Epidemiology basics" in result

    def test_summative_uses_all_unit_titles(self, quiz_service):
        module = MagicMock()
        module.title_fr = "Module Santé"
        module.title_en = "Health Module"
        module.description_fr = None
        module.description_en = None
        unit1 = MagicMock()
        unit1.title_fr = "Unité 1"
        unit1.title_en = "Unit 1"
        unit2 = MagicMock()
        unit2.title_fr = "Unité 2"
        unit2.title_en = "Unit 2"
        result = quiz_service._build_quiz_search_query(
            module, "summative", "fr", all_units=[unit1, unit2]
        )
        assert "Module Santé" in result
        assert "Unité 1" in result
        assert "Unité 2" in result


class TestUnitIdToUnitNumber:
    def test_converts_m01_u02_to_1_2(self, quiz_service):
        result = QuizService._unit_id_to_unit_number("M01-U02", 1)
        assert result == "1.2"

    def test_converts_m03_u05_to_3_5(self, quiz_service):
        result = QuizService._unit_id_to_unit_number("M03-U05", 3)
        assert result == "3.5"

    def test_returns_none_for_summative(self, quiz_service):
        result = QuizService._unit_id_to_unit_number("summative", 1)
        assert result is None

    def test_returns_none_for_invalid_format(self, quiz_service):
        result = QuizService._unit_id_to_unit_number("invalid", 1)
        assert result is None


class TestGenerateQuizContentPassesBooksSources:
    async def test_passes_books_sources_to_retriever(
        self, quiz_service, mock_retriever, mock_claude_service
    ):
        module_id = uuid.uuid4()
        mock_session = AsyncMock()
        mock_module = MagicMock()
        mock_module.id = module_id
        mock_module.title_fr = "Audit Interne GIAS 2024"
        mock_module.title_en = "Internal Audit GIAS 2024"
        mock_module.description_fr = None
        mock_module.description_en = None
        rag_collection_id = "a1b2c3d4-1234-5678-abcd-ef0123456789"
        mock_module.books_sources = {"some-pdf-filename": []}
        mock_course = MagicMock()
        mock_course.rag_collection_id = rag_collection_id
        mock_module.course = mock_course

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=mock_module)
        mock_session.execute = AsyncMock(return_value=mock_result)

        await quiz_service._generate_quiz_content(
            module_id=module_id,
            unit_id="M01-U01",
            language="fr",
            country="senegal",
            level=1,
            num_questions=5,
            session=mock_session,
        )

        call_kwargs = mock_retriever.search_for_module.call_args
        assert call_kwargs.kwargs["books_sources"] == {rag_collection_id: []}

    async def test_search_query_uses_module_title_not_hardcode(
        self, quiz_service, mock_retriever, mock_claude_service
    ):
        module_id = uuid.uuid4()
        mock_session = AsyncMock()
        mock_module = MagicMock()
        mock_module.id = module_id
        mock_module.title_fr = "Définition et Mission de l'Audit Interne"
        mock_module.title_en = "Definition and Mission of Internal Audit"
        mock_module.description_fr = None
        mock_module.description_en = None
        mock_module.books_sources = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=mock_module)
        mock_session.execute = AsyncMock(return_value=mock_result)

        await quiz_service._generate_quiz_content(
            module_id=module_id,
            unit_id="M01-U01",
            language="en",
            country="senegal",
            level=1,
            num_questions=5,
            session=mock_session,
        )

        call_kwargs = mock_retriever.search_for_module.call_args
        actual_query = call_kwargs.kwargs["query"]
        assert "Internal Audit" in actual_query
        assert "public health epidemiology" not in actual_query.lower()
