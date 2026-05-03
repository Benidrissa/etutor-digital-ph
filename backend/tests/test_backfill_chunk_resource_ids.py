"""Tests for the backfill helpers in ``scripts/backfill_chunk_resource_ids.py`` (#2190).

We exercise the resolution logic via ``_backfill_course``'s normalization +
fingerprint-match path with a fake async session that scripts the SQL
results. No real DB needed.
"""

from __future__ import annotations

import importlib.util
import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# Load the script as a module since it lives outside ``tests/``.
_SCRIPT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "scripts", "backfill_chunk_resource_ids.py"
)
spec = importlib.util.spec_from_file_location("backfill_chunk_resource_ids", _SCRIPT_PATH)
backfill_module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(backfill_module)


_normalize_for_match = backfill_module._normalize_for_match
_backfill_course = backfill_module._backfill_course


def _result(rows: list[tuple]) -> MagicMock:
    out = MagicMock()
    out.all.return_value = rows
    return out


@pytest.mark.asyncio
async def test_normalize_matches_chunk_against_raw_text():
    raw_text = "Quick brown fox the cat sat on the mat. " + ("alpha " * 100)
    chunk = "Quick brown fox the cat sat on the mat. " + ("alpha " * 50)
    fingerprint = _normalize_for_match(chunk)[:200]
    assert fingerprint in _normalize_for_match(raw_text)


@pytest.mark.asyncio
async def test_skips_single_resource_courses():
    # Single resource → nothing to disambiguate; script returns immediately.
    session = MagicMock()
    session.execute = AsyncMock(return_value=_result([("rid-a", "any text")]))
    scanned, updated, ambiguous = await _backfill_course(
        session, "course-1", "rag-1", dry_run=False
    )
    assert (scanned, updated, ambiguous) == (0, 0, 0)


@pytest.mark.asyncio
async def test_unique_match_updates_chunk():
    pdf_a_text = "alpha-only specific text " * 30
    pdf_b_text = "beta-only specific text " * 30
    chunk_id = "chunk-1"
    chunk_content = "alpha-only specific text " * 15

    session = MagicMock()
    # Sequence of execute() calls:
    #   1. SELECT resources
    #   2. SELECT chunks
    #   3. UPDATE for the resolved resource (only when not dry_run)
    update_call: list[Any] = []

    async def fake_execute(stmt, params=None):
        sql_str = str(stmt)
        if "FROM course_resources" in sql_str:
            return _result([("rid-a", pdf_a_text), ("rid-b", pdf_b_text)])
        if "FROM document_chunks" in sql_str:
            return _result([(chunk_id, chunk_content)])
        if sql_str.startswith("UPDATE") or "UPDATE" in sql_str:
            update_call.append(params)
            return MagicMock()
        raise AssertionError(f"unexpected SQL: {sql_str}")

    session.execute = AsyncMock(side_effect=fake_execute)
    session.commit = AsyncMock()

    scanned, updated, ambiguous = await _backfill_course(
        session, "course-1", "rag-1", dry_run=False
    )
    assert scanned == 1
    assert updated == 1
    assert ambiguous == 0
    assert len(update_call) == 1
    assert update_call[0]["rid"] == "rid-a"
    assert update_call[0]["ids"] == [chunk_id]
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_ambiguous_chunk_left_null():
    # Chunk content is shared boilerplate that appears in BOTH resources.
    boilerplate = "shared header paragraph " * 30
    pdf_a_text = boilerplate + "alpha unique " * 20
    pdf_b_text = boilerplate + "beta unique " * 20

    session = MagicMock()
    update_call: list[Any] = []

    async def fake_execute(stmt, params=None):
        sql_str = str(stmt)
        if "FROM course_resources" in sql_str:
            return _result([("rid-a", pdf_a_text), ("rid-b", pdf_b_text)])
        if "FROM document_chunks" in sql_str:
            return _result([("chunk-amb", boilerplate)])
        if "UPDATE" in sql_str:
            update_call.append(params)
            return MagicMock()
        raise AssertionError(f"unexpected SQL: {sql_str}")

    session.execute = AsyncMock(side_effect=fake_execute)
    session.commit = AsyncMock()

    scanned, updated, ambiguous = await _backfill_course(
        session, "course-1", "rag-1", dry_run=False
    )
    assert scanned == 1
    assert updated == 0
    assert ambiguous == 1
    assert update_call == []  # no UPDATE issued
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_dry_run_does_not_write():
    pdf_a_text = "alpha-only specific text " * 30
    pdf_b_text = "beta-only specific text " * 30
    chunk_content = "alpha-only specific text " * 15

    session = MagicMock()
    update_call: list[Any] = []

    async def fake_execute(stmt, params=None):
        sql_str = str(stmt)
        if "FROM course_resources" in sql_str:
            return _result([("rid-a", pdf_a_text), ("rid-b", pdf_b_text)])
        if "FROM document_chunks" in sql_str:
            return _result([("chunk-1", chunk_content)])
        if "UPDATE" in sql_str:
            update_call.append(params)
            return MagicMock()
        raise AssertionError(f"unexpected SQL: {sql_str}")

    session.execute = AsyncMock(side_effect=fake_execute)
    session.commit = AsyncMock()

    scanned, updated, ambiguous = await _backfill_course(session, "course-1", "rag-1", dry_run=True)
    assert scanned == 1
    assert updated == 1  # would update
    assert ambiguous == 0
    assert update_call == []  # but didn't actually
    session.commit.assert_not_awaited()
