"""Quiz ``option_misconceptions``: stored with the answer key, never served.

``option_misconceptions`` is a positional array parallel to ``options`` with
``null`` at ``correct_answer``'s index — so it reveals the answer. These tests
pin down the three properties that matter:

1. it survives storage and answer-key reads (``QuizQuestion`` declares it, so
   Pydantic's default ``extra="ignore"`` does not silently drop it);
2. no learner-facing quiz payload served before submission contains it — at the
   schema level, through every quiz read endpoint, and through FastAPI's
   ``response_model`` serialisation;
3. generation normalises it and runs the shared MCQ checks without failing the
   learner's request, and ``force_regenerate`` really replaces the cached row
   (the regeneration path the per-course backfill relies on).
"""

from __future__ import annotations

import copy
import json
import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.v1.schemas.quiz import (
    PracticeQuizContent,
    PublicQuizResponse,
    QuizContent,
    QuizQuestion,
    QuizResponse,
    to_public_quiz_response,
)
from app.domain.services.quiz_service import QuizService

FIELD = "option_misconceptions"

MISCONCEPTIONS = [
    "Thinks cholera is carried by mosquitoes",
    None,
    "Confuses a rash illness with a vector-borne one",
    "Thinks any tropical disease is mosquito-borne",
]


def _question(qid: str = "q1", **overrides) -> dict:
    question = {
        "id": qid,
        "question": "Which disease is transmitted by the Anopheles mosquito?",
        "options": ["Cholera", "Malaria", "Measles", "Tuberculosis"],
        "correct_answer": 1,
        FIELD: list(MISCONCEPTIONS),
        "explanation": "Anopheles mosquitoes carry Plasmodium.",
        "sources_cited": ["WHO fact sheet"],
        "difficulty": "easy",
    }
    question.update(overrides)
    return question


def _stored_content(unit_id: str = "1.2", questions: list[dict] | None = None) -> dict:
    return {
        "title": "Vector-borne diseases",
        "description": "",
        "questions": questions or [_question("q1"), _question("q2")],
        "time_limit_minutes": 15,
        "passing_score": 80.0,
        "unit_id": unit_id,
        "__complete": True,
    }


def _row(unit_id: str = "1.2", content: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        module_id=uuid.uuid4(),
        module_unit_id=uuid.uuid4(),
        content=content or _stored_content(unit_id),
        language="en",
        level=1,
        country_context="SN",
        generated_at=datetime(2026, 1, 1, 12, 0, 0),
        content_revision=1,
        is_manually_edited=False,
    )


def _assert_absent(payload) -> None:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    assert FIELD not in text, f"{FIELD} leaked into a learner payload: {text[:300]}"


# ── 1. Storage and answer-key reads ─────────────────────────────────────────


class TestStorageRoundTrip:
    def test_answer_key_model_keeps_the_field_on_dump(self):
        """What quiz_service stores is QuizContent.model_dump()."""
        stored = QuizContent(**{k: v for k, v in _stored_content().items() if k != "unit_id"})
        dumped = stored.model_dump()
        assert dumped["questions"][0][FIELD] == MISCONCEPTIONS

    def test_answer_key_read_keeps_the_field(self):
        content = {k: v for k, v in _stored_content().items() if k != "unit_id"}
        read = QuizContent.model_validate(content)
        assert read.questions[0].option_misconceptions == MISCONCEPTIONS

    def test_legacy_row_without_the_field_still_validates(self):
        legacy = _question()
        legacy.pop(FIELD)
        assert QuizQuestion(**legacy).option_misconceptions is None


# ── 2. Never in a learner-facing payload ────────────────────────────────────


def _practice_response(**kwargs) -> QuizResponse:
    content = QuizContent(**{k: v for k, v in _stored_content().items() if k != "unit_id"})
    return QuizResponse(
        id=uuid.uuid4(),
        module_id=uuid.uuid4(),
        unit_id=kwargs.get("unit_id", "1.2"),
        language="en",
        level=1,
        country_context="SN",
        content=content,
        generated_at="2026-01-01T12:00:00",
        cached=True,
    )


class TestSchemaLevel:
    def test_practice_response_strips_it_from_the_attribute(self):
        """Passing the stored answer key in must not keep it on the model."""
        resp = _practice_response()
        assert isinstance(resp.content, PracticeQuizContent)
        assert not isinstance(resp.content, QuizContent)
        assert not hasattr(resp.content.questions[0], FIELD)

    def test_practice_response_serialisations_omit_it(self):
        resp = _practice_response()
        _assert_absent(resp.model_dump_json())
        _assert_absent(resp.model_dump(mode="json"))
        # The practice viewer still gets what it uses for feedback.
        question = resp.model_dump()["content"]["questions"][0]
        assert question["correct_answer"] == 1
        assert question["explanation"]

    def test_public_response_omits_it(self):
        _assert_absent(to_public_quiz_response(_practice_response()).model_dump_json())

    @pytest.mark.parametrize("model", [QuizResponse, PublicQuizResponse])
    def test_learner_response_schemas_do_not_declare_it(self, model):
        """Guardrail: a learner response type that can carry it is a leak."""

        def property_names(node) -> set[str]:
            names: set[str] = set()
            if isinstance(node, dict):
                names.update((node.get("properties") or {}).keys())
                for value in node.values():
                    names |= property_names(value)
            elif isinstance(node, list):
                for value in node:
                    names |= property_names(value)
            return names

        declared = property_names(model.model_json_schema())
        assert "correct_answer" in declared or model is PublicQuizResponse
        assert FIELD not in declared

    def test_service_row_to_response_omits_it(self):
        resp = QuizService._quiz_response_from_row(_row(), "1.2", "SN", False)
        _assert_absent(resp.model_dump_json())


