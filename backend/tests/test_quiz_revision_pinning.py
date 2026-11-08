"""Answers are graded against the quiz revision the learner was served.

``force_regenerate`` (a learner's Refresh, the quality agent, the per-course
backfill) overwrites a quiz row in place: same row id, same question ids
``q1``..``qN``, new questions and answer key, ``content_revision`` + 1. A
learner part-way through the old quiz, or with answers queued offline, used
to be graded against the new answer key.

Now every in-place overwrite first saves the old content as a
``generated_content_revisions`` pre-image, learner payloads carry
``content_revision``, and a submission naming an older revision is graded
against that pre-image (409 ``quiz_changed`` when there is none). Route
handlers and services are driven with mocked sessions — no database.
"""

from __future__ import annotations

import copy
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.v1 import quiz as quiz_api
from app.api.v1.schemas.quiz import (
    PublicQuizResponse,
    QuizAnswerSubmission,
    QuizAttemptRequest,
    QuizContent,
    QuizResponse,
    to_public_quiz_response,
)
from app.domain.models.content import GeneratedContent
from app.domain.models.course_quality import GeneratedContentRevision
from app.domain.models.module import Module
from app.domain.models.module_unit import ModuleUnit
from app.domain.models.quiz import QuizAttempt, SummativeAssessmentAttempt
from app.domain.services import content_revisions
from app.domain.services.quiz_service import QuizService, default_question_count

USER = SimpleNamespace(id=str(uuid.uuid4()), role="user", preferred_language="fr")


def _question(qid: str, correct: int) -> dict:
    return {
        "id": qid,
        "question": f"Question {qid}, correct option {correct}?",
        "options": ["Alpha", "Bravo", "Charlie", "Delta"],
        "correct_answer": correct,
        "explanation": f"Option {correct} for {qid}.",
        "sources_cited": [],
        "difficulty": "medium",
    }


#: Revision 1 and revision 2 share question ids but not one correct answer.
REV1_KEY = {"q1": 0, "q2": 1, "q3": 2, "q4": 3}
REV2_KEY = {"q1": 1, "q2": 2, "q3": 3, "q4": 0}


def _content(key: dict[str, int], unit_id: str) -> dict:
    return {
        "title": "Quiz",
        "description": "",
        "questions": [_question(qid, correct) for qid, correct in key.items()],
        "time_limit_minutes": 10,
        "passing_score": 80.0,
        "unit_id": unit_id,
    }


def _row(unit_id: str = "1.2", *, revision: int = 2, key=REV2_KEY) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        module_id=uuid.uuid4(),
        module_unit_id=None if unit_id == "summative" else uuid.uuid4(),
        content_type="quiz",
        content=_content(key, unit_id),
        sources_cited=[],
        language="fr",
        level=1,
        country_context="SN",
        generated_at=datetime(2026, 1, 1, 12, 0, 0),
        content_revision=revision,
        is_manually_edited=False,
        validated=True,
        quality_score=None,
        quality_flags=[],
    )


