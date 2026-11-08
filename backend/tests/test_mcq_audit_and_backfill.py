"""Admin MCQ audit (report-only) and the per-course misconception backfill.

Everything here runs without Postgres, Redis or a Celery worker: the endpoint
handlers and task helpers are driven with mocked sessions, a mocked Redis
client and a mocked ``apply_async``; routing and the admin-only role gate are
exercised over HTTP with the auth and DB dependencies overridden.
"""

from __future__ import annotations

import copy
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from app.api.v1 import admin_quality
from app.api.v1.admin_quality import (
    McqBackfillRequest,
    audit_course_mcqs,
    build_mcq_audit,
    start_mcq_backfill,
)
from app.tasks import quiz_backfill

ADMIN = SimpleNamespace(id=str(uuid.uuid4()), role="admin")
COURSE_ID = uuid.uuid4()
MISCONCEPTIONS = ["Thinks cholera is mosquito-borne", None, "Confuses rash illnesses", "TB myth"]


def _question(qid: str = "q1", **overrides) -> dict:
    question = {
        "id": qid,
        "question": "Which disease is transmitted by the Anopheles mosquito?",
        "options": ["Cholera", "Malaria", "Measles", "Tuberculosis"],
        "correct_answer": 1,
        "option_misconceptions": list(MISCONCEPTIONS),
        "explanation": "Anopheles carry Plasmodium.",
        "sources_cited": [],
        "difficulty": "easy",
    }
    question.update(overrides)
    return question


def _legacy(qid: str = "q1", **overrides) -> dict:
    question = _question(qid, **overrides)
    question.pop("option_misconceptions")
    return question


def _gc(language: str, questions: list[dict], *, unit_uuid=None, module_id=None, **extra):
    return SimpleNamespace(
        id=uuid.uuid4(),
        module_id=module_id or uuid.uuid4(),
        module_unit_id=unit_uuid,
        content_type="quiz",
        content={"title": "Quiz", "questions": questions, "unit_id": "1.2"},
        language=language,
        level=1,
        country_context="SN",
        is_manually_edited=False,
        validated=False,
        quality_status="passing",
        content_revision=1,
        sources_cited=[],
        quality_score=None,
        quality_flags=[],
        generated_at=datetime(2026, 1, 1),
        **extra,
    )


# ── Audit: the pure report ───────────────────────────────────────────────────


class TestBuildMcqAudit:
    def test_clean_course_with_misconceptions(self):
        unit = uuid.uuid4()
        report = build_mcq_audit(COURSE_ID, [(_gc("en", [_question()], unit_uuid=unit), "1.2")])
        assert report.ok is True
        assert report.fully_checked is True
        assert report.rows[0].has_option_misconceptions is True
        assert report.rows[0].errors == [] and report.rows[0].warnings == []

    def test_findings_and_summary(self):
        unit = uuid.uuid4()
        en = _gc(
            "en",
            [
                _question("q1"),
                _question("q2", question="Malaria — which disease do they carry?"),
                _legacy("q3", options=["11", "12", "9", "14"], correct_answer=3),
            ],
            unit_uuid=unit,
        )
        fr = _gc(
            "fr", [_question("q1", correct_answer=2, option_misconceptions=None)], unit_uuid=unit
        )
        broken = _gc("en", [], unit_uuid=uuid.uuid4())
        broken.content = "not a dict"

        report = build_mcq_audit(COURSE_ID, [(en, "1.2"), (fr, "1.2"), (broken, "1.3")])

        assert report.ok is False
        assert report.fully_checked is False
        s = report.summary
        assert s.rows_checked == 3
        assert s.questions_checked == 4
        assert s.rows_with_errors == 2
        assert s.rows_lacking_option_misconceptions == 2  # en (q3) and fr
        assert s.questions_lacking_option_misconceptions == 2
        assert s.short_answer_leak_unchecked == 1

        en_row = report.rows[0]
        assert [(e.code, e.path) for e in en_row.errors] == [
            ("answer_leak", "questions[q2].question")
        ]
        assert {w.code for w in en_row.warnings} == {
            "misconceptions_unchecked",
            "leak_unchecked_short_answer",
        }
        assert en_row.has_option_misconceptions is False
        assert report.rows[2].errors[0].code == "malformed_question"

    def test_parity_is_warning_only_and_per_unit(self):
        unit = uuid.uuid4()
        en = _gc("en", [_question("q1"), _question("q2")], unit_uuid=unit)
        fr = _gc(
            "fr", [_question("q1", correct_answer=2, option_misconceptions=None)], unit_uuid=unit
        )
        report = build_mcq_audit(COURSE_ID, [(en, "1.2"), (fr, "1.2")])
        assert report.parity, "FR/EN divergence should be reported"
        assert {p.severity for p in report.parity} == {"warning"}
        assert all(p.path.startswith("units[1.2][level=1,country=SN]") for p in report.parity)
        assert report.summary.parity_warning_count == len(report.parity)

    def test_only_newest_row_per_language_is_compared(self):
        unit = uuid.uuid4()
        newest_en = _gc("en", [_question("q1")], unit_uuid=unit)
        older_en = _gc("en", [_question("zz")], unit_uuid=unit)
        fr = _gc("fr", [_question("q1")], unit_uuid=unit)
        report = build_mcq_audit(COURSE_ID, [(newest_en, "1.2"), (older_en, "1.2"), (fr, "1.2")])
        assert report.parity == []

    def test_different_countries_are_not_compared(self):
        unit = uuid.uuid4()
        en = _gc("en", [_question("q1")], unit_uuid=unit)
        fr = _gc("fr", [_question("q9")], unit_uuid=unit)
        fr.country_context = "CI"
        assert build_mcq_audit(COURSE_ID, [(en, "1.2"), (fr, "1.2")]).parity == []


