"""Tests for Celery Redis backend cascading failure fix (issue #1121).

Verifies that:
- Fire-and-forget tasks have ignore_result=True to prevent corrupted Redis metadata
  from poisoning subsequent tasks
- Celery config includes result_backend_always_retry and result_backend_max_retries
  as a belt-and-suspenders defence
"""


class TestCeleryConfigDefences:
    """Verify global Celery config has Redis backend retry settings."""

    def test_result_backend_always_retry_enabled(self):
        from app.tasks.celery_app import celery_app

        assert celery_app.conf.result_backend_always_retry is True

    def test_result_backend_max_retries_set(self):
        from app.tasks.celery_app import celery_app

        assert celery_app.conf.result_backend_max_retries == 3


class TestFireAndForgetTasksIgnoreResult:
    """Verify that all fire-and-forget tasks have ignore_result=True.

    These tasks track state via the courses.creation_step DB column, not via
    the Celery result backend. Storing results in Redis is unused overhead
    that causes cascading failures when a prior task leaves corrupted metadata.
    """

    def test_generate_course_syllabus_stores_result(self):
        from app.tasks.syllabus_generation import generate_course_syllabus

        assert generate_course_syllabus.ignore_result is False, (
            "generate_course_syllabus must have ignore_result=False — "
            "frontend polls AsyncResult.state for SUCCESS to enable the Next button"
        )

    def test_index_course_resources_ignores_result(self):
        from app.tasks.rag_indexation import index_course_resources

        assert index_course_resources.ignore_result is True, (
            "index_course_resources must have ignore_result=True — "
            "state is tracked via courses.creation_step, not Celery backend"
        )

    def test_reindex_course_images_ignores_result(self):
        from app.tasks.image_indexation import reindex_course_images

        assert reindex_course_images.ignore_result is True, (
            "reindex_course_images must have ignore_result=True — "
            "completion is tracked via logs/DB, not Celery backend"
        )
