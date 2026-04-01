"""Admin API endpoints for RAG index management."""

import json
import tempfile
import time
from typing import Any

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.deps_local_auth import AuthenticatedUser
from app.api.v1.admin.deps import require_admin
from app.domain.models.document_chunk import DocumentChunk
from app.infrastructure.cache.redis import redis_client
from app.tasks.rag_indexing import RAG_JOB_KEY_PREFIX, index_uploaded_pdf, reindex_source

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/admin/rag", tags=["admin-rag"])

MAX_UPLOAD_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB


class SourceStats(BaseModel):
    source: str
    chunk_count: int
    token_count: int
    last_indexed: str | None = None


class RAGStatusResponse(BaseModel):
    total_chunks: int
    total_tokens: int
    sources: list[SourceStats]


class ReindexRequest(BaseModel):
    source_id: str | None = Field(
        default=None,
        description="Source ID to re-index selectively. Omit to re-index all sources.",
    )


class ReindexResponse(BaseModel):
    job_id: str
    status: str
    message: str


class UploadResponse(BaseModel):
    job_id: str
    status: str
    source_id: str
    message: str


class DeleteSourceResponse(BaseModel):
    source_id: str
    chunks_removed: int
    message: str


class JobRecord(BaseModel):
    job_id: str
    status: str
    updated_at: int
    source: str | None = None
    chunks_indexed: int | None = None
    error: str | None = None
    total_chunks: int | None = None


class JobsResponse(BaseModel):
    jobs: list[JobRecord]


@router.get("/status", response_model=RAGStatusResponse)
async def get_rag_status(
    _: AuthenticatedUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> RAGStatusResponse:
    """Return RAG index statistics: total chunks, per-source breakdown."""
    result = await db.execute(
        select(
            DocumentChunk.source,
            func.count(DocumentChunk.id).label("chunk_count"),
            func.sum(DocumentChunk.token_count).label("token_count"),
            func.max(DocumentChunk.created_at).label("last_indexed"),
        ).group_by(DocumentChunk.source)
    )
    rows = result.all()

    sources = []
    total_chunks = 0
    total_tokens = 0

    for row in rows:
        chunk_count = row.chunk_count or 0
        tok_count = row.token_count or 0
        total_chunks += chunk_count
        total_tokens += tok_count
        sources.append(
            SourceStats(
                source=row.source,
                chunk_count=chunk_count,
                token_count=tok_count,
                last_indexed=row.last_indexed.isoformat() if row.last_indexed else None,
            )
        )

    return RAGStatusResponse(
        total_chunks=total_chunks,
        total_tokens=total_tokens,
        sources=sources,
    )


@router.post("/reindex", response_model=ReindexResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_reindex(
    body: ReindexRequest,
    _: AuthenticatedUser = Depends(require_admin),
) -> ReindexResponse:
    """Trigger a full or selective re-index as a Celery background task."""
    task = reindex_source.delay(source_id=body.source_id)

    # Pre-populate job status in Redis
    job_data = {
        "job_id": task.id,
        "status": "pending",
        "updated_at": int(time.time()),
        "source": body.source_id,
    }
    await redis_client.setex(
        f"{RAG_JOB_KEY_PREFIX}{task.id}",
        86400 * 7,
        json.dumps(job_data),
    )

    msg = (
        f"Re-indexing source '{body.source_id}' started"
        if body.source_id
        else "Full re-index started"
    )
    logger.info("RAG re-index triggered", job_id=task.id, source_id=body.source_id)
    return ReindexResponse(job_id=task.id, status="pending", message=msg)


@router.post("/upload", response_model=UploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_pdf(
    source_id: str,
    file: UploadFile = File(...),
    _: AuthenticatedUser = Depends(require_admin),
) -> UploadResponse:
    """Upload a new PDF and index it into the RAG pipeline."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Only PDF files are accepted",
        )

    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File exceeds maximum size of 50 MB",
        )

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(content)
        tmp.flush()
        tmp_name = tmp.name

    task = index_uploaded_pdf.delay(file_path=tmp_name, source_id=source_id)

    job_data = {
        "job_id": task.id,
        "status": "pending",
        "updated_at": int(time.time()),
        "source": source_id,
    }
    await redis_client.setex(
        f"{RAG_JOB_KEY_PREFIX}{task.id}",
        86400 * 7,
        json.dumps(job_data),
    )

    logger.info("PDF upload indexing triggered", job_id=task.id, source_id=source_id)
    return UploadResponse(
        job_id=task.id,
        status="pending",
        source_id=source_id,
        message=f"PDF '{file.filename}' accepted and queued for indexing as source '{source_id}'",
    )


@router.delete("/source/{source_id}", response_model=DeleteSourceResponse)
async def delete_source(
    source_id: str,
    _: AuthenticatedUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> DeleteSourceResponse:
    """Remove all chunks for a given source from the RAG index."""
    count_result = await db.execute(
        select(func.count(DocumentChunk.id)).where(DocumentChunk.source == source_id)
    )
    chunk_count = count_result.scalar() or 0

    if chunk_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No chunks found for source '{source_id}'",
        )

    await db.execute(delete(DocumentChunk).where(DocumentChunk.source == source_id))
    await db.commit()

    logger.info("Deleted RAG source chunks", source_id=source_id, count=chunk_count)
    return DeleteSourceResponse(
        source_id=source_id,
        chunks_removed=chunk_count,
        message=f"Removed {chunk_count} chunks for source '{source_id}'",
    )


@router.get("/jobs", response_model=JobsResponse)
async def list_jobs(
    _: AuthenticatedUser = Depends(require_admin),
) -> JobsResponse:
    """List recent RAG indexing jobs with status."""
    jobs: list[JobRecord] = []
    pattern = f"{RAG_JOB_KEY_PREFIX}*"

    async for key in redis_client.scan_iter(match=pattern):
        raw = await redis_client.get(key)
        if not raw:
            continue
        try:
            data: dict[str, Any] = json.loads(raw)
            jobs.append(
                JobRecord(
                    job_id=data.get("job_id", ""),
                    status=data.get("status", "unknown"),
                    updated_at=data.get("updated_at", 0),
                    source=data.get("source"),
                    chunks_indexed=data.get("chunks_indexed"),
                    error=data.get("error"),
                    total_chunks=data.get("total_chunks"),
                )
            )
        except (json.JSONDecodeError, KeyError):
            continue

    jobs.sort(key=lambda j: j.updated_at, reverse=True)
    return JobsResponse(jobs=jobs[:50])
