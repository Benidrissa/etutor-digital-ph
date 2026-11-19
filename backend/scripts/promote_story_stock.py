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
    ArtItem,
    load_course_looks,
)
from app.domain.services.story_stock_art import slot_candidates  # noqa: E402


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
            f"from {course}  /api/v1/story-art/{sid}/data"
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
    handlers = {"promote": promote, "list": list_stock, "approve": approve, "retire": retire}
    async with session_factory() as session:
        return await handlers[args.command](session, args)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
