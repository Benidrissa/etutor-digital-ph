#!/usr/bin/env python3
"""Promote an existing course's story art to shared stock, with a human review (#2714).

No image is drawn and no AI call is made: the images already stored for one
course (``story_art``) are copied into ``story_stock_art``, one slot per
cast role / variant and per place, so the other courses of the stack adopt
them instead of drawing their own (docs: ``app/domain/models/story_stock_art.py``).

**Dry run by default**: nothing is written without ``--apply``. Nothing becomes
stock without an explicit approval either: a promoted image is a ``candidate``
(never adopted, never served) until ``--approve`` names it.

Usage (inside the backend container)::

    # 1. what would be promoted from the course (reads only)
    python scripts/promote_story_stock.py promote --course <slug|uuid>
    # 2. write the candidates (idempotent: a slot that already has a live row is skipped)
    python scripts/promote_story_stock.py promote --course <slug|uuid> --apply
    # 3. review them: the list gives each image's URL path, once approved
    python scripts/promote_story_stock.py list
    # 4. approve what a human checked (skin tones, clothes, country); a slot
    #    with an approved image already gets the new one, the old one retired
    python scripts/promote_story_stock.py approve <stock id> [<stock id> ...] --apply
    python scripts/promote_story_stock.py approve --all-candidates --apply
    python scripts/promote_story_stock.py retire <stock id> --apply

Options of ``promote``: ``--pack`` (default ``west_africa``), ``--generic``
(places are stored for their theme alone, so any place of that theme adopts
them; by default a place is stored for its own id) and ``--only key,key``.
A character is promoted only when its four base poses are ready, drawn by the
course itself (a course that adopted stock is not a source).

Extra poses (#2741), all dry run by default, nothing is approved by them::

    # 6. the images that would be drawn (reads only, no AI call)
    python scripts/promote_story_stock.py draw-poses --pose surprised,sad
    # 7. draw them: one image edit per approved idle and pose (paid, ledger
    #    feature ``story_art``); each lands as a ``candidate`` in the slot
    python scripts/promote_story_stock.py draw-poses --pose surprised,sad --apply
    # 8. put each candidate beside its idle in a folder (reads only)
    python scripts/promote_story_stock.py review --out ./review
    # 9. courses that adopted a character before its new poses were approved
    #    (no AI call; writes only with --apply, ask the owner per stack)
    python scripts/promote_story_stock.py adopt-poses
    python scripts/promote_story_stock.py adopt-poses --apply
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select  # noqa: E402

from app.domain.models.story_art import (  # noqa: E402
    CHARACTER_POSES,
    EXTRA_CHARACTER_POSES,
    KIND_CHARACTER,
    KIND_PLACE,
    POSE_BACKDROP,
    POSE_IDLE,
    STATUS_READY,
    StoryArt,
)
from app.domain.models.story_stock_art import (  # noqa: E402
    DEFAULT_PACK,
    STOCK_APPROVED,
    STOCK_CANDIDATE,
    STOCK_RETIRED,
    StoryStockArt,
)
from app.domain.services.story_art_service import (  # noqa: E402
    ART_VERSION,
    ATTEMPTS_PER_IMAGE,
    CHARACTER_SIZE,
    EDIT_TIMEOUT_S,
    FEATURE_STORY_ART,
    SDK_MAX_RETRIES,
    ArtItem,
    failure_is_config,
    load_course_looks,
    pose_prompt,
    process_character,
    rate_limit_wait,
    stored_reference,
)
from app.domain.services.story_stock_art import (  # noqa: E402
    StockImage,
    slot_candidates,
    stock_row,
)


@dataclass
class Promotion:
    """One stock image to create."""

    kind: str
    theme: str
    variant: str
    pose: str
    art_id: uuid.UUID
    item_key: str
    look: str


def plan_promotion(
    items: list[ArtItem], rows: list[Any], taken: set[tuple[str, str, str, str]], *, generic: bool
) -> tuple[list[Promotion], list[str]]:
    """What to promote from a course, and why anything is left out (pure).

    ``rows``: the course's ``story_art`` rows; ``taken``: ``(kind, theme,
    variant, pose)`` of the live stock rows of the pack, which are not
    replaced. Items with no role (or place theme) have no slot.
    """
    by_item = {(row.kind, row.key, row.pose): row for row in rows}
    promotions: list[Promotion] = []
    notes: list[str] = []
    for item in items:
        slots = slot_candidates(item.kind, item.key, item.role, item.variant, item.look)
        if not slots:
            notes.append(f"{item.kind} {item.key}: no stock slot (no role or place theme)")
            continue
        kind, theme, variant = slots[-1] if generic and item.kind == KIND_PLACE else slots[0]
        poses = (POSE_BACKDROP,) if item.kind == KIND_PLACE else CHARACTER_POSES
        own = []
        for pose in (*poses, *(EXTRA_CHARACTER_POSES if item.kind == KIND_CHARACTER else ())):
            row = by_item.get((item.kind, item.key, pose))
            if (
                row is not None
                and row.status == STATUS_READY
                and not getattr(row, "stock_id", None)
                and row.art_version >= ART_VERSION
                and row.look_digest == item.digest
            ):
                own.append((pose, row))
        have = {pose for pose, _row in own}
        if not set(poses) <= have:
            missing = sorted(set(poses) - have)
            notes.append(f"{item.kind} {item.key}: not promoted, poses not ready: {missing}")
            continue
        if any((kind, theme, variant, pose) in taken for pose, _row in own):
            notes.append(f"{item.kind} {item.key}: slot {theme}/{variant or '-'} already has stock")
            continue
        promotions.extend(
            Promotion(kind, theme, variant, pose, row.id, item.key, item.look) for pose, row in own
        )
    return promotions, notes


async def find_course_id(session, ref: str) -> uuid.UUID | None:
    from app.domain.models.course import Course

    try:
        return (
            await session.execute(select(Course.id).where(Course.id == uuid.UUID(ref)))
        ).scalar_one_or_none()
    except ValueError:
        return (
            await session.execute(select(Course.id).where(Course.slug == ref))
        ).scalar_one_or_none()


async def promote(session, args) -> int:
    course_id = await find_course_id(session, args.course)
    if course_id is None:
        print(f"course {args.course!r} not found", file=sys.stderr)
        return 2
    looks = await load_course_looks(session, course_id)
    items = [
        item
        for item in looks.items
        if not args.only or item.key in {k.strip() for k in args.only.split(",")}
    ]
    rows = list(
        (await session.execute(select(StoryArt).where(StoryArt.course_id == course_id)))
        .scalars()
        .all()
    )
    live = await session.execute(
        select(
            StoryStockArt.kind, StoryStockArt.theme, StoryStockArt.variant, StoryStockArt.pose
        ).where(StoryStockArt.pack == args.pack, StoryStockArt.status != STOCK_RETIRED)
    )
    taken = {tuple(row) for row in live.all()}
    promotions, notes = plan_promotion(items, rows, taken, generic=args.generic)
    for note in notes:
        print(note)
    for promo in promotions:
        print(
            f"promote {promo.kind} {promo.item_key} {promo.pose} -> "
            f"{args.pack}/{promo.theme}/{promo.variant or '-'}"
        )
    print(f"{len(promotions)} images to promote as candidates.")
    if not args.apply:
        print("Dry run: nothing written (use --apply).")
        return 0
    by_id = {row.id: row for row in rows}
    for promo in promotions:
        source = by_id[promo.art_id]
        data = (
            await session.execute(select(StoryArt.image_data).where(StoryArt.id == source.id))
        ).scalar_one()
        session.add(
            StoryStockArt(
                id=uuid.uuid4(),
                kind=promo.kind,
                theme=promo.theme,
                variant=promo.variant,
                pack=args.pack,
                pose=promo.pose,
                status=STOCK_CANDIDATE,
                image_data=data,
                width=source.width,
                height=source.height,
                content_sha256=hashlib.sha256(data).hexdigest(),
                model=source.model,
                look=promo.look,
                source_course_id=course_id,
                source_art_id=source.id,
            )
        )
    await session.commit()
    print("Candidates written. Review them (list), then approve.")
    return 0


# -- Extra poses for approved stock characters (#2741) -------------------------


@dataclass
class PoseDraw:
    """One extra pose to draw from an approved stock idle."""

    idle_id: uuid.UUID
    pack: str
    theme: str
    variant: str
    pose: str
    look: str


def parse_poses(text: str) -> list[str]:
    """The ``--pose`` list, checked against the poses stock may hold (pure)."""
    poses = [p.strip() for p in text.split(",") if p.strip()]
    bad = [p for p in poses if p not in EXTRA_CHARACTER_POSES]
    if not poses or bad:
        raise ValueError(
            f"--pose takes some of {', '.join(EXTRA_CHARACTER_POSES)} (got {bad or text!r})"
        )
    return list(dict.fromkeys(poses))


def plan_pose_draws(
    idles: list[Any], live: set[tuple[str, str, str, str, str]], poses: list[str]
) -> tuple[list[PoseDraw], list[str]]:
    """What to draw: each approved idle x each pose not live in its slot (pure).

    ``idles``: approved idle rows (``id, pack, theme, variant, look``);
    ``live``: ``(pack, kind, theme, variant, pose)`` of every candidate or
    approved row, so a pose already drawn, pending or approved is skipped and
    an approved image is never replaced.
    """
    draws: list[PoseDraw] = []
    notes: list[str] = []
    for idle in idles:
        slot = f"{idle.pack}/{idle.theme}/{idle.variant or '-'}"
        if not idle.look:
            notes.append(f"{slot}: skipped, the idle has no stored look")
            continue
        for pose in poses:
            if (idle.pack, KIND_CHARACTER, idle.theme, idle.variant, pose) in live:
                notes.append(f"{slot}/{pose}: skipped, already a candidate or approved")
                continue
            draws.append(PoseDraw(idle.id, idle.pack, idle.theme, idle.variant, pose, idle.look))
    return draws, notes


async def _idles_and_live(session, pack: str):
    idles = (
        (
            await session.execute(
                select(StoryStockArt)
                .where(
                    StoryStockArt.kind == KIND_CHARACTER,
                    StoryStockArt.pose == POSE_IDLE,
                    StoryStockArt.status == STOCK_APPROVED,
                    StoryStockArt.pack == pack,
                )
                .order_by(StoryStockArt.theme, StoryStockArt.variant)
            )
        )
        .scalars()
        .all()
    )
    live = await session.execute(
        select(
            StoryStockArt.pack,
            StoryStockArt.kind,
            StoryStockArt.theme,
            StoryStockArt.variant,
            StoryStockArt.pose,
        ).where(StoryStockArt.pack == pack, StoryStockArt.status != STOCK_RETIRED)
    )
    return list(idles), {tuple(row) for row in live.all()}


async def _edit_with_attempts(edit, prompt: str, reference: bytes, model: str, sleep):
    """One image edit with the run's settings: at most ATTEMPTS_PER_IMAGE paid tries."""
    last: BaseException | None = None
    for attempt in range(1, ATTEMPTS_PER_IMAGE + 1):
        try:
            raw, used = await edit(
                prompt,
                reference,
                model=model,
                size=CHARACTER_SIZE,
                background="transparent",
                max_retries=SDK_MAX_RETRIES,
                timeout=EDIT_TIMEOUT_S,
            )
            data, width, height = await asyncio.to_thread(process_character, raw)
            return data, width, height, used
        except Exception as exc:
            last = exc
            print(f"  attempt {attempt} failed: {exc}", file=sys.stderr)
            if failure_is_config(exc):
                break  # the same model would fail the same way: no second call
            wait = rate_limit_wait(exc)
            if wait and attempt < ATTEMPTS_PER_IMAGE:
                await sleep(wait)
    raise RuntimeError(f"no image after {ATTEMPTS_PER_IMAGE} attempts: {last}")