# ── Audit: the endpoint is report-only ───────────────────────────────────────


def _audit_session(rows: list[tuple]) -> MagicMock:
    course_lookup = MagicMock()
    course_lookup.first.return_value = (None,)
    quiz_rows = MagicMock()
    quiz_rows.all.return_value = rows
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[course_lookup, quiz_rows])
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    session.add = MagicMock()
    return session


class TestAuditEndpoint:
    async def test_report_only(self):
        gc = _gc("en", [_question("q1", question="Malaria: which is it?")], unit_uuid=uuid.uuid4())
        before = (copy.deepcopy(gc.content), gc.validated, gc.quality_status)
        session = _audit_session([(gc, "1.2")])

        report = await audit_course_mcqs(
            course_id=COURSE_ID, language=None, current_user=ADMIN, session=session
        )

        assert report.rows[0].errors[0].code == "answer_leak"
        assert (gc.content, gc.validated, gc.quality_status) == before
        session.commit.assert_not_called()
        session.flush.assert_not_called()
        session.add.assert_not_called()

    async def test_unit_label_falls_back_to_the_sentinel(self):
        gc = _gc("en", [_question()], unit_uuid=None)
        gc.content["unit_id"] = "summative"
        report = await audit_course_mcqs(
            course_id=COURSE_ID,
            language="en",
            current_user=ADMIN,
            session=_audit_session([(gc, None)]),
        )
        assert report.rows[0].unit_id == "summative"
        assert report.language == "en"

    async def test_missing_course_is_404(self):
        lookup = MagicMock()
        lookup.first.return_value = None
        session = MagicMock()
        session.execute = AsyncMock(return_value=lookup)
        with pytest.raises(HTTPException) as exc_info:
            await audit_course_mcqs(
                course_id=COURSE_ID, language=None, current_user=ADMIN, session=session
            )
        assert exc_info.value.status_code == 404


class TestAdminOnlyOverHttp:
    @asynccontextmanager
    async def _client(self, role: str, session):
        from app.api.deps import get_db
        from app.api.deps_local_auth import AuthenticatedUser, get_current_user
        from app.main import app

        user = AuthenticatedUser(
            {"sub": "11111111-1111-1111-1111-111111111111", "email": "u@x.org", "role": role}
        )

        async def fake_db():
            yield session

        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = fake_db
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                yield client
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("GET", "/api/v1/admin/courses/{c}/quality/mcq-audit"),
            ("POST", "/api/v1/admin/courses/{c}/quality/mcq-backfill"),
            ("GET", "/api/v1/admin/courses/{c}/quality/mcq-backfill/abc"),
        ],
    )
    @pytest.mark.parametrize("role", ["expert", "user"])
    async def test_non_admins_are_forbidden(self, method, path, role):
        async with self._client(role, MagicMock()) as client:
            response = await client.request(method, path.format(c=COURSE_ID))
        assert response.status_code == 403

    async def test_admin_audit_over_http(self):
        gc = _gc("en", [_question()], unit_uuid=uuid.uuid4())
        async with self._client("sub_admin", _audit_session([(gc, "1.2")])) as client:
            response = await client.get(f"/api/v1/admin/courses/{COURSE_ID}/quality/mcq-audit")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["ok"] is True
        assert body["summary"]["rows_checked"] == 1


