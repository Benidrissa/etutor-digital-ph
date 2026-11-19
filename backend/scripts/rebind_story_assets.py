#!/usr/bin/env python3
"""Show the course's own pictures in module stories that are already stored (#2709).

A stored module story names educational props (a poster, a score card) that
the player can only draw as a name tag, while the course owns the right
pictures: the figure of its PDF, the illustration of its lesson. This script
binds each such prop to the module's saved asset catalogue
(``app/domain/services/story_assets.py``) and puts its close-up before the
line that says "look" at it. **No model call is made**: the binding is by the
words a prop and a picture share, and the close-up is placed in code. The
story is validated again, and ``module_story.revision`` moves so that offline
copies refresh. The chapters are not touched, so none becomes stale.

**Dry run by default**: nothing is written without ``--apply``. Running it
twice is safe (a bound story is left as it is). ``--revert`` undoes a
binding: the props' kinds, the close-ups added or moved, the revision.

The catalogue must exist (a story generated since #2709 saved it). With
``--build-catalogue`` it is built first, from the course's lessons: that is
the only step that reads the figure binaries and calls the embeddings API (no
chat model), so it is off by default. A built catalogue is saved with
``--apply`` only. ``--exclude ID`` / ``--pin ID`` (an asset id) edit the
catalogue's exclusions and pins before binding; ``--exclude`` also unbinds
the asset on the next run with ``--revert`` then ``--apply``.

A story is skipped, and reported, when binding would add a validation error.

Usage (inside the backend container)::

    python scripts/rebind_story_assets.py --module <uuid>               # dry run
    python scripts/rebind_story_assets.py --all                         # dry run, every module story
    python scripts/rebind_story_assets.py --module <uuid> --apply
    python scripts/rebind_story_assets.py --module <uuid> --revert --apply
    python scripts/rebind_story_assets.py --all --json /tmp/rebind.json
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import sys
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select  # noqa: E402

from app.domain.services.story_assets import (  # noqa: E402
    in_course,
    rebind_document,
    revert_document,
)


def _counts(report: Any) -> tuple[int, int]:
    return len(report.errors), len(report.warnings)


def process_story(
    content: dict[str, Any],
    catalogue: dict[str, Any],
    *,
    revert: bool = False,
    validate=None,
) -> dict[str, Any]:
    """Re-bind (or revert) one stored story document. Pure: no database, no model.

    Returns ``{"doc", "changed", "bound", "inserted", "moved", "errors_before",
    "errors_after", "figures_before", "figures_after", "revision_before",
    "revision_after", "skipped"}``; ``doc`` is the new document (a copy), to
    be stored only when ``changed`` and not ``skipped``.
    """
    if validate is None:
        from app.domain.services.story_module_assembly import validate_module_story

        validate = validate_module_story
    doc = copy.deepcopy(content)
    before = validate(copy.deepcopy(doc))
    out: dict[str, Any] = {
        "bound": {},
        "inserted": [],
        "moved": [],
        "figures_before": before.checks.props.get("figures", 0)
        if isinstance(before.checks.props, dict)
        else 0,
        "revision_before": (doc.get("module_story") or {}).get("revision"),
        "skipped": None,
    }
    # Defence in depth: only pictures of the catalogue's own course are ever bound.
    source = catalogue.get("source")
    entries = [
        e
        for e in catalogue.get("entries") or []
        if e.get("kind") == "illustration" or in_course(e.get("source"), source)
    ]
    if revert:
        changed = revert_document(doc)
    else:
        result = rebind_document(doc, entries, binding=catalogue.get("binding") or {})
        changed = result.changed
        out.update(bound=result.bound, inserted=result.inserted, moved=result.moved)
    after = validate(copy.deepcopy(doc)) if changed else before
    if changed:
        doc["checks"] = after.checks.model_dump(mode="json")
    out.update(
        doc=doc,
        changed=changed,
        errors_before=len(before.errors),
        errors_after=len(after.errors),
        figures_after=after.checks.props.get("figures", 0)
        if isinstance(after.checks.props, dict)
        else 0,
        revision_after=(doc.get("module_story") or {}).get("revision"),
    )
    if changed and not revert and out["errors_after"] > out["errors_before"]:
        out["skipped"] = "binding would add validation errors"
    return out


def render(rows: list[dict[str, Any]], *, applied: bool, revert: bool) -> str:
    lines: list[str] = []
    for row in rows:
        head = f"module {row['module_id']} [{row['language']}]"
        if row.get("note"):
            lines.append(f"{head}: {row['note']}")
            continue
        lines.append(
            f"{head}: {'revert' if revert else 'bind'} "
            f"{'changed' if row['changed'] else 'unchanged'}; "
            f"figures {row['figures_before']} -> {row['figures_after']}; "
            f"errors {row['errors_before']} -> {row['errors_after']}; "
            f"revision {row['revision_before']} -> {row['revision_after']}"
        )
        for pid, asset in row["bound"].items():
            lines.append(f"  prop {pid} <- asset {asset}")
        for item in row["inserted"]:
            lines.append(f"  close-up of {item['prop']} added in {item['chapter']}/{item['scene']}")
        for item in row["moved"]:
            lines.append(
                f"  close-up of {item['prop']} moved up in {item['chapter']}/{item['scene']}"
            )
        if row["skipped"]:
            lines.append(f"  SKIPPED: {row['skipped']}")
    changed = sum(1 for r in rows if r.get("changed") and not r.get("skipped"))
    lines.append("")
    lines.append(("APPLIED" if applied else "DRY RUN (nothing written; pass --apply)") + ":")
    lines.append(f"  stories: {len(rows)}")
    lines.append(f"  changed: {changed}")
    lines.append(
        f"  unchanged: {sum(1 for r in rows if not r.get('changed') and not r.get('note'))}"
    )
    lines.append(f"  skipped: {sum(1 for r in rows if r.get('skipped'))}")
    lines.append(f"  without catalogue: {sum(1 for r in rows if r.get('note'))}")
    lines.append("  model calls: 0")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("--module", help="this module (uuid)")
    which.add_argument("--all", action="store_true", help="every stored module story")
    parser.add_argument("--language", choices=("fr", "en"), default=None)
    parser.add_argument("--apply", action="store_true", help="write (default: dry run)")
    parser.add_argument("--revert", action="store_true", help="undo a binding")
    parser.add_argument(
        "--build-catalogue",
        action="store_true",
        help="build the catalogue first (reads binaries, embeddings; saved with --apply)",
    )
    parser.add_argument("--exclude", action="append", default=[], help="exclude an asset id")
    parser.add_argument("--pin", action="append", default=[], help="pin an asset id")
    parser.add_argument("--json", default=None, help="also write the report to this file")
    return parser.parse_args(argv)


async def _build(session, module_id: uuid.UUID, previous: dict[str, Any] | None, language: str):
    """Build a module's catalogue from its lessons (the only step that reads the network)."""
    from app.ai.rag.embeddings import EmbeddingService
    from app.ai.rag.retriever import SemanticRetriever
    from app.domain.models.course import Course
    from app.domain.models.module import Module
    from app.domain.services.story_assets import build_catalogue
    from app.domain.services.story_from_lesson_service import select_unit_content_row
    from app.domain.services.story_module_service import load_story_units
    from app.infrastructure.config.settings import get_settings
    from app.infrastructure.storage.s3 import S3StorageService

    module = await session.get(Module, module_id)
    if module is None:
        return None
    course = await session.get(Course, module.course_id) if module.course_id else None
    units = []
    for unit in await load_story_units(session, module_id):
        if unit.role != "lesson":
            continue
        row = await select_unit_content_row(
            session, unit.module_unit_id, "lesson", language, 1, None
        )
        if row is None:
            continue
        units.append(
            {
                "unit_id": unit.module_unit_id,
                "unit_number": unit.unit_number,
                "title": unit.title,
                "lesson_id": row.id,
                "content": row.content or {},
            }
        )
    settings = get_settings()
    retriever = SemanticRetriever(
        EmbeddingService(api_key=settings.openai_api_key, model=settings.embedding_model)
    )
    return await build_catalogue(
        session,
        module_id=module_id,
        course_source=course.rag_collection_id if course is not None else None,
        course_id=course.id if course is not None else None,
        units=units,
        storage=S3StorageService(),
        retriever=retriever,
        previous=previous,
    )


