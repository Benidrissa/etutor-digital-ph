"""Celery task for RAG indexation — processes course PDFs into vector embeddings."""

import time
import uuid
from pathlib import Path

import structlog
from celery import Task
from celery.exceptions import SoftTimeLimitExceeded, TimeLimitExceeded, WorkerLostError
from celery.signals import task_failure

from app.tasks.celery_app import celery_app

logger = structlog.get_logger(__name__)

UPLOAD_DIR = Path("uploads/course_resources")

_BYTES_PER_SECOND_ESTIMATE = 50_000
_CHUNK_EMBED_SECONDS_ESTIMATE = 0.05

# Stop starting new work this long before the soft time limit, so the in-flight
# image (several AI calls) and the linker can finish before Celery's signal fires.
_DEADLINE_MARGIN_SECONDS = 300


def indexation_deadline(task: Task, started_at: float) -> float | None:
    """Monotonic time after which an indexation task must stop starting new work.

    Celery's soft limit raises ``SoftTimeLimitExceeded`` (an ``Exception``) from a
    signal handler wherever the main thread happens to be. When that is sync code
    inside an ``except Exception`` block — PyMuPDF extraction, the per-image
    ``update_state`` — it is swallowed, the task runs on, and the hard limit
    SIGKILLs it with the course wedged at 'indexing'. Stopping on our own
    deadline first makes the signal a backstop only. See #2659.
    """
    timelimit = getattr(task.request, "timelimit", None) or (None, None)
    soft = timelimit[1] or task.soft_time_limit
    if not soft:
        return None
    return started_at + max(soft - _DEADLINE_MARGIN_SECONDS, soft / 2)


def connect_kill_finalizer(task: Task, *, transition: tuple[str, str] | None = None) -> None:
    """Finalize indexation state when the worker kills *task* outright.

    A hard time limit (SIGKILL) or a lost worker (OOM) never runs the task's own
    ``on_failure`` — the child process is gone — so the course keeps a dangling
    ``indexation_task_id`` and the wizard wedges. Celery still sends
    ``task_failure`` from the worker's main process in both cases, so finalize
    from there. Ordinary failures already went through ``on_failure``. See #2659.
    """

    def _receiver(sender=None, exception=None, args=None, kwargs=None, **_):
        if getattr(sender, "name", None) != task.name:
            return
        if not isinstance(exception, (TimeLimitExceeded, WorkerLostError)):
            return
        course_id = args[0] if args else (kwargs or {}).get("course_id")
        logger.warning(
            "Indexation task killed by worker — finalizing state",
            task=task.name,
            course_id=course_id,
            exception=repr(exception),
        )
        finalize_indexation_state(course_id, transition=transition)

    task_failure.connect(_receiver, weak=False)


def _estimate_seconds(pdf_files: list[Path]) -> int:
    total_bytes = sum(p.stat().st_size for p in pdf_files if p.exists())
    extraction_s = total_bytes / _BYTES_PER_SECOND_ESTIMATE
    estimated_chunks = total_bytes / 2048
    embedding_s = estimated_chunks * _CHUNK_EMBED_SECONDS_ESTIMATE
    return max(30, int(extraction_s + embedding_s))


def _db_only_resources(pdf_files: list[Path], db_resources: list) -> list:
    """Return DB resources that have extracted text but no file on disk.

    ``file_hash``-deduped uploads (``upload_course_resource``) create a thin
    ``CourseResource`` that copies the donor's ``content_hash`` and writes **no**
    file to disk. The disk-glob indexing path would skip them entirely, dropping
    the source from the course's RAG even though its chunks already exist on a
    donor and only need cloning. We index those "DB-only" resources via the
    clone-or-embed DB path alongside any on-disk PDFs.

    A resource counts as "on disk" when a PDF's stem equals its ``filename`` or
    its ``parent_filename`` (split parts share the parent's single file). See #2525.
    """
    disk_stems = {p.stem for p in pdf_files}
    out = []
    for r in db_resources:
        if not r.raw_text:
            continue
        if r.filename in disk_stems:
            continue
        if r.parent_filename and r.parent_filename in disk_stems:
            continue
        out.append(r)
    return out