# ── Backfill dispatch: idempotent while a run is in flight ───────────────────


def _redis(*, set_results=(True,), current=None):
    client = MagicMock()
    client.set = AsyncMock(side_effect=list(set_results))
    client.get = AsyncMock(return_value=current)
    client.eval = AsyncMock(return_value=1)
    return client


def _course_session() -> MagicMock:
    lookup = MagicMock()
    lookup.first.return_value = (None,)
    session = MagicMock()
    session.execute = AsyncMock(return_value=lookup)
    return session


async def _start(redis_client, *, state="STARTED", payload=None, apply_side_effect=None):
    task = MagicMock()
    task.apply_async = MagicMock(side_effect=apply_side_effect)
    task.AsyncResult.return_value = SimpleNamespace(state=state, info={})
    with (
        patch("app.infrastructure.cache.redis.redis_client", redis_client),
        patch.object(quiz_backfill, "backfill_course_quiz_misconceptions", task),
        patch("app.api.v1._task_status.mark_dispatched", AsyncMock()) as marked,
    ):
        response = await start_mcq_backfill(
            course_id=COURSE_ID, payload=payload, current_user=ADMIN, session=_course_session()
        )
    return response, task, marked


class TestStartBackfill:
    async def test_dispatches_with_the_lock_holder_as_task_id(self):
        redis_client = _redis()
        response, task, marked = await _start(redis_client, payload=McqBackfillRequest(force=True))
        assert response.status == "dispatched"
        kwargs = task.apply_async.call_args.kwargs
        assert kwargs["task_id"] == response.task_id
        assert kwargs["kwargs"] == {
            "course_id": str(COURSE_ID),
            "triggered_by_user_id": ADMIN.id,
            "force": True,
        }
        lock_call = redis_client.set.call_args
        assert lock_call.args == (quiz_backfill.lock_key(COURSE_ID), response.task_id)
        assert lock_call.kwargs["nx"] is True
        marked.assert_awaited_once_with(response.task_id)

    async def test_second_click_while_running_does_not_dispatch(self):
        redis_client = _redis(set_results=(False,), current="running-task")
        response, task, _ = await _start(redis_client, state="STARTED")
        assert response.status == "already_running"
        assert response.task_id == "running-task"
        task.apply_async.assert_not_called()

    async def test_queued_run_counts_as_running(self):
        redis_client = _redis(set_results=(False,), current="queued-task")
        response, task, _ = await _start(redis_client, state="PENDING")
        assert response.status == "already_running"
        task.apply_async.assert_not_called()

    async def test_stale_lock_from_a_finished_run_is_taken_over(self):
        redis_client = _redis(set_results=(False, True), current="old-task")
        response, task, _ = await _start(redis_client, state="SUCCESS")
        assert response.status == "dispatched"
        redis_client.eval.assert_awaited_once()
        assert redis_client.eval.await_args.args[-1] == "old-task"
        task.apply_async.assert_called_once()

    async def test_lost_takeover_race_reports_the_winner(self):
        redis_client = _redis(set_results=(False, False), current="old-task")
        response, task, _ = await _start(redis_client, state="FAILURE")
        assert response.status == "already_running"
        task.apply_async.assert_not_called()

    async def test_redis_outage_fails_open(self):
        redis_client = _redis()
        redis_client.set = AsyncMock(side_effect=ConnectionError("down"))
        response, task, _ = await _start(redis_client)
        assert response.status == "dispatched"
        task.apply_async.assert_called_once()

    async def test_failed_dispatch_releases_the_lock(self):
        redis_client = _redis()
        with pytest.raises(HTTPException) as exc_info:
            await _start(redis_client, apply_side_effect=RuntimeError("broker down"))
        assert exc_info.value.status_code == 500
        redis_client.eval.assert_awaited_once()


class TestBackfillStatus:
    async def test_reports_progress(self):
        task = MagicMock()
        task.AsyncResult.return_value = SimpleNamespace(
            state="PROGRESS", info={"done": 2, "total": 5}
        )
        with patch.object(quiz_backfill, "backfill_course_quiz_misconceptions", task):
            status = await admin_quality.get_mcq_backfill_status(
                course_id=COURSE_ID, task_id="t1", current_user=ADMIN, session=_course_session()
            )
        assert status.state == "progress"
        assert status.progress == {"done": 2, "total": 5}

    async def test_other_courses_task_is_404(self):
        task = MagicMock()
        task.AsyncResult.return_value = SimpleNamespace(
            state="SUCCESS", info={"course_id": str(uuid.uuid4())}
        )
        with (
            patch.object(quiz_backfill, "backfill_course_quiz_misconceptions", task),
            pytest.raises(HTTPException) as exc_info,
        ):
            await admin_quality.get_mcq_backfill_status(
                course_id=COURSE_ID, task_id="t1", current_user=ADMIN, session=_course_session()
            )
        assert exc_info.value.status_code == 404


