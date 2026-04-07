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


class RAGTask(Task):
    """Base task for RAG indexation with progress tracking."""

    def on_success(self, retval, task_id, args, kwargs):
        logger.info("RAG indexation completed", task_id=task_id, result=retval)

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        logger.error("RAG indexation failed", task_id=task_id, exception=str(exc))
        # Reset creation_step so the user can retry
        try:
            course_id = args[0] if args else kwargs.get("course_id")
            if course_id:
                from sqlalchemy import create_engine, text
                from sqlalchemy.orm import Session

                from app.infrastructure.config.settings import settings

                engine = create_engine(settings.database_url_sync, pool_pre_ping=True)
                with Session(engine) as session:
                    session.execute(
                        text(
                            "UPDATE courses SET creation_step = 'generated'"
                            " WHERE id = :cid AND creation_step = 'indexing'"
                        ),
                        {"cid": course_id},
                    )
                    session.commit()
                engine.dispose()
        except Exception as reset_exc:
            logger.warning("Failed to reset creation_step", error=str(reset_exc))


@celery_app.task(
    bind=True,
    base=RAGTask,
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 2, "countdown": 60},
    rate_limit="2/h",
    time_limit=1800,
    soft_time_limit=1500,
    ignore_result=True,
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

            image_count = 0
            if total_images > 0:
                logger.info(
                    "Images already indexed, skipping image extraction",
                    file=pdf_path.name,
                    course_id=course_id,
                    images_already=total_images,
                )
            else:
                try:
                    image_count = await pipeline.process_pdf_images(
                        pdf_path=str(pdf_path),
                        source=rag_collection_id,
                        rag_collection_id=rag_collection_id,
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

        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session

        from app.infrastructure.config.settings import settings

        sync_engine = create_engine(
            settings.database_url_sync,
            pool_pre_ping=True,
            pool_size=2,
            max_overflow=0,
        )
        try:
            from sqlalchemy import text

            with Session(sync_engine) as session:
                session.execute(
                    text("UPDATE courses SET creation_step = 'indexed' WHERE id = :cid"),
                    {"cid": course_id},
                )
                session.commit()
        finally:
            sync_engine.dispose()

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