def _pre_image(
    row, revision: int, key: dict[str, int], *, created_at: datetime | None = None
) -> SimpleNamespace:
    """A saved pre-image; written (its revision superseded) just now by default."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        generated_content_id=row.id,
        revision=revision,
        content=_content(key, row.content["unit_id"]),
        created_at=created_at or datetime.now(UTC),
    )


def _sheet(key: dict[str, int]) -> list[QuizAnswerSubmission]:
    return [
        QuizAnswerSubmission(question_id=qid, selected_option=correct, time_taken_seconds=3)
        for qid, correct in key.items()
    ]


class FakeSession:
    """Routes each ``execute`` by the entity it selects.

    ``pre_images`` maps ``(generated_content_id, revision)`` to a pre-image;
    every lookup is recorded in ``revision_lookups``, and every "has this row
    any pre-image?" lookup in ``any_lookups``.

    ``db_state`` is the row as the database has it when the session's copy
    (``row``) is stale: a select with ``populate_existing`` copies it onto the
    row, as SQLAlchemy refreshes an identity-mapped object. Row locks taken by
    selects are recorded in ``locks``.
    """

    def __init__(
        self, *, row=None, pre_images=None, attempt=None, module_unit_id=None, db_state=None
    ):
        self.row = row
        self.pre_images = dict(pre_images or {})
        self.attempt = attempt
        self.module_unit_id = module_unit_id
        self.db_state = dict(db_state or {})
        self.revision_lookups: list[tuple] = []
        self.any_lookups: list = []
        self.locks: list = []
        self.added: list = []
        self.commit = AsyncMock()
        self.flush = AsyncMock()
        self.rollback = AsyncMock()

        async def refresh(obj, **kwargs):
            if getattr(obj, "attempted_at", None) is None:
                obj.attempted_at = datetime(2026, 1, 2, 12, 0, 0)
            if getattr(obj, "generated_at", None) is None:
                obj.generated_at = datetime(2026, 1, 2, 12, 0, 0)

        self.refresh = AsyncMock(side_effect=refresh)

    def add(self, obj):
        self.added.append(obj)
        if isinstance(obj, GeneratedContentRevision):
            # Visible to later lookups, as after an autoflush.
            self.pre_images[(obj.generated_content_id, obj.revision)] = obj

    async def get(self, model, key):
        if model is GeneratedContent and self.row is not None and key == self.row.id:
            return self.row
        return None

    async def execute(self, stmt):
        description = stmt.column_descriptions[0]
        entity, name = description["entity"], description["name"]
        result = MagicMock()
        if entity is GeneratedContentRevision and name == "id":
            # Whether the row has any pre-image, i.e. has ever been overwritten.
            content_id = stmt.compile().params["generated_content_id_1"]
            self.any_lookups.append(content_id)
            ids = [p.id for (cid, _), p in self.pre_images.items() if cid == content_id]
            result.scalars.return_value.first.return_value = ids[0] if ids else None
        elif entity is GeneratedContentRevision:
            params = stmt.compile().params
            key = (params["generated_content_id_1"], params["revision_1"])
            self.revision_lookups.append(key)
            result.scalars.return_value.first.return_value = self.pre_images.get(key)
        elif entity is GeneratedContent:
            if stmt._for_update_arg is not None:
                self.locks.append(stmt._for_update_arg)
            if stmt.get_execution_options().get("populate_existing") and self.row is not None:
                for name, value in self.db_state.items():
                    setattr(self.row, name, copy.deepcopy(value))
            result.scalar_one_or_none.return_value = self.row
            result.scalars.return_value.first.return_value = self.row
        elif entity is ModuleUnit:
            result.scalar_one_or_none.return_value = self.module_unit_id
        elif entity is Module and name == "course_id":
            result.scalar_one_or_none.return_value = None  # no certificate path
        elif entity is Module:
            result.scalar_one_or_none.return_value = MagicMock()
        elif entity is SummativeAssessmentAttempt:
            result.scalars.return_value.all.return_value = []
            result.scalars.return_value.first.return_value = self.attempt
        else:
            result.scalar_one_or_none.return_value = None
            result.scalars.return_value.all.return_value = []
            result.scalars.return_value.first.return_value = None
        return result

    def attempts(self, model):
        return [obj for obj in self.added if isinstance(obj, model)]


# ── Unit quiz submission ─────────────────────────────────────────────────────


async def _submit_unit(session, row, answers, revision):
    request = QuizAttemptRequest(
        quiz_id=row.id, answers=answers, total_time_seconds=30, content_revision=revision
    )
    return await _post_unit(session, request)


async def _post_unit(session, request: QuizAttemptRequest):
    with (
        patch.object(quiz_api, "_check_subscription_or_first_unit", AsyncMock()),
        patch.object(quiz_api, "ProgressService") as progress,
        patch.object(quiz_api, "AnalyticsService") as analytics,
    ):
        progress.return_value.update_progress_after_quiz = AsyncMock()
        analytics.return_value.ingest_event = AsyncMock()
        return await quiz_api.submit_quiz_attempt(request, session, USER)


class TestUnitQuizSubmission:
    async def test_answers_to_the_served_revision_are_graded_against_it(self):
        """Served revision 1, regenerated to 2 since: the revision-1 sheet scores 100%."""
        row = _row(revision=2, key=REV2_KEY)
        session = FakeSession(row=row, pre_images={(row.id, 1): _pre_image(row, 1, REV1_KEY)})

        response = await _submit_unit(session, row, _sheet(REV1_KEY), revision=1)

        assert response.score == 100.0
        assert response.correct_answers == 4
        assert [r.correct_answer for r in response.results] == list(REV1_KEY.values())
        assert response.results[0].explanation == "Option 0 for q1."
        (attempt,) = session.attempts(QuizAttempt)
        assert attempt.answers["content_revision"] == 1
        # The existing structure is untouched for readers of the JSON.
        assert {"answers", "results"} <= set(attempt.answers)

    async def test_the_same_sheet_would_have_failed_against_the_current_revision(self):
        """Guards the test above: the two answer keys really differ."""
        row = _row(revision=2, key=REV2_KEY)
        response = await _submit_unit(FakeSession(row=row), row, _sheet(REV1_KEY), revision=2)
        assert response.score == 0.0

    async def test_unrecoverable_revision_is_409_quiz_changed(self):
        row = _row(revision=3, key=REV2_KEY)
        session = FakeSession(row=row)  # no pre-image at revision 1

        with pytest.raises(HTTPException) as exc_info:
            await _submit_unit(session, row, _sheet(REV1_KEY), revision=1)

        assert exc_info.value.status_code == 409
        assert exc_info.value.detail["error"] == "quiz_changed"
        assert session.revision_lookups == [(row.id, 1)]
        assert session.attempts(QuizAttempt) == []
        session.commit.assert_not_awaited()

    async def test_the_current_revision_needs_no_pre_image(self):
        row = _row(revision=2, key=REV2_KEY)
        session = FakeSession(row=row)
        response = await _submit_unit(session, row, _sheet(REV2_KEY), revision=2)
        assert response.score == 100.0
        assert session.revision_lookups == []

    def test_request_revision_is_optional_and_positive(self):
        assert QuizAttemptRequest(quiz_id=uuid.uuid4(), answers=[], total_time_seconds=0)
        with pytest.raises(ValueError):
            QuizAttemptRequest(
                quiz_id=uuid.uuid4(), answers=[], total_time_seconds=0, content_revision=0
            )


class TestUnrevisionedSubmissions:
    """A submission without ``content_revision`` names no questions: it came
    from an older client, or from answers queued offline from a copy taken
    before payloads carried a revision. Nothing it sends says which questions
    it answered — not even when it was answered: a copy taken before a
    regeneration can be answered long after it. So it is graded only against
    a quiz that has never changed (revision 1, no pre-image); otherwise 409
    ``quiz_changed``, and the client reloads the quiz."""

    async def test_a_quiz_that_never_changed_is_graded(self):
        row = _row(revision=1, key=REV1_KEY)
        session = FakeSession(row=row)

        response = await _submit_unit(session, row, _sheet(REV1_KEY), None)

        assert response.score == 100.0
        assert session.any_lookups == [row.id]
        (attempt,) = session.attempts(QuizAttempt)
        assert attempt.answers["content_revision"] == 1

    @pytest.mark.parametrize(
        ("revision", "pre_image_revisions"),
        [(2, [1]), (1, [1]), (2, []), (5, [1, 2, 3, 4])],
        ids=["changed", "revision-1-with-a-pre-image", "pre-image-gone", "changed-often"],
    )
    async def test_a_quiz_that_has_changed_is_409(self, revision, pre_image_revisions):
        row = _row(revision=revision, key=REV2_KEY)
        session = FakeSession(
            row=row,
            pre_images={(row.id, r): _pre_image(row, r, REV1_KEY) for r in pre_image_revisions},
        )

        with pytest.raises(HTTPException) as exc_info:
            await _submit_unit(session, row, _sheet(REV2_KEY), None)

        assert exc_info.value.status_code == 409
        assert exc_info.value.detail["error"] == "quiz_changed"
        assert exc_info.value.detail["current_revision"] == revision
        assert session.attempts(QuizAttempt) == []
        session.commit.assert_not_awaited()

    async def test_a_pre_deploy_offline_copy_answered_after_a_regeneration_is_409(self):
        """The copy was taken at revision 1, before payloads carried a revision.
        The MCQ backfill then regenerated the quiz to revision 2, and the
        learner, still offline, answered the old copy. Any answer time it
        sends is after the change, so dating the answers cannot tell them
        apart from answers to the new questions: they are refused."""
        from app.tasks import quiz_backfill

        row = _row(revision=1, key=REV1_KEY)
        offline_copy = copy.deepcopy(row.content)  # no content_revision in it
        session = FakeSession(row=row)

        async def regenerate(**kwargs):
            # The in-place overwrite: same id and question ids, new key.
            row.content = _content(REV2_KEY, "1.2")
            row.content_revision += 1
            row.generated_at = datetime.now(UTC).replace(tzinfo=None)

        service = MagicMock()
        service.get_or_generate_quiz = AsyncMock(side_effect=regenerate)
        assert await quiz_backfill.regenerate_quiz_row(session, service, row.id) == "regenerated"
        assert row.content_revision == 2
        assert (row.id, 1) in session.pre_images  # the backfill's own pre-image

        # Answered offline from the old copy, synced two hours later. An older
        # client also sent answered_at; it is ignored.
        request = QuizAttemptRequest.model_validate(
            {
                "quiz_id": str(row.id),
                "answers": [
                    {
                        "question_id": q["id"],
                        "selected_option": q["correct_answer"],
                        "time_taken_seconds": 0,
                    }
                    for q in offline_copy["questions"]
                ],
                "total_time_seconds": 30,
                "answered_at": (datetime.now(UTC) + timedelta(hours=2)).isoformat(),
            }
        )
        assert request.content_revision is None

        with pytest.raises(HTTPException) as exc_info:
            await _post_unit(session, request)

        assert exc_info.value.status_code == 409
        assert exc_info.value.detail["error"] == "quiz_changed"
        assert session.attempts(QuizAttempt) == []

    def test_the_request_has_no_answer_time(self):
        assert "answered_at" not in QuizAttemptRequest.model_fields
        request = QuizAttemptRequest.model_validate(
            {
                "quiz_id": str(uuid.uuid4()),
                "answers": [],
                "total_time_seconds": 0,
                "answered_at": "2026-01-02T03:04:05.678Z",
            }
        )
        assert "answered_at" not in request.model_dump()


# ── Summative submission and review ──────────────────────────────────────────


async def _submit_summative(session, row, answers, revision):
    request = QuizAttemptRequest(
        quiz_id=row.id, answers=answers, total_time_seconds=60, content_revision=revision
    )
    with (
        patch(
            "app.domain.services.progress_service.touch_course_interaction_by_module",
            AsyncMock(),
        ),
        patch(
            "app.domain.services.progress_service.rollup_course_completion_by_module",
            AsyncMock(),
        ),
    ):
        return await quiz_api.submit_summative_assessment_attempt(
            request, MagicMock(), session, USER
        )


class TestSummativeSubmission:
    async def test_answers_to_the_served_revision_are_graded_against_it(self):
        row = _row("summative", revision=2, key=REV2_KEY)
        session = FakeSession(row=row, pre_images={(row.id, 1): _pre_image(row, 1, REV1_KEY)})

        response = await _submit_summative(session, row, _sheet(REV1_KEY), revision=1)

        assert response.score == 100.0
        assert response.passed is True
        (attempt,) = session.attempts(SummativeAssessmentAttempt)
        assert attempt.answers["content_revision"] == 1
        assert [r["correct_answer"] for r in attempt.answers["results"]] == list(REV1_KEY.values())

    async def test_unrecoverable_revision_is_409_quiz_changed(self):
        row = _row("summative", revision=2, key=REV2_KEY)
        session = FakeSession(row=row)

        with pytest.raises(HTTPException) as exc_info:
            await _submit_summative(session, row, _sheet(REV1_KEY), revision=1)

        assert exc_info.value.status_code == 409
        assert exc_info.value.detail["error"] == "quiz_changed"
        assert session.attempts(SummativeAssessmentAttempt) == []

    async def test_without_a_revision_a_quiz_that_never_changed_is_graded(self):
        row = _row("summative", revision=1, key=REV1_KEY)
        session = FakeSession(row=row)
        response = await _submit_summative(session, row, _sheet(REV1_KEY), revision=None)
        assert response.score == 100.0
        (attempt,) = session.attempts(SummativeAssessmentAttempt)
        assert attempt.answers["content_revision"] == 1

    async def test_without_a_revision_a_changed_quiz_is_409(self):
        row = _row("summative", revision=2, key=REV2_KEY)
        session = FakeSession(row=row, pre_images={(row.id, 1): _pre_image(row, 1, REV1_KEY)})

        with pytest.raises(HTTPException) as exc_info:
            await _submit_summative(session, row, _sheet(REV2_KEY), revision=None)

        assert exc_info.value.status_code == 409
        assert exc_info.value.detail["error"] == "quiz_changed"
        assert session.attempts(SummativeAssessmentAttempt) == []


class TestSummativeOnlyGradesRecentlySupersededRevisions:
    """A summative is timed and taken online: an older revision can only have
    been served to this learner within the time limit of being superseded. Any
    recoverable revision used to be graded, so a key exposed by a passing
    learner's review of revision 1 passed the module gate at revision 5."""

    async def test_a_revision_superseded_long_ago_is_409(self):
        row = _row("summative", revision=5, key=REV2_KEY)
        old = _pre_image(row, 1, REV1_KEY, created_at=datetime.now(UTC) - timedelta(days=30))
        session = FakeSession(row=row, pre_images={(row.id, 1): old})

        with pytest.raises(HTTPException) as exc_info:
            await _submit_summative(session, row, _sheet(REV1_KEY), revision=1)

        assert exc_info.value.status_code == 409
        assert exc_info.value.detail["error"] == "quiz_changed"
        assert session.attempts(SummativeAssessmentAttempt) == []

    @pytest.mark.parametrize(("minutes_ago", "graded"), [(89, True), (91, False)])
    async def test_the_window_is_the_time_limit_plus_a_grace(self, minutes_ago, graded):
        """Time limit 60 min (platform setting) + 30 min grace."""
        row = _row("summative", revision=3, key=REV2_KEY)  # generated_at months ago
        superseded = datetime.now(UTC) - timedelta(minutes=minutes_ago)
        pre_image = _pre_image(row, 2, REV1_KEY, created_at=superseded)
        session = FakeSession(row=row, pre_images={(row.id, 2): pre_image})
        cache = MagicMock()
        cache.get.side_effect = lambda key, default=None: (
            60 if key == "quiz-summative-time-limit-minutes" else default
        )

        with patch("app.api.v1.quiz.SettingsCache.instance", return_value=cache):
            if graded:
                response = await _submit_summative(session, row, _sheet(REV1_KEY), revision=2)
                assert response.score == 100.0
            else:
                with pytest.raises(HTTPException) as exc_info:
                    await _submit_summative(session, row, _sheet(REV1_KEY), revision=2)
                assert exc_info.value.detail["error"] == "quiz_changed"

    async def test_the_overwrite_time_counts_when_the_pre_image_was_stamped_early(self):
        """created_at is the start of the regenerating transaction (an AI call
        earlier); the row's generated_at is stamped at the overwrite itself."""
        row = _row("summative", revision=2, key=REV2_KEY)
        row.generated_at = (datetime.now(UTC) - timedelta(minutes=5)).replace(tzinfo=None)
        early = _pre_image(row, 1, REV1_KEY, created_at=datetime.now(UTC) - timedelta(hours=3))
        session = FakeSession(row=row, pre_images={(row.id, 1): early})

        response = await _submit_summative(session, row, _sheet(REV1_KEY), revision=1)

        assert response.score == 100.0

    async def test_unit_quizzes_keep_old_revisions_gradeable(self):
        """Unit quiz answers can sit in the offline queue for days."""
        row = _row(revision=2, key=REV2_KEY)
        old = _pre_image(row, 1, REV1_KEY, created_at=datetime.now(UTC) - timedelta(days=30))
        session = FakeSession(row=row, pre_images={(row.id, 1): old})

        response = await _submit_unit(session, row, _sheet(REV1_KEY), revision=1)

        assert response.score == 100.0


