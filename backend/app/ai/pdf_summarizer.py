"""Multi-pass PDF summarizer for syllabus generation.

Replaces naive truncation with a summarize-then-combine approach that
preserves content from every page of every PDF, regardless of size.

Algorithm:
  1. Split each PDF's extracted text into chunks that fit comfortably in the
     model context window (computed dynamically from model capabilities).
  2. Generate a structured summary for each chunk (topics, concepts, hierarchy).
  3. Combine chunk summaries into one unified per-PDF summary.
  4. Return all per-PDF summaries joined for use as syllabus context.

The combining step deduplicates overlapping content across chunks.
For very large PDFs the combine step itself may be chunked (2-level hierarchy).

Budget-aware mode (target_chars):
  When target_chars is provided, word limits are injected into prompts and
  max_tokens is capped so outputs are predictably sized to fit the context window.

Dynamic defaults:
  All chunk/token limits are computed from model capabilities via model_registry.
  Platform settings override these computed values for admin fine-tuning.
  Pass None to any size/token parameter to use the computed default.

Chunk-summary caching (P2 resilience):
  When course_id and session_factory are provided, each chunk summary is saved
  to the chunk_summaries DB table immediately after generation. On retry,
  existing summaries are loaded from DB and only missing chunks are re-summarized.
"""

from __future__ import annotations

import asyncio
import os
import uuid as _uuid_mod
from collections.abc import Callable
from typing import TYPE_CHECKING

import structlog

from app.ai.model_registry import get_model_caps

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = structlog.get_logger(__name__)

_SUMMARIZER_MODEL = "claude-sonnet-4-6"
_CHARS_PER_WORD = 5

_CHUNK_SUMMARY_SYSTEM = (
    "You are an expert educational content analyst. Your task is to extract "
    "the key knowledge structure from a portion of a textbook or reference document "
    "that will be used to build a course syllabus. Be concise but thorough."
)

_CHUNK_SUMMARY_PROMPT = (
    "Analyze the following excerpt from '{book_name}' (chunk {chunk_num} of {total_chunks}).\n\n"
    "Extract and list in structured form:\n"
    "1. Main topic areas / chapter titles covered in this excerpt\n"
    "2. Key concepts, theories, frameworks, and methods introduced\n"
    "3. Important sub-topics and their relationships\n"
    "4. Estimated depth/importance of each topic (brief, moderate, extensive)\n"
    "5. Any learning objectives or competencies explicitly stated\n\n"
    "Be precise and exhaustive — every topic here must appear in the final summary. "
    "Use bullet points. Do not include page text verbatim.{word_limit_instruction}\n\n"
    "EXCERPT:\n{excerpt}"
)

_COMBINE_SYSTEM = (
    "You are an expert curriculum designer. Your task is to synthesize multiple "
    "structured content analyses of sections from the same textbook into one "
    "unified, deduplicated summary of the book's knowledge structure."
)

_COMBINE_PROMPT = (
    "The following are structured analyses of consecutive sections of '{book_name}'. "
    "Combine them into one unified summary that:\n"
    "- Lists all unique topic areas (deduplicated)\n"
    "- Preserves the chapter/section hierarchy\n"
    "- Notes depth/importance of each topic area\n"
    "- Includes key concepts, frameworks, and methods\n"
    "- Preserves any explicit learning objectives\n\n"
    "Remove duplicates but do not lose any unique topics. "
    "This summary will be used to generate a complete course syllabus.{word_limit_instruction}\n\n"
    "SECTION ANALYSES:\n{analyses}"
)