async def draw_poses(session, args, *, edit=None, model: str | None = None, sleep=None) -> int:
    """Draw extra poses of the approved idles into candidate stock rows.

    Dry run unless ``--apply``. ``edit`` and ``model`` are injectable for tests;
    otherwise the image provider and the ``ai-model-image`` setting are used.
    """
    try:
        poses = parse_poses(args.pose)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    idles, live = await _idles_and_live(session, args.pack)
    draws, notes = plan_pose_draws(idles, live, poses)
    for note in notes:
        print(note)
    for d in draws:
        print(f"draw {d.pose} for {d.pack}/{d.theme}/{d.variant or '-'} (idle {d.idle_id})")
    print(f"{len(draws)} images to draw as candidates (at most {ATTEMPTS_PER_IMAGE} tries each).")
    if not args.apply:
        print("Dry run: nothing drawn, nothing written (use --apply).")
        return 0
    if edit is None:
        from app.ai.providers.image_provider import DEFAULT_IMAGE_MODEL, edit_image
        from app.ai.usage_context import set_ai_context
        from app.domain.services.platform_settings_service import SettingsCache

        edit = edit_image
        model = model or SettingsCache.instance().get("ai-model-image", DEFAULT_IMAGE_MODEL)
        set_ai_context(FEATURE_STORY_ART)  # ledger, as tasks/story_art.py
    sleep = sleep or asyncio.sleep
    by_id = {row.id: row for row in idles}
    done = failed = 0
    for d in draws:
        data_idle = (
            await session.execute(
                select(StoryStockArt.image_data).where(StoryStockArt.id == d.idle_id)
            )
        ).scalar_one()
        try:
            reference = await asyncio.to_thread(stored_reference, data_idle)
            data, width, height, used = await _edit_with_attempts(
                edit, pose_prompt(d.look, d.pose), reference, model, sleep
            )
        except Exception as exc:
            failed += 1
            print(f"FAILED {d.theme}/{d.variant or '-'}/{d.pose}: {exc}", file=sys.stderr)
            continue
        idle = by_id[d.idle_id]
        session.add(
            StoryStockArt(
                id=uuid.uuid4(),
                kind=KIND_CHARACTER,
                theme=d.theme,
                variant=d.variant,
                pack=d.pack,
                pose=d.pose,
                status=STOCK_CANDIDATE,
                image_data=data,
                width=width,
                height=height,
                content_sha256=hashlib.sha256(data).hexdigest(),
                model=used,
                look=idle.look,
                source_course_id=None,
                source_art_id=idle.id,  # the idle's stock id (plain id, no foreign key)
            )
        )
        await session.commit()  # one image at a time: a later failure keeps the paid ones
        done += 1
        print(f"candidate written {d.theme}/{d.variant or '-'}/{d.pose}")
    print(f"{done} candidates written, {failed} failed (rerun to redraw only those).")
    return 0 if not failed else 1