def _passed_attempt(row, *, answered_key, revision) -> SimpleNamespace:
    answers = {
        "answers": [],
        "results": [
            {"question_id": qid, "is_correct": True, "user_answer": c, "correct_answer": c}
            for qid, c in answered_key.items()
        ],
    }
    if revision is not None:
        answers["content_revision"] = revision
    return SimpleNamespace(
        id=uuid.uuid4(),
        assessment_id=row.id,
        answers=answers,
        score=100.0,
        correct_answers=len(answered_key),
        total_questions=len(answered_key),
        attempted_at=datetime(2026, 1, 3, 12, 0, 0),
    )


class TestSummativeReview:
    async def test_review_shows_the_revision_that_was_answered(self):
        row = _row("summative", revision=2, key=REV2_KEY)
        attempt = _passed_attempt(row, answered_key=REV1_KEY, revision=1)
        session = FakeSession(
            row=row, attempt=attempt, pre_images={(row.id, 1): _pre_image(row, 1, REV1_KEY)}
        )

        review = await quiz_api.get_summative_assessment_review(row.module_id, session, USER)

        assert [q.question for q in review.questions] == [
            f"Question {qid}, correct option {c}?" for qid, c in REV1_KEY.items()
        ]
        assert [q.explanation for q in review.questions] == [
            f"Option {c} for {qid}." for qid, c in REV1_KEY.items()
        ]

    async def test_attempt_of_the_current_revision_reads_current_content(self):
        row = _row("summative", revision=2, key=REV2_KEY)
        attempt = _passed_attempt(row, answered_key=REV2_KEY, revision=2)
        session = FakeSession(row=row, attempt=attempt)

        review = await quiz_api.get_summative_assessment_review(row.module_id, session, USER)

        assert review.questions[0].question == "Question q1, correct option 1?"
        assert session.revision_lookups == []

    async def test_old_attempt_without_a_recorded_revision_falls_back_to_current(self):
        row = _row("summative", revision=2, key=REV2_KEY)
        attempt = _passed_attempt(row, answered_key=REV2_KEY, revision=None)
        session = FakeSession(row=row, attempt=attempt)

        review = await quiz_api.get_summative_assessment_review(row.module_id, session, USER)

        assert len(review.questions) == 4
        assert review.questions[0].question == "Question q1, correct option 1?"
        assert session.revision_lookups == []