def finalize_indexation_state(
    course_id: str | None,
    *,
    transition: tuple[str, str] | None = None,
) -> None:
    """Clear ``courses.indexation_task_id``; optionally transition ``creation_step``.

    Called from Celery task lifecycle callbacks so the
    ``(creation_step, indexation_task_id)`` pair is always written
    atomically on every terminal exit. The conditional ``creation_step``
    transition is idempotent — if the user cancelled while the task was
    running, the WHERE clause skips the transition and we still null
    the task pointer. See #2085.
    """
    if not course_id:
        return
    try:
        from sqlalchemy import create_engine, text
        from sqlalchemy.orm import Session

        from app.infrastructure.config.settings import settings

        engine = create_engine(settings.database_url_sync, pool_pre_ping=True)
        try:
            with Session(engine) as session:
                if transition is None:
                    session.execute(
                        text("UPDATE courses SET indexation_task_id = NULL WHERE id = :cid"),
                        {"cid": course_id},
                    )
                else:
                    from_step, to_step = transition
                    session.execute(
                        text(
                            "UPDATE courses SET indexation_task_id = NULL,"
                            " creation_step = CASE WHEN creation_step = :from_step"
                            " THEN :to_step ELSE creation_step END"
                            " WHERE id = :cid"
                        ),
                        {
                            "cid": course_id,
                            "from_step": from_step,
                            "to_step": to_step,
                        },
                    )
                session.commit()
        finally:
            engine.dispose()
    except Exception as exc:
        logger.warning(
            "Failed to finalize indexation state",
            course_id=course_id,
            transition=transition,
            error=str(exc),
        )


class RAGTask(Task):
    """Base task for RAG indexation. Owns the lifecycle of
    ``(creation_step, indexation_task_id)`` so terminal exits — success,
    raised exception, or revoke — always converge to a consistent state.
    See #2085 for the bug this prevents (dangling task pointer wedging
    the wizard).
    """

    def on_success(self, retval, task_id, args, kwargs):
        course_id = args[0] if args else kwargs.get("course_id")
        logger.info("RAG indexation completed", task_id=task_id, course_id=course_id)
        finalize_indexation_state(course_id, transition=("indexing", "indexed"))

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        course_id = args[0] if args else kwargs.get("course_id")
        logger.error(
            "RAG indexation failed",
            task_id=task_id,
            course_id=course_id,
            exception=str(exc),
        )
        finalize_indexation_state(course_id, transition=("indexing", "generated"))


