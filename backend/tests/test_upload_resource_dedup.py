"""Regression test for file-hash-deduped uploads writing the PDF to disk (#2548).

The dedup branch of `upload_course_resource` inherits the donor's extracted text and skips
the extraction task, but it must still write the PDF bytes to disk — image indexation globs
`course_dir` for `*.pdf` and `process_pdf_images` requires the file, so without the bytes a
deduped course silently ends up with text but ZERO images.

Calls the endpoint directly with mocks (the DB-integration resource tests are skipped under
the current async-fixture setup — see #554), so it runs in CI.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.v1 import admin_courses


@pytest.mark.asyncio
async def test_deduped_upload_still_writes_pdf_to_disk(tmp_path):
    course_id = uuid.uuid4()
    data = b"%PDF-1.4 fake donaldson bytes"

    course = MagicMock()
    course.creation_step = "info"
    donor = MagicMock()  # inherited fields are read as plain attributes

    course_result = MagicMock()
    course_result.scalar_one_or_none = MagicMock(return_value=course)
    donor_result = MagicMock()
    donor_result.scalar_one_or_none = MagicMock(return_value=donor)

    db = MagicMock()
    db.execute = AsyncMock(side_effect=[course_result, donor_result])
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    file = MagicMock()
    file.content_type = "application/pdf"
    file.filename = "donaldson.pdf"
    file.read = AsyncMock(return_value=data)

    with patch.object(admin_courses, "UPLOAD_DIR", tmp_path):
        result = await admin_courses.upload_course_resource(
            course_id=course_id, file=file, current_user=MagicMock(), db=db
        )

    # Extraction task was skipped (text inherited) ...
    assert result["extraction_status"] == admin_courses.EXTRACTION_STATUS_DONE
    # ... but the PDF is on disk so image indexation can extract figures.
    written = tmp_path / str(course_id) / "donaldson.pdf"
    assert written.exists()
    assert written.read_bytes() == data