# ── Payloads carry content_revision ──────────────────────────────────────────


class TestPayloadsCarryTheRevision:
    def test_service_row_to_response(self):
        resp = QuizService._quiz_response_from_row(_row(revision=3), "1.2", "SN", False)
        assert resp.content_revision == 3

    def test_unrefreshed_insert_reads_as_revision_1(self):
        """content_revision is a server default: None until refreshed."""
        row = _row(revision=1)
        row.content_revision = None
        assert content_revisions.current_revision(row) == 1

    def test_public_summative_payload_keeps_it(self):
        resp = QuizService._quiz_response_from_row(_row("summative", revision=4), "s", "SN", False)
        public = to_public_quiz_response(resp)
        assert isinstance(public, PublicQuizResponse)
        assert public.content_revision == 4
        assert "correct_answer" not in public.model_dump_json()

    async def test_get_quiz_endpoints(self):
        from app.api.v1 import content as content_api

        row = _row(revision=5)
        resp = await quiz_api.get_quiz(row.id, FakeSession(row=row))
        assert resp.content_revision == 5
        resp = await content_api.get_quiz(
            quiz_id=row.id, session=FakeSession(row=row), current_user=USER
        )
        assert resp.content_revision == 5

    async def test_generate_cache_hit(self):
        import json

        from app.api.v1.schemas.quiz import QuizGenerationRequest

        row = _row(revision=6)
        with (
            patch.object(quiz_api, "_check_subscription_or_first_unit", AsyncMock()),
            patch.object(quiz_api, "_resolve_module_uuid", AsyncMock(return_value=row.module_id)),
            patch(
                "app.domain.services._unit_resolution.resolve_module_unit_id",
                AsyncMock(return_value=row.module_unit_id),
            ),
        ):
            response = await quiz_api.generate_quiz(
                request=QuizGenerationRequest(
                    module_id=str(row.module_id),
                    unit_id="1.2",
                    language="fr",
                    country="SN",
                    level=1,
                ),
                quiz_service=MagicMock(),
                session=FakeSession(row=row),
                current_user=USER,
            )
        assert json.loads(response.body)["content_revision"] == 6

    async def test_summative_generate_cache_hit(self):
        import json

        from app.api.v1.schemas.quiz import SummativeAssessmentRequest

        row = _row("summative", revision=7)
        service = MagicMock()
        service.get_cached_quiz = AsyncMock(
            return_value=QuizService._quiz_response_from_row(row, "summative", "SN", False)
        )
        with patch.object(quiz_api, "_resolve_module_uuid", AsyncMock(return_value=row.module_id)):
            response = await quiz_api.generate_summative_assessment(
                request=SummativeAssessmentRequest(
                    module_id=str(row.module_id), language="fr", country="SN", level=1
                ),
                quiz_service=service,
                session=FakeSession(row=row),
                current_user=USER,
            )
        body = json.loads(response.body)
        assert body["content_revision"] == 7
        assert "correct_answer" not in response.body.decode()