def _contact_sheet(pairs: list[tuple[str, bytes, bytes]]):
    """One image: a row per candidate, idle on the left, the new pose on the right."""
    import io

    from PIL import Image, ImageDraw

    cell = 360
    label = 22
    sheet = Image.new("RGB", (2 * cell, len(pairs) * (cell + label)), (235, 235, 235))
    draw = ImageDraw.Draw(sheet)
    for i, (name, idle, cand) in enumerate(pairs):
        top = i * (cell + label)
        draw.text((6, top + 5), name, fill=(0, 0, 0))
        for col, raw in enumerate((idle, cand)):
            image = Image.open(io.BytesIO(raw)).convert("RGBA")
            image.thumbnail((cell - 8, cell - 8))
            sheet.paste(image, (col * cell + 4, top + label + cell - 4 - image.height), image)
    return sheet


async def review(session, args) -> int:
    """Write each candidate beside its idle into ``--out`` (reads only)."""
    out = Path(args.out)
    cands = (
        (
            await session.execute(
                select(StoryStockArt)
                .where(
                    StoryStockArt.status == STOCK_CANDIDATE, StoryStockArt.kind == KIND_CHARACTER
                )
                .order_by(StoryStockArt.theme, StoryStockArt.variant, StoryStockArt.pose)
            )
        )
        .scalars()
        .all()
    )
    pairs: list[tuple[str, bytes, bytes]] = []
    for cand in cands:
        if cand.pose not in EXTRA_CHARACTER_POSES:
            continue
        idle = None
        if cand.source_art_id:
            idle = (
                await session.execute(
                    select(StoryStockArt).where(StoryStockArt.id == cand.source_art_id)
                )
            ).scalar_one_or_none()
        if idle is None:  # the slot's live idle
            idle = (
                await session.execute(
                    select(StoryStockArt).where(
                        StoryStockArt.kind == cand.kind,
                        StoryStockArt.theme == cand.theme,
                        StoryStockArt.variant == cand.variant,
                        StoryStockArt.pack == cand.pack,
                        StoryStockArt.pose == POSE_IDLE,
                        StoryStockArt.status != STOCK_RETIRED,
                    )
                )
            ).scalar_one_or_none()
        if idle is None:
            print(f"{cand.id}: no idle to compare with, skipped", file=sys.stderr)
            continue
        name = f"{cand.theme}-{cand.variant or 'any'}-{cand.pose}"
        pairs.append((f"{name}  id {cand.id}", idle.image_data, cand.image_data))
        print(
            f"{cand.id}  {cand.pack}/{cand.theme}/{cand.variant or '-'}/{cand.pose}  {cand.model}"
        )
    if not pairs:
        print("No candidate pose to review.")
        return 0
    out.mkdir(parents=True, exist_ok=True)
    sheet = _contact_sheet(pairs)
    sheet.save(out / "contact-sheet.png")
    print(f"{len(pairs)} candidates; contact sheet: {out / 'contact-sheet.png'}")
    print("Approve what a person checked (face, skin tone, outfit): approve <id> --apply")
    return 0