def _compute_defaults(model: str) -> dict:
    """Compute chunk/token defaults dynamically from model capabilities.

    For claude-sonnet-4-6 (1M ctx, 64K out, 3.5 cpt):
      chunk_size_chars          = min(1_000_000 * 0.5 * 3.5, 500_000) = 500_000
      combine_chunk_size_chars  = min(1_000_000 * 0.4 * 3.5, 400_000) = 400_000
      chunk_max_output_tokens   = min(64_000 // 4, 16_000)             = 16_000
      combine_max_output_tokens = min(64_000, 64_000)                  = 64_000
    """
    caps = get_model_caps(model)
    ctx = caps["context_window_tokens"]
    max_out = caps["max_output_tokens"]
    cpt = caps["chars_per_token"]
    return {
        "chunk_size_chars": min(int(ctx * 0.5 * cpt), 500_000),
        "combine_chunk_size_chars": min(int(ctx * 0.4 * cpt), 400_000),
        "chunk_max_output_tokens": min(max_out // 4, 16_000),
        "combine_max_output_tokens": min(max_out, 64_000),
    }


def _split_into_chunks(text: str, chunk_size: int) -> list[str]:
    """Split text into chunks of at most chunk_size chars, breaking on newlines."""
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        if end >= len(text):
            chunks.append(text[start:])
            break
        boundary = text.rfind("\n", start, end)
        if boundary <= start:
            boundary = end
        chunks.append(text[start:boundary])
        start = boundary
    return chunks


def _load_cached_summaries(
    session_factory: Callable[[], Session],
    course_id: str,
    book_name: str,
    total_chunks: int,
) -> dict[int, str]:
    """Load existing chunk summaries from DB for a given course + book.

    Returns a dict mapping chunk_index → summary_text.
    Only returns entries matching the current total_chunks to avoid stale data.
    """
    from app.domain.models.chunk_summary import ChunkSummary
    from sqlalchemy import select

    result: dict[int, str] = {}
    try:
        with session_factory() as session:
            rows = session.execute(
                select(ChunkSummary).where(
                    ChunkSummary.course_id == _uuid_mod.UUID(course_id),
                    ChunkSummary.book_name == book_name,
                    ChunkSummary.total_chunks == total_chunks,
                )
            ).scalars().all()
            for row in rows:
                result[row.chunk_index] = row.summary_text
    except Exception as exc:
        logger.warning("Failed to load cached chunk summaries", error=str(exc))
    return result


def _save_chunk_summary(
    session_factory: Callable[[], Session],
    course_id: str,
    book_name: str,
    chunk_index: int,
    total_chunks: int,
    summary_text: str,
    model: str,
) -> None:
    """Persist a single chunk summary to DB (upsert via delete+insert)."""
    from app.domain.models.chunk_summary import ChunkSummary
    from sqlalchemy import delete

    try:
        with session_factory() as session:
            session.execute(
                delete(ChunkSummary).where(
                    ChunkSummary.course_id == _uuid_mod.UUID(course_id),
                    ChunkSummary.book_name == book_name,
                    ChunkSummary.chunk_index == chunk_index,
                )
            )
            session.add(
                ChunkSummary(
                    course_id=_uuid_mod.UUID(course_id),
                    book_name=book_name,
                    chunk_index=chunk_index,
                    total_chunks=total_chunks,
                    summary_text=summary_text,
                    model=model,
                )
            )
            session.commit()
    except Exception as exc:
        logger.warning(
            "Failed to save chunk summary",
            course_id=course_id,
            book=book_name,
            chunk=chunk_index,
            error=str(exc),
        )


async def _summarize_chunk(
    client,
    book_name: str,
    excerpt: str,
    chunk_num: int,
    total_chunks: int,
    model: str = _SUMMARIZER_MODEL,
    max_tokens: int = 16_000,
    target_words: int | None = None,
) -> str:
    """Generate a structured summary for a single chunk using Claude."""
    word_limit_instruction = (
        f"\n\nLimit your summary to approximately {target_words} words. "
        "Focus on the most important topics."
        if target_words is not None
        else ""
    )
    adjusted_max_tokens = (
        min(max_tokens, max(256, target_words * 2)) if target_words is not None else max_tokens
    )
    prompt = _CHUNK_SUMMARY_PROMPT.format(
        book_name=book_name,
        chunk_num=chunk_num,
        total_chunks=total_chunks,
        excerpt=excerpt,
        word_limit_instruction=word_limit_instruction,
    )
    response = await client.messages.create(
        model=model,
        max_tokens=adjusted_max_tokens,
        system=_CHUNK_SUMMARY_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


async def _combine_summaries(
    client,
    book_name: str,
    summaries: list[str],
    combine_chunk_size: int,
    model: str = _SUMMARIZER_MODEL,
    max_tokens: int = 64_000,
    target_words: int | None = None,
    max_concurrent: int = 5,
    _shared_semaphore: asyncio.Semaphore | None = None,
) -> str:
    """Combine chunk summaries into a single unified per-PDF summary.

    If the concatenated summaries are too large for one call, they are
    combined hierarchically (in groups) before the final merge.
    Intermediate combine batches are processed concurrently up to max_concurrent.
    """
    joined = "\n\n---\n\n".join(f"[Section {i + 1}]\n{s}" for i, s in enumerate(summaries))

    if len(joined) <= combine_chunk_size:
        batches = [joined]
    else:
        batches = _split_into_chunks(joined, combine_chunk_size)

    word_limit_instruction = (
        f"\n\nThe final unified summary must be under {target_words} words total."
        if target_words is not None
        else ""
    )
    adjusted_max_tokens = (
        min(max_tokens, max(256, target_words * 2)) if target_words is not None else max_tokens
    )

    if len(batches) == 1:
        prompt = _COMBINE_PROMPT.format(
            book_name=book_name,
            analyses=batches[0],
            word_limit_instruction=word_limit_instruction,
        )
        response = await client.messages.create(
            model=model,
            max_tokens=adjusted_max_tokens,
            system=_COMBINE_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()

    semaphore = (
        _shared_semaphore if _shared_semaphore is not None else asyncio.Semaphore(max_concurrent)
    )

    async def _bounded_combine(i: int, batch: str) -> str:
        async with semaphore:
            prompt = _COMBINE_PROMPT.format(
                book_name=book_name,
                analyses=batch,
                word_limit_instruction=word_limit_instruction,
            )
            response = await client.messages.create(
                model=model,
                max_tokens=adjusted_max_tokens,
                system=_COMBINE_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            result = response.content[0].text.strip()
            logger.debug(
                "Intermediate combine done",
                book=book_name,
                batch=i + 1,
                total_batches=len(batches),
            )
            return result

    intermediate: list[str] = list(
        await asyncio.gather(*[_bounded_combine(i, b) for i, b in enumerate(batches)])
    )

    final_joined = "\n\n---\n\n".join(f"[Group {i + 1}]\n{s}" for i, s in enumerate(intermediate))
    prompt = _COMBINE_PROMPT.format(
        book_name=book_name,
        analyses=final_joined,
        word_limit_instruction=word_limit_instruction,
    )
    response = await client.messages.create(
        model=model,
        max_tokens=adjusted_max_tokens,
        system=_COMBINE_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


async def summarize_pdf_for_syllabus(
    book_name: str,
    full_text: str,
    toc: list | None = None,
    chunk_size_chars: int | None = None,
    combine_chunk_size_chars: int | None = None,
    model: str = _SUMMARIZER_MODEL,
    chunk_max_output_tokens: int | None = None,
    combine_max_output_tokens: int | None = None,
    target_chars: int | None = None,
    max_concurrent: int = 5,
    _shared_semaphore: asyncio.Semaphore | None = None,
    course_id: str | None = None,
    session_factory: Callable[[], Session] | None = None,
) -> str:
    """Produce a compact, complete knowledge-structure summary of one PDF.

    Args:
        book_name: Human-readable book title (used in prompts).
        full_text: Complete extracted text of the PDF.
        toc: Optional table of contents list from PyMuPDF get_toc().
        chunk_size_chars: Max characters per chunk. None = compute from model.
        combine_chunk_size_chars: Max chars when combining chunk summaries. None = compute.
        model: Claude model name to use.
        chunk_max_output_tokens: Max tokens for chunk summary responses. None = compute.
        combine_max_output_tokens: Max tokens for combined summary responses. None = compute.
        target_chars: Target character budget for the final summary. When set,
            word limits are injected into prompts and max_tokens is capped to
            ensure the output fits within the context window.
        max_concurrent: Max parallel Claude API calls for chunk summarization.
        course_id: When provided (with session_factory), enables chunk summary caching.
        session_factory: Sync SQLAlchemy session factory for DB persistence.

    Returns:
        A structured text summary covering 100% of the PDF's content.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.warning(
            "ANTHROPIC_API_KEY not set — returning TOC-only summary",
            book=book_name,
        )
        if toc:
            toc_lines = [f"{'  ' * (lvl - 1)}{title}" for lvl, title, _ in toc]
            return "Table of Contents:\n" + "\n".join(toc_lines[:200])
        return f"[No API key — full text not summarized for {book_name}]"

    defaults = _compute_defaults(model)
    chunk_size = chunk_size_chars if chunk_size_chars is not None else defaults["chunk_size_chars"]
    combine_chunk_size = (
        combine_chunk_size_chars
        if combine_chunk_size_chars is not None
        else defaults["combine_chunk_size_chars"]
    )
    chunk_max_tokens = (
        chunk_max_output_tokens
        if chunk_max_output_tokens is not None
        else defaults["chunk_max_output_tokens"]
    )
    combine_max_tokens = (
        combine_max_output_tokens
        if combine_max_output_tokens is not None
        else defaults["combine_max_output_tokens"]
    )

    import anthropic

    client = anthropic.AsyncAnthropic(api_key=api_key, timeout=300.0)

    toc_prefix = ""
    if toc:
        toc_lines = [f"{'  ' * (lvl - 1)}{title}" for lvl, title, _ in toc[:200]]
        toc_prefix = "TABLE OF CONTENTS:\n" + "\n".join(toc_lines) + "\n\n"

    text_to_chunk = toc_prefix + full_text
    chunks = _split_into_chunks(text_to_chunk, chunk_size)
    total = len(chunks)

    target_words: int | None = None
    target_per_chunk_words: int | None = None
    if target_chars is not None:
        target_words = target_chars // _CHARS_PER_WORD
        target_per_chunk_words = max(100, target_words // total)

    cached: dict[int, str] = {}
    caching_enabled = course_id is not None and session_factory is not None
    if caching_enabled:
        cached = _load_cached_summaries(session_factory, course_id, book_name, total)
        if cached:
            logger.info(
                "Loaded cached chunk summaries",
                book=book_name,
                cached_count=len(cached),
                total_chunks=total,
                missing=total - len(cached),
            )

    logger.info(
        "Starting multi-pass summarization",
        book=book_name,
        total_chars=len(full_text),
        chunk_count=total,
        chunk_size_chars=chunk_size,
        chunk_max_output_tokens=chunk_max_tokens,
        combine_max_output_tokens=combine_max_tokens,
        target_chars=target_chars,
        target_words=target_words,
        target_per_chunk_words=target_per_chunk_words,
        max_concurrent=max_concurrent,
        cached_chunks=len(cached),
    )

    if total == 1:
        if 0 in cached:
            logger.info("Single-chunk summary loaded from cache", book=book_name)
            summary = cached[0]
        else:
            summary = await _summarize_chunk(
                client,
                book_name,
                chunks[0],
                1,
                1,
                model=model,
                max_tokens=chunk_max_tokens,
                target_words=target_words,
            )
            if caching_enabled:
                _save_chunk_summary(
                    session_factory, course_id, book_name, 0, total, summary, model
                )
        logger.info(
            "Single-chunk summary done",
            book=book_name,
            actual_chars=len(summary),
            target_chars=target_chars,
        )
        return summary

    semaphore = (
        _shared_semaphore if _shared_semaphore is not None else asyncio.Semaphore(max_concurrent)
    )

    async def _bounded_chunk(i: int, chunk: str) -> str:
        if i in cached:
            logger.info(
                "Chunk summary loaded from cache — skipping Claude call",
                book=book_name,
                chunk=i + 1,
                total=total,
            )
            return cached[i]
        async with semaphore:
            result = await _summarize_chunk(
                client,
                book_name,
                chunk,
                i + 1,
                total,
                model=model,
                max_tokens=chunk_max_tokens,
                target_words=target_per_chunk_words,
            )
            logger.info(
                "Chunk summarized",
                book=book_name,
                chunk=i + 1,
                total=total,
                summary_chars=len(result),
            )
            if caching_enabled:
                _save_chunk_summary(
                    session_factory, course_id, book_name, i, total, result, model
                )
            return result

    summaries: list[str] = list(
        await asyncio.gather(*[_bounded_chunk(i, c) for i, c in enumerate(chunks)])
    )

    combined = await _combine_summaries(
        client,
        book_name,
        summaries,
        combine_chunk_size=combine_chunk_size,
        model=model,
        max_tokens=combine_max_tokens,
        target_words=target_words,
        max_concurrent=max_concurrent,
        _shared_semaphore=semaphore,
    )
    logger.info(
        "Multi-pass summarization complete",
        book=book_name,
        chunk_count=total,
        summary_chars=len(combined),
        target_chars=target_chars,
        within_budget=target_chars is None or len(combined) <= target_chars,
    )
    return combined


def summarize_pdfs_sync(
    pdf_texts: list[tuple[str, str, list]],
    chunk_size_chars: int | None = None,
    combine_chunk_size_chars: int | None = None,
    model: str = _SUMMARIZER_MODEL,
    chunk_max_output_tokens: int | None = None,
    combine_max_output_tokens: int | None = None,
    total_budget_chars: int | None = None,
    max_concurrent: int = 5,
    course_id: str | None = None,
    session_factory: Callable[[], Session] | None = None,
) -> list[str]:
    """Synchronous wrapper — summarize a list of (book_name, full_text, toc) tuples.

    Used from Celery tasks that call asyncio.run() explicitly.

    Args:
        pdf_texts: List of (book_name, full_text, toc) tuples.
        chunk_size_chars: Max characters per chunk. None = compute from model.
        combine_chunk_size_chars: Max chars when combining chunk summaries. None = compute.
        model: Claude model name to use.
        chunk_max_output_tokens: Max tokens for chunk summary responses. None = compute.
        combine_max_output_tokens: Max tokens for combined summary responses. None = compute.
        total_budget_chars: Total character budget shared across all PDFs. When set,
            each PDF receives a proportional share based on its text length, and word
            limits are injected into prompts to guarantee combined output fits context window.
        max_concurrent: Max parallel Claude API calls per PDF.
        course_id: When provided (with session_factory), enables chunk summary caching.
        session_factory: Sync SQLAlchemy session factory for DB persistence.

    Returns:
        List of structured summaries, one per PDF, in the same order.
    """
    per_pdf_budgets: list[int | None] = _proportional_budgets(pdf_texts, total_budget_chars)

    if total_budget_chars is not None:
        logger.info(
            "Budget-aware summarization",
            total_budget_chars=total_budget_chars,
            num_pdfs=len(pdf_texts),
            per_pdf_budgets=per_pdf_budgets,
        )

    async def _run_all():
        shared_semaphore = asyncio.Semaphore(max_concurrent)
        tasks = [
            summarize_pdf_for_syllabus(
                name,
                text,
                toc,
                chunk_size_chars=chunk_size_chars,
                combine_chunk_size_chars=combine_chunk_size_chars,
                model=model,
                chunk_max_output_tokens=chunk_max_output_tokens,
                combine_max_output_tokens=combine_max_output_tokens,
                target_chars=budget,
                max_concurrent=max_concurrent,
                _shared_semaphore=shared_semaphore,
                course_id=course_id,
                session_factory=session_factory,
            )
            for (name, text, toc), budget in zip(pdf_texts, per_pdf_budgets, strict=True)
        ]
        return await asyncio.gather(*tasks)

    return list(asyncio.run(_run_all()))


def _proportional_budgets(
    pdf_texts: list[tuple[str, str, list]],
    total_budget_chars: int | None,
) -> list[int | None]:
    """Compute per-PDF character budgets proportional to each PDF's text size.

    Returns a list of None values if total_budget_chars is None.
    Falls back to even split if total text size is zero.
    """
    if total_budget_chars is None:
        return [None] * len(pdf_texts)
    if not pdf_texts:
        return []
    sizes = [len(txt) for _, txt, _ in pdf_texts]
    total = sum(sizes)
    if total == 0:
        even = total_budget_chars // len(pdf_texts)
        return [even] * len(pdf_texts)
    return [int(total_budget_chars * s / total) for s in sizes]