# ── In-place overwrite writes the pre-image ──────────────────────────────────


def _new_content(unit_id: str) -> dict:
    return _content(REV2_KEY, unit_id)


async def _overwrite(session, row, *, module_unit_uuid):
    return await QuizService(AsyncMock(), AsyncMock())._overwrite_cached_quiz(
        session,
        module_id=row.module_id,
        unit_id=row.content["unit_id"],
        module_unit_uuid=module_unit_uuid,
        language=row.language,
        country=row.country_context,
        level=row.level,
        content=_new_content(row.content["unit_id"]),
        sources=["new source"],
    )


class TestOverwriteWritesPreImage:
    @pytest.mark.parametrize("unit_id", ["1.2", "summative"])
    async def test_pre_image_of_the_current_revision_is_written_first(self, unit_id):
        row = _row(unit_id, revision=1, key=REV1_KEY)
        old_content = copy.deepcopy(row.content)
        session = FakeSession(row=row)

        overwritten = await _overwrite(session, row, module_unit_uuid=row.module_unit_id)

        assert overwritten is row
        (pre_image,) = session.attempts(GeneratedContentRevision)
        assert pre_image.generated_content_id == row.id
        assert pre_image.revision == 1
        assert pre_image.content == old_content
        assert pre_image.trigger == content_revisions.REGENERATE_TRIGGER
        assert row.content_revision == 2
        assert row.content["questions"][0]["correct_answer"] == REV2_KEY["q1"]
        assert row.sources_cited == ["new source"]
        assert row.validated is False

    async def test_an_existing_pre_image_is_not_duplicated(self):
        """The quality agent / backfill write their own first in the same session."""
        row = _row(revision=1, key=REV1_KEY)
        theirs = _pre_image(row, 1, REV1_KEY)
        session = FakeSession(row=row, pre_images={(row.id, 1): theirs})

        await _overwrite(session, row, module_unit_uuid=row.module_unit_id)

        assert session.attempts(GeneratedContentRevision) == []
        assert row.content_revision == 2

    async def test_every_overwrite_stays_gradeable(self):
        """Two regenerations in a row: one pre-image per revision, no collision."""
        row = _row(revision=1, key=REV1_KEY)
        session = FakeSession(row=row)
        await _overwrite(session, row, module_unit_uuid=row.module_unit_id)
        await _overwrite(session, row, module_unit_uuid=row.module_unit_id)
        assert [p.revision for p in session.attempts(GeneratedContentRevision)] == [1, 2]
        assert row.content_revision == 3

    async def test_manually_edited_row_is_left_alone(self):
        row = _row(revision=1, key=REV1_KEY)
        row.is_manually_edited = True
        session = FakeSession(row=row)
        assert await _overwrite(session, row, module_unit_uuid=row.module_unit_id) is None
        assert session.added == []
        assert row.content_revision == 1

    async def test_force_regenerate_response_carries_the_new_revision(self):
        row = _row(revision=1, key=REV1_KEY)
        session = FakeSession(row=row)
        service = QuizService(AsyncMock(), AsyncMock())
        generated = QuizContent(**{k: v for k, v in _new_content("1.2").items() if k != "unit_id"})
        with (
            patch(
                "app.domain.services._unit_resolution.resolve_module_unit_id",
                AsyncMock(return_value=row.module_unit_id),
            ),
            patch.object(service, "_generate_quiz_content", AsyncMock(return_value=generated)),
        ):
            resp = await service.get_or_generate_quiz(
                module_id=row.module_id,
                unit_id="1.2",
                language="fr",
                country="SN",
                level=1,
                session=session,
                force_regenerate=True,
            )
        assert isinstance(resp, QuizResponse)
        assert resp.id == row.id
        assert resp.content_revision == 2
        assert len(session.attempts(GeneratedContentRevision)) == 1


