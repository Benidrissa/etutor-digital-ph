#!/usr/bin/env python3
"""Regenerate lesson audio summaries affected by the empty-content bug.

The bug (fixed in PRs #1489 + #1492) caused audio generated via
pregenerate_on_publish, prefetch_next_lessons, and
generate_country_targeted_content to receive empty lesson text.
This script deletes those bad audio records and re-dispatches
generation with the correct lesson content.

Usage:
    # Dry run — report what would be deleted
    python scripts/regenerate_audio.py --dry-run

    # Target a specific course
    python scripts/regenerate_audio.py --course-slug intro-stats

    # Regenerate all
    python scripts/regenerate_audio.py
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from app.domain.models.content import GeneratedContent
from app.domain.models.course import Course
from app.domain.models.generated_audio import GeneratedAudio
from app.domain.models.module import Module
from app.domain.services.lesson_service import extract_lesson_text
from app.infrastructure.persistence.database import async_session_factory
from app.infrastructure.storage.s3 import S3StorageService


async def main(course_slug: str | None, dry_run: bool):
    storage = S3StorageService()

    async with async_session_factory() as session:
        # Build query: all "ready" audio, optionally filtered by course
        query = (
            select(GeneratedAudio)
            .where(GeneratedAudio.status == "ready")
            .options(selectinload(GeneratedAudio.module))
        )

        if course_slug:
            query = query.join(
                Module, GeneratedAudio.module_id == Module.id
            ).join(
                Course, Module.course_id == Course.id
            ).where(Course.slug == course_slug)

        result = await session.execute(query)
        audio_records = list(result.scalars().all())

        if not audio_records:
            print("No audio records found to regenerate.")
            return

        print(f"Found {len(audio_records)} audio records to regenerate.")

        # Collect lesson content for re-dispatch
        dispatch_list = []
        for audio in audio_records:
            lesson_content = None
            if audio.lesson_id:
                content_row = await session.get(
                    GeneratedContent, audio.lesson_id
                )
                if content_row and content_row.content:
                    lesson_content = extract_lesson_text(
                        content_row.content
                    )

            dispatch_list.append({
                "lesson_id": str(audio.lesson_id) if audio.lesson_id else None,
                "module_id": str(audio.module_id) if audio.module_id else None,
                "unit_id": audio.unit_id,
                "language": audio.language,
                "storage_key": audio.storage_key,
                "audio_id": str(audio.id),
                "lesson_text": (lesson_content or "")[:4000],
            })

        # Report
        for item in dispatch_list:
            has_text = "YES" if item["lesson_text"] else "NO"
            print(
                f"  {item['unit_id']}:{item['language']} "
                f"— lesson_text={has_text} "
                f"— storage={item['storage_key']}"
            )

        if dry_run:
            print(f"\n[DRY RUN] Would delete {len(audio_records)} "
                  f"audio records and re-dispatch generation.")
            return

        # Phase 1: Delete MinIO objects
        deleted_s3 = 0
        for item in dispatch_list:
            if item["storage_key"]:
                try:
                    await storage.delete_object(item["storage_key"])
                    deleted_s3 += 1
                except Exception as exc:
                    print(f"  Warning: failed to delete "
                          f"{item['storage_key']}: {exc}")
        print(f"Deleted {deleted_s3} MinIO objects.")

        # Phase 2: Delete DB rows
        audio_ids = [a.id for a in audio_records]
        await session.execute(
            delete(GeneratedAudio)
            .where(GeneratedAudio.id.in_(audio_ids))
        )
        await session.commit()
        print(f"Deleted {len(audio_ids)} DB records.")

        # Phase 3: Re-dispatch Celery tasks
        from app.tasks.content_generation import generate_lesson_audio

        dispatched = 0
        skipped = 0
        for item in dispatch_list:
            if not item["lesson_text"] or not item["lesson_id"]:
                skipped += 1
                print(
                    f"  Skipped {item['unit_id']}:{item['language']}"
                    f" — no lesson content found"
                )
                continue

            generate_lesson_audio.apply_async(
                kwargs={
                    "lesson_id": item["lesson_id"],
                    "module_id": item["module_id"],
                    "unit_id": item["unit_id"],
                    "language": item["language"],
                    "lesson_content": item["lesson_text"],
                },
                priority=5,
            )
            dispatched += 1

        print(f"\nDone: {dispatched} tasks dispatched, "
              f"{skipped} skipped (no lesson content).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Regenerate lesson audio affected by "
                    "empty-content bug"
    )
    parser.add_argument(
        "--course-slug",
        default=None,
        help="Only regenerate audio for this course (by slug)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be deleted without acting",
    )
    args = parser.parse_args()
    asyncio.run(main(args.course_slug, args.dry_run))
