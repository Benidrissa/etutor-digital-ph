"""Unit tests for the body-text figure purge (#2431).

Covers ``_run_body_text_purge_with_factory`` directly so no engine/DB is
needed — the SQL ``WHERE figure_kind = 'body_text'`` predicate itself is
enforced by Postgres; here we verify the dry-run preview and the
delete-from-storage-then-DB behaviour on the rows the query returns.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.models.source_image import SourceImage
from app.tasks.image_indexation import _run_body_text_purge_with_factory


def _make_row(**overrides) -> MagicMock:
    img = MagicMock(spec=SourceImage)
    img.id = overrides.get("id", uuid.uuid4())
    img.rag_collection_id = overrides.get("rag_collection_id", "col-1")
    img.page_number = overrides.get("page_number", 97)
    img.figure_number = overrides.get("figure_number", "Figure 3.2")
    img.figure_kind = "body_text"
    img.width = overrides.get("width", 1024)
    img.height = overrides.get("height", 682)
    img.storage_key = overrides.get("storage_key", "source-images/col-1/x.webp")
    img.storage_key_fr = overrides.get("storage_key_fr")
    return img


def _factory_returning(rows: list):
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.delete = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    session.execute = AsyncMock(return_value=result)

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=cm), session


@pytest.mark.asyncio
async def test_dry_run_counts_without_deleting():
    rows = [_make_row(), _make_row()]
    factory, session = _factory_returning(rows)
    storage = AsyncMock()

    result = await _run_body_text_purge_with_factory(
        rag_collection_id=None,
        limit=None,
        dry_run=True,
        session_factory=factory,
        storage=storage,
    )

    assert result["status"] == "dry_run"
    assert result["eligible"] == 2
    assert len(result["preview"]) == 2
    assert result["preview"][0]["figure_kind"] == "body_text"
    session.delete.assert_not_called()
    storage.delete_object.assert_not_awaited()


@pytest.mark.asyncio
async def test_real_run_deletes_rows_and_objects():
    rows = [
        _make_row(storage_key="a.webp", storage_key_fr="a_fr.svg"),
        _make_row(storage_key="b.webp", storage_key_fr=None),
    ]
    factory, session = _factory_returning(rows)
    storage = AsyncMock()

    result = await _run_body_text_purge_with_factory(
        rag_collection_id="col-1",
        limit=None,
        dry_run=False,
        session_factory=factory,
        storage=storage,
    )

    assert result["status"] == "complete"
    assert result["deleted"] == 2
    assert result["storage_failed"] == 0
    assert session.delete.await_count == 2
    # a.webp + a_fr.svg + b.webp = 3 object deletes (b has no FR variant)
    assert storage.delete_object.await_count == 3
    session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_storage_failure_does_not_block_db_delete():
    rows = [_make_row(storage_key="boom.webp", storage_key_fr=None)]
    factory, session = _factory_returning(rows)
    storage = AsyncMock()
    storage.delete_object = AsyncMock(side_effect=ConnectionError("MinIO down"))

    result = await _run_body_text_purge_with_factory(
        rag_collection_id=None,
        limit=None,
        dry_run=False,
        session_factory=factory,
        storage=storage,
    )

    assert result["deleted"] == 1
    assert result["storage_failed"] == 1
    session.delete.assert_awaited_once()
    session.commit.assert_awaited()
