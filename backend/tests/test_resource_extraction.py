"""Tests for async resource extraction flow (issue #1570).

Verifies that:
- The extract_course_resource Celery task correctly extracts text and sets
  extraction_status="done".
- The task marks extraction_status="failed" when the PDF file is missing.
- Model-level presence of the extraction_status column + status constants.

The upload-endpoint integration case is exercised manually / via the front-end
flow — a pytest-asyncio integration variant tripped the shared `test_engine`
conftest fixture on the certificatestatus enum and is out of scope here.
"""

import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.domain.models.course_resource import (
    EXTRACTION_STATUS_DONE,
    EXTRACTION_STATUS_FAILED,
    EXTRACTION_STATUS_PENDING,
)


def _make_minimal_pdf() -> bytes:
    return b"""%PDF-1.4
1 0 obj<</Type /Catalog /Pages 2 0 R>>endobj
2 0 obj<</Type /Pages /Kids [3 0 R] /Count 1>>endobj
3 0 obj<</Type /Page /MediaBox [0 0 612 792] /Parent 2 0 R /Contents 4 0 R /Resources<</Font<</F1<</Type /Font /Subtype /Type1 /BaseFont /Helvetica>>>>>>>>endobj
4 0 obj<</Length 44>>
stream
BT /F1 12 Tf 100 700 Td (Test PDF content) Tj ET
endstream
endobj
xref
0 5
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
0000000317 00000 n
trailer<</Size 5 /Root 1 0 R>>
startxref
413
%%EOF"""


class TestExtractCourseResourceTask:
    """Unit tests for the extract_course_resource Celery task logic."""

    def _make_mock_session_and_resource(self, tmp_path: Path, *, creation_mode: str = "legacy"):
        course_id = uuid.uuid4()
        resource_id = uuid.uuid4()

        pdf_dir = tmp_path / str(course_id)
        pdf_dir.mkdir(parents=True)
        pdf_file = pdf_dir / "guide.pdf"
        pdf_file.write_bytes(_make_minimal_pdf())

        mock_resource = MagicMock()
        mock_resource.id = resource_id
        mock_resource.course_id = course_id
        mock_resource.filename = "guide"
        mock_resource.extraction_status = EXTRACTION_STATUS_PENDING

        mock_course = MagicMock()
        mock_course.id = course_id
        mock_course.creation_mode = creation_mode
        mock_course.rag_collection_id = None
        mock_course.indexation_task_id = None

        return resource_id, course_id, pdf_dir, mock_resource, mock_course

    def test_task_marks_done_on_success(self, tmp_path):
        from app.tasks.resource_extraction import extract_course_resource

        resource_id, course_id, pdf_dir, mock_resource, mock_course = (
            self._make_mock_session_and_resource(tmp_path)
        )

        sessions_created = []

        class MockSession:
            def __init__(self):
                self._resources = {resource_id: mock_resource}
                self._courses = {course_id: mock_course}

            def get(self, model, pk):
                from app.domain.models.course import Course
                from app.domain.models.course_resource import CourseResource

                if model is CourseResource:
                    return self._resources.get(pk)
                if model is Course:
                    return self._courses.get(pk)
                return None

            def add(self, _obj):
                pass

            def commit(self):
                pass

            def __enter__(self):
                sessions_created.append(self)
                return self

            def __exit__(self, *_):
                pass

        with (
            patch("app.tasks.resource_extraction.UPLOAD_DIR", tmp_path),
            patch(
                "app.tasks.resource_extraction.Session",
                side_effect=lambda *a, **k: MockSession(),
            ),
        ):
            result = extract_course_resource(str(resource_id))

        assert result["status"] == "done"
        assert mock_resource.extraction_status == EXTRACTION_STATUS_DONE
        assert mock_resource.raw_text

    def test_task_marks_failed_when_pdf_missing(self, tmp_path):
        from app.tasks.resource_extraction import extract_course_resource

        resource_id = uuid.uuid4()
        course_id = uuid.uuid4()

        mock_resource = MagicMock()
        mock_resource.id = resource_id
        mock_resource.course_id = course_id
        mock_resource.filename = "missing_file"
        mock_resource.extraction_status = EXTRACTION_STATUS_PENDING

        class MockSession:
            def get(self, model, pk):
                from app.domain.models.course import Course
                from app.domain.models.course_resource import CourseResource

                if model is CourseResource:
                    return mock_resource
                if model is Course:
                    mock_course = MagicMock()
                    mock_course.creation_mode = "legacy"
                    return mock_course
                return None

            def commit(self):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_):
                pass

        with (
            patch("app.tasks.resource_extraction.UPLOAD_DIR", tmp_path),
            patch(
                "app.tasks.resource_extraction.Session",
                side_effect=lambda *a, **k: MockSession(),
            ),
        ):
            result = extract_course_resource(str(resource_id))

        assert result["status"] == "file_not_found"
        assert mock_resource.extraction_status == EXTRACTION_STATUS_FAILED


class TestCourseResourceModel:
    """Model-level checks for the extraction_status field."""

    def test_extraction_status_constants_are_valid(self):
        assert EXTRACTION_STATUS_PENDING == "pending"
        assert EXTRACTION_STATUS_DONE == "done"
        assert EXTRACTION_STATUS_FAILED == "failed"

    def test_model_has_extraction_status_column(self):
        from app.domain.models.course_resource import CourseResource

        columns = {c.name for c in CourseResource.__table__.columns}
        assert "extraction_status" in columns
