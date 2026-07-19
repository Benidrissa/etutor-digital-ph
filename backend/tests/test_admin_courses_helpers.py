"""Unit tests for admin_courses helpers introduced by #2015 / #2016 / #2017.

These exercise pure helpers with no DB or HTTP dependencies, sidestepping the
pytest-asyncio event-loop conflict that keeps the integration suite skipped
(see test_courses.py).
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api.v1 import admin_courses
from app.api.v1.admin_courses import (
    SuggestMetadataResponse,
    _build_metadata_source_context,
    _diagnose_indexation_pointer,
    _require_extracted_sources,
    _require_indexed_sources,
    _safe_task_meta,
    suggest_course_metadata,
)


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
# #2079 — _require_extracted_sources gate (raw_text-based, not chunk-based)
# ---------------------------------------------------------------------------


def _make_db_with_extracted_count(count: int):
    """Mock db.execute that returns a count for the extracted-resources query."""

    class _Result:
        def scalar_one(self):
            return count

    db = SimpleNamespace()
    db.execute = AsyncMock(return_value=_Result())
    return db


@pytest.mark.asyncio
async def test_require_extracted_sources_passes_when_raw_text_present():
    """Regression case for #2079: AI wizard reaches ai_proposal before Indexation.

    raw_text is populated by extract_course_resource at upload time (well before
    the dedicated Indexation step), so suggest-metadata / generate-structure /
    regenerate-syllabus must succeed even when DocumentChunk count is zero.
    """
    course = SimpleNamespace(id="course-1", rag_collection_id="col-1")
    db = _make_db_with_extracted_count(1)
    await _require_extracted_sources(course, db)  # no exception


@pytest.mark.asyncio
async def test_require_extracted_sources_blocks_when_no_extracted_text():
    course = SimpleNamespace(id="course-1", rag_collection_id="col-1")
    db = _make_db_with_extracted_count(0)
    with pytest.raises(HTTPException) as exc_info:
        await _require_extracted_sources(course, db)
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["code"] == "no_source_summary"
    assert exc_info.value.detail["message_key"] == "course.generate.no_source_summary"


@pytest.mark.asyncio
async def test_require_extracted_sources_query_filters_on_done_and_nonempty():
    """The SQL must filter on extraction_status=DONE AND length(raw_text) > 0.

    Source-level assertion catches accidental regressions if someone weakens
    the predicate (e.g. drops the length check, which would let
    extraction_status=DONE with empty raw_text slip through).
    """
    import inspect

    from app.api.v1 import admin_courses

    src = inspect.getsource(admin_courses._require_extracted_sources)
    assert "EXTRACTION_STATUS_DONE" in src
    assert "raw_text" in src
    assert "length" in src.lower()


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


# ---------------------------------------------------------------------------
# #2100 — _diagnose_indexation_pointer classifies stuck pointers
# ---------------------------------------------------------------------------


def _patch_async_result(monkeypatch, state: str, info):
    """Replace AsyncResult in admin_courses with a stub returning (state, info)."""

    class _Stub:
        def __init__(self, _task_id):
            self.state = state

        @property
        def info(self):
            return info

    monkeypatch.setattr("app.api.v1.admin_courses.AsyncResult", _Stub)


def test_diagnose_pointer_returns_stale_no_pointer_when_task_id_null():
    course = SimpleNamespace(indexation_task_id=None)
    verdict, state, meta = _diagnose_indexation_pointer(course, require_progress=False)
    assert verdict == "stale_no_pointer"
    assert state == ""
    assert meta == {}


def test_diagnose_pointer_returns_stale_terminal_for_success(monkeypatch):
    _patch_async_result(monkeypatch, "SUCCESS", {})
    course = SimpleNamespace(indexation_task_id="t-1")
    verdict, state, _meta = _diagnose_indexation_pointer(course, require_progress=False)
    assert verdict == "stale_terminal"
    assert state == "SUCCESS"


def test_diagnose_pointer_returns_stale_terminal_for_failure(monkeypatch):
    _patch_async_result(monkeypatch, "FAILURE", {})
    course = SimpleNamespace(indexation_task_id="t-1")
    verdict, state, _meta = _diagnose_indexation_pointer(course, require_progress=False)
    assert verdict == "stale_terminal"
    assert state == "FAILURE"


def test_diagnose_pointer_returns_stale_terminal_for_revoked(monkeypatch):
    _patch_async_result(monkeypatch, "REVOKED", {})
    course = SimpleNamespace(indexation_task_id="t-1")
    verdict, _state, _meta = _diagnose_indexation_pointer(course, require_progress=False)
    assert verdict == "stale_terminal"


def test_diagnose_pointer_evicted_pending_no_meta_trigger_path(monkeypatch):
    """Trigger endpoint (require_progress=False) clears evicted pointers even
    without indexed chunks/images — the admin's manual click is signal enough.
    """
    _patch_async_result(monkeypatch, "PENDING", {})
    course = SimpleNamespace(indexation_task_id="t-1")
    verdict, _state, _meta = _diagnose_indexation_pointer(course, require_progress=False)
    assert verdict == "stale_evicted"


def test_diagnose_pointer_evicted_status_path_requires_progress(monkeypatch):
    """Status endpoint (require_progress=True) needs durable evidence the
    task ran. PENDING+empty-meta with no chunks looks identical to a freshly
    enqueued task — hold the verdict at "live".
    """
    _patch_async_result(monkeypatch, "PENDING", {})
    course = SimpleNamespace(indexation_task_id="t-1")
    verdict, _state, _meta = _diagnose_indexation_pointer(
        course, require_progress=True, chunks_indexed=0, images_indexed=0
    )
    assert verdict == "live"


def test_diagnose_pointer_evicted_status_path_with_chunks(monkeypatch):
    _patch_async_result(monkeypatch, "PENDING", {})
    course = SimpleNamespace(indexation_task_id="t-1")
    verdict, _state, _meta = _diagnose_indexation_pointer(
        course, require_progress=True, chunks_indexed=42, images_indexed=0
    )
    assert verdict == "stale_evicted"


def test_diagnose_pointer_returns_live_for_started(monkeypatch):
    _patch_async_result(monkeypatch, "STARTED", {"step": "embedding"})
    course = SimpleNamespace(indexation_task_id="t-1")
    verdict, state, meta = _diagnose_indexation_pointer(course, require_progress=False)
    assert verdict == "live"
    assert state == "STARTED"
    assert meta == {"step": "embedding"}


def test_diagnose_pointer_returns_live_for_pending_with_meta(monkeypatch):
    """A freshly-enqueued task picked up by a worker reports PENDING but with
    meta. Don't treat it as evicted.
    """
    _patch_async_result(monkeypatch, "PENDING", {"progress": 5})
    course = SimpleNamespace(indexation_task_id="t-1")
    verdict, _state, _meta = _diagnose_indexation_pointer(course, require_progress=False)
    assert verdict == "live"


# ---- list_course_resources: per-source "really used" status (DB-driven) ----


class _ResourcesResult:
    """Scriptable stand-in for a SQLAlchemy Result across the endpoint's queries."""

    def __init__(self, *, scalar=None, scalars_all=None, rows=None):
        self._scalar = scalar
        self._scalars_all = scalars_all
        self._rows = rows

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        from unittest.mock import MagicMock

        inner = MagicMock()
        inner.all.return_value = self._scalars_all
        return inner

    def all(self):
        return self._rows


