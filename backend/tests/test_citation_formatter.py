"""Tests for the read-side citation rewriter (#2168)."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.domain.services.citation_formatter import (
    _replace_uuid_prefix,
    _starts_with_uuid,
    humanize_filename,
    rewrite_uuid_citations_with_context,
    rewrite_uuid_in_source_dicts,
    rewrite_uuid_in_string,
)

_UUID = "bd2e9508-9b48-46f4-959c-14b682cba886"


def _make_resource(filename: str, parent_filename: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(filename=filename, parent_filename=parent_filename)


def _make_course(title_fr: str = "Statistiques de Santé Publique", title_en: str = "Public Health Statistics") -> SimpleNamespace:
    return SimpleNamespace(id="course-id", title_fr=title_fr, title_en=title_en)


class TestUUIDDetection:
    def test_detects_lowercase_uuid(self):
        assert _starts_with_uuid(f"{_UUID}, p.43")

    def test_detects_mixed_case_uuid(self):
        assert _starts_with_uuid("Bd2E9508-9B48-46F4-959C-14B682Cba886, p.43")

    def test_rejects_normal_text(self):
        assert not _starts_with_uuid("Donaldson Ch.4, p.67")
        assert not _starts_with_uuid("Triola, p.43")

    def test_rejects_empty(self):
        assert not _starts_with_uuid("")
        assert not _starts_with_uuid(None)  # type: ignore[arg-type]


class TestHumanizeFilename:
    def test_strips_extension_and_titlecases(self):
        assert humanize_filename("triola_chapter_3.pdf") == "Triola Chapter 3"

    def test_handles_dashes(self):
        assert humanize_filename("public-health-essentials.pdf") == "Public Health Essentials"

    def test_no_extension(self):
        assert humanize_filename("biology_textbook") == "Biology Textbook"

    def test_empty(self):
        assert humanize_filename("") == ""
        assert humanize_filename(None) == ""

    def test_keeps_unusually_long_extension(self):
        # Anything longer than 5 chars isn't treated as an extension.
        assert humanize_filename("file.archive_v2") == "File.Archive V2"


class TestReplaceUUIDPrefix:
    def test_replaces_uuid_with_label(self):
        s = f"{_UUID}, p.43"
        assert _replace_uuid_prefix(s, "Triola Chapter 3") == "Triola Chapter 3, p.43"

    def test_preserves_chapter_and_page(self):
        s = f"{_UUID} Ch.5, p.120"
        assert _replace_uuid_prefix(s, "Donaldson") == "Donaldson Ch.5, p.120"

    def test_passes_through_non_uuid(self):
        s = "Donaldson Ch.4, p.67"
        assert _replace_uuid_prefix(s, "Other") == s


class TestRewriteWithContext:
    def test_single_resource_uses_filename(self):
        course = _make_course()
        resources = [_make_resource("triola_chapter_3.pdf")]
        sources = [f"{_UUID}, p.43", f"{_UUID}, p.45"]
        result = rewrite_uuid_citations_with_context(sources, course, resources, "fr")
        assert result == ["Triola Chapter 3, p.43", "Triola Chapter 3, p.45"]

    def test_single_resource_prefers_parent_filename(self):
        course = _make_course()
        resources = [_make_resource("triola_part1.pdf", parent_filename="triola_full.pdf")]
        sources = [f"{_UUID}, p.43"]
        result = rewrite_uuid_citations_with_context(sources, course, resources, "fr")
        assert result == ["Triola Full, p.43"]

    def test_multi_resource_falls_back_to_course_title(self):
        course = _make_course()
        resources = [
            _make_resource("triola.pdf"),
            _make_resource("donaldson.pdf"),
        ]
        sources = [f"{_UUID}, p.43"]
        result = rewrite_uuid_citations_with_context(sources, course, resources, "fr")
        assert result == ["Statistiques de Santé Publique, p.43"]

    def test_english_uses_english_title(self):
        course = _make_course()
        resources = [_make_resource("a.pdf"), _make_resource("b.pdf")]
        result = rewrite_uuid_citations_with_context(
            [f"{_UUID}, p.43"], course, resources, "en"
        )
        assert result == ["Public Health Statistics, p.43"]

    def test_no_resources_no_course_keeps_input(self):
        result = rewrite_uuid_citations_with_context([f"{_UUID}, p.43"], None, [], "fr")
        assert result == [f"{_UUID}, p.43"]

    def test_legacy_named_source_passes_through(self):
        course = _make_course()
        resources = [_make_resource("triola.pdf")]
        result = rewrite_uuid_citations_with_context(
            ["Donaldson Ch.4, p.67"], course, resources, "fr"
        )
        assert result == ["Donaldson Ch.4, p.67"]

    def test_mixed_input_only_rewrites_uuid_entries(self):
        course = _make_course()
        resources = [_make_resource("triola.pdf")]
        result = rewrite_uuid_citations_with_context(
            [f"{_UUID}, p.43", "Donaldson Ch.4, p.67"], course, resources, "fr"
        )
        assert result == ["Triola, p.43", "Donaldson Ch.4, p.67"]

    def test_empty_returns_empty(self):
        assert rewrite_uuid_citations_with_context([], _make_course(), [], "fr") == []
        assert rewrite_uuid_citations_with_context(None, _make_course(), [], "fr") == []


class TestRewriteUUIDInString:
    def test_single_resource(self):
        course = _make_course()
        resources = [_make_resource("triola.pdf")]
        assert rewrite_uuid_in_string(f"{_UUID}, p.43", course, resources) == "Triola, p.43"

    def test_legacy_passes_through(self):
        assert rewrite_uuid_in_string("Donaldson", None, []) == "Donaldson"

    def test_none(self):
        assert rewrite_uuid_in_string(None, None, []) == ""


@pytest.mark.asyncio
class TestRewriteUUIDInSourceDicts:
    async def test_no_uuids_short_circuits(self):
        # Should not even hit the DB.
        sources = [{"source": "Donaldson", "page": 67}]
        session = MagicMock()
        result = await rewrite_uuid_in_source_dicts(sources, _make_course(), session, "fr")
        assert result == sources
        session.execute.assert_not_called()

    async def test_no_course_passes_through(self):
        sources = [{"source": _UUID, "page": 43}]
        session = MagicMock()
        result = await rewrite_uuid_in_source_dicts(sources, None, session, "fr")
        assert result == sources

    async def test_single_resource_rewrites_uuid_field(self):
        sources = [{"source": _UUID, "page": 43, "chapter": "3"}]

        course = _make_course()
        course.id = "course-uuid"

        # Build a fake async session whose execute() returns a result whose
        # .scalars().all() yields our resource list.
        from unittest.mock import AsyncMock

        scalars = MagicMock()
        scalars.all.return_value = [_make_resource("triola_chapter_3.pdf")]
        result_obj = MagicMock()
        result_obj.scalars.return_value = scalars
        session = MagicMock()
        session.execute = AsyncMock(return_value=result_obj)

        out = await rewrite_uuid_in_source_dicts(sources, course, session, "fr")
        assert out[0]["source"] == "Triola Chapter 3"
        assert out[0]["page"] == 43
        assert out[0]["chapter"] == "3"
