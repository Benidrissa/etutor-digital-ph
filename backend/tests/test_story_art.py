"""Tests for story-mode cartoon art (#2675): looks, planning, drawing, serving.

Every image call is a fake and Redis is a fake: these tests never reach a paid
API. The one test that needs PostgreSQL makes a scratch database (like the
other story tests) and is skipped when no server is reachable.
"""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import io
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from openai.resources.images import AsyncImages
from PIL import Image

from app.ai.providers.image_provider import (
    GeminiImageProvider,
    ImageCapabilityError,
    OpenAIImageProvider,
    edit_image,
    generate_image,
)
from app.api.deps import get_db
from app.api.deps_local_auth import (
    AuthenticatedUser,
    get_current_user,
    require_subscription_or_free_module,
)
from app.api.v1 import story_courses as api
from app.domain.models.story_art import CHARACTER_POSES, StoryArt
from app.domain.services import story_art_service as svc
from app.domain.services.image_service import PEOPLE_CONSTRAINT
from app.domain.services.story_art_service import (
    BACKDROP_SIZE,
    CHARACTER_SIZE,
    MAX_CHARACTER_HEIGHT,
    MAX_IMAGES_PER_RUN,
    POSE_CHANGES,
    STYLE_LINE,
    ArtItem,
    ArtJob,
    ArtProcessingError,
    StoryArtGenerator,
    apply_cap,
    build_art_map,
    character_prompt,
    collect_looks,
    look_digest,
    place_prompt,
    plan_art,
    pose_prompt,
    process_backdrop,
    process_character,
    stored_reference,
)
from app.main import app
from app.tasks import story_art as story_art_task
from app.tasks.story_art import STORY_ART_DISPATCH_TTL_S, story_art_dispatch_key

COURSE_ID = uuid.UUID("5c0a8b7e-1d2f-4e3a-9b8c-7d6e5f4a3b2c")
MODULE_ID = uuid.UUID("7a6b5c4d-3e2f-4a1b-9c8d-7e6f5a4b3c2d")

#: A story document with the course bible (#2674): a hero with two variants,
#: two other cast members with looks, one without (an old cast entry), places.
DOC: dict[str, Any] = {
    "format": "story-course/1",
    "id": f"module-{MODULE_ID.hex}-fr",
    "cast": [
        {
            "id": "hero",
            "role": "hero",
            "name": "{child}",
            "variants": [
                {"id": "girl", "look": "girl look: a 9-year-old girl in a school uniform"},
                {"id": "boy", "look": "boy look: a 9-year-old boy in a school uniform"},
            ],
        },
        {"id": "mentor", "role": "mentor", "look": "mentor look: a teacher in a blue shirt"},
        {"id": "margo", "role": "tutor", "look": "margo look: a friendly green gecko"},
        {"id": "peer", "name": "Awa"},
    ],
    "places": [
        {"id": "market", "title": {"en": "Market", "fr": "Marché"}, "look": "market look"},
        {"id": "school", "title": {"en": "School", "fr": "École"}, "look": "school look"},
    ],
}

GIRL = ArtItem("character", "hero:girl", "girl look: a 9-year-old girl in a school uniform")
BOY = ArtItem("character", "hero:boy", "boy look: a 9-year-old boy in a school uniform")
MENTOR = ArtItem("character", "mentor", "mentor look: a teacher in a blue shirt")
MARGO = ArtItem("character", "margo", "margo look: a friendly green gecko")
MARKET = ArtItem("place", "market", "market look")
SCHOOL = ArtItem("place", "school", "school look")
ALL_ITEMS = [GIRL, BOY, MENTOR, MARGO, MARKET, SCHOOL]


# --------------------------------------------------------------------------
# Image fixtures
# --------------------------------------------------------------------------


def figure_png(
    size: tuple[int, int] = (200, 300),
    box: tuple[int, int, int, int] = (50, 40, 150, 280),
    shade: int = 0,
) -> bytes:
    """A transparent canvas with one opaque "character" rectangle."""
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    figure = Image.new("RGBA", (box[2] - box[0], box[3] - box[1]), (120, 60 + shade % 150, 30, 255))
    image.paste(figure, box[:2])
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def backdrop_png(size: tuple[int, int] = (300, 200)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (200, 150, 90)).save(buffer, format="PNG")
    return buffer.getvalue()


def decode(data: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(data))
    image.load()
    return image


def row(
    item: ArtItem,
    pose: str,
    *,
    status: str = "ready",
    digest: str | None = None,
    updated_at: datetime | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        kind=item.kind,
        key=item.key,
        pose=pose,
        look_digest=digest if digest is not None else item.digest,
        status=status,
        updated_at=updated_at,
    )


def ready_rows(items: list[ArtItem]) -> list[SimpleNamespace]:
    return [row(item, pose) for item in items for pose in item.poses]


# --------------------------------------------------------------------------
# Looks
# --------------------------------------------------------------------------


class TestCollectLooks:
    def test_reads_cast_hero_variants_and_places(self):
        assert collect_looks([DOC]) == ALL_ITEMS

    def test_the_hero_is_keyed_by_variant_never_bare(self):
        keys = [item.key for item in collect_looks([DOC])]
        assert "hero:girl" in keys and "hero:boy" in keys and "hero" not in keys

    def test_a_cast_entry_without_a_look_is_skipped(self):
        assert "peer" not in {item.key for item in collect_looks([DOC])}

    def test_an_old_story_has_no_looks(self):
        old = {"cast": [{"id": "mentor", "name": "M. Kaboré", "art": "teacher"}], "chapters": []}
        assert collect_looks([old]) == []
        assert collect_looks([{}]) == []

    def test_keys_are_deduplicated_across_stories_the_first_wins(self):
        newer = {
            "cast": [{"id": "mentor", "look": "mentor look, newer"}],
            "places": [{"id": "market", "look": "market look, newer"}],
        }
        items = collect_looks([newer, DOC])
        by_key = {item.key: item for item in items}
        assert by_key["mentor"].look == "mentor look, newer"
        assert by_key["market"].look == "market look, newer"
        assert [item.key for item in items].count("mentor") == 1
        # The older story still contributes what the newer one lacks.
        assert {"hero:girl", "hero:boy", "margo", "school"} <= set(by_key)

    def test_characters_come_before_places(self):
        places_first = {"places": DOC["places"], "cast": DOC["cast"]}
        kinds = [item.kind for item in collect_looks([{"places": DOC["places"]}, places_first])]
        assert kinds == sorted(kinds, key=lambda kind: kind != "character")

    def test_malformed_entries_are_ignored(self):
        doc = {
            "cast": ["mentor", {"look": "no id"}, {"id": " ", "look": "blank id"}, None],
            "places": "market",
        }
        assert collect_looks([doc, None, "x"]) == []

    def test_a_look_is_normalised_and_capped(self):
        long = "a  tall\n teacher " + "x" * 1000
        (item,) = collect_looks([{"cast": [{"id": "mentor", "look": long}]}])
        assert item.look.startswith("a tall teacher x")
        assert len(item.look) == svc.MAX_LOOK_CHARS


class TestLookDigest:
    def test_same_look_same_digest_whitespace_aside(self):
        assert look_digest("a  teacher\n") == look_digest("a teacher")

    def test_a_changed_look_changes_the_digest(self):
        assert look_digest("a teacher") != look_digest("a tall teacher")

    def test_the_art_version_is_part_of_it(self):
        before = look_digest("a teacher")
        with patch.object(svc, "ART_VERSION", svc.ART_VERSION + 1):
            assert look_digest("a teacher") != before


