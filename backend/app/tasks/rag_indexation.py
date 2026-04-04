"""Celery task for RAG indexation of course PDF resources."""

import asyncio
import uuid
from datetime import UTC, datetime

import structlog
from celery import Task
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.tasks.celery_app import celery_app

logger = structlog.get_logger(__name__)

RAG_SOFT_LIMIT = 1800
RAG_HARD_LIMIT = 1860


class RAGIndexationTask(Task):
    def on_success(self, retval, task_id, args, kwargs):
        logger.info("RAG indexation task completed", task_id=task_id, result=retval)

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        logger.error(
            "RAG indexation task failed",
            task_id=task_id,
            exception=str(exc),
            traceback=einfo.traceback,
        )


async def _update_job_status(
    session: AsyncSession,
    job_id: str,
    state: str,
    chunk_count: int | None = None,
    progress_pct: float | None = None,
    error_message: str | None = None,
) -> None:
    now = datetime.now(UTC)
    fields = ["state = :state", "updated_at = :updated_at"]
    params: dict = {"job_id": job_id, "state": state, "updated_at": now}

    if chunk_count is not None:
        fields.append("chunk_count = :chunk_count")
        params["chunk_count"] = chunk_count

    if progress_pct is not None:
        fields.append("progress_pct = :progress_pct")
        params["progress_pct"] = progress_pct

    if error_message is not None:
        fields.append("error_message = :error_message")
        params["error_message"] = error_message

    if state == "complete":
        fields.append("completed_at = :completed_at")
        params["completed_at"] = now

    set_clause = ", ".join(fields)
    await session.execute(
        text(f"UPDATE rag_indexation_jobs SET {set_clause} WHERE id = :job_id"), params
    )
    await session.commit()


@celery_app.task(
    bind=True,
    base=RAGIndexationTask,
    soft_time_limit=RAG_SOFT_LIMIT,
    time_limit=RAG_HARD_LIMIT,
    rate_limit="2/m",
    max_retries=2,
)
def index_course_resources(self, course_id: str, job_id: str) -> dict:
    """Index all PDFs uploaded for a course into pgvector for RAG retrieval.

    Steps:
      1. extracting — find uploaded PDF temp files for this course
      2. chunking   — split text into 512-token chunks
      3. embedding  — generate OpenAI embeddings for each chunk
      4. storing    — upsert chunks into document_chunks scoped by rag_collection_id
      5. indexing   — create/refresh HNSW index on document_chunks

    Args:
        course_id: UUID string of the course
        job_id: UUID string of the rag_indexation_jobs row

    Returns:
        dict with status and chunk_count
    """
    from app.ai.rag.embeddings import EmbeddingService
    from app.ai.rag.pipeline import RAGPipeline
    from app.infrastructure.config.settings import settings

    logger.info(
        "Starting RAG indexation",
        course_id=course_id,
        job_id=job_id,
        task_id=self.request.id,
    )

    async def _run() -> dict:
        engine = create_async_engine(settings.database_url, echo=False, pool_size=5, max_overflow=2)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        try:
            async with session_factory() as session:
                await _update_job_status(session, job_id, "extracting", progress_pct=5.0)

                result = await session.execute(
                    text("SELECT id, slug, rag_collection_id FROM courses WHERE id = :course_id"),
                    {"course_id": uuid.UUID(course_id)},
                )
                course_row = result.mappings().one_or_none()
                if not course_row:
                    raise ValueError(f"Course not found: {course_id}")

                rag_collection_id = course_row["rag_collection_id"] or course_id
                slug = course_row["slug"]

                pdf_result = await session.execute(
                    text(
                        """
                        SELECT file_path, original_name
                        FROM uploaded_course_pdfs
                        WHERE course_id = :course_id
                        ORDER BY uploaded_at
                        """
                    ),
                    {"course_id": uuid.UUID(course_id)},
                )
                pdf_rows = pdf_result.mappings().all()

                await _update_job_status(session, job_id, "chunking", progress_pct=15.0)

                embedding_service = EmbeddingService(
                    api_key=settings.openai_api_key, model=settings.embedding_model
                )
                pipeline = RAGPipeline(embedding_service=embedding_service)

                total_chunks = 0

                if pdf_rows:
                    per_pdf_progress = 70.0 / max(len(pdf_rows), 1)
                    for i, pdf_row in enumerate(pdf_rows):
                        source_name = f"{slug}_{pdf_row['original_name'].rsplit('.', 1)[0].lower()}"
                        try:
                            await _update_job_status(
                                session,
                                job_id,
                                "embedding",
                                progress_pct=15.0 + i * per_pdf_progress,
                            )
                            chunks = await pipeline.process_pdf_document(
                                pdf_path=pdf_row["file_path"],
                                source=source_name,
                                session=session,
                            )
                            total_chunks += chunks
                            logger.info(
                                "Indexed PDF",
                                source=source_name,
                                chunks=chunks,
                                job_id=job_id,
                            )
                        except FileNotFoundError:
                            logger.warning(
                                "PDF file not found, skipping",
                                path=pdf_row["file_path"],
                                source=source_name,
                                job_id=job_id,
                            )
                else:
                    logger.warning(
                        "No uploaded PDFs found for course, indexing backend resources",
                        course_id=course_id,
                        rag_collection_id=rag_collection_id,
                    )
                    import os
                    from pathlib import Path

                    resources_dir = Path(os.path.dirname(__file__)).parent.parent / "resources"
                    if resources_dir.exists():
                        await _update_job_status(session, job_id, "embedding", progress_pct=20.0)
                        results = await pipeline.process_resources_directory(
                            resources_dir=resources_dir,
                        )
                        total_chunks = sum(results.values())
                    else:
                        logger.warning(
                            "No resources directory found",
                            resources_dir=str(resources_dir),
                        )

                await _update_job_status(
                    session, job_id, "embedding", chunk_count=total_chunks, progress_pct=85.0
                )

                try:
                    await session.execute(
                        text("DROP INDEX IF EXISTS idx_document_chunks_embedding_hnsw")
                    )
                    await session.execute(
                        text(
                            "CREATE INDEX idx_document_chunks_embedding_hnsw "
                            "ON document_chunks USING hnsw (embedding vector_cosine_ops) "
                            "WITH (m = 16, ef_construction = 64)"
                        )
                    )
                    await session.commit()
                    logger.info("HNSW index created/refreshed", job_id=job_id)
                except Exception as idx_exc:
                    logger.warning(
                        "HNSW index creation failed (non-fatal)",
                        error=str(idx_exc),
                        job_id=job_id,
                    )
                    await session.rollback()

                await _update_job_status(
                    session,
                    job_id,
                    "complete",
                    chunk_count=total_chunks,
                    progress_pct=100.0,
                )

                return {"status": "complete", "chunk_count": total_chunks, "job_id": job_id}

        except Exception as exc:
            async with session_factory() as error_session:
                await _update_job_status(
                    error_session,
                    job_id,
                    "failed",
                    error_message=str(exc)[:500],
                    progress_pct=0.0,
                )
            raise
        finally:
            await engine.dispose()

    try:
        result = asyncio.run(_run())
        logger.info(
            "RAG indexation completed",
            course_id=course_id,
            job_id=job_id,
            result=result,
            task_id=self.request.id,
        )
        return result
    except Exception as exc:
        logger.error(
            "RAG indexation task failed",
            course_id=course_id,
            job_id=job_id,
            exception=str(exc),
            task_id=self.request.id,
        )
        return {"status": "failed", "error": str(exc), "job_id": job_id}
