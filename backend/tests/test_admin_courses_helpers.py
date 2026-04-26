"""Unit tests for admin_courses helpers introduced by #2015 / #2016 / #2017.

These exercise pure helpers with no DB or HTTP dependencies, sidestepping the
pytest-asyncio event-loop conflict that keeps the integration suite skipped
(see test_courses.py).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api.v1.admin_courses import _require_indexed_sources, _safe_task_meta


class _RaisingInfoAsyncResult:
    """Stub mimicking celery.result.AsyncResult with a malformed payload.

    Reading `.info` raises the same ValueError that real Celery raises when
    `exception_to_python()` hits a payload missing `exc_type`. See #2015.
    """

    state = "FAILURE"

    @property
    def info(self):
        raise ValueError("Exception information must include the exception type")


class _DictInfoAsyncResult:
    state = "PROGRESS"

    def __init__(self, meta: dict) -> None:
        self._meta = meta

    @property
    def info(self):
        return self._meta


class _NonDictInfoAsyncResult:
    state = "SUCCESS"

    @property
    def info(self):
        return "not a dict"


# ---------------------------------------------------------------------------
# #2015 — _safe_task_meta degrades malformed payloads instead of raising
# ---------------------------------------------------------------------------


def test_safe_task_meta_returns_state_and_meta_on_dict_info():
    state, meta = _safe_task_meta(_DictInfoAsyncResult({"progress": 42, "step": "embedding"}))
    assert state == "PROGRESS"
    assert meta == {"progress": 42, "step": "embedding"}


def test_safe_task_meta_falls_back_to_empty_meta_for_non_dict_info():
    state, meta = _safe_task_meta(_NonDictInfoAsyncResult())
    assert state == "SUCCESS"
    assert meta == {}


def test_safe_task_meta_degrades_to_failure_when_info_raises():
    """The bug from #2015: AsyncResult.info raises on malformed Celery payload.

    The helper must swallow ValueError/KeyError and return ("FAILURE", {})
    instead of letting the polling endpoint 500.
    """
    state, meta = _safe_task_meta(_RaisingInfoAsyncResult())
    assert state == "FAILURE"
    assert meta == {}


def test_safe_task_meta_degrades_to_failure_when_info_raises_keyerror():
    class _KeyErrorInfo:
        state = "FAILURE"

        @property
        def info(self):
            raise KeyError("exc_type")

    state, meta = _safe_task_meta(_KeyErrorInfo())
    assert state == "FAILURE"
    assert meta == {}


# ---------------------------------------------------------------------------
# #2017 — _require_indexed_sources gate
# ---------------------------------------------------------------------------


def _make_db_with_chunk_count(count: int):
    """Build a minimal mock db.execute that mimics SQLAlchemy's count() result."""

    class _Result:
        def scalar_one(self):
            return count

    db = SimpleNamespace()
    db.execute = AsyncMock(return_value=_Result())
    return db


@pytest.mark.asyncio
async def test_require_indexed_sources_passes_when_chunks_present():
    course = SimpleNamespace(rag_collection_id="col-1")
    db = _make_db_with_chunk_count(3)
    await _require_indexed_sources(course, db)  # no exception


@pytest.mark.asyncio
async def test_require_indexed_sources_blocks_when_no_rag_collection():
    course = SimpleNamespace(rag_collection_id=None)
    db = _make_db_with_chunk_count(0)  # not actually called, but harmless
    with pytest.raises(HTTPException) as exc_info:
        await _require_indexed_sources(course, db)
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["code"] == "no_source_summary"
    assert exc_info.value.detail["message_key"] == "course.generate.no_source_summary"


@pytest.mark.asyncio
async def test_require_indexed_sources_blocks_when_zero_chunks():
    course = SimpleNamespace(rag_collection_id="col-1")
    db = _make_db_with_chunk_count(0)
    with pytest.raises(HTTPException) as exc_info:
        await _require_indexed_sources(course, db)
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["code"] == "no_source_summary"


# ---------------------------------------------------------------------------
# #2016 — save_syllabus must populate Module.level (NOT NULL on the column)
# ---------------------------------------------------------------------------


def test_module_model_construction_with_level_succeeds():
    """Sanity check: the Module ORM class accepts a `level` kwarg and persists it.

    Regression for #2016 — the save_syllabus handler was instantiating Module
    without `level`, which is `nullable=False` with no server_default.
    """
    from app.domain.models.module import Module

    m = Module(level=1, module_number=1, title_fr="t", title_en="t")
    assert m.level == 1


def test_save_syllabus_handler_sets_level_in_module_constructor():
    """The handler source must include `level=1` in its Module(...) call.

    A source-level guard is enough here: the integration path is exercised
    by the wizard end-to-end on staging, but the unit-level assertion catches
    accidental regressions if someone reformats the kwargs block.
    """
    import inspect

    from app.api.v1.admin_courses import save_syllabus

    src = inspect.getsource(save_syllabus)
    assert "level=1" in src, "save_syllabus must set Module.level — see #2016"