class TestLoadCourseLooks:
    async def test_reads_only_cast_and_places_newest_first_without_archived(self):
        captured: list[Any] = []

        class Session:
            async def execute(self, statement):
                captured.append(statement)
                newer = ([{"id": "mentor", "look": "newer"}], None)
                older = (DOC["cast"], DOC["places"])
                return SimpleNamespace(all=lambda: [newer, older])

        items = await svc.load_course_looks(Session(), COURSE_ID)
        sql = str(captured[0].compile(dialect=sa.dialects.postgresql.dialect()))
        # Only the two sub-objects are selected, never the whole document.
        assert sql.startswith("SELECT story_courses.content[") and ", story_courses.content[" in sql
        assert "story_courses.content," not in sql and "story_courses.id" not in sql
        assert "ORDER BY story_courses.updated_at DESC" in sql
        assert "story_courses.status !=" in sql
        assert "story_courses.course_id =" in sql
        assert {item.key: item.look for item in items}["mentor"] == "newer"
        assert len(items) == len(ALL_ITEMS)


# --------------------------------------------------------------------------
# Planning: digest skip, regenerate, cap
# --------------------------------------------------------------------------


class TestPlan:
    def test_nothing_is_drawn_when_everything_is_ready_for_its_look(self):
        assert plan_art(ALL_ITEMS, ready_rows(ALL_ITEMS)) == []

    def test_missing_art_is_drawn_whole(self):
        jobs = plan_art([GIRL, MARKET], [])
        assert jobs == [ArtJob(GIRL, CHARACTER_POSES), ArtJob(MARKET, ("backdrop",))]

    def test_a_changed_look_redraws_every_pose(self):
        stale = [row(GIRL, pose, digest="old") for pose in CHARACTER_POSES]
        assert plan_art([GIRL], stale) == [ArtJob(GIRL, CHARACTER_POSES)]

    def test_a_stale_idle_redraws_the_poses_even_if_they_match(self):
        rows = [row(GIRL, "idle", digest="old")] + [row(GIRL, p) for p in CHARACTER_POSES[1:]]
        assert plan_art([GIRL], rows) == [ArtJob(GIRL, CHARACTER_POSES)]

    def test_a_missing_pose_is_an_edit_of_the_stored_idle(self):
        idle = row(GIRL, "idle")
        jobs = plan_art([GIRL], [idle, row(GIRL, "happy")])
        assert jobs == [ArtJob(GIRL, ("talk", "think"), idle_row_id=idle.id)]

    def test_a_changed_place_look_redraws_only_the_backdrop(self):
        rows = ready_rows([GIRL]) + [row(MARKET, "backdrop", digest="old")]
        assert plan_art([GIRL, MARKET], rows) == [ArtJob(MARKET, ("backdrop",))]

    def test_failed_art_is_not_retried_for_the_same_look(self):
        rows = [row(MARKET, "backdrop", status="failed")]
        assert plan_art([MARKET], rows) == []
        assert plan_art([MARKET], rows, retry_failed=True) == [ArtJob(MARKET, ("backdrop",))]

    def test_failed_art_is_retried_when_its_look_changes(self):
        rows = [row(MARKET, "backdrop", status="failed", digest="old")]
        assert plan_art([MARKET], rows) == [ArtJob(MARKET, ("backdrop",))]

    def test_poses_without_a_ready_idle_cost_nothing(self):
        rows = [row(GIRL, "idle", status="failed")]
        (job,) = plan_art([GIRL], rows)
        assert job.poses == CHARACTER_POSES[1:] and job.idle_row_id is None and job.cost == 0

    def test_a_failed_idle_is_retried_with_its_poses_on_request(self):
        rows = [row(GIRL, pose, status="failed") for pose in CHARACTER_POSES]
        assert plan_art([GIRL], rows, retry_failed=True) == [ArtJob(GIRL, CHARACTER_POSES)]


class TestCap:
    def test_a_usual_course_fits_under_the_cap(self):
        usual = [GIRL, BOY, MENTOR, MARGO, ArtItem("character", "friend", "f")] + [
            ArtItem("place", f"p{i}", "p") for i in range(6)
        ]
        jobs = plan_art(usual, [])
        assert sum(job.cost for job in jobs) == 26 <= MAX_IMAGES_PER_RUN == 40

    def test_whole_jobs_are_kept_in_order_and_the_rest_skipped(self):
        jobs = plan_art(ALL_ITEMS, [])
        kept, skipped = apply_cap(jobs, 5)
        assert [job.item.key for job in kept] == ["hero:girl", "market"]
        assert [job.item.key for job in skipped] == ["hero:boy", "mentor", "margo", "school"]

    def test_a_character_is_never_split_from_its_idle(self):
        kept, skipped = apply_cap(plan_art([GIRL], []), 3)
        assert kept == [] and [job.item for job in skipped] == [GIRL]


# --------------------------------------------------------------------------
# The art map
# --------------------------------------------------------------------------


class TestArtMap:
    def test_none_without_looks(self):
        result = build_art_map([], [])
        assert result.art == {"status": "none", "characters": {}, "places": {}}
        assert result.outstanding == 0

    def test_pending_when_nothing_is_ready(self):
        result = build_art_map(ALL_ITEMS, [])
        assert result.art == {"status": "pending", "characters": {}, "places": {}}
        assert result.outstanding == 4 * 4 + 2

    def test_partial_while_some_is_ready(self):
        rows = ready_rows([GIRL, MARKET])
        result = build_art_map([GIRL, MENTOR, MARKET], rows)
        assert result.art["status"] == "partial"
        assert set(result.art["characters"]) == {"hero:girl"}
        assert set(result.art["characters"]["hero:girl"]) == set(CHARACTER_POSES)
        assert set(result.art["places"]) == {"market"}
        assert result.outstanding == 4

    def test_ready_with_relative_data_urls(self):
        rows = ready_rows(ALL_ITEMS)
        by_key = {(r.key, r.pose): r.id for r in rows}
        result = build_art_map(ALL_ITEMS, rows)
        assert result.art["status"] == "ready" and result.outstanding == 0
        assert result.art["characters"]["hero:boy"]["think"] == (
            f"/api/v1/story-art/{by_key[('hero:boy', 'think')]}/data"
        )
        assert result.art["places"]["school"] == (
            f"/api/v1/story-art/{by_key[('school', 'backdrop')]}/data"
        )
        assert set(result.art["characters"]) == {"hero:girl", "hero:boy", "mentor", "margo"}

    def test_failed_images_leave_it_partial_with_nothing_outstanding(self):
        rows = ready_rows([GIRL]) + [row(MARKET, "backdrop", status="failed")]
        result = build_art_map([GIRL, MARKET], rows)
        assert result.art["status"] == "partial" and result.outstanding == 0
        assert result.art["places"] == {}

    def test_everything_failed_is_partial_not_pending(self):
        result = build_art_map([MARKET], [row(MARKET, "backdrop", status="failed")])
        assert result.art["status"] == "partial" and result.outstanding == 0

    def test_stale_art_is_not_served_and_is_outstanding(self):
        rows = [row(MARKET, "backdrop", digest="old")]
        result = build_art_map([MARKET], rows)
        assert result.art["status"] == "pending" and result.outstanding == 1

    def test_art_drawn_after_the_document_from_a_newer_look_is_served(self):
        written = datetime(2026, 11, 1, tzinfo=UTC)
        newer = [row(MARKET, "backdrop", digest="newer", updated_at=written + timedelta(hours=1))]
        older = [row(MARKET, "backdrop", digest="older", updated_at=written - timedelta(hours=1))]
        assert build_art_map([MARKET], newer, document_updated_at=written).art["status"] == "ready"
        assert build_art_map([MARKET], older, document_updated_at=written).outstanding == 1