# NOTE: SoftTimeLimitExceeded is deliberately excluded from autoretry. It is a
# subclass of Exception, so `autoretry_for=(Exception,)` would otherwise treat a
# time-limit hit as a transient error and re-run the entire (tens-of-minutes)
# pipeline — redoing all the per-image Claude work and re-surfacing a hard error
# in the wizard even though the work had actually completed. The task stops on
# its own deadline before the soft limit (see indexation_deadline) and catches
# the signal only as a backstop, finalizing the partial result as a success.
# The limits below are sized for image-heavy courses (per-image embedding +
# classify + FR/EN translate + flowchart SVG re-derivation can run ~20 min on
# 300+ images).
@celery_app.task(
    bind=True,
    base=RAGTask,
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 2, "countdown": 60},
    rate_limit="6/h",
    time_limit=3600,
    soft_time_limit=3300,
    # ignore_result must stay False (the global default). With ignore_result=True
    # the result backend never stores this task's STARTED/custom states, so
    # AsyncResult.state reads PENDING for a *live* task — which (a) makes the
    # trigger-side duplicate guard (_diagnose_indexation_pointer) misclassify a
    # running task as evicted and dispatch a second concurrent run, and (b) stops
    # /index-status from surfacing live progress, tripping the wizard's stale
    # watchdog. The global config sets task_ignore_result=False + track_started
    # for exactly this reason; do not re-add the override here.
    acks_late=False,  # Acknowledge immediately to prevent duplicate dispatch
)
def index_course_resources(self, course_id: str, rag_collection_id: str) -> dict:
    """Index uploaded PDFs for a course into pgvector.

    This runs synchronously in a Celery worker. We use asyncio.run()
    to call the async RAG pipeline from the sync Celery context.
    """
    import asyncio

    deadline = indexation_deadline(self, time.monotonic())

    logger.info(
        "Starting RAG indexation",
        task_id=self.request.id,
        course_id=course_id,
        rag_collection_id=rag_collection_id,
    )

    course_dir = UPLOAD_DIR / course_id
    pdf_files = list(course_dir.glob("*.pdf")) if course_dir.exists() else []

    # Always load DB resources. file_hash-deduped uploads carry raw_text + a
    # donor content_hash but write no file to disk, so the disk-glob path would
    # skip them. We index those "DB-only" resources alongside the on-disk PDFs
    # instead of only when no PDF exists on disk (the old mutual exclusion). #2525
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from app.domain.models.course_resource import CourseResource
    from app.infrastructure.config.settings import settings

    _eng = create_engine(settings.database_url_sync, pool_pre_ping=True)
    try:
        with Session(_eng) as _sess:
            all_db_resources = list(
                _sess.execute(
                    select(CourseResource).where(CourseResource.course_id == uuid.UUID(course_id))
                )
                .scalars()
                .all()
            )
    finally:
        _eng.dispose()

    db_only_resources = _db_only_resources(pdf_files, all_db_resources)

    if not pdf_files and not db_only_resources:
        self.update_state(
            state="FAILURE",
            meta={
                "step": "failed",
                "progress": 0,
                "error": f"No resource directory found: {course_dir}",
            },
        )
        return {
            "status": "failed",
            "error": f"No resource directory found: {course_dir}",
            "chunks_stored": 0,
        }

    estimated_seconds = (
        _estimate_seconds(pdf_files) if pdf_files else max(30, len(db_only_resources) * 60)
    )
    start_time = time.monotonic()

    def _remaining(progress_pct: float) -> int:
        elapsed = time.monotonic() - start_time
        if progress_pct > 0:
            total_estimated = elapsed / (progress_pct / 100)
            return max(0, int(total_estimated - elapsed))
        return estimated_seconds

    # Sources still owed text / images, trimmed as each one completes, so both the
    # normal return and the soft-limit backstop report exactly what a partial run
    # left out instead of a bare "success" (#2659).
    pending_text = [r.filename for r in db_only_resources] + [p.name for p in pdf_files]
    pending_images = [p.name for p in pdf_files]
    budget_spent = False

    def _out_of_time() -> bool:
        nonlocal budget_spent
        if deadline is not None and time.monotonic() >= deadline:
            budget_spent = True
        return budget_spent

    def _partial_report() -> dict:
        return {
            "partial": bool(pending_text or pending_images),
            "text_incomplete": list(pending_text),
            "images_incomplete": list(pending_images),
        }

    self.update_state(
        state="EXTRACTING",
        meta={
            "step": "extracting",
            "step_label": "Extraction du texte des PDFs",
            "progress": 5,
            "files_total": len(pdf_files),
            "files_processed": 0,
            "chunks_processed": 0,
            "estimated_seconds_remaining": estimated_seconds,
        },
    )

    async def _run_pipeline():
        import uuid as _uuid

        from app.ai.usage_context import set_ai_context
        from app.infrastructure.config.settings import settings

        try:
            set_ai_context("rag_indexing", course_id=_uuid.UUID(course_id))
        except (ValueError, TypeError):
            set_ai_context("rag_indexing")

        # Resolves a tenant-set override (encrypted) or the env fallback.
        openai_key = settings.openai_api_key
        if not openai_key:
            raise ValueError("OPENAI_API_KEY not set — cannot generate embeddings")

        from app.ai.rag.chunker import TextChunker, detect_language
        from app.ai.rag.embeddings import EmbeddingService
        from app.ai.rag.pipeline import RAGPipeline

        embedding_service = EmbeddingService(api_key=openai_key)
        pipeline = RAGPipeline(embedding_service)

        total_chunks = 0
        total_images = 0

        # Phase 1: DB-only resources (file_hash-deduped; no file on disk).
        # Cloning from a donor is ~instant, so index these first — a soft time
        # limit hit on a heavy disk PDF afterward can't starve them. #2525
        if db_only_resources:
            logger.info(
                "Indexing DB-only course_resources (no file on disk)",
                course_id=course_id,
                resource_count=len(db_only_resources),
            )
            from app.infrastructure.persistence.database import async_session_factory

            chunker = TextChunker()
            files_count = len(db_only_resources)
            for i, res in enumerate(db_only_resources):
                resource_name = res.filename
                # Cap DB-only progress at 30%; the disk loop owns 5→100 below.
                extract_progress = 5 + int((i / files_count) * 25)
                self.update_state(
                    state="EMBEDDING",
                    meta={
                        "step": "embedding",
                        "step_label": f"Indexation depuis DB: {resource_name}",
                        "progress": extract_progress,
                        "files_total": files_count + len(pdf_files),
                        "files_processed": i,
                        "current_file": resource_name,
                        "chunks_processed": total_chunks,
                        "estimated_seconds_remaining": _remaining(extract_progress),
                    },
                )
                # Idempotent re-index: drop this resource's existing chunks + images
                # first so a re-run replaces rather than appends (clone + embed paths
                # below have no dedup of their own). Scoped by course_resource_id. #2534
                async with async_session_factory() as _clear_session:
                    await pipeline.clear_resource_chunks(rag_collection_id, res.id, _clear_session)
                    await pipeline.clear_resource_images(rag_collection_id, res.id, _clear_session)

                # Content-hash dedup: clone from donor course if same text already indexed.
                cloned_text = False
                if res.content_hash:
                    async with async_session_factory() as _dedup_session:
                        donors = await pipeline._find_donor_chunks(
                            res.content_hash, res.id, _dedup_session
                        )
                        if donors:
                            cloned = await pipeline._clone_chunks(
                                donors, rag_collection_id, res.id, _dedup_session
                            )
                            total_chunks += cloned
                            cloned_text = True
                            logger.info(
                                "Cloned chunks from donor — skipped embedding API (DB path)",
                                filename=resource_name,
                                cloned=cloned,
                                course_id=course_id,
                            )

                if not cloned_text:
                    text = res.raw_text
                    language = detect_language(text)
                    chunks = list(
                        chunker.chunk_document(
                            text=text,
                            source=rag_collection_id,
                            language=language,
                            course_resource_id=res.id,
                        )
                    )
                    if chunks:
                        chunk_texts = [c.content for c in chunks]
                        embeddings = await embedding_service.generate_embeddings_batch(chunk_texts)
                        async with async_session_factory() as _db_session:
                            stored = await pipeline._store_chunks(chunks, embeddings, _db_session)
                        total_chunks += stored
                        logger.info(
                            "Indexed DB resource text",
                            filename=resource_name,
                            chunks=stored,
                            course_id=course_id,
                        )

                # Image cache (#2580): a file_hash-deduped resource has no PDF on
                # disk, so images can only come from a donor course that indexed the
                # same source. Without this, deduped courses rendered figureless.
                # Runs after text so the linker (inside clone_images_from_donor) can
                # join freshly-cloned chunks. Keyed on file_hash (exact), then
                # content_hash. Idempotent via clear_resource_images above.
                async with async_session_factory() as _img_session:
                    img_cloned = await pipeline.clone_images_from_donor(
                        new_source=rag_collection_id,
                        new_rag_collection_id=rag_collection_id,
                        new_resource_id=res.id,
                        file_hash=res.file_hash,
                        content_hash=res.content_hash,
                        session=_img_session,
                    )
                if img_cloned:
                    total_images += img_cloned
                    logger.info(
                        "Cloned images from donor — skipped extraction (DB path)",
                        filename=resource_name,
                        images=img_cloned,
                        course_id=course_id,
                    )
                pending_text.remove(resource_name)

        # Pure-deduped course (every source was file_hash-deduped): no disk PDFs
        # to extract text/images from, so we're done.
        if not pdf_files:
            return total_chunks, total_images

        # Build pdf_path → course_resource_id lookup so chunks land with
        # their originating PDF identity (#2186). Resolves by `filename` or
        # `parent_filename` (DB stores stems without extension).
        # Also capture content_hash + file_hash for cross-course chunk/image dedup.
        resource_id_by_stem: dict[str, uuid.UUID] = {}
        resource_hash_by_stem: dict[str, str] = {}
        resource_filehash_by_stem: dict[str, str] = {}
        if pdf_files:
            from sqlalchemy import create_engine, select
            from sqlalchemy.orm import Session

            from app.domain.models.course_resource import CourseResource
            from app.infrastructure.config.settings import settings

            _eng = create_engine(settings.database_url_sync, pool_pre_ping=True)
            try:
                with Session(_eng) as _sess:
                    res_rows = (
                        _sess.execute(
                            select(
                                CourseResource.id,
                                CourseResource.filename,
                                CourseResource.parent_filename,
                                CourseResource.content_hash,
                                CourseResource.file_hash,
                            ).where(CourseResource.course_id == uuid.UUID(course_id))
                        )
                    ).all()
                    for rid, fname, parent, chash, fhash in res_rows:
                        for stem in (fname, parent):
                            if not stem:
                                continue
                            resource_id_by_stem.setdefault(stem, rid)
                            if chash:
                                resource_hash_by_stem.setdefault(stem, chash)
                            if fhash:
                                resource_filehash_by_stem.setdefault(stem, fhash)
            finally:
                _eng.dispose()

        def _resource_keys(pdf_path: Path) -> tuple[uuid.UUID | None, str | None, str | None]:
            def _get(lookup: dict):
                return lookup.get(pdf_path.stem) or lookup.get(pdf_path.name)

            return (
                _get(resource_id_by_stem),
                _get(resource_hash_by_stem),
                _get(resource_filehash_by_stem),
            )

        files_total = len(pdf_files)

        # Phase 2: text for every disk PDF before any image work. Images are the
        # slow part (~20 min on 300+ figures); the old per-PDF text → images order
        # let one image-heavy PDF burn the time budget and leave every later PDF
        # with no text chunks at all while the run still reported success. Now a
        # budget hit can only cost images, which reindex-images recovers. #2659
        text_slot = 35 / files_total
        for i, pdf_path in enumerate(pdf_files):
            extract_progress = 5 + int(i * text_slot)
            self.update_state(
                state="EXTRACTING",
                meta={
                    "step": "extracting",
                    "step_label": f"Extraction PDF {i + 1}/{files_total}: {pdf_path.name}",
                    "progress": extract_progress,
                    "files_total": files_total,
                    "files_processed": i,
                    "current_file": pdf_path.name,
                    "chunks_processed": total_chunks,
                    "estimated_seconds_remaining": _remaining(extract_progress),
                },
            )

            chunk_progress = 5 + int((i + 0.3) * text_slot)
            self.update_state(
                state="CHUNKING",
                meta={
                    "step": "chunking",
                    "step_label": f"Découpage en segments: {pdf_path.name}",
                    "progress": chunk_progress,
                    "files_total": files_total,
                    "files_processed": i,
                    "current_file": pdf_path.name,
                    "chunks_processed": total_chunks,
                    "estimated_seconds_remaining": _remaining(chunk_progress),
                },
            )

            embed_progress = 5 + int((i + 0.5) * text_slot)
            self.update_state(
                state="EMBEDDING",
                meta={
                    "step": "embedding",
                    "step_label": f"Génération des embeddings: {pdf_path.name}",
                    "progress": embed_progress,
                    "files_total": files_total,
                    "files_processed": i,
                    "current_file": pdf_path.name,
                    "chunks_processed": total_chunks,
                    "estimated_seconds_remaining": _remaining(embed_progress),
                },
            )

            resource_id, content_hash, _ = _resource_keys(pdf_path)
            chunks = await pipeline.process_pdf_document(
                pdf_path=str(pdf_path),
                source=rag_collection_id,
                course_resource_id=resource_id,
                content_hash=content_hash,
            )
            total_chunks += chunks
            pending_text.remove(pdf_path.name)

            store_progress = 5 + int((i + 1) * text_slot)
            self.update_state(
                state="STORING",
                meta={
                    "step": "storing",
                    "step_label": f"Stockage de {total_chunks} fragments",
                    "progress": store_progress,
                    "files_total": files_total,
                    "files_processed": i + 1,
                    "current_file": pdf_path.name,
                    "chunks_processed": total_chunks,
                    "estimated_seconds_remaining": _remaining(store_progress),
                },
            )

            logger.info(
                "PDF text indexed",
                file=pdf_path.name,
                chunks=chunks,
                course_id=course_id,
            )

        # Phase 3: images, inside the remaining time budget. Checked between PDFs
        # here and between images inside the pipeline (should_stop).
        image_slot = 55 / files_total
        for i, pdf_path in enumerate(pdf_files):
            if _out_of_time():
                logger.warning(
                    "Indexation time budget exhausted — skipping remaining PDF images",
                    course_id=course_id,
                    skipped=pending_images,
                )
                break

            img_progress = 40 + int(i * image_slot)
            link_progress = 40 + int((i + 1) * image_slot)
            self.update_state(
                state="EXTRACTING_IMAGES",
                meta={
                    "step": "extracting_images",
                    "step_label": f"Extraction des illustrations: {pdf_path.name}",
                    "progress": img_progress,
                    "files_total": files_total,
                    "files_processed": i,
                    "current_file": pdf_path.name,
                    "chunks_processed": total_chunks,
                    "images_processed": total_images,
                    "estimated_seconds_remaining": _remaining(img_progress),
                },
            )

            # Per-image progress callback: lets the celery task stream live
            # progress to /index-status while images are being processed,
            # instead of freezing at img_progress for the whole pass (#2029).
            # Loop locals are bound via default args so the closure captures
            # this iteration's values, not the moving loop bindings.
            def _image_progress_cb(
                done: int,
                total: int,
                figure_label: str | None,
                *,
                _img_progress: int = img_progress,
                _link_progress: int = link_progress,
                _running_total: int = total_images,
                _pdf_name: str = pdf_path.name,
                _files_processed: int = i,
                _total_chunks: int = total_chunks,
                _files_total: int = files_total,
            ) -> None:
                if total <= 0:
                    return
                ratio = min(done / total, 1.0)
                live_progress = _img_progress + int((_link_progress - _img_progress) * ratio)
                self.update_state(
                    state="EXTRACTING_IMAGES",
                    meta={
                        "step": "extracting_images",
                        "step_label": (
                            f"Extraction des illustrations: {_pdf_name} ({done}/{total})"
                        ),
                        "progress": live_progress,
                        "files_total": _files_total,
                        "files_processed": _files_processed,
                        "current_file": _pdf_name,
                        "chunks_processed": _total_chunks,
                        "images_processed": _running_total + done,
                        "estimated_seconds_remaining": _remaining(live_progress),
                    },
                )

            resource_id, content_hash, file_hash = _resource_keys(pdf_path)
            image_count = 0
            try:
                image_count = await pipeline.process_pdf_images(
                    pdf_path=str(pdf_path),
                    source=rag_collection_id,
                    rag_collection_id=rag_collection_id,
                    progress_callback=_image_progress_cb,
                    course_resource_id=resource_id,
                    file_hash=file_hash,
                    content_hash=content_hash,
                    should_stop=_out_of_time,
                )
                total_images += image_count
            except SoftTimeLimitExceeded:
                # The backstop must reach the outer handler, not this guard.
                raise
            except Exception as img_exc:
                logger.warning(
                    "Image extraction failed for PDF (non-blocking)",
                    file=pdf_path.name,
                    course_id=course_id,
                    error=str(img_exc),
                )
            if not budget_spent:
                pending_images.remove(pdf_path.name)

            self.update_state(
                state="LINKING_IMAGES",
                meta={
                    "step": "linking_images",
                    "step_label": f"Liaison images-texte: {image_count} liens créés",
                    "progress": link_progress,
                    "files_total": files_total,
                    "files_processed": i + 1,
                    "current_file": pdf_path.name,
                    "chunks_processed": total_chunks,
                    "images_processed": total_images,
                    "estimated_seconds_remaining": _remaining(link_progress),
                },
            )

            logger.info(
                "PDF images indexed",
                file=pdf_path.name,
                images=image_count,
                course_id=course_id,
            )

        return total_chunks, total_images

    async def _run_pipeline_with_fresh_engine():
        # asyncpg + Celery prefork: child workers inherit the parent's engine
        # but its pooled connections are bound to the parent loop. Dispose
        # before and after so this task — and the next one to land on this
        # worker — both start with a clean pool. See #2103.
        from app.infrastructure.persistence.database import engine

        await engine.dispose()
        try:
            return await _run_pipeline()
        finally:
            await engine.dispose()

    def _finish(totals: dict) -> dict:
        # Shared by the normal return and the soft-limit backstop. A partial run
        # is still a SUCCESS (drives RAGTask.on_success → 'indexed'), but says so:
        # /index-status surfaces the report and the wizard offers a re-index.
        report = _partial_report()
        files_done = sum(
            p.name not in pending_text and p.name not in pending_images for p in pdf_files
        )
        self.update_state(
            state="COMPLETE",
            meta={
                "step": "complete",
                "step_label": (
                    "Indexation partielle (limite de temps atteinte)"
                    if report["partial"]
                    else "Indexation terminée"
                ),
                "progress": 100,
                **totals,
                "files_processed": files_done,
                "files_total": len(pdf_files),
                "estimated_seconds_remaining": 0,
                **report,
            },
        )
        return {
            "status": "partial_timeout" if report["partial"] else "complete",
            **totals,
            "files_processed": files_done,
            "rag_collection_id": rag_collection_id,
            **report,
        }

    try:
        total_chunks, total_images = asyncio.run(_run_pipeline_with_fresh_engine())

        if budget_spent:
            logger.warning(
                "RAG indexation stopped at its time budget — finalizing partial result",
                task_id=self.request.id,
                course_id=course_id,
                images_incomplete=pending_images,
            )

        # State transition (creation_step → 'indexed', indexation_task_id → NULL)
        # is owned by RAGTask.on_success so success/failure/revoke all converge
        # through one code path. See #2085.
        return _finish({"chunks_stored": total_chunks, "images_stored": total_images})

    except SoftTimeLimitExceeded:
        # Backstop: the signal beat the task's own deadline (one blocking step
        # overran the margin). Everything processed so far is already committed
        # — text chunks per PDF and source images per image — so finalize as a
        # SUCCESS rather than let autoretry re-run the whole pipeline and
        # re-surface an error in the wizard.
        logger.warning(
            "RAG indexation hit soft time limit — finalizing partial result",
            task_id=self.request.id,
            course_id=course_id,
            rag_collection_id=rag_collection_id,
            text_incomplete=pending_text,
            images_incomplete=pending_images,
        )
        return _finish({})

    except Exception as exc:
        logger.error(
            "RAG indexation failed",
            course_id=course_id,
            error=str(exc),
        )
        raise


connect_kill_finalizer(index_course_resources, transition=("indexing", "generated"))