@dataclass
class PoseAdoption:
    course_id: uuid.UUID
    key: str
    pose: str
    digest: str
    art_version: int
    image: StockImage


def plan_pose_adoptions(
    adopters: list[Any],
    approved: dict[tuple[str, str, str], dict[str, uuid.UUID]],
    have: set[tuple[uuid.UUID, str, str]],
) -> list[PoseAdoption]:
    """Rows to give the courses that adopted a character (pure).

    ``adopters``: the courses' adopted idle rows (``course_id, key,
    look_digest, art_version, pack, theme, variant``); ``approved``: ``(pack,
    theme, variant)`` -> pose -> approved stock id; ``have``: ``(course_id,
    key, pose)`` rows that exist. Only approved extra poses, only the missing.
    """
    out: list[PoseAdoption] = []
    for row in adopters:
        images = approved.get((row.pack, row.theme, row.variant), {})
        for pose in EXTRA_CHARACTER_POSES:
            if pose in images and (row.course_id, row.key, pose) not in have:
                out.append(
                    PoseAdoption(
                        row.course_id,
                        row.key,
                        pose,
                        row.look_digest,
                        row.art_version,
                        StockImage(images[pose], pose),
                    )
                )
    return out


async def adopt_poses(session, args) -> int:
    """Give courses that adopted a stock character the rows of its new poses.

    No image call. Dry run unless ``--apply``; run it on a stack only with the
    owner's go-ahead for that stack. Story text is never touched.
    """
    adopters = (
        await session.execute(
            select(
                StoryArt.course_id,
                StoryArt.key,
                StoryArt.look_digest,
                StoryArt.art_version,
                StoryStockArt.pack,
                StoryStockArt.theme,
                StoryStockArt.variant,
            )
            .join(StoryStockArt, StoryStockArt.id == StoryArt.stock_id)
            .where(
                StoryArt.kind == KIND_CHARACTER,
                StoryArt.pose == POSE_IDLE,
                StoryArt.status == STATUS_READY,
                StoryStockArt.pack == args.pack,
            )
        )
    ).all()
    approved: dict[tuple[str, str, str], dict[str, uuid.UUID]] = {}
    for sid, pack, theme, variant, pose in (
        await session.execute(
            select(
                StoryStockArt.id,
                StoryStockArt.pack,
                StoryStockArt.theme,
                StoryStockArt.variant,
                StoryStockArt.pose,
            ).where(
                StoryStockArt.kind == KIND_CHARACTER,
                StoryStockArt.status == STOCK_APPROVED,
                StoryStockArt.pack == args.pack,
                StoryStockArt.pose.in_(EXTRA_CHARACTER_POSES),
            )
        )
    ).all():
        approved.setdefault((pack, theme, variant), {})[pose] = sid
    have = {
        (c, k, p)
        for c, k, p in (
            await session.execute(
                select(StoryArt.course_id, StoryArt.key, StoryArt.pose).where(
                    StoryArt.kind == KIND_CHARACTER, StoryArt.pose.in_(EXTRA_CHARACTER_POSES)
                )
            )
        ).all()
    }
    plan = plan_pose_adoptions(list(adopters), approved, have)
    courses = {p.course_id for p in plan}
    print(f"{len(courses)} courses, {len(plan)} rows to add (no image call).")
    if not args.apply:
        print("Dry run: nothing written (use --apply).")
        return 0
    for p in plan:
        session.add(
            stock_row(p.course_id, KIND_CHARACTER, p.key, p.pose, p.digest, p.image, p.art_version)
        )
    await session.commit()
    print("Rows written.")
    return 0