# --------------------------------------------------------------------------
# Prompts
# --------------------------------------------------------------------------


class TestPrompts:
    def test_every_prompt_starts_with_the_shared_style_line(self):
        for prompt in (
            character_prompt("x"),
            pose_prompt("x", "talk"),
            place_prompt("x"),
        ):
            assert prompt.startswith(STYLE_LINE)
        for words in ("flat 2D vector cartoon", "thick", "outlines", "warm palette", "picture"):
            assert words in STYLE_LINE

    def test_characters_are_full_body_front_view_and_west_african(self):
        prompt = character_prompt("a teacher")
        assert "a teacher" in prompt
        for words in ("Full body", "front", "Transparent background", "no text"):
            assert words in prompt
        assert prompt.endswith(PEOPLE_CONSTRAINT)

    @pytest.mark.parametrize("pose", ["talk", "happy", "think"])
    def test_a_pose_changes_only_the_expression_and_the_arms(self, pose):
        prompt = pose_prompt("a teacher", pose)
        assert POSE_CHANGES[pose] in prompt
        assert "Change only the facial expression and the arms" in prompt
        for kept in ("same face", "outfit", "proportions", "framing"):
            assert kept in prompt

    def test_a_backdrop_has_no_people_no_text_and_ground_below(self):
        prompt = place_prompt("a market")
        for words in ("no people", "no text", "lower third"):
            assert words in prompt
        assert PEOPLE_CONSTRAINT not in prompt


# --------------------------------------------------------------------------
# Post-processing
# --------------------------------------------------------------------------


class TestProcessCharacter:
    def test_trims_the_margin_and_stands_on_the_bottom_edge(self):
        data, width, height = process_character(figure_png())
        image = decode(data).convert("RGBA")
        assert decode(data).format == "WEBP"
        assert (width, height) == image.size == (100, 240)
        alpha = image.getchannel("A")
        # Opaque on the bottom row (the feet) and the top row (the head).
        assert alpha.crop((0, height - 1, width, height)).getextrema()[1] == 255
        assert alpha.crop((0, 0, width, 1)).getextrema()[1] == 255

    def test_caps_the_height_and_keeps_the_aspect(self):
        data, width, height = process_character(
            figure_png(size=(600, 1600), box=(100, 50, 500, 1550))
        )
        assert height == MAX_CHARACTER_HEIGHT
        assert width == round(400 * MAX_CHARACTER_HEIGHT / 1500)
        assert decode(data).size == (width, height)

    def test_keeps_transparency_around_the_figure(self):
        raw = figure_png(size=(200, 300), box=(50, 40, 150, 280))
        image = Image.open(io.BytesIO(raw)).convert("RGBA")
        # A diagonal notch: the trimmed image must keep transparent pixels.
        for i in range(30):
            image.putpixel((50 + i, 40 + i), (0, 0, 0, 0))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        data, _, _ = process_character(buffer.getvalue())
        image = decode(data)
        assert image.mode == "RGBA"  # WebP with alpha
        assert image.getchannel("A").getextrema()[0] < 255

    def test_an_opaque_flat_background_is_cleared(self):
        image = Image.new("RGB", (200, 300), (255, 255, 255))
        image.paste(Image.new("RGB", (80, 200), (40, 20, 10)), (60, 60))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        _, width, height = process_character(buffer.getvalue())
        assert (width, height) == (80, 200)

    def test_an_empty_image_is_refused(self):
        buffer = io.BytesIO()
        Image.new("RGBA", (50, 50), (0, 0, 0, 0)).save(buffer, format="PNG")
        with pytest.raises(ArtProcessingError):
            process_character(buffer.getvalue())

    def test_garbage_is_refused(self):
        with pytest.raises(ArtProcessingError):
            process_character(b"not an image")


class TestProcessBackdrop:
    @pytest.mark.parametrize(
        ("size", "expected"),
        [
            ((1536, 1024), (1536, 1024)),
            ((3072, 2048), (1536, 1024)),
            ((1024, 1024), (1024, 683)),
            ((2000, 1000), (1500, 1000)),
        ],
    )
    def test_cropped_to_three_by_two_and_capped(self, size, expected):
        data, width, height = process_backdrop(backdrop_png(size))
        image = decode(data)
        assert image.format == "WEBP" and image.mode == "RGB"
        assert (width, height) == image.size == expected


class TestStoredReference:
    def test_the_trimmed_idle_goes_back_on_a_portrait_canvas(self):
        webp, width, height = process_character(figure_png())
        reference = stored_reference(webp)
        assert reference.startswith(b"\x89PNG")
        canvas = decode(reference)
        assert canvas.height > height and canvas.width >= width
        assert abs(canvas.width / canvas.height - 2 / 3) < 0.05
        bbox = canvas.getchannel("A").getbbox()
        assert bbox is not None and canvas.height - bbox[3] < canvas.height * 0.1


# --------------------------------------------------------------------------
# The run
# --------------------------------------------------------------------------


class FakeImages:
    """Records every image call; fails the prompts that contain a needle."""

    def __init__(self, failures: dict[str, int] | None = None, delay: float = 0.0) -> None:
        self.calls: list[SimpleNamespace] = []
        self.failures = dict(failures or {})
        self.delay = delay
        self.in_flight = 0
        self.max_in_flight = 0

    async def _call(self, kind: str, prompt: str, image: bytes | None, size: str, background):
        call = SimpleNamespace(
            kind=kind, prompt=prompt, image=image, size=size, background=background, returned=None
        )
        self.calls.append(call)
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(self.delay)
        finally:
            self.in_flight -= 1
        for needle, left in self.failures.items():
            if left and needle in prompt:
                self.failures[needle] = left - 1
                raise RuntimeError(f"boom: {needle}")
        if size == BACKDROP_SIZE:
            call.returned = backdrop_png()
        else:
            call.returned = figure_png(shade=len(self.calls))
        return call.returned, "gpt-image-1"

    async def generate(self, prompt, *, model, size, background=None):
        return await self._call("generate", prompt, None, size, background)

    async def edit(self, prompt, image, *, model, size, background=None):
        return await self._call("edit", prompt, image, size, background)


class FakeSessions:
    """Stands in for the task's session factory: records the generator's writes."""

    def __init__(self, idle_webp: bytes | None = None) -> None:
        self.written: list[StoryArt] = []
        self.deletes: list[str] = []
        self.idle_webp = idle_webp

    def __call__(self) -> _FakeSession:
        return _FakeSession(self)

    def by_item(self) -> dict[tuple[str, str], StoryArt]:
        return {(art.key, art.pose): art for art in self.written}


class _FakeSession:
    def __init__(self, owner: FakeSessions) -> None:
        self.owner = owner

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def execute(self, statement):
        sql = str(statement)
        if sql.startswith("DELETE FROM story_art"):
            self.owner.deletes.append(sql)
            return MagicMock()
        if sql.startswith("SELECT story_art.image_data"):
            return SimpleNamespace(scalar_one_or_none=lambda: self.owner.idle_webp)
        raise AssertionError(f"unexpected query: {sql}")

    def add(self, obj: StoryArt) -> None:
        self.owner.written.append(obj)

    async def commit(self) -> None:
        return None