# ── The task: one row through the existing regeneration path ────────────────


def _row_session(gc, unit=None, *, revision_exists=False):
    revision_lookup = MagicMock()
    revision_lookup.scalars.return_value.first.return_value = (
        uuid.uuid4() if revision_exists else None
    )
    session = MagicMock()

    async def get(model, key):
        return gc if model.__name__ == "GeneratedContent" else unit

    session.get = AsyncMock(side_effect=get)
    session.execute = AsyncMock(return_value=revision_lookup)
    session.add = MagicMock()
    session.refresh = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


def _quiz_service(gc, *, overwrite=True):
    async def regenerate(**kwargs):
        if overwrite:
            gc.content = {"title": "New", "questions": [_question()], "unit_id": "1.2"}
            gc.content_revision += 1

    service = MagicMock()
    service.get_or_generate_quiz = AsyncMock(side_effect=regenerate)
    return service


class TestRegenerateQuizRow:
    async def test_legacy_row_is_regenerated_in_place(self):
        gc = _gc("fr", [_legacy("q1"), _legacy("q2")], unit_uuid=uuid.uuid4())
        unit = SimpleNamespace(unit_number="1.2")
        session = _row_session(gc, unit)
        service = _quiz_service(gc)
        user = uuid.uuid4()

        outcome = await quiz_backfill.regenerate_quiz_row(
            session, service, gc.id, triggered_by_user_id=user
        )

        assert outcome == "regenerated"
        kwargs = service.get_or_generate_quiz.await_args.kwargs
        assert kwargs["force_regenerate"] is True
        assert kwargs["unit_id"] == "1.2"
        assert (kwargs["language"], kwargs["country"], kwargs["level"]) == ("fr", "SN", 1)
        assert kwargs["num_questions"] == 2
        revision = session.add.call_args.args[0]
        assert revision.trigger == "mcq_backfill"
        assert revision.revision == 1
        assert revision.triggered_by_user_id == user
        assert revision.content["questions"][0]["id"] == "q1"
        assert gc.quality_status == "pending"
        session.commit.assert_awaited()

    async def test_existing_pre_image_is_not_duplicated(self):
        gc = _gc("fr", [_legacy()], unit_uuid=uuid.uuid4())
        session = _row_session(gc, SimpleNamespace(unit_number="1.2"), revision_exists=True)
        outcome = await quiz_backfill.regenerate_quiz_row(session, _quiz_service(gc), gc.id)
        assert outcome == "regenerated"
        session.add.assert_not_called()

    async def test_summative_row_uses_the_sentinel(self):
        gc = _gc("en", [_legacy()], unit_uuid=None)
        gc.content["unit_id"] = "summative"
        service = _quiz_service(gc)
        await quiz_backfill.regenerate_quiz_row(_row_session(gc), service, gc.id)
        assert service.get_or_generate_quiz.await_args.kwargs["unit_id"] == "summative"

    @pytest.mark.parametrize(
        ("mutate", "outcome"),
        [
            (lambda gc: setattr(gc, "is_manually_edited", True), "skipped_manually_edited"),
            (lambda gc: setattr(gc, "country_context", None), "skipped_no_country"),
            (lambda gc: setattr(gc, "content_type", "lesson"), "missing"),
        ],
    )
    async def test_rows_that_must_not_be_regenerated(self, mutate, outcome):
        gc = _gc("fr", [_legacy()], unit_uuid=uuid.uuid4())
        mutate(gc)
        service = _quiz_service(gc)
        result = await quiz_backfill.regenerate_quiz_row(
            _row_session(gc, SimpleNamespace(unit_number="1.2")), service, gc.id
        )
        assert result == outcome
        service.get_or_generate_quiz.assert_not_called()

    async def test_rows_with_misconceptions_are_skipped_unless_forced(self):
        gc = _gc("fr", [_question()], unit_uuid=uuid.uuid4())
        unit = SimpleNamespace(unit_number="1.2")
        service = _quiz_service(gc)
        assert (
            await quiz_backfill.regenerate_quiz_row(_row_session(gc, unit), service, gc.id)
            == "skipped_has_misconceptions"
        )
        assert (
            await quiz_backfill.regenerate_quiz_row(
                _row_session(gc, unit), service, gc.id, force=True
            )
            == "regenerated"
        )

    async def test_a_write_that_missed_the_row_is_not_counted_as_done(self):
        gc = _gc("fr", [_legacy()], unit_uuid=uuid.uuid4())
        outcome = await quiz_backfill.regenerate_quiz_row(
            _row_session(gc, SimpleNamespace(unit_number="1.2")),
            _quiz_service(gc, overwrite=False),
            gc.id,
        )
        assert outcome == "not_overwritten"
        assert gc.quality_status == "passing"