async def list_stock(session, args) -> int:
    rows = await session.execute(
        select(
            StoryStockArt.id,
            StoryStockArt.status,
            StoryStockArt.pack,
            StoryStockArt.kind,
            StoryStockArt.theme,
            StoryStockArt.variant,
            StoryStockArt.pose,
            StoryStockArt.width,
            StoryStockArt.height,
            StoryStockArt.source_course_id,
        ).order_by(
            StoryStockArt.pack, StoryStockArt.kind, StoryStockArt.theme, StoryStockArt.variant
        )
    )
    count = 0
    for sid, status, pack, kind, theme, variant, pose, w, h, course in rows.all():
        count += 1
        print(
            f"{sid}  {status:<9} {pack}/{kind}/{theme}/{variant or '-'}/{pose}  {w}x{h}  "
            f"from {course}  "
            + (
                "(candidate: not served, use the review command)"
                if status == STOCK_CANDIDATE
                else f"/api/v1/story-art/{sid}/data"
            )
        )
    print(f"{count} stock images.")
    return 0


async def approve(session, args) -> int:
    from sqlalchemy import func

    ids = [uuid.UUID(i) for i in args.ids]
    query = select(StoryStockArt).where(StoryStockArt.status == STOCK_CANDIDATE)
    if not args.all_candidates:
        query = query.where(StoryStockArt.id.in_(ids))
    elif ids:
        print("give ids or --all-candidates, not both", file=sys.stderr)
        return 2
    candidates = list((await session.execute(query)).scalars().all())
    if not args.all_candidates and len(candidates) != len(set(ids)):
        print("some ids are not candidates (unknown, approved or retired)", file=sys.stderr)
        return 2
    retired = 0
    for cand in candidates:
        old = (
            (
                await session.execute(
                    select(StoryStockArt).where(
                        StoryStockArt.kind == cand.kind,
                        StoryStockArt.theme == cand.theme,
                        StoryStockArt.variant == cand.variant,
                        StoryStockArt.pack == cand.pack,
                        StoryStockArt.pose == cand.pose,
                        StoryStockArt.status == STOCK_APPROVED,
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in old:
            row.status = STOCK_RETIRED
            retired += 1
        if old and args.apply:
            await session.flush()  # free the slot's unique index before approving
        print(
            f"approve {cand.id} {cand.pack}/{cand.kind}/{cand.theme}/{cand.variant or '-'}/{cand.pose}"
        )
        cand.status = STOCK_APPROVED
        cand.approved_at = func.now()
    print(f"{len(candidates)} to approve, {retired} previous images retired.")
    if not args.apply:
        print("Dry run: nothing written (use --apply).")
        await session.rollback()
        return 0
    await session.commit()
    return 0


async def retire(session, args) -> int:
    rows = list(
        (
            await session.execute(
                select(StoryStockArt).where(StoryStockArt.id.in_([uuid.UUID(i) for i in args.ids]))
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        print(f"retire {row.id} {row.pack}/{row.kind}/{row.theme}/{row.variant or '-'}/{row.pose}")
        row.status = STOCK_RETIRED
    if not args.apply:
        print("Dry run: nothing written (use --apply).")
        await session.rollback()
        return 0
    await session.commit()
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("promote", help="copy a course's ready art into candidate stock")
    p.add_argument("--course", required=True, help="course slug or id")
    p.add_argument("--pack", default=DEFAULT_PACK)
    p.add_argument("--generic", action="store_true", help="store places for their theme alone")
    p.add_argument("--only", default="", help="comma-separated art keys")
    p.add_argument("--apply", action="store_true")
    sub.add_parser("list", help="every stock image and its status")
    d = sub.add_parser(
        "draw-poses",
        help="draw extra poses of the approved idles as candidates (paid; dry run by default)",
        description=(
            "For each approved idle of the pack, edit it into each --pose and write a "
            "'candidate' row in the same slot: source_course_id is empty and source_art_id "
            "holds the idle's stock id (a plain id, no foreign key). A pose already live "
            "(candidate or approved) is skipped; an approved image is never replaced. "
            "Approving a candidate (approve) is what makes courses adopt it."
        ),
    )
    d.add_argument("--pose", default=",".join(EXTRA_CHARACTER_POSES), help="surprised,sad")
    d.add_argument("--pack", default=DEFAULT_PACK)
    d.add_argument("--apply", action="store_true", help="spend: call the image model")
    r = sub.add_parser("review", help="write each candidate pose beside its idle (reads only)")
    r.add_argument("--out", default="story-stock-review", help="folder for the contact sheet")
    a = sub.add_parser(
        "adopt-poses",
        help="give courses that adopted a stock character its new approved poses (no AI call)",
    )
    a.add_argument("--pack", default=DEFAULT_PACK)
    a.add_argument("--apply", action="store_true")
    for name in ("approve", "retire"):
        q = sub.add_parser(name)
        q.add_argument("ids", nargs="*")
        if name == "approve":
            q.add_argument("--all-candidates", action="store_true")
        q.add_argument("--apply", action="store_true")
    return parser.parse_args(argv)


async def main(argv: list[str] | None = None, session_factory=None) -> int:
    args = parse_args(argv)
    if session_factory is None:
        from app.infrastructure.persistence.database import async_session_factory

        session_factory = async_session_factory
    handlers = {
        "promote": promote,
        "list": list_stock,
        "approve": approve,
        "retire": retire,
        "draw-poses": draw_poses,
        "review": review,
        "adopt-poses": adopt_poses,
    }
    async with session_factory() as session:
        return await handlers[args.command](session, args)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