async def run_generator(
    items: list[ArtItem],
    rows: list[Any] | None = None,
    *,
    images: FakeImages | None = None,
    sessions: FakeSessions | None = None,
    **kwargs: Any,
) -> tuple[dict, FakeImages, FakeSessions]:
    images = images or FakeImages()
    sessions = sessions or FakeSessions()
    with (
        patch.object(svc, "load_course_looks", AsyncMock(return_value=list(items))),
        patch.object(svc, "load_art_rows", AsyncMock(return_value=list(rows or []))),
    ):
        generator = StoryArtGenerator(
            sessions, model="gpt-image-1", generate=images.generate, edit=images.edit, **kwargs
        )
        report = await generator.run(COURSE_ID)
    return report, images, sessions


def is_webp(data: bytes | None) -> bool:
    return bool(data) and data[:4] == b"RIFF" and data[8:12] == b"WEBP"


class TestRun:
    async def test_idle_first_then_poses_edited_from_the_idle_bytes(self):
        report, images, sessions = await run_generator([GIRL])
        assert [call.kind for call in images.calls] == ["generate", "edit", "edit", "edit"]
        idle = images.calls[0]
        assert idle.prompt == character_prompt(GIRL.look)
        assert (idle.size, idle.background) == (CHARACTER_SIZE, "transparent")
        for edit in images.calls[1:]:
            assert edit.image == idle.returned  # the idle's own bytes
            assert (edit.size, edit.background) == (CHARACTER_SIZE, "transparent")
        assert sorted(call.prompt for call in images.calls[1:]) == sorted(
            pose_prompt(GIRL.look, pose) for pose in ("talk", "happy", "think")
        )
        assert report == {
            "status": "complete",
            "planned": 4,
            "ready": 4,
            "failed": 0,
            "skipped": [],
        }
        stored = sessions.by_item()
        assert set(stored) == {("hero:girl", pose) for pose in CHARACTER_POSES}
        for art in stored.values():
            assert art.status == "ready" and art.look_digest == GIRL.digest
            assert art.kind == "character" and art.course_id == COURSE_ID
            assert is_webp(art.image_data) and art.height and art.width
            assert art.model == "gpt-image-1"

    async def test_every_character_is_drawn_idle_before_its_poses(self):
        _, images, _ = await run_generator(
            [GIRL, BOY, MENTOR, MARGO], images=FakeImages(delay=0.001)
        )
        for item in (GIRL, BOY, MENTOR, MARGO):
            mine = [i for i, call in enumerate(images.calls) if f": {item.look}" in call.prompt]
            assert images.calls[mine[0]].kind == "generate"
            assert [images.calls[i].kind for i in mine[1:]] == ["edit"] * 3
            idle_bytes = images.calls[mine[0]].returned
            assert all(images.calls[i].image == idle_bytes for i in mine[1:])

    async def test_a_backdrop_is_one_wide_generation(self):
        _, images, sessions = await run_generator([MARKET])
        (call,) = images.calls
        assert (call.kind, call.size, call.background) == ("generate", BACKDROP_SIZE, None)
        assert call.prompt == place_prompt(MARKET.look)
        art = sessions.by_item()[("market", "backdrop")]
        assert art.kind == "place" and art.status == "ready" and is_webp(art.image_data)

    async def test_ready_art_for_the_same_look_is_not_drawn_again(self):
        report, images, sessions = await run_generator(ALL_ITEMS, ready_rows(ALL_ITEMS))
        assert images.calls == [] and sessions.written == []
        assert report["planned"] == 0

    async def test_a_changed_look_is_drawn_again_under_a_new_id(self):
        old = [row(MARKET, "backdrop", digest="old")]
        _, images, sessions = await run_generator([MARKET], old)
        assert len(images.calls) == 1 and len(sessions.deletes) == 1
        (art,) = sessions.written
        assert art.look_digest == MARKET.digest and art.id != old[0].id

    async def test_a_missing_pose_is_edited_from_the_stored_idle(self):
        idle_webp, _, _ = process_character(figure_png())
        idle = row(GIRL, "idle")
        rows = [idle, row(GIRL, "happy")]
        _, images, sessions = await run_generator(
            [GIRL], rows, sessions=FakeSessions(idle_webp=idle_webp)
        )
        assert [call.kind for call in images.calls] == ["edit", "edit"]
        for call in images.calls:
            assert call.image.startswith(b"\x89PNG")  # the stored idle, back on a canvas
        assert set(sessions.by_item()) == {("hero:girl", "talk"), ("hero:girl", "think")}

    async def test_a_failed_image_is_retried_once_then_succeeds(self):
        images = FakeImages(failures={"market look": 1})
        report, images, sessions = await run_generator([MARKET], images=images)
        assert len(images.calls) == 2
        assert sessions.by_item()[("market", "backdrop")].status == "ready"
        assert report["ready"] == 1 and report["failed"] == 0

    async def test_an_image_failing_twice_is_stored_as_failed_and_not_tried_again(self):
        images = FakeImages(failures={"market look": 5})
        report, images, sessions = await run_generator([MARKET], images=images)
        assert len(images.calls) == 2  # the first try and one retry, never more
        art = sessions.by_item()[("market", "backdrop")]
        assert art.status == "failed" and art.image_data is None
        assert "boom: market look" in art.error and art.look_digest == MARKET.digest
        assert report["failed"] == 1

    async def test_a_failed_pose_is_retried_once(self):
        images = FakeImages(failures={POSE_CHANGES["talk"]: 1})
        report, images, sessions = await run_generator([GIRL], images=images)
        assert [call.kind for call in images.calls].count("edit") == 4
        assert all(art.status == "ready" for art in sessions.written)
        assert report["ready"] == 4

    async def test_a_failed_idle_fails_its_poses_without_drawing_them(self):
        images = FakeImages(failures={f"alone: {GIRL.look}": 5})
        report, images, sessions = await run_generator([GIRL], images=images)
        assert [call.kind for call in images.calls] == ["generate", "generate"]
        stored = sessions.by_item()
        assert all(art.status == "failed" for art in stored.values())
        assert {pose for _, pose in stored} == set(CHARACTER_POSES)
        assert stored[("hero:girl", "talk")].error == "idle pose unavailable"
        assert report["failed"] == 4 and report["ready"] == 0

    async def test_garbage_from_the_model_counts_as_a_failed_attempt(self):
        calls = 0

        async def generate(prompt, *, model, size, background=None):
            nonlocal calls
            calls += 1
            return (b"garbage" if calls == 1 else backdrop_png()), "gpt-image-1"

        sessions = FakeSessions()
        with (
            patch.object(svc, "load_course_looks", AsyncMock(return_value=[MARKET])),
            patch.object(svc, "load_art_rows", AsyncMock(return_value=[])),
        ):
            await StoryArtGenerator(
                sessions, model="gpt-image-1", generate=generate, edit=AsyncMock()
            ).run(COURSE_ID)
        assert calls == 2 and sessions.written[0].status == "ready"

    async def test_the_cap_skips_whole_items_and_logs_them(self):
        with patch.object(svc, "logger") as log:
            report, images, sessions = await run_generator(ALL_ITEMS, max_images=5)
        assert len(images.calls) == 5  # the girl's four poses and the market
        assert {key for key, _ in sessions.by_item()} == {"hero:girl", "market"}
        assert report["skipped"] == ["hero:boy", "mentor", "margo", "school"]
        assert report["planned"] == 5
        warned = [c for c in log.warning.call_args_list if c.args[0] == "story_art.cap_reached"]
        assert warned and warned[0].kwargs["skipped"][0] == {"key": "hero:boy", "images": 4}

    async def test_no_more_images_in_flight_than_the_concurrency(self):
        images = FakeImages(delay=0.01)
        await run_generator(ALL_ITEMS, images=images, concurrency=2)
        assert len(images.calls) == 18
        assert images.max_in_flight == 2

    async def test_the_default_backends_are_the_provider_functions(self):
        from app.ai.providers import image_provider

        generator = StoryArtGenerator(FakeSessions(), model="gpt-image-1")
        assert generator._generate is image_provider.generate_image
        assert generator._edit is image_provider.edit_image


