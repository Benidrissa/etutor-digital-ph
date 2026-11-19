"""Surprised and sad poses for the stock characters (#2741).

Every image call is a fake; nothing here reaches a paid API or a database.
"""

from __future__ import annotations

import importlib.util
import io
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from app.domain.models.story_art import CHARACTER_POSES, EXTRA_CHARACTER_POSES
from app.domain.services import story_art_service as svc
from app.domain.services.story_art_service import ArtItem, build_art_map, plan_art, pose_prompt

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "promote_story_stock.py"
_spec = importlib.util.spec_from_file_location("promote_story_stock_poses", _SCRIPT)
script = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = script
_spec.loader.exec_module(script)

LOOK = "a girl of about nine in a yellow dress"


def _webp(colour=(200, 50, 50, 255)) -> bytes:
    buffer = io.BytesIO()
    image = Image.new("RGBA", (200, 300), (0, 0, 0, 0))
    image.paste(Image.new("RGBA", (100, 200), colour), (50, 50))
    image.save(buffer, format="WEBP")
    return buffer.getvalue()


def _png() -> bytes:
    buffer = io.BytesIO()
    image = Image.new("RGBA", (400, 600), (0, 0, 0, 0))
    image.paste(Image.new("RGBA", (200, 400), (10, 120, 60, 255)), (100, 100))
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _idle(theme="hero", variant="girl", pack="west_africa", look=LOOK):
    return SimpleNamespace(
        id=uuid.uuid4(), pack=pack, theme=theme, variant=variant, look=look, image_data=_webp()
    )


class TestPrompts:
    @pytest.mark.parametrize("pose", EXTRA_CHARACTER_POSES)
    def test_the_prompt_exists_and_keeps_the_height_rule(self, pose):
        assert pose in svc.POSE_CHANGES
        prompt = pose_prompt(LOOK, pose)
        assert LOOK in prompt and "Change only the facial expression and the arms" in prompt
        assert "no higher than" in svc.POSE_CHANGES[pose]

    def test_a_run_still_draws_four_poses_and_the_art_version_is_unchanged(self):
        assert CHARACTER_POSES == ("idle", "talk", "happy", "think")
        assert svc.ART_VERSION == 2
        item = ArtItem("character", "mentor", LOOK, "mentor")
        jobs = plan_art([item], [])
        assert [job.poses for job in jobs] == [CHARACTER_POSES]

    def test_a_course_with_no_extra_pose_serves_the_four(self):
        item = ArtItem("character", "mentor", LOOK, "mentor")
        rows = [
            SimpleNamespace(
                id=uuid.uuid4(),
                kind="character",
                key="mentor",
                pose=pose,
                look_digest=item.digest,
                status="ready",
                art_version=svc.ART_VERSION,
                model="m",
                error=None,
                failed_runs=0,
                retry_after=None,
                stock_id=None,
            )
            for pose in CHARACTER_POSES
        ]
        poses = build_art_map([item], rows).art["characters"]["mentor"]
        assert set(poses) == set(CHARACTER_POSES)


class TestPlan:
    def test_six_idles_two_poses_make_twelve_images(self):
        idles = [_idle(theme=t) for t in ("hero", "friend", "mentor", "family", "tutor", "x")]
        draws, notes = script.plan_pose_draws(idles, set(), ["surprised", "sad"])
        assert len(draws) == 12 and notes == []

    def test_a_live_pose_is_skipped_and_a_retired_one_is_not_live(self):
        idle = _idle()
        live = {("west_africa", "character", "hero", "girl", "sad")}
        draws, notes = script.plan_pose_draws([idle], live, ["surprised", "sad"])
        assert [d.pose for d in draws] == ["surprised"]
        assert any("already" in n for n in notes)

    def test_an_idle_without_a_look_is_skipped(self):
        draws, notes = script.plan_pose_draws([_idle(look=None)], set(), ["sad"])
        assert draws == [] and "no stored look" in notes[0]

    def test_only_the_extra_poses_are_accepted(self):
        assert script.parse_poses("surprised, sad,sad") == ["surprised", "sad"]
        with pytest.raises(ValueError):
            script.parse_poses("walk")


class _Result:
    def __init__(self, value):
        self._value = value

    def scalar_one(self):
        return self._value


class _Session:
    def __init__(self, idle_bytes):
        self.idle_bytes = idle_bytes
        self.added: list = []
        self.commits = 0

    async def execute(self, _query):
        return _Result(self.idle_bytes)

    def add(self, row):
        self.added.append(row)

    async def commit(self):
        self.commits += 1


