"""Unit tests for the unreadable-image purge (#2540).

Covers ``_run_unreadable_purge_with_factory`` directly so no engine/DB is
needed. Unlike the sibling purges the verdict is content-based, so a fake
storage returns real image bytes per key and the task runs the same
``assess_readability`` check used at extraction time.
"""

from __future__ import annotations

import io
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image, ImageDraw

from app.domain.models.source_image import SourceImage
from app.tasks.image_indexation import _run_unreadable_purge_with_factory


def _blank_png() -> bytes:
    buf = io.BytesIO()
    Image.new("L", (256, 256), 255).save(buf, format="PNG")
    return buf.getvalue()


def _readable_png() -> bytes:
    img = Image.new("L", (256, 256), 255)
    draw = ImageDraw.Draw(img)
    draw.rectangle((40, 40, 120, 90), outline=0, width=2)
    draw.line((120, 65, 180, 65), fill=0, width=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_row(**overrides) -> MagicMock:
    img = MagicMock(spec=SourceImage)
    img.id = overrides.get("id", uuid.uuid4())
    img.rag_collection_id = overrides.get("rag_collection_id", "col-1")
    img.page_number = overrides.get("page_number", 12)
    img.figure_number = overrides.get("figure_number", "Figure 1.1")
    img.width = overrides.get("width", 256)
    img.height = overrides.get("height", 256)
    img.storage_key = overrides["storage_key"]
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


def _storage_for(content: dict[str, bytes]) -> AsyncMock:
    storage = AsyncMock()
    storage.download_bytes = AsyncMock(side_effect=lambda key: content[key])
    storage.delete_object = AsyncMock()
    return storage


@pytest.mark.asyncio
async def test_dry_run_flags_only_unreadable():
    rows = [
        _make_row(storage_key="blank.webp"),
        _make_row(storage_key="ok.webp"),
    ]
    factory, session = _factory_returning(rows)
    storage = _storage_for({"blank.webp": _blank_png(), "ok.webp": _readable_png()})

    result = await _run_unreadable_purge_with_factory(
        rag_collection_id=None,
        limit=None,
        dry_run=True,
        session_factory=factory,
        storage=storage,
    )

    assert result["status"] == "dry_run"
    assert result["scanned"] == 2
    assert result["unreadable"] == 1
    assert len(result["preview"]) == 1
    assert result["preview"][0]["storage_key"] == "blank.webp"
    assert result["preview"][0]["reason"].startswith("blank")
    session.delete.assert_not_called()
    storage.delete_object.assert_not_awaited()


@pytest.mark.asyncio
async def test_real_run_deletes_only_unreadable():
    rows = [
        _make_row(storage_key="blank.webp", storage_key_fr="blank_fr.svg"),
        _make_row(storage_key="ok.webp"),
    ]
    factory, session = _factory_returning(rows)
    storage = _storage_for({"blank.webp": _blank_png(), "ok.webp": _readable_png()})

    result = await _run_unreadable_purge_with_factory(
        rag_collection_id="col-1",
        limit=None,
        dry_run=False,
        session_factory=factory,
        storage=storage,
    )

    assert result["status"] == "complete"
    assert result["scanned"] == 2
    assert result["unreadable"] == 1
    assert result["deleted"] == 1
    # Only the blank row's objects are removed: blank.webp + blank_fr.svg.
    assert storage.delete_object.await_count == 2
    session.delete.assert_awaited_once()
    session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_download_failure_is_skipped_not_deleted():
    rows = [_make_row(storage_key="gone.webp")]
    factory, session = _factory_returning(rows)
    storage = AsyncMock()
    storage.download_bytes = AsyncMock(side_effect=ConnectionError("MinIO down"))
    storage.delete_object = AsyncMock()

    result = await _run_unreadable_purge_with_factory(
        rag_collection_id=None,
        limit=None,
        dry_run=False,
        session_factory=factory,
        storage=storage,
    )

    assert result["download_failed"] == 1
    assert result["unreadable"] == 0
    assert result["deleted"] == 0
    session.delete.assert_not_called()