# --------------------------------------------------------------------------
# The provider: transparency, edit, routing, ledger
# --------------------------------------------------------------------------


_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


def _settings(*, google: str = "", openai: str = "ok") -> SimpleNamespace:
    return SimpleNamespace(
        google_api_key=google, openai_api_key=openai, gemini_openai_base_url=_GEMINI_BASE_URL
    )


def _response(payload: bytes = b"IMG") -> MagicMock:
    import base64

    response = MagicMock()
    response.data = [MagicMock(b64_json=base64.b64encode(payload).decode())]
    return response


@pytest.fixture
def openai_client():
    """A fake AsyncOpenAI client shared by every provider built in the test."""
    client = MagicMock()
    client.images.generate = AsyncMock(return_value=_response(b"GEN"))
    client.images.edit = AsyncMock(return_value=_response(b"EDIT"))
    with patch("app.ai.providers.image_provider.AsyncOpenAI", return_value=client) as cls:
        client.cls = cls
        yield client


@pytest.fixture
def ledger():
    with patch(
        "app.domain.services.ai_usage_service.record_ai_usage", new_callable=AsyncMock
    ) as record:
        yield record


class TestInstalledSdk:
    """The parameters the providers send exist in the pinned openai SDK."""

    def test_edit_accepts_the_parameters_used(self):
        params = inspect.signature(AsyncImages.edit).parameters
        for name in ("image", "prompt", "model", "size", "background", "input_fidelity"):
            assert name in params
        for name in ("quality", "output_format"):
            assert name in params

    def test_generate_accepts_background_and_output_format(self):
        params = inspect.signature(AsyncImages.generate).parameters
        assert "background" in params and "output_format" in params


class TestOpenAIProvider:
    async def test_a_transparent_generation_asks_for_png(self, openai_client):
        provider = OpenAIImageProvider(api_key="ok")
        out = await provider.generate("p", size="1024x1536", background="transparent")
        kwargs = openai_client.images.generate.call_args.kwargs
        assert kwargs == {
            "model": "gpt-image-1",
            "prompt": "p",
            "size": "1024x1536",
            "quality": "medium",
            "background": "transparent",
            "output_format": "png",
        }
        assert out == b"GEN"

    async def test_an_ordinary_generation_is_unchanged(self, openai_client):
        await OpenAIImageProvider(api_key="ok").generate("p")
        kwargs = openai_client.images.generate.call_args.kwargs
        assert "background" not in kwargs and "output_format" not in kwargs

    async def test_edit_sends_the_reference_with_high_input_fidelity(self, openai_client):
        provider = OpenAIImageProvider(api_key="ok")
        out = await provider.edit("p", b"REF", size="1024x1536", background="transparent")
        kwargs = openai_client.images.edit.call_args.kwargs
        assert kwargs == {
            "model": "gpt-image-1",
            "image": ("ref.png", b"REF", "image/png"),
            "prompt": "p",
            "size": "1024x1536",
            "quality": "medium",
            "background": "transparent",
            "output_format": "png",
            "input_fidelity": "high",
        }
        assert out == b"EDIT"

    async def test_mini_models_get_no_input_fidelity(self, openai_client):
        await OpenAIImageProvider(api_key="ok", model="gpt-image-1-mini").edit("p", b"REF")
        assert "input_fidelity" not in openai_client.images.edit.call_args.kwargs


class TestGeminiProvider:
    async def test_cannot_edit(self, openai_client):
        provider = GeminiImageProvider(api_key="gk", model="gemini-2.5-flash-image", base_url="u")
        assert provider.supports_edit is False and provider.supports_transparency is False
        with pytest.raises(ImageCapabilityError):
            await provider.edit("p", b"REF")
        with pytest.raises(ImageCapabilityError):
            await provider.generate("p", background="transparent")
        openai_client.images.edit.assert_not_awaited()
        openai_client.images.generate.assert_not_awaited()


class TestRouting:
    async def test_an_edit_with_gemini_configured_goes_to_gpt_image_1(self, openai_client, ledger):
        with patch(
            "app.ai.providers.image_provider.get_settings", return_value=_settings(google="gk")
        ):
            data, used = await edit_image(
                "p", b"REF", model="gemini-2.5-flash-image", background="transparent"
            )
        assert (data, used) == (b"EDIT", "gpt-image-1")
        assert openai_client.images.edit.call_args.kwargs["model"] == "gpt-image-1"
        # Built against OpenAI, not Google's endpoint.
        assert "base_url" not in openai_client.cls.call_args.kwargs
        ledger.assert_awaited_once()
        assert ledger.await_args.kwargs == {
            "provider": "openai",
            "model": "gpt-image-1",
            "operation": "image",
            "images_count": 1,
        }

    async def test_a_transparent_render_with_gemini_configured_goes_to_gpt_image_1(
        self, openai_client, ledger
    ):
        with patch(
            "app.ai.providers.image_provider.get_settings", return_value=_settings(google="gk")
        ):
            _, used = await generate_image(
                "p", model="gemini-2.5-flash-image", size="1024x1536", background="transparent"
            )
        assert used == "gpt-image-1"
        kwargs = openai_client.images.generate.call_args.kwargs
        assert kwargs["model"] == "gpt-image-1" and kwargs["background"] == "transparent"
        assert ledger.await_count == 1

    async def test_the_routing_is_logged(self, openai_client, ledger):
        with (
            patch(
                "app.ai.providers.image_provider.get_settings", return_value=_settings(google="gk")
            ),
            patch("app.ai.providers.image_provider.logger") as log,
        ):
            await edit_image("p", b"REF", model="gemini-2.5-flash-image")
        (call,) = log.info.call_args_list
        assert call.kwargs["missing"] == ["edit"] and call.kwargs["requested_model"] == (
            "gemini-2.5-flash-image"
        )

    async def test_an_opaque_backdrop_stays_on_the_configured_gemini(self, openai_client, ledger):
        with patch(
            "app.ai.providers.image_provider.get_settings", return_value=_settings(google="gk")
        ):
            _, used = await generate_image("p", model="gemini-2.5-flash-image")
        assert used == "gemini-2.5-flash-image"
        assert openai_client.cls.call_args.kwargs["base_url"] == _GEMINI_BASE_URL
        assert ledger.await_args.kwargs["provider"] == "google"

    async def test_a_failed_edit_is_recorded_and_raised(self, openai_client, ledger):
        openai_client.images.edit.side_effect = RuntimeError("400 bad image")
        with (
            patch("app.ai.providers.image_provider.get_settings", return_value=_settings()),
            pytest.raises(RuntimeError),
        ):
            await edit_image("p", b"REF", model="gpt-image-1")
        assert openai_client.images.edit.await_count == 1  # no fallback loop on OpenAI
        assert ledger.await_args.kwargs["success"] is False
        assert ledger.await_args.kwargs["error_type"] == "RuntimeError"

    async def test_a_failing_gemini_backdrop_falls_back_with_two_ledger_rows(
        self, openai_client, ledger
    ):
        openai_client.images.generate.side_effect = [RuntimeError("429"), _response(b"FB")]
        with patch(
            "app.ai.providers.image_provider.get_settings", return_value=_settings(google="gk")
        ):
            data, used = await generate_image("p", model="gemini-2.5-flash-image")
        assert (data, used) == (b"FB", "gpt-image-1")
        rows = [c.kwargs for c in ledger.await_args_list]
        assert [r["model"] for r in rows] == ["gemini-2.5-flash-image", "gpt-image-1"]
        assert rows[0]["success"] is False and rows[1]["images_count"] == 1