class _Edit:
    def __init__(self, fail_first=0):
        self.calls: list[tuple[str, dict]] = []
        self.fail_first = fail_first

    async def __call__(self, prompt, image, **kwargs):
        self.calls.append((prompt, kwargs))
        if len(self.calls) <= self.fail_first:
            raise RuntimeError("boom")
        return _png(), "fake-model"


@pytest.fixture
def one_idle(monkeypatch):
    idle = _idle()

    async def fake(_session, _pack):
        return [idle], set()

    monkeypatch.setattr(script, "_idles_and_live", fake)
    return idle


def _args(*extra):
    return script.parse_args(["draw-poses", *extra])


class TestDrawPoses:
    async def test_dry_run_draws_nothing_and_writes_nothing(self, one_idle, capsys):
        edit, session = _Edit(), _Session(_webp())
        assert await script.draw_poses(session, _args(), edit=edit, model="m") == 0
        assert edit.calls == [] and session.added == []
        assert "2 images to draw" in capsys.readouterr().out

    async def test_apply_writes_candidates_in_the_idles_slot(self, one_idle):
        edit, session = _Edit(), _Session(_webp())

        async def no_sleep(_s):
            return None

        code = await script.draw_poses(
            session, _args("--apply"), edit=edit, model="m", sleep=no_sleep
        )
        assert code == 0 and len(edit.calls) == 2
        prompt, kwargs = edit.calls[0]
        assert prompt == pose_prompt(LOOK, "surprised")
        assert kwargs["timeout"] == svc.EDIT_TIMEOUT_S and kwargs["max_retries"] == 0
        assert kwargs["model"] == "m"
        assert [r.pose for r in session.added] == ["surprised", "sad"]
        for row in session.added:
            assert row.status == "candidate"
            assert (row.kind, row.theme, row.variant, row.pack) == (
                "character",
                "hero",
                "girl",
                "west_africa",
            )
            assert row.source_course_id is None and row.source_art_id == one_idle.id
            assert row.look == LOOK and row.model == "fake-model"
            assert Image.open(io.BytesIO(row.image_data)).format == "WEBP"
        assert session.commits == 2

    async def test_a_failed_image_is_retried_once_then_reported(self, one_idle):
        edit, session = _Edit(fail_first=100), _Session(_webp())

        async def no_sleep(_s):
            return None

        code = await script.draw_poses(
            session, _args("--apply", "--pose", "sad"), edit=edit, model="m", sleep=no_sleep
        )
        assert code == 1 and session.added == []
        assert len(edit.calls) == svc.ATTEMPTS_PER_IMAGE


class TestReview:
    def test_the_contact_sheet_has_a_row_per_candidate(self):
        sheet = script._contact_sheet([("a", _webp(), _webp()), ("b", _webp(), _webp())])
        assert sheet.width == 720 and sheet.height == 2 * (360 + 22)


class TestAdoption:
    def _adopter(self, course, key="hero:girl"):
        return SimpleNamespace(
            course_id=course,
            key=key,
            look_digest="d",
            art_version=2,
            pack="west_africa",
            theme="hero",
            variant="girl",
        )

    def test_adds_only_the_approved_missing_poses(self):
        c1, c2 = uuid.uuid4(), uuid.uuid4()
        sad, surprised = uuid.uuid4(), uuid.uuid4()
        approved = {("west_africa", "hero", "girl"): {"sad": sad, "surprised": surprised}}
        have = {(c2, "hero:girl", "sad")}
        plan = script.plan_pose_adoptions([self._adopter(c1), self._adopter(c2)], approved, have)
        assert sorted((p.course_id == c1, p.pose) for p in plan) == [
            (False, "surprised"),
            (True, "sad"),
            (True, "surprised"),
        ]
        assert {p.image.id for p in plan} == {sad, surprised}

    def test_nothing_without_an_approved_pose(self):
        assert script.plan_pose_adoptions([self._adopter(uuid.uuid4())], {}, set()) == []

    def test_a_second_run_adds_nothing(self):
        c = uuid.uuid4()
        approved = {("west_africa", "hero", "girl"): {"sad": uuid.uuid4()}}
        assert (
            script.plan_pose_adoptions([self._adopter(c)], approved, {(c, "hero:girl", "sad")})
            == []
        )