async def main(argv: list[str] | None = None, session_factory=None, builder=None) -> int:
    args = parse_args(argv)
    if session_factory is None:
        from app.infrastructure.persistence.database import async_session_factory

        session_factory = async_session_factory
    builder = builder or _build

    from app.api.v1.schemas.story_course import StoryCourse
    from app.domain.models.story_course import StoryCourseRecord
    from app.domain.services.story_assets import load_catalogue, save_catalogue
    from app.domain.services.story_from_lesson_service import (
        ModuleStoryBinding,
        upsert_story_course,
    )
    from app.domain.services.story_module_assembly import validate_module_story

    rows: list[dict[str, Any]] = []
    async with session_factory() as session:
        query = select(StoryCourseRecord).where(
            StoryCourseRecord.module_id.is_not(None), StoryCourseRecord.module_unit_id.is_(None)
        )
        if args.module:
            query = query.where(StoryCourseRecord.module_id == uuid.UUID(args.module))
        if args.language:
            query = query.where(StoryCourseRecord.language == args.language)
        records = list((await session.execute(query.order_by(StoryCourseRecord.slug))).scalars())
        catalogues: dict[uuid.UUID, dict[str, Any] | None] = {}
        for record in records:
            module_id = record.module_id
            if module_id not in catalogues:
                catalogue = await load_catalogue(session, module_id)
                if args.build_catalogue:
                    catalogue = (
                        await builder(session, module_id, catalogue, record.language) or catalogue
                    )
                if catalogue is not None:
                    for asset in args.exclude:
                        if asset not in catalogue.setdefault("exclusions", []):
                            catalogue["exclusions"].append(asset)
                    for asset in args.pin:
                        if asset not in catalogue.setdefault("pins", []):
                            catalogue["pins"].append(asset)
                    catalogue["entries"] = [
                        e
                        for e in catalogue.get("entries", [])
                        if e.get("asset_id") not in catalogue["exclusions"]
                    ]
                catalogues[module_id] = catalogue
            catalogue = catalogues[module_id]
            row: dict[str, Any] = {"module_id": str(module_id), "language": record.language}
            if not catalogue or not catalogue.get("entries"):
                row["note"] = "no catalogue entries (generate the story, or --build-catalogue)"
                rows.append(row)
                continue
            outcome = process_story(
                record.content, catalogue, revert=args.revert, validate=validate_module_story
            )
            row.update({k: v for k, v in outcome.items() if k != "doc"})
            rows.append(row)
            if not (args.apply and outcome["changed"] and not outcome["skipped"]):
                continue
            doc = outcome["doc"]
            report = validate_module_story(copy.deepcopy(doc))
            await upsert_story_course(
                session,
                course=StoryCourse.model_validate(doc),
                content=doc,
                report=report,
                course_id=record.course_id,
                publish=report.ok,
                binding=ModuleStoryBinding(
                    module_id=module_id,
                    language=record.language,
                    source_rows=record.source_rows,
                    units_digest=record.source_units_digest,
                ),
            )
            if args.revert:
                catalogue["binding"] = {}
            else:
                catalogue["binding"] = {**(catalogue.get("binding") or {}), **outcome["bound"]}
        if args.apply:
            for module_id, catalogue in catalogues.items():
                if catalogue is not None:
                    await save_catalogue(session, module_id, catalogue)
            await session.commit()
        else:
            await session.rollback()

    print(render(rows, applied=args.apply, revert=args.revert))
    if args.json:
        Path(args.json).write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