# --------------------------------------------------------------------------
# Dispatch dedup
# --------------------------------------------------------------------------


class FakeRedis:
    def __init__(self, *, fail: bool = False) -> None:
        self.data: dict[str, str] = {}
        self.fail = fail
        self.ttls: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        if self.fail:
            raise ConnectionError("redis down")
        return self.data.get(key)

    async def set(self, key: str, value: str, nx: bool = False, ex: int | None = None):
        if self.fail:
            raise ConnectionError("redis down")
        if nx and key in self.data:
            return None
        self.data[key] = value
        if ex is not None:
            self.ttls[key] = ex
        return True

    async def eval(self, _script: str, _numkeys: int, key: str, task_id: str) -> int:
        if self.data.get(key) == task_id:
            del self.data[key]
            return 1
        return 0


@pytest.fixture
def dispatch():
    redis = FakeRedis()
    with (
        patch("app.infrastructure.cache.redis.redis_client", redis),
        patch.object(api.generate_story_art, "apply_async") as apply_async,
        patch.object(api, "AsyncResult", return_value=SimpleNamespace(state="PENDING")) as result,
    ):
        yield SimpleNamespace(redis=redis, apply_async=apply_async, result=result)


KEY = story_art_dispatch_key(COURSE_ID)


class TestDispatch:
    async def test_the_first_view_claims_the_course_key_and_dispatches(self, dispatch):
        task_id = await api.dispatch_story_art_generation(COURSE_ID)
        assert dispatch.redis.data == {KEY: task_id}
        assert dispatch.redis.ttls[KEY] == STORY_ART_DISPATCH_TTL_S
        dispatch.apply_async.assert_called_once_with(
            args=[str(COURSE_ID)], kwargs={"dedup_key": KEY}, task_id=task_id
        )

    async def test_a_second_view_joins_the_running_task(self, dispatch):
        first = await api.dispatch_story_art_generation(COURSE_ID)
        second = await api.dispatch_story_art_generation(COURSE_ID)
        assert first == second and dispatch.apply_async.call_count == 1

    async def test_a_finished_task_is_replaced(self, dispatch):
        first = await api.dispatch_story_art_generation(COURSE_ID)
        dispatch.result.return_value = SimpleNamespace(state="SUCCESS")
        second = await api.dispatch_story_art_generation(COURSE_ID)
        assert second != first and dispatch.redis.data == {KEY: second}
        assert dispatch.apply_async.call_count == 2

    async def test_a_view_that_loses_the_race_joins_the_winner(self, dispatch):
        redis = dispatch.redis
        original_get = redis.get
        calls = 0

        async def get(key):
            nonlocal calls
            calls += 1
            if calls == 1:
                return None  # nothing running yet...
            return await original_get(key)

        redis.get = get
        redis.data[KEY] = "winner"  # ...but another view claims it first
        assert await api.dispatch_story_art_generation(COURSE_ID) == "winner"
        dispatch.apply_async.assert_not_called()

    async def test_without_redis_nothing_is_dispatched(self, dispatch):
        dispatch.redis.fail = True
        assert await api.dispatch_story_art_generation(COURSE_ID) is None
        dispatch.apply_async.assert_not_called()

    async def test_a_failed_dispatch_frees_the_key(self, dispatch):
        dispatch.apply_async.side_effect = RuntimeError("broker down")
        assert await api.dispatch_story_art_generation(COURSE_ID) is None
        assert dispatch.redis.data == {}


# --------------------------------------------------------------------------
# The story routes attach the art map
# --------------------------------------------------------------------------


def _user(role: str = "user") -> AuthenticatedUser:
    return AuthenticatedUser(
        {"sub": "22222222-2222-2222-2222-222222222222", "email": "l@example.com", "role": role}
    )


class _Db:
    """A session stub for the story routes: the module lookup and one record."""

    def __init__(self, record: Any = None) -> None:
        self.record = record
        self.rollback = AsyncMock()

    async def execute(self, statement):
        sql = str(statement)
        if "FROM modules" in sql:
            return SimpleNamespace(first=lambda: (MODULE_ID,))
        return SimpleNamespace(scalar_one_or_none=lambda: self.record)


