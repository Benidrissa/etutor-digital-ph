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


class TestSoftTimeLimitHandling:
    """Image-heavy courses can run past the soft time limit. The task must
    finalize the partial (already-committed) result as a SUCCESS instead of
    letting ``autoretry_for=(Exception,)`` re-run the whole pipeline and
    re-surface a hard error in the wizard. Regression guard for the
    course-creation "Erreur lors de l'indexation." bug.
    """

    def test_soft_time_limit_finalizes_partial_without_retrying(self) -> None:
        from pathlib import Path

        from celery.exceptions import SoftTimeLimitExceeded

        import app.tasks.rag_indexation as mod

        task = mod.index_course_resources

        course_path = MagicMock()
        course_path.exists.return_value = True
        # One PDF on disk so we reach the asyncio.run try-block.
        course_path.glob.return_value = [Path("/tmp/nonexistent-for-test.pdf")]

        def _raise_soft_timeout(coro):
            # Close the un-run coroutine to avoid a "never awaited" warning,
            # then simulate Celery raising at the soft time limit.
            coro.close()
            raise SoftTimeLimitExceeded()

        # The task now always loads CourseResource rows up front (to index
        # file_hash-deduped DB-only sources alongside disk PDFs, #2525). Stub the
        # query so it returns no DB-only resources for this disk-PDF scenario.
        empty_session = MagicMock()
        empty_session.execute.return_value.scalars.return_value.all.return_value = []
        empty_session.__enter__ = lambda self: self
        empty_session.__exit__ = lambda *a: None

        with (
            patch.object(mod, "UPLOAD_DIR") as mock_upload_dir,
            patch("sqlalchemy.create_engine"),
            patch("sqlalchemy.orm.Session", return_value=empty_session),
            patch("asyncio.run", side_effect=_raise_soft_timeout),
            patch.object(task, "update_state") as mock_update_state,
        ):
            mock_upload_dir.__truediv__.return_value = course_path

            # Must NOT raise — raising would trigger autoretry of a ~20-min run.
            result = task.run("11111111-1111-1111-1111-111111111111", "collection-x")

        assert result["status"] == "partial_timeout"
        assert result["rag_collection_id"] == "collection-x"
        # Finalized as COMPLETE (drives RAGTask.on_success → 'indexed'),
        # never re-raised into the autoretry path.
        assert any(
            call.kwargs.get("state") == "COMPLETE" for call in mock_update_state.call_args_list
        )

    def test_decorator_keeps_result_tracking_and_realistic_limits(self) -> None:
        """ignore_result must stay False (so AsyncResult.state is readable for
        the duplicate-dispatch guard and /index-status), and the time budget
        must comfortably exceed an image-heavy run."""
        from app.tasks.rag_indexation import index_course_resources

        assert index_course_resources.ignore_result is False
        assert index_course_resources.soft_time_limit >= 3000
        assert index_course_resources.time_limit > index_course_resources.soft_time_limit


class TestDbOnlyResources:
    """Unit tests for ``_db_only_resources`` — the partition that keeps
    file_hash-deduped uploads (no file on disk) from being silently dropped by
    the disk-glob indexing path. See #2525.
    """

    @staticmethod
    def _res(filename, *, raw_text="text", parent_filename=None):
        from types import SimpleNamespace

        return SimpleNamespace(
            filename=filename, parent_filename=parent_filename, raw_text=raw_text
        )

    def test_deduped_db_only_resource_is_selected_when_disk_pdf_coexists(self) -> None:
        from pathlib import Path

        from app.tasks.rag_indexation import _db_only_resources

        pdf_files = [Path("/u/course/Douglas.pdf")]
        douglas = self._res("Douglas")  # on disk
        donaldson = self._res("donaldson")  # file_hash-deduped, no file on disk

        out = _db_only_resources(pdf_files, [douglas, donaldson])

        # The regression: donaldson must be picked up even though a disk PDF
        # exists — the old `if not pdf_files` gate dropped it entirely.
        assert out == [donaldson]

    def test_resource_matching_disk_stem_is_excluded(self) -> None:
        from pathlib import Path

        from app.tasks.rag_indexation import _db_only_resources

        pdf_files = [Path("/u/course/Douglas.pdf")]
        out = _db_only_resources(pdf_files, [self._res("Douglas")])
        assert out == []

    def test_split_part_excluded_when_parent_on_disk(self) -> None:
        from pathlib import Path

        from app.tasks.rag_indexation import _db_only_resources

        pdf_files = [Path("/u/course/Douglas.pdf")]
        part = self._res("Douglas_part2", parent_filename="Douglas")
        out = _db_only_resources(pdf_files, [part])
        assert out == []

    def test_resource_without_raw_text_excluded(self) -> None:
        from app.tasks.rag_indexation import _db_only_resources

        out = _db_only_resources([], [self._res("pending", raw_text=None)])
        assert out == []

    def test_all_deduped_course_with_no_disk_files(self) -> None:
        from app.tasks.rag_indexation import _db_only_resources

        a = self._res("a")
        b = self._res("b")
        out = _db_only_resources([], [a, b])
        assert out == [a, b]
