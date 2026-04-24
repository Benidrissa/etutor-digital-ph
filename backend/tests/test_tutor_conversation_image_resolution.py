"""Unit tests for the source_image-marker resolution used by get_conversation (#1937).

Uses a mocked async session because the integration db_session fixture is
blocked on #554 (create_all vs Alembic enum types). The helpers under test
are pure: they only call ``session.execute`` with a SELECT and shape results.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.services.tutor_service import (
    _attach_source_image_refs,
    _resolve_source_images_by_uuid,
)


def _fake_source_image(
    image_id: uuid.UUID,
    figure_number: int = 1,
    caption: str = "A figure",
) -> SimpleNamespace:
    """Minimal stand-in for ``SourceImage`` with a ``.to_meta_dict()`` method."""
    return SimpleNamespace(
        id=image_id,
        to_meta_dict=lambda: {
            "figure_number": figure_number,
            "caption": caption,
            "caption_fr": caption,
            "caption_en": caption,
            "attribution": "Donaldson Ch. 10",
            "image_type": "photo",
            "storage_url": "https://minio/bucket/x.png",
            "storage_url_fr": None,
            "alt_text_fr": caption,
            "alt_text_en": caption,
        },
    )


def _mock_session_returning(images: list) -> MagicMock:
    """Build an AsyncSession mock whose .execute returns a Result containing images."""
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=images)
    result = MagicMock()
    result.scalars = MagicMock(return_value=scalars)
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    return session


class TestResolveByUuid:
    async def test_empty_uuids_skips_db(self):
        session = MagicMock()
        session.execute = AsyncMock()
        out = await _resolve_source_images_by_uuid(set(), session)
        assert out == {}
        session.execute.assert_not_awaited()

    async def test_returns_map_keyed_on_uuid_string(self):
        img_id = uuid.UUID("7a49d4fd-cbf6-4adb-b5eb-b770b2a00a88")
        session = _mock_session_returning([_fake_source_image(img_id, figure_number=7)])

        out = await _resolve_source_images_by_uuid({str(img_id)}, session)

        assert set(out.keys()) == {str(img_id)}
        entry = out[str(img_id)]
        assert entry["id"] == str(img_id)
        assert entry["figure_number"] == 7
        assert entry["storage_url"] == "https://minio/bucket/x.png"

    async def test_missing_uuids_are_silently_dropped(self):
        found = uuid.UUID("7a49d4fd-cbf6-4adb-b5eb-b770b2a00a88")
        missing = "00000000-0000-0000-0000-000000000000"
        session = _mock_session_returning([_fake_source_image(found)])

        out = await _resolve_source_images_by_uuid({str(found), missing}, session)

        assert str(found) in out
        assert missing not in out

    async def test_db_error_returns_empty_map(self):
        session = MagicMock()
        session.execute = AsyncMock(side_effect=RuntimeError("connection lost"))

        out = await _resolve_source_images_by_uuid(
            {"7a49d4fd-cbf6-4adb-b5eb-b770b2a00a88"}, session
        )

        assert out == {}


class TestAttachRefs:
    async def test_user_messages_untouched(self):
        session = _mock_session_returning([])
        messages = [
            {
                "role": "user",
                "content": "Please show a figure.",
                "timestamp": "2026-04-24T00:00:00",
            },
        ]
        out = await _attach_source_image_refs(messages, session)
        assert "source_image_refs" not in out[0]
        # No marker anywhere → no DB query at all.
        session.execute.assert_not_awaited()

    async def test_assistant_without_markers_untouched(self):
        session = _mock_session_returning([])
        messages = [
            {
                "role": "assistant",
                "content": "Just text, no markers here.",
                "timestamp": "2026-04-24T00:00:00",
            }
        ]
        out = await _attach_source_image_refs(messages, session)
        assert "source_image_refs" not in out[0]

    async def test_single_marker_attaches_ref(self):
        img_id = uuid.UUID("7a49d4fd-cbf6-4adb-b5eb-b770b2a00a88")
        session = _mock_session_returning([_fake_source_image(img_id)])
        messages = [
            {
                "role": "assistant",
                "content": f"See figure: {{{{source_image:{img_id}}}}}",
                "timestamp": "2026-04-24T00:00:00",
            }
        ]
        out = await _attach_source_image_refs(messages, session)
        refs = out[0]["source_image_refs"]
        assert len(refs) == 1
        assert refs[0]["id"] == str(img_id)

    async def test_duplicate_uuid_in_same_message_deduplicated(self):
        img_id = uuid.UUID("7a49d4fd-cbf6-4adb-b5eb-b770b2a00a88")
        session = _mock_session_returning([_fake_source_image(img_id)])
        marker = f"{{{{source_image:{img_id}}}}}"
        messages = [
            {
                "role": "assistant",
                "content": f"Look: {marker}. Compare to: {marker}",
                "timestamp": "2026-04-24T00:00:00",
            }
        ]
        out = await _attach_source_image_refs(messages, session)
        assert len(out[0]["source_image_refs"]) == 1

    async def test_multiple_messages_share_one_batched_query(self):
        a_id = uuid.UUID("7a49d4fd-cbf6-4adb-b5eb-b770b2a00a88")
        b_id = uuid.UUID("11111111-2222-3333-4444-555555555555")
        session = _mock_session_returning(
            [_fake_source_image(a_id, figure_number=1), _fake_source_image(b_id, figure_number=2)]
        )
        messages = [
            {
                "role": "assistant",
                "content": f"First: {{{{source_image:{a_id}}}}}",
                "timestamp": "2026-04-24T00:00:00",
            },
            {"role": "user", "content": "cool", "timestamp": "2026-04-24T00:00:01"},
            {
                "role": "assistant",
                "content": f"And also both: {{{{source_image:{a_id}}}}} and {{{{source_image:{b_id}}}}}",
                "timestamp": "2026-04-24T00:00:02",
            },
        ]
        out = await _attach_source_image_refs(messages, session)
        # One DB round-trip for the union of UUIDs.
        assert session.execute.await_count == 1
        assert [r["id"] for r in out[0]["source_image_refs"]] == [str(a_id)]
        assert "source_image_refs" not in out[1]
        assert [r["id"] for r in out[2]["source_image_refs"]] == [str(a_id), str(b_id)]

    async def test_does_not_mutate_input(self):
        img_id = uuid.UUID("7a49d4fd-cbf6-4adb-b5eb-b770b2a00a88")
        session = _mock_session_returning([_fake_source_image(img_id)])
        original = {
            "role": "assistant",
            "content": f"See: {{{{source_image:{img_id}}}}}",
            "timestamp": "2026-04-24T00:00:00",
        }
        await _attach_source_image_refs([original], session)
        assert "source_image_refs" not in original

    @pytest.mark.parametrize(
        "marker",
        [
            "{{source_image:7A49D4FD-CBF6-4ADB-B5EB-B770B2A00A88}}",  # upper-case
            "{{Source_Image:7a49d4fd-cbf6-4adb-b5eb-b770b2a00a88}}",  # mixed case label
        ],
    )
    async def test_case_insensitive_matching(self, marker: str):
        img_id = uuid.UUID("7a49d4fd-cbf6-4adb-b5eb-b770b2a00a88")
        session = _mock_session_returning([_fake_source_image(img_id)])
        messages = [
            {
                "role": "assistant",
                "content": f"Figure: {marker}",
                "timestamp": "2026-04-24T00:00:00",
            }
        ]
        out = await _attach_source_image_refs(messages, session)
        assert out[0]["source_image_refs"][0]["id"] == str(img_id)