async def test_list_course_resources_reports_per_source_chunk_counts(tmp_path, monkeypatch):
    """DB-driven listing: resources missing from disk still appear, and each
    carries chunks_indexed (the "used in RAG" signal). A failed source shows
    chunks_indexed=0; an indexed source shows its count.
    """
    import uuid as _uuid
    from datetime import UTC, datetime
    from unittest.mock import AsyncMock

    from app.api.v1 import admin_courses
    from app.api.v1.admin_courses import list_course_resources

    course_id = _uuid.uuid4()
    used = SimpleNamespace(
        id=_uuid.uuid4(),
        filename="indexed_source",
        char_count=4200,
        extraction_status="done",
        extracted_at=datetime(2026, 6, 6, tzinfo=UTC),
    )
    dropped = SimpleNamespace(
        id=_uuid.uuid4(),
        filename="Donor_Alignment",  # uploaded as .PDF / file_not_found → not on disk
        char_count=None,
        extraction_status="failed",
        extracted_at=datetime(2026, 6, 6, tzinfo=UTC),
    )

    course = SimpleNamespace(id=course_id, rag_collection_id="rag-collection-1")

    db = SimpleNamespace()
    db.execute = AsyncMock(
        side_effect=[
            _ResourcesResult(scalar=course),  # SELECT Course
            _ResourcesResult(scalars_all=[used, dropped]),  # SELECT CourseResource
            _ResourcesResult(rows=[(used.id, 12)]),  # grouped chunk counts
        ]
    )

    # No files on disk → both resources still listed (DB-driven), on_disk False.
    monkeypatch.setattr(admin_courses, "UPLOAD_DIR", tmp_path)

    resp = await list_course_resources(course_id=course_id, current_user=None, db=db)

    by_id = {f["resource_id"]: f for f in resp["files"]}
    assert by_id[str(used.id)]["chunks_indexed"] == 12
    assert by_id[str(used.id)]["extraction_status"] == "done"
    assert by_id[str(dropped.id)]["chunks_indexed"] == 0
    assert by_id[str(dropped.id)]["extraction_status"] == "failed"
    assert by_id[str(dropped.id)]["on_disk"] is False
    # The dropped source is visible even though it has no file on disk.
    assert len(resp["files"]) == 2


# ---------------------------------------------------------------------------
# #2452 — suggest-metadata routes through the pluggable provider (not the
# Anthropic SDK), so non-Anthropic content models (e.g. Moonshot) work.
# ---------------------------------------------------------------------------


class _Result:
    def __init__(self, scalar=None, rows=None):
        self._scalar = scalar
        self._rows = rows or []

    def scalar_one_or_none(self):
        return self._scalar

    def __iter__(self):
        return iter(self._rows)