# ── An overwrite starts from the database's revision ─────────────────────────

#: A third answer key: what another writer regenerated the row to meanwhile.
REV3_KEY = {"q1": 2, "q2": 3, "q3": 0, "q4": 1}


def _stale_row(unit_id: str = "1.2"):
    """The session's copy at revision 1, while the database is at revision 2.

    Another writer (the MCQ backfill) regenerated the row and committed after
    this session loaded it: revision 2 holds REV3_KEY and learners are being
    served it; the backfill saved revision 1's pre-image.
    """
    row = _row(unit_id, revision=1, key=REV1_KEY)
    db_state = {"content_revision": 2, "content": _content(REV3_KEY, unit_id)}
    pre_images = {(row.id, 1): _pre_image(row, 1, REV1_KEY)}
    return row, db_state, pre_images


class TestOverwriteStartsFromTheDatabaseRevision:
    """A stale in-memory revision used to overwrite revision 2 under its own
    number: no pre-image of it, and learners served it graded against new
    questions. The row is now re-read under a lock before the pre-image."""

    @pytest.mark.parametrize("unit_id", ["1.2", "summative"])
    async def test_a_stale_copy_is_re_read_before_the_pre_image(self, unit_id):
        row, db_state, pre_images = _stale_row(unit_id)
        session = FakeSession(row=row, db_state=db_state, pre_images=pre_images)

        await _overwrite(session, row, module_unit_uuid=row.module_unit_id)

        (pre_image,) = session.attempts(GeneratedContentRevision)
        assert pre_image.revision == 2
        assert pre_image.content == _content(REV3_KEY, unit_id)
        assert row.content_revision == 3
        # A learner served revision 2 is graded against what they saw.
        graded, revision = await quiz_api._content_to_grade(session, row, 2)
        assert revision == 2
        assert [q["correct_answer"] for q in graded["questions"]] == list(REV3_KEY.values())

    @pytest.mark.parametrize("unit_id", ["1.2", "summative"])
    async def test_the_row_is_locked_for_the_overwrite(self, unit_id):
        row = _row(unit_id, revision=1, key=REV1_KEY)
        session = FakeSession(row=row)
        await _overwrite(session, row, module_unit_uuid=row.module_unit_id)
        # FOR NO KEY UPDATE: concurrent writers wait; pre-image inserts do not.
        assert [(lock.key_share, lock.read) for lock in session.locks] == [(True, False)]

    async def test_a_pre_image_holding_other_content_is_a_conflict(self):
        """Never skip a pre-image that does not match: that hid the overwrite."""
        row = _row(revision=1, key=REV1_KEY)
        session = FakeSession(row=row, pre_images={(row.id, 1): _pre_image(row, 1, REV3_KEY)})

        with pytest.raises(content_revisions.RevisionConflict):
            await _overwrite(session, row, module_unit_uuid=row.module_unit_id)

        assert row.content_revision == 1
        assert row.content == _content(REV1_KEY, "1.2")
        assert session.attempts(GeneratedContentRevision) == []

    async def test_quality_agent_saves_the_revision_learners_are_served(self):
        """Its pre-image (trigger quality_loop) is of the database's revision 2."""
        from app.domain.services.quality_agent_service import CourseQualityService

        row, db_state, pre_images = _stale_row()
        row.regeneration_attempts = 0
        session = FakeSession(row=row, db_state=db_state, pre_images=pre_images)

        async def get(model, key):
            return row if model is GeneratedContent else SimpleNamespace(unit_number="1.2")

        session.get = get
        with patch(
            "app.domain.services.quiz_service.QuizService.get_or_generate_quiz", AsyncMock()
        ):
            await CourseQualityService(MagicMock(), MagicMock()).regenerate_with_constraints(
                content_id=row.id, constraints=[], session=session
            )

        (pre_image,) = session.attempts(GeneratedContentRevision)
        assert (pre_image.revision, pre_image.trigger) == (2, "quality_loop")
        assert pre_image.content == _content(REV3_KEY, "1.2")
        assert row.content_revision == 3
        assert session.locks and session.locks[0].key_share is True


