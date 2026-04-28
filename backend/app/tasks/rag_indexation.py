"""Celery task for RAG indexation — processes course PDFs into vector embeddings."""

import os
import time
import uuid
from pathlib import Path

import structlog
from celery import Task

from app.tasks.celery_app import celery_app

logger = structlog.get_logger(__name__)

UPLOAD_DIR = Path("uploads/course_resources")

_BYTES_PER_SECOND_ESTIMATE = 50_000
_CHUNK_EMBED_SECONDS_ESTIMATE = 0.05


def _estimate_seconds(pdf_files: list[Path]) -> int:
    total_bytes = sum(p.stat().st_size for p in pdf_files if p.exists())
    extraction_s = total_bytes / _BYTES_PER_SECOND_ESTIMATE
    estimated_chunks = total_bytes / 2048
    embedding_s = estimated_chunks * _CHUNK_EMBED_SECONDS_ESTIMATE
    return max(30, int(extraction_s + embedding_s))


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
                        text(
                            "UPDATE courses SET indexation_task_id = NULL"
                            " WHERE id = :cid"
                        ),
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


@celery_app.task(
    bind=True,
    base=RAGTask,
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 2, "countdown": 60},
    rate_limit="2/h",
    time_limit=1800,
    soft_time_limit=1500,
    ignore_result=True,
    acks_late=False,  # Acknowledge immediately to prevent duplicate dispatch
)
def index_course_resources(self, course_id: str, rag_collection_id: str) -> dict:
    """Index uploaded PDFs for a course into pgvector.

    This runs synchronously in a Celery worker. We use asyncio.run()
    to call the async RAG pipeline from the sync Celery context.
    """
    import asyncio

    logger.info(
        "Starting RAG indexation",
        task_id=self.request.id,
        course_id=course_id,
        rag_collection_id=rag_collection_id,
    )

    course_dir = UPLOAD_DIR / course_id
    pdf_files = list(course_dir.glob("*.pdf")) if course_dir.exists() else []

    db_resources: list = []
    if not pdf_files:
        from sqlalchemy import create_engine, select
        from sqlalchemy.orm import Session

        from app.domain.models.course_resource import CourseResource
        from app.infrastructure.config.settings import settings

        _eng = create_engine(settings.database_url_sync, pool_pre_ping=True)
        try:
            with Session(_eng) as _sess:
                db_resources = (
                    _sess.execute(
                        select(CourseResource).where(
                            CourseResource.course_id == uuid.UUID(course_id)
                        )
                    )
                    .scalars()
                    .all()
                )
                db_resources = [r for r in db_resources if r.raw_text]
        finally:
            _eng.dispose()

    if not pdf_files and not db_resources:
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
        _estimate_seconds(pdf_files) if pdf_files else max(30, len(db_resources) * 60)
    )
    start_time = time.monotonic()

    def _remaining(progress_pct: float) -> int:
        elapsed = time.monotonic() - start_time
        if progress_pct > 0:
            total_estimated = elapsed / (progress_pct / 100)
            return max(0, int(total_estimated - elapsed))
        return estimated_seconds

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
        openai_key = os.getenv("OPENAI_API_KEY", "")
        if not openai_key:
            raise ValueError("OPENAI_API_KEY not set — cannot generate embeddings")

        from app.ai.rag.chunker import TextChunker, detect_language
        from app.ai.rag.embeddings import EmbeddingService
        from app.ai.rag.pipeline import RAGPipeline

        embedding_service = EmbeddingService(api_key=openai_key)
        pipeline = RAGPipeline(embedding_service)

        total_chunks = 0
        total_images = 0

        if not pdf_files and db_resources:
            logger.info(
                "No PDFs on disk — indexing text chunks from DB course_resources",
                course_id=course_id,
                resource_count=len(db_resources),
            )
            from app.infrastructure.persistence.database import async_session_factory

            chunker = TextChunker()
            files_count = len(db_resources)
            for i, res in enumerate(db_resources):
                resource_name = res.filename
                extract_progress = 5 + int((i / files_count) * 80)
                self.update_state(
                    state="EMBEDDING",
                    meta={
                        "step": "embedding",
                        "step_label": f"Indexation depuis DB: {resource_name}",
                        "progress": extract_progress,
                        "files_total": files_count,
                        "files_processed": i,
                        "current_file": resource_name,
                        "chunks_processed": total_chunks,
                        "estimated_seconds_remaining": _remaining(extract_progress),
                    },
                )
                text = res.raw_text
                language = detect_language(text)
                chunks = list(
                    chunker.chunk_document(text=text, source=rag_collection_id, language=language)
                )
                if not chunks:
                    continue
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

            # Extract images from any PDFs on disk even in DB-resources path
            if course_dir.exists():
                img_pdfs = list(course_dir.glob("*.pdf"))
                for pdf_path in img_pdfs:
                    try:
                        ic = await pipeline.process_pdf_images(
                            pdf_path=str(pdf_path),
                            source=rag_collection_id,
                            rag_collection_id=rag_collection_id,
                        )
                        total_images += ic
                        logger.info(
                            "Extracted images from PDF (DB resources path)",
                            file=pdf_path.name,
                            images=ic,
                            course_id=course_id,
                        )
                    except Exception as img_exc:
                        logger.warning(
                            "Image extraction failed (DB path, non-blocking)",
                            file=pdf_path.name,
                            course_id=course_id,
                            error=str(img_exc),
                        )

            return total_chunks, total_images

        for i, pdf_path in enumerate(pdf_files):
            extract_progress = 5 + int((i / len(pdf_files)) * 30)
            self.update_state(
                state="EXTRACTING",
                meta={
                    "step": "extracting",
                    "step_label": f"Extraction PDF {i + 1}/{len(pdf_files)}: {pdf_path.name}",
                    "progress": extract_progress,
                    "files_total": len(pdf_files),
                    "files_processed": i,
                    "current_file": pdf_path.name,
                    "chunks_processed": total_chunks,
                    "estimated_seconds_remaining": _remaining(extract_progress),
                },
            )

            self.update_state(
                state="CHUNKING",
                meta={
                    "step": "chunking",
                    "step_label": f"Découpage en segments: {pdf_path.name}",
                    "progress": extract_progress + 5,
                    "files_total": len(pdf_files),
                    "files_processed": i,
                    "current_file": pdf_path.name,
                    "chunks_processed": total_chunks,
                    "estimated_seconds_remaining": _remaining(extract_progress + 5),
                },
            )

            embed_progress = 35 + int(((i + 0.5) / len(pdf_files)) * 50)
            self.update_state(
                state="EMBEDDING",
                meta={
                    "step": "embedding",
                    "step_label": f"Génération des embeddings: {pdf_path.name}",
                    "progress": embed_progress,
                    "files_total": len(pdf_files),
                    "files_processed": i,
                    "current_file": pdf_path.name,
                    "chunks_processed": total_chunks,
                    "estimated_seconds_remaining": _remaining(embed_progress),
                },
            )

            chunks = await pipeline.process_pdf_document(
                pdf_path=str(pdf_path),
                source=rag_collection_id,
            )
            total_chunks += chunks

            store_progress = 35 + int(((i + 1) / len(pdf_files)) * 45)
            self.update_state(
                state="STORING",
                meta={
                    "step": "storing",
                    "step_label": f"Stockage de {total_chunks} fragments",
                    "progress": store_progress,
                    "files_total": len(pdf_files),
                    "files_processed": i + 1,
                    "current_file": pdf_path.name,
                    "chunks_processed": total_chunks,
                    "estimated_seconds_remaining": _remaining(store_progress),
                },
            )

            img_progress = store_progress + int((1 / len(pdf_files)) * 8)
            self.update_state(
                state="EXTRACTING_IMAGES",
                meta={
                    "step": "extracting_images",
                    "step_label": f"Extraction des illustrations: {pdf_path.name}",
                    "progress": img_progress,
                    "files_total": len(pdf_files),
                    "files_processed": i + 1,
                    "current_file": pdf_path.name,
                    "chunks_processed": total_chunks,
                    "estimated_seconds_remaining": _remaining(img_progress),
                },
            )

            # Per-image progress callback: lets the celery task stream live
            # progress to /index-status while images are being processed,
            # instead of freezing at img_progress for the whole pass (#2029).
            # Loop locals are bound via default args so the closure captures
            # this iteration's values, not the moving loop bindings.
            _link_progress_for_pdf = img_progress + int((1 / len(pdf_files)) * 7)

            def _image_progress_cb(
                done: int,
                total: int,
                figure_label: str | None,
                *,
                _img_progress: int = img_progress,
                _link_progress: int = _link_progress_for_pdf,
                _running_total: int = total_images,
                _pdf_name: str = pdf_path.name,
                _files_processed: int = i + 1,
                _total_chunks: int = total_chunks,
                _files_total: int = len(pdf_files),
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

            image_count = 0
            try:
                image_count = await pipeline.process_pdf_images(
                    pdf_path=str(pdf_path),
                    source=rag_collection_id,
                    rag_collection_id=rag_collection_id,
                    progress_callback=_image_progress_cb,
                )
                total_images += image_count
            except Exception as img_exc:
                logger.warning(
                    "Image extraction failed for PDF (non-blocking)",
                    file=pdf_path.name,
                    course_id=course_id,
                    error=str(img_exc),
                )

            link_progress = img_progress + int((1 / len(pdf_files)) * 7)
            self.update_state(
                state="LINKING_IMAGES",
                meta={
                    "step": "linking_images",
                    "step_label": f"Liaison images-texte: {image_count} liens créés",
                    "progress": link_progress,
                    "files_total": len(pdf_files),
                    "files_processed": i + 1,
                    "current_file": pdf_path.name,
                    "chunks_processed": total_chunks,
                    "images_processed": total_images,
                    "estimated_seconds_remaining": _remaining(link_progress),
                },
            )

            logger.info(
                "PDF indexed",
                file=pdf_path.name,
                chunks=chunks,
                images=image_count,
                course_id=course_id,
            )

        return total_chunks, total_images

    try:
        total_chunks, total_images = asyncio.run(_run_pipeline())

        self.update_state(
            state="COMPLETE",
            meta={
                "step": "complete",
                "step_label": "Indexation terminée",
                "progress": 100,
                "chunks_stored": total_chunks,
                "images_stored": total_images,
                "files_processed": len(pdf_files),
                "files_total": len(pdf_files),
                "estimated_seconds_remaining": 0,
            },
        )

        # State transition (creation_step → 'indexed', indexation_task_id → NULL)
        # is owned by RAGTask.on_success so success/failure/revoke all converge
        # through one code path. See #2085.

        return {
            "status": "complete",
            "chunks_stored": total_chunks,
            "images_stored": total_images,
            "files_processed": len(pdf_files),
            "rag_collection_id": rag_collection_id,
        }

    except Exception as exc:
        logger.error(
            "RAG indexation failed",
            course_id=course_id,
            error=str(exc),
        )
        raise