class _QueuedDB:
    """Async DB stub returning queued execute() results in order."""

    def __init__(self, results):
        self._results = list(results)

    async def execute(self, *args, **kwargs):
        return self._results.pop(0)


def _fake_course():
    return SimpleNamespace(
        languages="fr,en",
        objectives_json={"fr": ["Comprendre X"], "en": ["Understand X"]},
        taxonomy_categories=[SimpleNamespace(slug="public_health", type="domain")],
        estimated_hours=20,
    )


def _patch_model(monkeypatch, model: str):
    import app.domain.services.platform_settings_service as pss

    monkeypatch.setattr(
        pss.SettingsCache,
        "instance",
        staticmethod(lambda: SimpleNamespace(get=lambda k, d=None: model)),
    )


@pytest.mark.asyncio
async def test_suggest_metadata_routes_through_resolve_provider(monkeypatch):
    monkeypatch.setattr(admin_courses, "_require_extracted_sources", AsyncMock(return_value=None))
    _patch_model(monkeypatch, "moonshot-v1-128k")

    captured: dict = {}

    class _Provider:
        async def complete(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                text='{"title_fr": "Titre", "title_en": "Title", '
                '"description_fr": "Desc fr", "description_en": "Desc en"}',
                stop_reason="end_turn",
                usage={},
            )

    def _fake_resolve(model):
        captured["resolved_model"] = model
        return _Provider()

    monkeypatch.setattr("app.ai.providers.resolve_provider", _fake_resolve)

    db = _QueuedDB(
        [_Result(scalar=_fake_course()), _Result(rows=[("doc.pdf", "Some extracted text", None)])]
    )

    resp = await suggest_course_metadata(course_id=uuid.uuid4(), db=db)

    assert isinstance(resp, SuggestMetadataResponse)
    assert resp.title_fr == "Titre" and resp.description_en == "Desc en"
    # Routed through the configured (non-Anthropic) model via the provider, JSON mode on.
    assert captured["resolved_model"] == "moonshot-v1-128k"
    assert captured["model"] == "moonshot-v1-128k"
    assert captured["json_object"] is True


@pytest.mark.asyncio
async def test_suggest_metadata_missing_provider_key_returns_503(monkeypatch):
    monkeypatch.setattr(admin_courses, "_require_extracted_sources", AsyncMock(return_value=None))
    _patch_model(monkeypatch, "moonshot-v1-128k")

    def _raise(model):
        raise ValueError("MOONSHOT_API_KEY required for model 'moonshot-v1-128k'")

    monkeypatch.setattr("app.ai.providers.resolve_provider", _raise)

    db = _QueuedDB([_Result(scalar=_fake_course()), _Result(rows=[("doc.pdf", "text", None)])])

    with pytest.raises(HTTPException) as exc:
        await suggest_course_metadata(course_id=uuid.uuid4(), db=db)
    assert exc.value.status_code == 503


# ── _build_metadata_source_context (#2648) ──────────────────────────


def test_metadata_context_splits_budget_across_all_sources():
    resources = [
        ("cialdini.pdf", "A" * 650_000, None),
        ("mentaliste.pdf", "B" * 450_000, None),
        ("mindware.pdf", "C" * 670_000, None),
    ]
    ctx = _build_metadata_source_context(resources, budget=30_000)
    for name in ("cialdini.pdf", "mentaliste.pdf", "mindware.pdf"):
        assert f"### {name}" in ctx
    sections = ctx.split("\n\n---\n\n")
    assert len(sections) == 3
    # Each source got an equal slice; no single book crowds out the others.
    for section, letter in zip(sections, "ABC", strict=True):
        assert section.count(letter) == 10_000
    assert len(ctx) <= 30_000 + len("\n\n---\n\n") * 2 + sum(
        len(f"### {n}\n") for n, _, _ in resources
    )


def test_metadata_context_prefers_summary_over_raw_text():
    resources = [
        ("a.pdf", "RAW-A " * 100, "SUMMARY-A"),
        ("b.pdf", "RAW-B " * 100, None),
    ]
    ctx = _build_metadata_source_context(resources, budget=10_000)
    assert "SUMMARY-A" in ctx
    assert "RAW-A" not in ctx
    assert "RAW-B" in ctx


def test_metadata_context_skips_empty_resources():
    resources = [
        ("empty.pdf", None, None),
        ("blank.pdf", "", ""),
        ("real.pdf", "content here", None),
    ]
    ctx = _build_metadata_source_context(resources, budget=1_000)
    assert "### real.pdf" in ctx
    assert "empty.pdf" not in ctx and "blank.pdf" not in ctx
    # Sole usable source gets the whole budget, not budget // 3.
    assert "content here" in ctx


def test_metadata_context_empty_when_no_usable_sources():
    assert _build_metadata_source_context([]) == ""
    assert _build_metadata_source_context([("a.pdf", None, None)]) == ""


def test_metadata_context_single_source_gets_full_budget():
    ctx = _build_metadata_source_context([("book.pdf", "X" * 100_000, None)], budget=40_000)
    assert ctx.count("X") == 40_000