def _story(**overrides: Any) -> SimpleNamespace:
    values = {
        "slug": f"module-{MODULE_ID.hex}-fr",
        "status": "published",
        "is_valid": True,
        "module_id": MODULE_ID,
        "module_unit_id": None,
        "course_id": COURSE_ID,
        "updated_at": datetime(2026, 11, 1, tzinfo=UTC),
        "content": dict(DOC),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture
def routes():
    from app.domain.services.story_module_assembly import StoryUnit

    unit = StoryUnit(
        module_unit_id=uuid.uuid4(),
        unit_number="1.1",
        unit_type="lesson",
        order_index=0,
        role="lesson",
        title={"en": "U", "fr": "U"},
    )
    with (
        patch.object(api, "story_mode_enabled", return_value=True),
        patch.object(api, "load_story_units", AsyncMock(return_value=[unit])),
        patch.object(api, "find_module_story", AsyncMock(return_value=None)) as find,
        patch.object(api, "module_story_is_fresh", AsyncMock(return_value=True)),
        patch.object(api, "load_art_rows", AsyncMock(return_value=[])) as rows,
        patch.object(
            api, "dispatch_story_art_generation", AsyncMock(return_value="art-task")
        ) as dispatch,
    ):
        yield SimpleNamespace(find=find, rows=rows, dispatch=dispatch)


def _install(db: _Db, role: str = "user") -> None:
    async def session():
        yield db

    app.dependency_overrides[get_current_user] = lambda: _user(role)
    app.dependency_overrides[require_subscription_or_free_module] = lambda: _user(role)
    app.dependency_overrides[get_db] = session


MODULE_URL = f"/api/v1/story-courses/module/{MODULE_ID}"


class TestModuleStoryArt:
    async def test_missing_art_is_dispatched_and_reported_pending(self, client, routes):
        record = _story()
        routes.find.return_value = record
        _install(_Db())
        resp = await client.get(MODULE_URL, params={"language": "fr"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["art"] == {"status": "pending", "characters": {}, "places": {}}
        assert body["cast"] == DOC["cast"]
        routes.dispatch.assert_awaited_once_with(COURSE_ID)
        assert routes.rows.await_args.args[1] == COURSE_ID
        assert "art" not in record.content  # never stored

    async def test_ready_art_is_served_without_a_dispatch(self, client, routes):
        rows = ready_rows(ALL_ITEMS)
        routes.rows.return_value = rows
        routes.find.return_value = _story()
        _install(_Db())
        body = (await client.get(MODULE_URL)).json()
        assert body["art"]["status"] == "ready"
        girl_idle = next(r for r in rows if (r.key, r.pose) == ("hero:girl", "idle"))
        assert body["art"]["characters"]["hero:girl"]["idle"] == (
            f"/api/v1/story-art/{girl_idle.id}/data"
        )
        assert set(body["art"]["places"]) == {"market", "school"}
        routes.dispatch.assert_not_awaited()

    async def test_some_ready_is_partial_and_dispatched(self, client, routes):
        routes.rows.return_value = ready_rows([GIRL])
        routes.find.return_value = _story()
        _install(_Db())
        body = (await client.get(MODULE_URL)).json()
        assert body["art"]["status"] == "partial"
        assert set(body["art"]["characters"]) == {"hero:girl"}
        routes.dispatch.assert_awaited_once()

    async def test_an_old_story_without_looks_has_no_art(self, client, routes):
        routes.find.return_value = _story(content={"format": "story-course/1", "cast": []})
        _install(_Db())
        body = (await client.get(MODULE_URL)).json()
        assert body["art"] == {"status": "none", "characters": {}, "places": {}}
        routes.rows.assert_not_awaited()
        routes.dispatch.assert_not_awaited()

    async def test_a_story_without_a_course_has_no_art(self, client, routes):
        routes.find.return_value = _story(course_id=None)
        _install(_Db())
        assert (await client.get(MODULE_URL)).json()["art"]["status"] == "none"
        routes.dispatch.assert_not_awaited()

    async def test_an_art_failure_never_fails_the_story(self, client, routes):
        routes.rows.side_effect = RuntimeError("relation story_art does not exist")
        routes.find.return_value = _story()
        db = _Db()
        _install(db)
        resp = await client.get(MODULE_URL)
        assert resp.status_code == 200
        assert resp.json()["art"]["status"] == "pending"
        routes.dispatch.assert_not_awaited()
        db.rollback.assert_awaited()

    async def test_a_dispatch_failure_never_fails_the_story(self, client, routes):
        routes.dispatch.side_effect = RuntimeError("boom")
        routes.find.return_value = _story()
        _install(_Db())
        resp = await client.get(MODULE_URL)
        assert resp.status_code == 200 and resp.json()["art"]["status"] == "pending"


class TestSlugRouteArt:
    def _authored(self, **overrides: Any) -> SimpleNamespace:
        return _story(slug="maths-u1-w01", module_id=None, **overrides)

    async def test_an_authored_week_with_art_pending_is_not_cached_for_an_hour(
        self, client, routes
    ):
        _install(_Db(self._authored()))
        resp = await client.get("/api/v1/story-courses/maths-u1-w01")
        assert resp.status_code == 200
        assert resp.json()["art"]["status"] == "pending"
        assert resp.headers["cache-control"] == "public, no-cache"
        routes.dispatch.assert_awaited_once_with(COURSE_ID)

    async def test_an_authored_week_with_its_art_ready_keeps_the_hour(self, client, routes):
        routes.rows.return_value = ready_rows(ALL_ITEMS)
        _install(_Db(self._authored()))
        resp = await client.get("/api/v1/story-courses/maths-u1-w01")
        assert resp.json()["art"]["status"] == "ready"
        assert resp.headers["cache-control"] == "public, max-age=3600"

    async def test_an_admin_reading_a_module_story_gets_its_art(self, client, routes):
        routes.rows.return_value = ready_rows(ALL_ITEMS)
        _install(_Db(_story()), role="admin")
        resp = await client.get(f"/api/v1/story-courses/module-{MODULE_ID.hex}-fr")
        assert resp.json()["art"]["status"] == "ready"
        assert resp.headers["cache-control"] == "private, no-store"


# --------------------------------------------------------------------------
# GET /api/v1/story-art/{id}/data
# --------------------------------------------------------------------------


class _ArtDb:
    def __init__(self, found: tuple[str, bytes | None] | None) -> None:
        self.found = found
        self.statements: list[str] = []

    async def execute(self, statement):
        self.statements.append(str(statement))
        return SimpleNamespace(first=lambda: self.found)


class TestDataEndpoint:
    async def _get(self, client, found) -> Any:
        db = _ArtDb(found)

        async def session():
            yield db

        app.dependency_overrides[get_db] = session
        resp = await client.get(f"/api/v1/story-art/{uuid.uuid4()}/data")
        return resp, db

    async def test_a_ready_image_is_webp_and_immutable_without_a_token(self, client):
        resp, db = await self._get(client, ("ready", b"RIFFxxxxWEBP"))
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/webp"
        assert resp.headers["cache-control"] == "public, max-age=31536000, immutable"
        assert resp.content == b"RIFFxxxxWEBP"
        assert "story_art.image_data" in db.statements[0]

    async def test_a_failed_image_is_404_and_not_cached(self, client):
        resp, _ = await self._get(client, ("failed", None))
        assert resp.status_code == 404
        assert resp.json()["detail"]["error"] == "story_art_not_ready"
        assert "immutable" not in resp.headers.get("cache-control", "")

    async def test_an_unknown_image_is_404(self, client):
        resp, _ = await self._get(client, None)
        assert resp.status_code == 404
        assert resp.json()["detail"]["error"] == "story_art_not_found"

    def test_the_route_is_registered(self):
        paths = {route.path for route in app.routes}
        assert "/api/v1/story-art/{art_id}/data" in paths


# --------------------------------------------------------------------------
# The Celery task
# --------------------------------------------------------------------------


TASK_ID = "art-task-1"


def run_task(*args: Any, **kwargs: Any) -> dict:
    task = story_art_task.generate_story_art
    task.push_request(id=TASK_ID)
    try:
        return task.run(*args, **kwargs)
    finally:
        task.pop_request()


@pytest.fixture
def task_wiring():
    engine = MagicMock()
    engine.dispose = AsyncMock()
    generator = MagicMock()
    generator.run = AsyncMock(return_value={"status": "complete", "planned": 0})
    cache = MagicMock()
    cache.get.return_value = "gemini-2.5-flash-image"
    with (
        patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=engine),
        patch(
            "app.domain.services.story_art_service.StoryArtGenerator", return_value=generator
        ) as generator_cls,
        patch(
            "app.domain.services.platform_settings_service.SettingsCache.instance",
            return_value=cache,
        ),
        patch.object(story_art_task, "_hold_story_dispatch") as hold,
        patch.object(story_art_task, "_release_story_dispatch") as release,
    ):
        yield SimpleNamespace(
            engine=engine,
            generator=generator,
            generator_cls=generator_cls,
            cache=cache,
            hold=hold,
            release=release,
        )


class TestTask:
    def test_a_run_uses_the_image_setting_and_holds_then_releases_the_key(self, task_wiring):
        result = run_task(str(COURSE_ID), dedup_key=KEY)
        assert result == {"status": "complete", "planned": 0}
        task_wiring.cache.get.assert_called_once_with("ai-model-image", "gemini-2.5-flash-image")
        assert task_wiring.generator_cls.call_args.kwargs["model"] == "gemini-2.5-flash-image"
        assert task_wiring.generator_cls.call_args.kwargs["retry_failed"] is False
        task_wiring.generator.run.assert_awaited_once_with(COURSE_ID)
        task_wiring.hold.assert_called_once_with(KEY, TASK_ID, STORY_ART_DISPATCH_TTL_S)
        task_wiring.release.assert_called_once_with(KEY, TASK_ID)
        task_wiring.engine.dispose.assert_awaited_once()

    def test_a_crash_is_reported_and_the_key_still_released(self, task_wiring):
        task_wiring.generator.run.side_effect = RuntimeError("db down")
        result = run_task(str(COURSE_ID), dedup_key=KEY)
        assert result == {"status": "failed", "error": "db down"}
        task_wiring.release.assert_called_once_with(KEY, TASK_ID)

    def test_operators_can_retry_failures(self, task_wiring):
        run_task(str(COURSE_ID), retry_failed=True)
        assert task_wiring.generator_cls.call_args.kwargs["retry_failed"] is True

    def test_the_task_is_never_autoretried_and_has_a_bounded_key(self):
        task = story_art_task.generate_story_art
        assert not getattr(task, "autoretry_for", ())
        assert STORY_ART_DISPATCH_TTL_S < 3600  # under the broker visibility timeout
        assert STORY_ART_DISPATCH_TTL_S > story_art_task.STORY_ART_HARD_LIMIT

    def test_the_worker_imports_the_task(self):
        from app.tasks.celery_app import celery_app

        assert "app.tasks.story_art" in celery_app.conf.include


# --------------------------------------------------------------------------
# Migration 109
# --------------------------------------------------------------------------


MIGRATION_109 = Path(__file__).resolve().parents[1] / "migrations" / "versions" / "109_story_art.py"


class _RecordingOp:
    def __init__(self) -> None:
        self.tables: dict[str, list[Any]] = {}
        self.dropped: list[str] = []

    def create_table(self, name: str, *elements: Any, **_: Any) -> None:
        self.tables[name] = list(elements)

    def drop_table(self, name: str, *_a: Any, **_k: Any) -> None:
        self.dropped.append(name)


def _load_migration(name: str):
    spec = importlib.util.spec_from_file_location(name, MIGRATION_109)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestMigration:
    @pytest.fixture(scope="class")
    def recorded(self) -> _RecordingOp:
        recorder = _RecordingOp()
        module = _load_migration("migration_109")
        module.op = recorder  # type: ignore[attr-defined]
        module.upgrade()
        return recorder

    def test_revision_chain(self):
        module = _load_migration("migration_109_meta")
        assert module.revision == "109_story_art"
        assert module.down_revision == "108_story_course_bible"
        assert len(module.revision) <= 32  # alembic_version.version_num

    def test_creates_only_story_art(self, recorded):
        assert set(recorded.tables) == {"story_art"}

    def test_columns_match_the_model(self, recorded):
        columns = {e.name: e for e in recorded.tables["story_art"] if isinstance(e, sa.Column)}
        model = StoryArt.__table__.columns
        assert set(columns) == {c.name for c in model}
        dialect = sa.dialects.postgresql.dialect()
        for name, column in columns.items():
            assert column.nullable == model[name].nullable, name
            assert column.type.compile(dialect=dialect) == model[name].type.compile(
                dialect=dialect
            ), name

    def test_the_course_foreign_key_cascades(self, recorded):
        course = next(
            e
            for e in recorded.tables["story_art"]
            if isinstance(e, sa.Column) and e.name == "course_id"
        )
        (fk,) = course.foreign_keys
        assert fk.target_fullname == "courses.id" and fk.ondelete == "CASCADE"

    def test_unique_per_course_kind_key_pose(self, recorded):
        (unique,) = [e for e in recorded.tables["story_art"] if isinstance(e, sa.UniqueConstraint)]
        assert unique.name == "uq_story_art_course_item"
        assert list(unique._pending_colargs) == ["course_id", "kind", "key", "pose"]
        model_unique = next(
            c for c in StoryArt.__table__.constraints if isinstance(c, sa.UniqueConstraint)
        )
        assert [c.name for c in model_unique.columns] == ["course_id", "kind", "key", "pose"]
        assert model_unique.name == unique.name

    def test_check_constraints_match_the_model(self, recorded):
        def checks(elements) -> dict[str, str]:
            return {
                c.name: " ".join(str(c.sqltext).split())
                for c in elements
                if isinstance(c, sa.CheckConstraint)
            }

        migration = checks(recorded.tables["story_art"])
        model = checks(StoryArt.__table__.constraints)
        assert migration == model
        assert set(migration) == {"ck_story_art_kind", "ck_story_art_pose", "ck_story_art_status"}

    def test_downgrade_drops_the_table(self):
        recorder = _RecordingOp()
        module = _load_migration("migration_109_down")
        module.op = recorder  # type: ignore[attr-defined]
        module.downgrade()
        assert recorder.dropped == ["story_art"]


# --------------------------------------------------------------------------
# On PostgreSQL (scratch database; skipped without a server)
# --------------------------------------------------------------------------


SMALL_DOC = {
    "cast": [{"id": "mentor", "role": "mentor", "look": "mentor look"}],
    "places": [{"id": "market", "look": "market look"}],
}


def test_on_postgres_a_run_stores_skips_and_redraws_under_new_ids():
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.domain.models import Base
    from app.domain.models.course import Course
    from app.domain.models.story_course import StoryCourseRecord
    from tests._story_db import create_tables, scratch_database, story_tables

    with scratch_database("story_art") as url:
        create_tables(url, [*story_tables(), Base.metadata.tables["story_art"]])

        async def scenario() -> None:
            engine = create_async_engine(url)
            maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            try:
                course_id = uuid.uuid4()
                async with maker() as session:
                    session.add(
                        Course(
                            id=course_id,
                            slug=f"course-{course_id.hex[:8]}",
                            title_en="Course",
                            title_fr="Cours",
                        )
                    )
                    await session.flush()
                    story = StoryCourseRecord(
                        slug=f"week-{course_id.hex[:8]}",
                        course_id=course_id,
                        course_label="Course",
                        week=1,
                        title={"en": "T", "fr": "T"},
                        languages={"target": "en", "home": "fr"},
                        format_version="story-course/1",
                        content=SMALL_DOC,
                    )
                    session.add(story)
                    await session.commit()

                async def run(images: FakeImages) -> dict:
                    return await StoryArtGenerator(
                        maker, model="gpt-image-1", generate=images.generate, edit=images.edit
                    ).run(course_id)

                first_images = FakeImages()
                first = await run(first_images)
                assert first["ready"] == 5 and len(first_images.calls) == 5
                async with maker() as session:
                    rows = await svc.load_art_rows(session, course_id)
                    looks = await svc.load_course_looks(session, course_id)
                assert {(r.key, r.pose) for r in rows} == {
                    *(("mentor", pose) for pose in CHARACTER_POSES),
                    ("market", "backdrop"),
                }
                assert build_art_map(looks, rows).art["status"] == "ready"
                ids = {(r.key, r.pose): r.id for r in rows}

                # Nothing changed: nothing is drawn.
                second_images = FakeImages()
                assert (await run(second_images))["planned"] == 0
                assert second_images.calls == []

                # The place's look changed: only its backdrop is redrawn, under a new id.
                async with maker() as session:
                    record = await session.get(StoryCourseRecord, story.id)
                    record.content = {**SMALL_DOC, "places": [{"id": "market", "look": "new"}]}
                    await session.commit()
                third_images = FakeImages()
                await run(third_images)
                assert len(third_images.calls) == 1
                async with maker() as session:
                    rows = await svc.load_art_rows(session, course_id)
                    data = (
                        await session.execute(
                            sa.select(StoryArt.image_data).where(
                                StoryArt.key == "market", StoryArt.course_id == course_id
                            )
                        )
                    ).scalar_one()
                new_ids = {(r.key, r.pose): r.id for r in rows}
                assert len(rows) == 5
                assert new_ids[("market", "backdrop")] != ids[("market", "backdrop")]
                assert all(new_ids[k] == ids[k] for k in ids if k[0] == "mentor")
                assert is_webp(data)
            finally:
                await engine.dispose()

        asyncio.run(scenario())