class TestRunBackfill:
    async def test_one_failure_does_not_stop_the_course(self):
        ids = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
        listing = MagicMock()
        listing.scalars.return_value.all.return_value = ids
        sessions = []

        @asynccontextmanager
        async def session_factory():
            session = MagicMock()
            session.execute = AsyncMock(return_value=listing)
            session.rollback = AsyncMock()
            sessions.append(session)
            yield session

        outcomes = iter(
            ["regenerated", RuntimeError("model overloaded"), "skipped_manually_edited"]
        )

        async def fake_row(session, service, content_id, **kwargs):
            outcome = next(outcomes)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        progress = []
        with patch.object(quiz_backfill, "regenerate_quiz_row", fake_row):
            result = await quiz_backfill.run_backfill(
                COURSE_ID,
                session_factory=session_factory,
                quiz_service=MagicMock(),
                on_progress=progress.append,
            )

        assert result["total"] == 3
        assert result["regenerated"] == 1
        assert result["failed"] == 1
        assert result["skipped_manually_edited"] == 1
        assert result["failures"][0]["content_id"] == str(ids[1])
        assert len(sessions) == 4  # one listing session + one per row
        sessions[2].rollback.assert_awaited_once()
        assert progress[-1]["done"] == 3


class TestCeleryTask:
    def test_registered_with_celery(self):
        from app.tasks.celery_app import celery_app

        assert "app.tasks.quiz_backfill" in celery_app.conf.include
        assert quiz_backfill.backfill_course_quiz_misconceptions.name in celery_app.tasks

    def test_attributes_ai_spend_and_releases_the_lock(self):
        user = str(uuid.uuid4())
        run = AsyncMock(
            return_value={"status": "complete", **dict.fromkeys(quiz_backfill.OUTCOMES, 0)}
        )
        engine = MagicMock()
        engine.dispose = AsyncMock()
        with (
            patch.object(quiz_backfill, "set_ai_context") as set_ctx,
            patch.object(quiz_backfill, "run_backfill", run),
            patch.object(quiz_backfill, "_release_lock") as release,
            patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=engine),
            patch("app.ai.rag.embeddings.EmbeddingService"),
            patch("app.ai.claude_service.ClaudeService"),
        ):
            result = quiz_backfill.backfill_course_quiz_misconceptions.run(
                course_id=str(COURSE_ID), triggered_by_user_id=user, force=False
            )

        assert result["status"] == "complete"
        set_ctx.assert_called_once_with(
            "quiz_generation", user_id=uuid.UUID(user), course_id=COURSE_ID
        )
        assert run.await_args.kwargs["force"] is False
        release.assert_called_once()
        assert release.call_args.args[0] == str(COURSE_ID)

    def test_lock_is_released_even_when_the_run_fails(self):
        engine = MagicMock()
        engine.dispose = AsyncMock()
        with (
            patch.object(quiz_backfill, "set_ai_context"),
            patch.object(quiz_backfill, "run_backfill", AsyncMock(side_effect=RuntimeError("db"))),
            patch.object(quiz_backfill, "_release_lock") as release,
            patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=engine),
            patch("app.ai.rag.embeddings.EmbeddingService"),
            patch("app.ai.claude_service.ClaudeService"),
        ):
            result = quiz_backfill.backfill_course_quiz_misconceptions.run(course_id=str(COURSE_ID))
        assert result["status"] == "failed"
        release.assert_called_once()


class TestHasMisconceptions:
    def test_every_question_must_carry_the_field(self):
        assert quiz_backfill.has_misconceptions({"questions": [_question(), _question("q2")]})
        assert not quiz_backfill.has_misconceptions({"questions": [_question(), _legacy("q2")]})
        assert not quiz_backfill.has_misconceptions({"questions": []})
        assert not quiz_backfill.has_misconceptions("nope")