def _session_returning(row) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    result.scalars.return_value.first.return_value = row
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    return session


class TestReadEndpoints:
    async def test_quiz_router_get_quiz(self):
        from app.api.v1.quiz import get_quiz

        resp = await get_quiz(quiz_id=uuid.uuid4(), session=_session_returning(_row()))
        _assert_absent(resp.model_dump_json())

    async def test_content_router_get_quiz(self):
        from app.api.v1.content import get_quiz

        resp = await get_quiz(
            quiz_id=uuid.uuid4(),
            session=_session_returning(_row()),
            current_user=SimpleNamespace(id=uuid.uuid4()),
        )
        _assert_absent(resp.model_dump_json())

    async def test_generate_cache_hit_json_response(self):
        """POST /quiz/generate serialises by hand via JSONResponse."""
        from app.api.v1 import quiz as quiz_module
        from app.api.v1.schemas.quiz import QuizGenerationRequest

        session = _session_returning(_row())
        with (
            patch.object(quiz_module, "_check_subscription_or_first_unit", AsyncMock()),
            patch.object(quiz_module, "_resolve_module_uuid", AsyncMock(return_value=uuid.uuid4())),
            patch(
                "app.domain.services._unit_resolution.resolve_module_unit_id",
                AsyncMock(return_value=uuid.uuid4()),
            ),
        ):
            response = await quiz_module.generate_quiz(
                request=QuizGenerationRequest(
                    module_id=str(uuid.uuid4()),
                    unit_id="1.2",
                    language="en",
                    country="SN",
                    level=1,
                ),
                quiz_service=MagicMock(),
                session=session,
                current_user=SimpleNamespace(id=uuid.uuid4()),
            )
        assert response.status_code == 200
        body = response.body.decode()
        _assert_absent(body)
        assert json.loads(body)["content"]["questions"][0]["correct_answer"] == 1

    async def test_summative_payload_omits_it(self):
        from app.api.v1.quiz import get_quiz

        row = _row(unit_id="summative")
        resp = await get_quiz(quiz_id=uuid.uuid4(), session=_session_returning(row))
        assert isinstance(resp, PublicQuizResponse)
        _assert_absent(resp.model_dump_json())


class TestOverHttp:
    """Through FastAPI's response_model serialisation, end to end."""

    @pytest.fixture
    async def client(self):
        from app.api.deps import get_db
        from app.api.deps_local_auth import require_active_subscription
        from app.main import app

        session = _session_returning(_row())

        async def fake_db():
            yield session

        app.dependency_overrides[get_db] = fake_db
        app.dependency_overrides[require_active_subscription] = lambda: SimpleNamespace(
            id=uuid.uuid4()
        )
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
        app.dependency_overrides.clear()

    @pytest.mark.parametrize("path", ["/api/v1/quiz/{id}", "/api/v1/content/quizzes/{id}"])
    async def test_get_quiz_body_has_no_misconceptions(self, client, path):
        response = await client.get(path.format(id=uuid.uuid4()))
        assert response.status_code == 200, response.text
        _assert_absent(response.text)
        assert response.json()["content"]["questions"][0]["correct_answer"] == 1


# ── 3. Generation: normalise, check, keep; regenerate in place ──────────────


@pytest.fixture
def service():
    return QuizService(AsyncMock(), AsyncMock())


class TestValidateQuestion:
    def test_misconceptions_are_aligned_and_nulled_at_the_answer(self, service):
        question = _question(**{FIELD: ["a", "leaks the answer"]})
        service._validate_question(question, "question 1")
        assert question[FIELD] == ["a", None, None, None]

    def test_missing_field_is_stored_as_null(self, service):
        question = _question()
        question.pop(FIELD)
        findings = service._validate_question(question, "question 1")
        assert question[FIELD] is None
        assert "misconceptions_unchecked" in {f.code for f in findings}

    def test_defects_are_returned_not_raised(self, service):
        """The learner's generation path has no retry: a leak must not turn an
        imperfect quiz into no quiz."""
        question = _question(question="Malaria: which disease do Anopheles carry?")
        question["options"] = ["Malaria", "Malaria", "Measles", "Tuberculosis"]
        question["correct_answer"] = 0
        findings = service._validate_question(question, "question 1")
        codes = {f.code for f in findings if f.severity == "error"}
        assert {"answer_leak", "duplicate_options"} <= codes

    def test_normalised_quiz_keeps_misconceptions_through_quiz_content(self, service):
        data = _stored_content()
        data.pop("unit_id")
        data["questions"][0][FIELD] = ["a", "b", "c"]
        normalised = service._validate_and_normalize_quiz(data, "1.2", 2)
        content = QuizContent(**normalised)
        assert content.questions[0].option_misconceptions == ["a", None, "c", None]

    def test_defects_are_logged_once_per_quiz(self, service):
        data = _stored_content()
        data.pop("unit_id")
        data["questions"][0]["question"] = "Malaria — which disease is it?"
        with patch("app.domain.services.quiz_service.logger") as log:
            service._validate_and_normalize_quiz(data, "1.2", 2)
        warned = [c for c in log.warning.call_args_list if "MCQ defects" in c.args[0]]
        assert len(warned) == 1
        assert warned[0].kwargs["defects"] == ["answer_leak@questions[q1].question"]


