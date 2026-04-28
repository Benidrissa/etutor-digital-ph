"""Tests for the indexation lifecycle ownership fix (#2085).

Verifies that ``RAGTask`` / ``ImageIndexTask`` Celery callbacks always
clear ``courses.indexation_task_id`` on terminal exits, and that
``finalize_indexation_state`` writes the right SQL for each call shape.
"""

from unittest.mock import MagicMock, patch


class TestFinalizeIndexationState:
    """Unit tests for the lifecycle helper that owns
    (creation_step, indexation_task_id) writes.
    """

    def test_no_op_on_missing_course_id(self) -> None:
        from app.tasks.rag_indexation import finalize_indexation_state

        with patch("sqlalchemy.create_engine") as mock_engine:
            finalize_indexation_state(None)
            mock_engine.assert_not_called()

    def test_clears_pointer_only_when_no_transition(self) -> None:
        from app.tasks.rag_indexation import finalize_indexation_state

        captured: dict = {}

        def _capture_execute(stmt, params):
            captured["sql"] = str(stmt)
            captured["params"] = params
            return MagicMock()

        mock_session = MagicMock()
        mock_session.execute.side_effect = _capture_execute
        mock_session.__enter__ = lambda self: self
        mock_session.__exit__ = lambda *a: None

        with (
            patch("sqlalchemy.create_engine") as mock_engine,
            patch("sqlalchemy.orm.Session", return_value=mock_session),
        ):
            mock_engine.return_value = MagicMock()
            finalize_indexation_state("abc-123")

        assert "indexation_task_id = NULL" in captured["sql"]
        assert "creation_step" not in captured["sql"]
        assert captured["params"] == {"cid": "abc-123"}

    def test_transitions_creation_step_idempotently(self) -> None:
        from app.tasks.rag_indexation import finalize_indexation_state

        captured: dict = {}

        def _capture_execute(stmt, params):
            captured["sql"] = str(stmt)
            captured["params"] = params
            return MagicMock()

        mock_session = MagicMock()
        mock_session.execute.side_effect = _capture_execute
        mock_session.__enter__ = lambda self: self
        mock_session.__exit__ = lambda *a: None

        with (
            patch("sqlalchemy.create_engine") as mock_engine,
            patch("sqlalchemy.orm.Session", return_value=mock_session),
        ):
            mock_engine.return_value = MagicMock()
            finalize_indexation_state("abc-123", transition=("indexing", "indexed"))

        sql = captured["sql"]
        assert "indexation_task_id = NULL" in sql
        # Idempotent transition: only flip if currently in from_step.
        # Protects against user-cancel races during success.
        assert "CASE WHEN creation_step = :from_step" in sql
        assert captured["params"] == {
            "cid": "abc-123",
            "from_step": "indexing",
            "to_step": "indexed",
        }

    def test_swallows_db_errors(self) -> None:
        """Lifecycle callbacks must never raise — Celery would mark the
        task as failed-after-success and the queue would loop."""
        from app.tasks.rag_indexation import finalize_indexation_state

        with patch("sqlalchemy.create_engine", side_effect=RuntimeError("db down")):
            finalize_indexation_state("abc-123")  # must not raise


class TestRAGTaskCallbacks:
    """RAGTask owns the (creation_step, indexation_task_id) transition
    for the full text+image indexation flow.
    """

    def test_on_success_transitions_indexing_to_indexed(self) -> None:
        from app.tasks.rag_indexation import RAGTask

        task = RAGTask()

        with patch("app.tasks.rag_indexation.finalize_indexation_state") as mock_finalize:
            task.on_success(
                retval={"status": "complete"},
                task_id="task-1",
                args=("course-abc",),
                kwargs={},
            )

        mock_finalize.assert_called_once_with("course-abc", transition=("indexing", "indexed"))

    def test_on_failure_transitions_indexing_to_generated(self) -> None:
        from app.tasks.rag_indexation import RAGTask

        task = RAGTask()

        with patch("app.tasks.rag_indexation.finalize_indexation_state") as mock_finalize:
            task.on_failure(
                exc=RuntimeError("boom"),
                task_id="task-1",
                args=("course-abc",),
                kwargs={},
                einfo=None,
            )

        mock_finalize.assert_called_once_with("course-abc", transition=("indexing", "generated"))

    def test_callback_reads_course_id_from_kwargs(self) -> None:
        from app.tasks.rag_indexation import RAGTask

        task = RAGTask()

        with patch("app.tasks.rag_indexation.finalize_indexation_state") as mock_finalize:
            task.on_success(
                retval={},
                task_id="task-1",
                args=(),
                kwargs={"course_id": "course-abc"},
            )

        mock_finalize.assert_called_once_with("course-abc", transition=("indexing", "indexed"))


class TestImageIndexTaskCallbacks:
    """ImageIndexTask clears the pointer but does NOT transition
    creation_step — image-only re-index runs against any creation_step.
    """

    def test_on_success_clears_pointer_no_transition(self) -> None:
        from app.tasks.image_indexation import ImageIndexTask

        task = ImageIndexTask()

        with patch("app.tasks.rag_indexation.finalize_indexation_state") as mock_finalize:
            task.on_success(
                retval={"status": "complete"},
                task_id="task-1",
                args=("course-abc",),
                kwargs={},
            )

        mock_finalize.assert_called_once_with("course-abc")

    def test_on_failure_clears_pointer_no_transition(self) -> None:
        from app.tasks.image_indexation import ImageIndexTask

        task = ImageIndexTask()

        with patch("app.tasks.rag_indexation.finalize_indexation_state") as mock_finalize:
            task.on_failure(
                exc=RuntimeError("boom"),
                task_id="task-1",
                args=("course-abc",),
                kwargs={},
                einfo=None,
            )

        mock_finalize.assert_called_once_with("course-abc")
