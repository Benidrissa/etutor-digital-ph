"""The flashcard endpoint maps CourseNotIndexedError to HTTP 409 (#2491).

Flashcards are served synchronously, so a course with zero indexed chunks must
surface a distinct ``course_not_indexed`` response (409) the frontend can detect
via ``ApiError.code`` — separate from the 404 (module not found) and 400
(no relevant content) cases. The 409 branch must precede the ValueError handler
because CourseNotIndexedError subclasses ValueError.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.api.v1 import flashcards as flashcards_module
from app.domain.services.exceptions import CourseNotIndexedError


async def _invoke(side_effect):
    service = MagicMock()
    service.get_or_generate_flashcard_set = AsyncMock(side_effect=side_effect)
    # A UUID string resolves without a DB lookup in _resolve_module_id.
    await flashcards_module.get_module_flashcards(
        module_id=str(uuid.uuid4()),
        language="fr",
        country="CI",
        level=1,
        current_user=MagicMock(),
        flashcard_service=service,
        session=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_course_not_indexed_maps_to_409():
    with pytest.raises(HTTPException) as exc:
        await _invoke(CourseNotIndexedError())

    assert exc.value.status_code == 409
    assert exc.value.detail["error"] == "course_not_indexed"
    # `code` is what the frontend apiFetch reads into ApiError.code.
    assert exc.value.detail["code"] == "course_not_indexed"


@pytest.mark.asyncio
async def test_module_not_found_still_maps_to_404():
    with pytest.raises(HTTPException) as exc:
        await _invoke(ValueError("Module abc not found"))

    assert exc.value.status_code == 404
    assert exc.value.detail["error"] == "module_not_found"


@pytest.mark.asyncio
async def test_plain_no_content_valueerror_still_maps_to_400():
    # A unit/content miss (course IS indexed) must NOT be swallowed by the 409.
    with pytest.raises(HTTPException) as exc:
        await _invoke(ValueError("No relevant content found for module x"))

    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "invalid_request"