class TestPrompts:
    def test_user_message_asks_for_misconceptions(self, service):
        _, user = service._build_quiz_prompt(
            context="ctx", unit_id="1.2", language="en", country="SN", level=1, num_questions=5
        )
        assert '"option_misconceptions"' in user
        assert "null for the correct option" in user

    @pytest.mark.parametrize("key", ["ai-prompt-quiz-system", "ai-prompt-quiz-kids-system"])
    def test_system_prompt_defaults_ask_for_misconceptions_and_still_render(self, key):
        from collections import defaultdict

        from app.infrastructure.config.platform_defaults import DEFAULTS_BY_KEY

        template = DEFAULTS_BY_KEY[key].default
        rendered = template.format_map(defaultdict(str))
        assert '"option_misconceptions"' in rendered
        assert "null for the correct option" in rendered
        # Literal JSON braces must stay doubled in the template so they render
        # as single braces.
        assert "{{" not in rendered
        assert rendered.count("{") == rendered.count("}")


def _generated_content() -> QuizContent:
    data = _stored_content()
    data.pop("unit_id")
    return QuizContent(**data)


class TestForceRegenerateOverwritesInPlace:
    async def _run(self, service, *, unit_uuid, existing, unit_id="1.2"):
        session = MagicMock()
        result = MagicMock()
        result.scalars.return_value.first.return_value = existing
        session.execute = AsyncMock(return_value=result)
        session.get = AsyncMock(return_value=existing)
        session.commit = AsyncMock()

        async def refresh(obj):
            # The DB's server_default would fill generated_at on a real INSERT.
            if getattr(obj, "generated_at", None) is None:
                obj.generated_at = datetime(2026, 1, 2, 12, 0, 0)

        session.refresh = AsyncMock(side_effect=refresh)
        session.rollback = AsyncMock()
        session.add = MagicMock()
        with (
            patch(
                "app.domain.services._unit_resolution.resolve_module_unit_id",
                AsyncMock(return_value=unit_uuid),
            ),
            patch.object(
                service, "_generate_quiz_content", AsyncMock(return_value=_generated_content())
            ) as generate,
        ):
            resp = await service.get_or_generate_quiz(
                module_id=uuid.uuid4(),
                unit_id=unit_id,
                language="en",
                country="SN",
                level=1,
                session=session,
                force_regenerate=True,
            )
        return resp, session, generate

    async def test_unit_quiz_row_is_replaced_not_inserted(self, service):
        existing = _row(content=_stored_content(questions=[_question(**{FIELD: None})]))
        old_content = copy.deepcopy(existing.content)
        resp, session, _ = await self._run(service, unit_uuid=uuid.uuid4(), existing=existing)

        session.add.assert_not_called()
        assert resp.id == existing.id
        assert existing.content != old_content
        assert existing.content["questions"][0][FIELD] == MISCONCEPTIONS
        assert existing.content["unit_id"] == "1.2"
        assert existing.content_revision == 2
        assert existing.validated is False
        _assert_absent(resp.model_dump_json())

    async def test_summative_row_is_replaced_not_inserted(self, service):
        existing = _row(unit_id="summative")
        existing.module_unit_id = None
        resp, session, generate = await self._run(
            service, unit_uuid=None, existing=existing, unit_id="summative"
        )
        session.add.assert_not_called()
        assert resp.id == existing.id
        assert existing.content_revision == 2
        assert existing.content["unit_id"] == "summative"
        # num_questions defaults to the summative length when not given.
        assert generate.await_args.kwargs["num_questions"] == 20

    async def test_manually_edited_row_is_never_overwritten(self, service):
        existing = _row()
        existing.is_manually_edited = True
        before = copy.deepcopy(existing.content)
        _, session, _ = await self._run(service, unit_uuid=None, existing=existing)
        assert existing.content == before
        session.add.assert_called_once()  # falls back to the plain insert path

    async def test_unit_quiz_defaults_to_ten_questions(self, service):
        _, _, generate = await self._run(service, unit_uuid=uuid.uuid4(), existing=_row())
        assert generate.await_args.kwargs["num_questions"] == 10