# ── Regeneration keeps the question count ────────────────────────────────────


class TestQuestionCount:
    def test_defaults_read_the_platform_settings(self):
        cache = MagicMock()
        cache.get.side_effect = lambda key, default=None: {
            "quiz-unit-questions-count": 7,
            "quiz-summative-questions-count": 15,
        }.get(key, default)
        with patch("app.domain.services.quiz_service.SettingsCache.instance", return_value=cache):
            assert default_question_count("1.2") == 7
            assert default_question_count("summative") == 15

    def test_defaults_without_overrides(self):
        assert default_question_count("1.2") == 10
        assert default_question_count("summative") == 20

    async def test_quality_agent_regeneration_keeps_the_count(self):
        from app.domain.services.quality_agent_service import CourseQualityService

        row = _row(revision=1, key=REV1_KEY)  # 4 questions
        row.regeneration_attempts = 0
        row.quality_status = "failing"
        unit = SimpleNamespace(unit_number="1.2")
        session = FakeSession(row=row)

        async def get(model, key):
            return row if model is GeneratedContent else unit

        session.get = get

        async def regenerate(**kwargs):
            # The in-place overwrite path: it bumps the revision itself.
            row.content = _new_content("1.2")
            row.content_revision += 1

        with patch(
            "app.domain.services.quiz_service.QuizService.get_or_generate_quiz",
            AsyncMock(side_effect=regenerate),
        ) as generate:
            await CourseQualityService(MagicMock(), MagicMock()).regenerate_with_constraints(
                content_id=row.id, constraints=["fix it"], session=session
            )

        assert generate.await_args.kwargs["num_questions"] == 4
        # Its own pre-image (trigger quality_loop), written once.
        (pre_image,) = session.attempts(GeneratedContentRevision)
        assert (pre_image.revision, pre_image.trigger) == (1, "quality_loop")
        # Bumped once (by the overwrite), not again on top: revision 2 is the
        # one learners are served, and revision 1 has its pre-image.
        assert row.content_revision == 2

    async def test_quality_agent_still_bumps_when_the_generator_did_not(self):
        from app.domain.services.quality_agent_service import CourseQualityService

        row = _row(revision=3, key=REV1_KEY)
        row.regeneration_attempts = 0
        session = FakeSession(row=row, pre_images={(row.id, 3): _pre_image(row, 3, REV1_KEY)})

        async def get(model, key):
            return row if model is GeneratedContent else SimpleNamespace(unit_number="1.2")

        session.get = get
        with patch(
            "app.domain.services.quiz_service.QuizService.get_or_generate_quiz", AsyncMock()
        ):
            await CourseQualityService(MagicMock(), MagicMock()).regenerate_with_constraints(
                content_id=row.id, constraints=[], session=session
            )
        assert row.content_revision == 4
        # A pre-image already existed at revision 3: not inserted again.
        assert session.attempts(GeneratedContentRevision) == []
