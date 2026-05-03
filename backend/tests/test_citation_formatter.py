"""Tests for the read-side citation rewriter (#2168, #2178)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.services.citation_formatter import (
    _normalize_for_match,
    _parse_chapter_page,
    _replace_uuid_prefix,
    _starts_with_uuid,
    humanize_filename,
    rewrite_uuid_citations_for_module,
    rewrite_uuid_citations_with_context,
    rewrite_uuid_in_source_dicts,
    rewrite_uuid_in_string,
)

_UUID = "bd2e9508-9b48-46f4-959c-14b682cba886"


def _make_resource(
    filename: str,
    parent_filename: str | None = None,
    raw_text: str | None = None,
    rid: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        filename=filename,
        parent_filename=parent_filename,
        raw_text=raw_text,
        id=rid or filename,
    )


def _make_course(
    title_fr: str = "Statistiques de Santé Publique",
    title_en: str = "Public Health Statistics",
    rag_collection_id: str | None = "collection-1",
) -> SimpleNamespace:
    return SimpleNamespace(
        id="course-id",
        title_fr=title_fr,
        title_en=title_en,
        rag_collection_id=rag_collection_id,
        course_id="course-id",
    )


def _make_module(course_id: str = "course-id") -> SimpleNamespace:
    return SimpleNamespace(id="module-id", course_id=course_id)


def _make_chunk_row(
    chapter: str | None,
    page: int | None,
    content: str,
    chunk_id: str | None = None,
    course_resource_id: object | None = None,
) -> tuple:
    """Mimic an SQLAlchemy Row for the (id, chapter, page, content, course_resource_id) projection."""
    return (
        chunk_id or f"chunk-{chapter}-{page}",
        chapter,
        page,
        content,
        course_resource_id,
    )


class _FakeAsyncSession:
    """Minimal async session that replays scripted results.

    `gets` maps (model_name, key) -> returned object.
    `execute_results` is a queue of mock result objects yielded by execute().
    """

    def __init__(
        self,
        gets: dict[tuple[str, object], object] | None = None,
        execute_queue: list[object] | None = None,
    ):
        self._gets = gets or {}
        self._queue = list(execute_queue or [])
        self.execute_calls: list[object] = []

    async def get(self, model, key):
        return self._gets.get((model.__name__, str(key)))

    async def execute(self, stmt):
        self.execute_calls.append(stmt)
        if not self._queue:
            raise AssertionError("Unexpected execute() call — queue empty")
        return self._queue.pop(0)


def _scalar_result(items: list[object]) -> MagicMock:
    scalars = MagicMock()
    scalars.all.return_value = items
    result = MagicMock()
    result.scalars.return_value = scalars
    return result


def _row_result(rows: list[tuple]) -> MagicMock:
    result = MagicMock()
    result.all.return_value = rows
    return result


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

    # 8-char hex stem variants (#2174)
    def test_detects_8char_hex_with_chapter(self):
        assert _starts_with_uuid("E8883D1E Ch.1")

    def test_detects_8char_hex_with_page(self):
        assert _starts_with_uuid("F89C2931, p.43")

    def test_detects_8char_hex_alone(self):
        assert _starts_with_uuid("E8883D1E")

    def test_rejects_8char_word_followed_by_non_separator(self):
        # ``Donaldso`` (the first 8 chars of "Donaldson") contains 'o', 'n',
        # 'l', 's' which aren't hex, so it doesn't match anyway. But this
        # also guards against a hypothetical hex-shaped word that is
        # actually part of a longer identifier.
        assert not _starts_with_uuid("Cafebabexyz Ch.1")  # not separated
        assert not _starts_with_uuid("Donaldson")

    def test_rejects_seven_char_hex(self):
        assert not _starts_with_uuid("E8883D1 Ch.1")  # only 7 hex chars


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
        result = rewrite_uuid_citations_with_context([f"{_UUID}, p.43"], course, resources, "en")
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

    # 8-char hex variants (#2174)
    def test_rewrites_8char_hex_with_chapter(self):
        course = _make_course()
        resources = [_make_resource("triola.pdf")]
        result = rewrite_uuid_citations_with_context(["E8883D1E Ch.1"], course, resources, "fr")
        assert result == ["Triola Ch.1"]

    def test_rewrites_8char_hex_with_page(self):
        course = _make_course()
        resources = [_make_resource("triola.pdf")]
        result = rewrite_uuid_citations_with_context(["F89C2931, p.43"], course, resources, "fr")
        assert result == ["Triola, p.43"]

    def test_rewrites_mixed_full_and_short_uuids(self):
        course = _make_course()
        resources = [_make_resource("triola.pdf")]
        result = rewrite_uuid_citations_with_context(
            [f"{_UUID}, p.43", "E8883D1E Ch.1", "Donaldson, p.67"], course, resources, "fr"
        )
        assert result == ["Triola, p.43", "Triola Ch.1", "Donaldson, p.67"]


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


class TestParseChapterPage:
    def test_parses_chapter_and_page(self):
        assert _parse_chapter_page(f"{_UUID} Ch.3, p.43") == ("3", 43)

    def test_parses_page_only(self):
        assert _parse_chapter_page(f"{_UUID}, p.43") == (None, 43)

    def test_parses_chapter_only(self):
        assert _parse_chapter_page(f"{_UUID} Ch.5") == ("5", None)

    def test_handles_chapter_with_dot_or_colon(self):
        assert _parse_chapter_page(f"{_UUID} Ch.3.2, p.10") == ("3.2", 10)

    def test_returns_nones_when_neither_present(self):
        assert _parse_chapter_page("Donaldson") == (None, None)


class TestNormalizeForMatch:
    def test_collapses_whitespace_and_lowercases(self):
        normalized = _normalize_for_match("Hello   World\n\tBig.")
        assert "hello world" in normalized
        assert "big" in normalized

    def test_strips_page_noise(self):
        # Match what TextChunker._clean_text removes.
        normalized = _normalize_for_match("intro Page 12 body")
        assert "page" not in normalized
        assert "intro" in normalized and "body" in normalized


@pytest.mark.asyncio
class TestRewriteForModuleMultiResource:
    """Multi-PDF per-citation resolution for the lesson endpoint path."""

    async def test_multi_resource_resolves_per_citation(self):
        # Two PDFs, distinct content. Citations on (Ch.1, p.10) and
        # (Ch.2, p.20) — each chunk's content is a substring of exactly one
        # resource's raw_text.
        chunk_a_content = (
            "alpha textbook intro paragraph. " * 4
            + "unique alpha marker phrase one two three four five six. " * 4
        )
        chunk_b_content = (
            "beta handbook opening section. " * 4
            + "unique beta marker phrase one two three four five six. " * 4
        )
        pdf_a = _make_resource(
            "alpha_textbook.pdf",
            raw_text=chunk_a_content + " ... lots more alpha content ... " * 5,
            rid="rid-a",
        )
        pdf_b = _make_resource(
            "beta_textbook.pdf",
            raw_text=chunk_b_content + " ... lots more beta content ... " * 5,
            rid="rid-b",
        )
        course = _make_course()
        module = _make_module()

        session = _FakeAsyncSession(
            gets={
                ("Module", "module-id"): module,
                ("Course", "course-id"): course,
            },
            execute_queue=[
                _scalar_result([pdf_a, pdf_b]),
                _row_result(
                    [
                        _make_chunk_row("1", 10, chunk_a_content),
                        _make_chunk_row("2", 20, chunk_b_content),
                    ]
                ),
            ],
        )
        sources = [f"{_UUID} Ch.1, p.10", f"{_UUID} Ch.2, p.20"]
        out = await rewrite_uuid_citations_for_module(sources, "module-id", session, "fr")
        assert out == ["Alpha Textbook Ch.1, p.10", "Beta Textbook Ch.2, p.20"]

    async def test_unresolved_citation_falls_back_to_course_title(self):
        # Multi-resource course but the chunk SELECT returns nothing for one
        # of the (chapter, page) pairs — that single citation falls back to
        # course title; the other still resolves.
        pdf_a = _make_resource(
            "alpha_textbook.pdf",
            raw_text="alpha unique-fragment-A unique-fragment-A unique-fragment-A "
            + "unique-fragment-A " * 30,
            rid="rid-a",
        )
        pdf_b = _make_resource(
            "beta_textbook.pdf",
            raw_text="beta unique-fragment-B " + "unique-fragment-B " * 30,
            rid="rid-b",
        )
        course = _make_course()
        module = _make_module()

        chunk_a_content = "alpha unique-fragment-A unique-fragment-A unique-fragment-A " + (
            "unique-fragment-A " * 10
        )

        session = _FakeAsyncSession(
            gets={
                ("Module", "module-id"): module,
                ("Course", "course-id"): course,
            },
            execute_queue=[
                _scalar_result([pdf_a, pdf_b]),
                _row_result([_make_chunk_row("1", 10, chunk_a_content)]),
            ],
        )
        sources = [f"{_UUID} Ch.1, p.10", f"{_UUID} Ch.99, p.999"]
        out = await rewrite_uuid_citations_for_module(sources, "module-id", session, "fr")
        # First citation resolves to alpha, second falls back to course title.
        assert out[0] == "Alpha Textbook Ch.1, p.10"
        assert out[1] == "Statistiques de Santé Publique Ch.99, p.999"

    async def test_ambiguous_chunk_falls_back_to_course_title(self):
        # Boilerplate paragraph appears in both PDFs — chunk fingerprint
        # matches both resources. With no linked image text to break the tie,
        # the citation falls back to the course title.
        boilerplate = "this generic introduction paragraph " * 20
        pdf_a = _make_resource(
            "alpha_textbook.pdf",
            raw_text=boilerplate + "alpha-only " * 20,
            rid="rid-a",
        )
        pdf_b = _make_resource(
            "beta_textbook.pdf",
            raw_text=boilerplate + "beta-only " * 20,
            rid="rid-b",
        )
        course = _make_course()
        module = _make_module()

        session = _FakeAsyncSession(
            gets={
                ("Module", "module-id"): module,
                ("Course", "course-id"): course,
            },
            execute_queue=[
                _scalar_result([pdf_a, pdf_b]),
                _row_result([("chunk-amb-1", "1", 1, boilerplate, None)]),
                _row_result([]),  # no linked images for the deferred chunk
            ],
        )
        sources = [f"{_UUID} Ch.1, p.1"]
        out = await rewrite_uuid_citations_for_module(sources, "module-id", session, "fr")
        # Per-citation fallback to course title (no resource uniquely matches).
        assert out == ["Statistiques de Santé Publique Ch.1, p.1"]

    async def test_module_not_found_returns_input(self):
        session = _FakeAsyncSession(gets={}, execute_queue=[])
        sources = [f"{_UUID}, p.43"]
        out = await rewrite_uuid_citations_for_module(sources, "module-id", session, "fr")
        assert out == sources

    async def test_single_resource_path_unchanged(self):
        pdf_a = _make_resource("alpha_textbook.pdf", raw_text="x" * 500, rid="rid-a")
        course = _make_course()
        module = _make_module()
        # Only the resources query runs — no chunk SELECT for single-resource.
        session = _FakeAsyncSession(
            gets={
                ("Module", "module-id"): module,
                ("Course", "course-id"): course,
            },
            execute_queue=[_scalar_result([pdf_a])],
        )
        sources = [f"{_UUID}, p.43", f"{_UUID} Ch.2, p.50"]
        out = await rewrite_uuid_citations_for_module(sources, "module-id", session, "fr")
        assert out == ["Alpha Textbook, p.43", "Alpha Textbook Ch.2, p.50"]


@pytest.mark.asyncio
class TestFKFastPath:
    """Chunks with course_resource_id set bypass the fingerprint vote (#2186)."""

    async def test_fk_fast_path_resolves_directly(self):
        # Both PDFs would substring-match the chunk content (boilerplate),
        # but the FK on the chunk row is decisive.
        boilerplate = "shared paragraph " * 30
        pdf_a = _make_resource("alpha.pdf", raw_text=boilerplate, rid="rid-a")
        pdf_b = _make_resource("beta.pdf", raw_text=boilerplate, rid="rid-b")
        course = _make_course()
        module = _make_module()

        # FK -> rid-b (beta), even though substring vote would be ambiguous.
        chunk_row = _make_chunk_row("1", 5, boilerplate, course_resource_id="rid-b")

        session = _FakeAsyncSession(
            gets={
                ("Module", "module-id"): module,
                ("Course", "course-id"): course,
            },
            execute_queue=[
                _scalar_result([pdf_a, pdf_b]),
                _row_result([chunk_row]),
            ],
        )
        sources = [f"{_UUID} Ch.1, p.5"]
        out = await rewrite_uuid_citations_for_module(sources, "module-id", session, "fr")
        assert out == ["Beta Ch.1, p.5"]

    async def test_null_fk_falls_back_to_fingerprint(self):
        # Chunk content matches PDF A uniquely; FK is NULL → fingerprint
        # path resolves it to A.
        pdf_a = _make_resource(
            "alpha.pdf",
            raw_text="alpha-content " + "fingerprint-A " * 30,
            rid="rid-a",
        )
        pdf_b = _make_resource(
            "beta.pdf",
            raw_text="beta-content " + "fingerprint-B " * 30,
            rid="rid-b",
        )
        course = _make_course()
        module = _make_module()
        chunk_content = "alpha-content " + "fingerprint-A " * 15
        chunk_row = _make_chunk_row("1", 5, chunk_content, course_resource_id=None)

        session = _FakeAsyncSession(
            gets={
                ("Module", "module-id"): module,
                ("Course", "course-id"): course,
            },
            execute_queue=[
                _scalar_result([pdf_a, pdf_b]),
                _row_result([chunk_row]),
            ],
        )
        sources = [f"{_UUID} Ch.1, p.5"]
        out = await rewrite_uuid_citations_for_module(sources, "module-id", session, "fr")
        assert out == ["Alpha Ch.1, p.5"]

    async def test_fk_dangling_falls_back_to_fingerprint(self):
        # FK references a resource id that's no longer in the loaded list
        # (ON DELETE SET NULL would normally NULL the column, but defend
        # against the transient state). Multi-resource course so the chunk
        # SELECT still runs.
        pdf_a = _make_resource(
            "alpha.pdf",
            raw_text="alpha-content " + "fingerprint-A " * 30,
            rid="rid-a",
        )
        pdf_b = _make_resource(
            "beta.pdf",
            raw_text="beta-content " + "fingerprint-B " * 30,
            rid="rid-b",
        )
        course = _make_course()
        module = _make_module()
        chunk_content = "alpha-content " + "fingerprint-A " * 15

        session = _FakeAsyncSession(
            gets={
                ("Module", "module-id"): module,
                ("Course", "course-id"): course,
            },
            execute_queue=[
                _scalar_result([pdf_a, pdf_b]),
                _row_result(
                    [_make_chunk_row("1", 5, chunk_content, course_resource_id="rid-deleted")]
                ),
            ],
        )
        sources = [f"{_UUID} Ch.1, p.5"]
        out = await rewrite_uuid_citations_for_module(sources, "module-id", session, "fr")
        # FK is dangling → falls through to fingerprint vote → resolves to A.
        assert out == ["Alpha Ch.1, p.5"]


@pytest.mark.asyncio
class TestImageTiebreaker:
    """When chunk content matches multiple resources, ``SourceImage.surrounding_text``
    breaks ties (#2181)."""

    async def test_surrounding_text_breaks_tie(self):
        # Both PDFs share a paragraph (boilerplate). Chunk content matches
        # both. But a linked SourceImage's surrounding_text appears in only
        # one — that's the winner.
        boilerplate = "shared header paragraph " * 30
        pdf_a_unique = "alpha-only specific marker " * 20
        pdf_b_unique = "beta-only specific marker " * 20
        pdf_a = _make_resource(
            "alpha.pdf",
            raw_text=boilerplate + pdf_a_unique,
            rid="rid-a",
        )
        pdf_b = _make_resource(
            "beta.pdf",
            raw_text=boilerplate + pdf_b_unique,
            rid="rid-b",
        )
        course = _make_course()
        module = _make_module()

        chunk_id = "chunk-1"
        # Chunk content == boilerplate, so it matches BOTH resources.
        chunk_row = (chunk_id, "1", 5, boilerplate, None)
        # Linked surrounding_text contains alpha-specific marker → unique to A.
        img_row = (chunk_id, "alpha-only specific marker " * 5)

        session = _FakeAsyncSession(
            gets={
                ("Module", "module-id"): module,
                ("Course", "course-id"): course,
            },
            execute_queue=[
                _scalar_result([pdf_a, pdf_b]),
                _row_result([chunk_row]),
                _row_result([img_row]),
            ],
        )
        sources = [f"{_UUID} Ch.1, p.5"]
        out = await rewrite_uuid_citations_for_module(sources, "module-id", session, "fr")
        assert out == ["Alpha Ch.1, p.5"]

    async def test_no_image_keeps_ambiguous_fallback(self):
        # Chunk content matches both resources, no linked image → still
        # ambiguous, falls back to course title.
        boilerplate = "shared header paragraph " * 30
        pdf_a = _make_resource("alpha.pdf", raw_text=boilerplate + "x" * 200, rid="rid-a")
        pdf_b = _make_resource("beta.pdf", raw_text=boilerplate + "y" * 200, rid="rid-b")
        course = _make_course()
        module = _make_module()

        chunk_row = ("chunk-1", "1", 5, boilerplate, None)

        session = _FakeAsyncSession(
            gets={
                ("Module", "module-id"): module,
                ("Course", "course-id"): course,
            },
            execute_queue=[
                _scalar_result([pdf_a, pdf_b]),
                _row_result([chunk_row]),
                _row_result([]),  # no linked images
            ],
        )
        sources = [f"{_UUID} Ch.1, p.5"]
        out = await rewrite_uuid_citations_for_module(sources, "module-id", session, "fr")
        assert out == ["Statistiques de Santé Publique Ch.1, p.5"]

    async def test_image_text_ambiguous_keeps_fallback(self):
        # Chunk content + linked image text both match multiple resources →
        # still ambiguous, falls back.
        boilerplate = "shared header paragraph " * 30
        pdf_a = _make_resource("alpha.pdf", raw_text=boilerplate + "alpha-x " * 50, rid="rid-a")
        pdf_b = _make_resource("beta.pdf", raw_text=boilerplate + "beta-y " * 50, rid="rid-b")
        course = _make_course()
        module = _make_module()

        chunk_row = ("chunk-1", "1", 5, boilerplate, None)
        img_row = ("chunk-1", boilerplate)  # surrounding_text is also shared

        session = _FakeAsyncSession(
            gets={
                ("Module", "module-id"): module,
                ("Course", "course-id"): course,
            },
            execute_queue=[
                _scalar_result([pdf_a, pdf_b]),
                _row_result([chunk_row]),
                _row_result([img_row]),
            ],
        )
        sources = [f"{_UUID} Ch.1, p.5"]
        out = await rewrite_uuid_citations_for_module(sources, "module-id", session, "fr")
        assert out == ["Statistiques de Santé Publique Ch.1, p.5"]


@pytest.mark.asyncio
class TestRewriteUUIDInSourceDictsMultiResource:
    """Multi-PDF per-dict resolution for the tutor citation path."""

    async def test_multi_resource_per_dict_resolution(self):
        pdf_a = _make_resource(
            "alpha.pdf",
            raw_text="alpha-content " + "fingerprint-A " * 30,
            rid="rid-a",
        )
        pdf_b = _make_resource(
            "beta.pdf",
            raw_text="beta-content " + "fingerprint-B " * 30,
            rid="rid-b",
        )
        course = _make_course()

        chunk_a_content = "alpha-content " + "fingerprint-A " * 15
        chunk_b_content = "beta-content " + "fingerprint-B " * 15

        session = _FakeAsyncSession(
            gets={},
            execute_queue=[
                _scalar_result([pdf_a, pdf_b]),
                _row_result(
                    [
                        _make_chunk_row("1", 5, chunk_a_content),
                        _make_chunk_row("2", 7, chunk_b_content),
                    ]
                ),
            ],
        )
        sources = [
            {"source": _UUID, "chapter": "1", "page": 5},
            {"source": _UUID, "chapter": "2", "page": 7},
        ]
        out = await rewrite_uuid_in_source_dicts(sources, course, session, "fr")
        assert out[0]["source"] == "Alpha"
        assert out[1]["source"] == "Beta"
