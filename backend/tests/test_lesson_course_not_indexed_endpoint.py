"""Tests that the lesson endpoint maps CourseNotIndexedError to HTTP 409 (#2487).

A course with zero indexed chunks must surface a distinct ``course_not_indexed``
response (409), separate from the generic 400 used for "no relevant content for
this unit", so the frontend can show a "still being prepared" state.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.api.v1 import content as content_module
from app.domain.services.exceptions import CourseNotIndexedError


def _request() -> MagicMock:
    request = MagicMock()
    request.module_id = "a1cc100e-266d-42c5-87ff-3930eba2e075"
    request.unit_id = "2.4"
    request.language = "fr"
    request.country = "CI"
    request.level = 1
    return request


async def _invoke(side_effect):
    lesson_service = MagicMock()
    lesson_service.get_or_generate_lesson = AsyncMock(side_effect=side_effect)
    await content_module.generate_lesson(
        _request(),
        lesson_service=lesson_service,
        session=AsyncMock(),
        current_user=MagicMock(),
    )


@pytest.mark.asyncio
async def test_course_not_indexed_maps_to_409():
    with pytest.raises(HTTPException) as exc:
        await _invoke(CourseNotIndexedError())

    assert exc.value.status_code == 409
    assert exc.value.detail["error"] == "course_not_indexed"


@pytest.mark.asyncio
async def test_plain_no_content_valueerror_still_maps_to_400():
    # A unit miss (course IS indexed) must NOT be swallowed by the 409 branch.
    with pytest.raises(HTTPException) as exc:
        await _invoke(ValueError("No relevant content found for module x, unit 2.4"))

    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "invalid_request"
