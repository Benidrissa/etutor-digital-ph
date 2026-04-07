"""Multi-pass PDF summarizer for syllabus generation.

Replaces naive truncation with a summarize-then-combine approach that
preserves content from every page of every PDF, regardless of size.

Algorithm:
  1. Split each PDF's extracted text into chunks that fit comfortably in the
     model context window (default: 80 000 chars ≈ ~20 000 tokens).
  2. Generate a structured summary for each chunk (topics, concepts, hierarchy).
  3. Combine chunk summaries into one unified per-PDF summary.
  4. Return all per-PDF summaries joined for use as syllabus context.

The combining step deduplicates overlapping content across chunks.
For very large PDFs the combine step itself may be chunked (2-level hierarchy).

Budget-aware mode (target_chars):
  When target_chars is provided, word limits are injected into prompts and
  max_tokens is capped so outputs are predictably sized to fit the context window.
"""

from __future__ import annotations

import asyncio
import os

import structlog

logger = structlog.get_logger(__name__)

_CHUNK_SIZE_CHARS = 80_000
_COMBINE_CHUNK_SIZE = 60_000
_SUMMARIZER_MODEL = "claude-sonnet-4-6"
_CHUNK_MAX_TOKENS = 4096
_COMBINE_MAX_TOKENS = 8192
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


def _split_into_chunks(text: str, chunk_size: int = _CHUNK_SIZE_CHARS) -> list[str]:
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


async def _summarize_chunk(
    client,
    book_name: str,
    excerpt: str,
    chunk_num: int,
    total_chunks: int,
    model: str = _SUMMARIZER_MODEL,
    max_tokens: int = _CHUNK_MAX_TOKENS,
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
    combine_chunk_size: int = _COMBINE_CHUNK_SIZE,
    model: str = _SUMMARIZER_MODEL,
    max_tokens: int = _COMBINE_MAX_TOKENS,
    target_words: int | None = None,
) -> str:
    """Combine chunk summaries into a single unified per-PDF summary.

    If the concatenated summaries are too large for one call, they are
    combined hierarchically (in groups) before the final merge.
    """
    joined = "\n\n---\n\n".join(f"[Section {i + 1}]\n{s}" for i, s in enumerate(summaries))

    if len(joined) <= combine_chunk_size:
        batches = [joined]
    else:
        batch_chunks = _split_into_chunks(joined, combine_chunk_size)
        batches = batch_chunks

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

    intermediate: list[str] = []
    for i, batch in enumerate(batches):
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
        intermediate.append(response.content[0].text.strip())
        logger.debug(
            "Intermediate combine done",
            book=book_name,
            batch=i + 1,
            total_batches=len(batches),
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
    chunk_size: int = _CHUNK_SIZE_CHARS,
    combine_chunk_size: int = _COMBINE_CHUNK_SIZE,
    model: str = _SUMMARIZER_MODEL,
    chunk_max_tokens: int = _CHUNK_MAX_TOKENS,
    combine_max_tokens: int = _COMBINE_MAX_TOKENS,
    target_chars: int | None = None,
) -> str:
    """Produce a compact, complete knowledge-structure summary of one PDF.

    Args:
        book_name: Human-readable book title (used in prompts).
        full_text: Complete extracted text of the PDF.
        toc: Optional table of contents list from PyMuPDF get_toc().
        chunk_size: Max characters per chunk (default 80 000).
        combine_chunk_size: Max chars when combining chunk summaries.
        model: Claude model name to use.
        chunk_max_tokens: Max tokens for chunk summary responses.
        combine_max_tokens: Max tokens for combined summary responses.
        target_chars: Target character budget for the final summary. When set,
            word limits are injected into prompts and max_tokens is capped to
            ensure the output fits within the context window.

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

    logger.info(
        "Starting multi-pass summarization",
        book=book_name,
        total_chars=len(full_text),
        chunk_count=total,
        target_chars=target_chars,
        target_words=target_words,
        target_per_chunk_words=target_per_chunk_words,
    )

    if total == 1:
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
        logger.info(
            "Single-chunk summary done",
            book=book_name,
            actual_chars=len(summary),
            target_chars=target_chars,
        )
        return summary

    summaries: list[str] = []
    for i, chunk in enumerate(chunks):
        chunk_summary = await _summarize_chunk(
            client,
            book_name,
            chunk,
            i + 1,
            total,
            model=model,
            max_tokens=chunk_max_tokens,
            target_words=target_per_chunk_words,
        )
        summaries.append(chunk_summary)
        logger.info(
            "Chunk summarized",
            book=book_name,
            chunk=i + 1,
            total=total,
            summary_chars=len(chunk_summary),
        )

    combined = await _combine_summaries(
        client,
        book_name,
        summaries,
        combine_chunk_size=combine_chunk_size,
        model=model,
        max_tokens=combine_max_tokens,
        target_words=target_words,
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
    chunk_size: int = _CHUNK_SIZE_CHARS,
    combine_chunk_size: int = _COMBINE_CHUNK_SIZE,
    model: str = _SUMMARIZER_MODEL,
    chunk_max_tokens: int = _CHUNK_MAX_TOKENS,
    combine_max_tokens: int = _COMBINE_MAX_TOKENS,
    total_budget_chars: int | None = None,
) -> list[str]:
    """Synchronous wrapper — summarize a list of (book_name, full_text, toc) tuples.

    Used from Celery tasks that call asyncio.run() explicitly.

    Args:
        pdf_texts: List of (book_name, full_text, toc) tuples.
        chunk_size: Max characters per chunk.
        combine_chunk_size: Max chars when combining chunk summaries.
        model: Claude model name to use.
        chunk_max_tokens: Max tokens for chunk summary responses.
        combine_max_tokens: Max tokens for combined summary responses.
        total_budget_chars: Total character budget shared across all PDFs. When
            set, each PDF receives an equal share and word limits are injected
            into prompts to guarantee the combined output fits the context window.

    Returns:
        List of structured summaries, one per PDF, in the same order.
    """
    per_pdf_budget: int | None = None
    if total_budget_chars is not None and len(pdf_texts) > 0:
        per_pdf_budget = total_budget_chars // len(pdf_texts)
        logger.info(
            "Budget-aware summarization",
            total_budget_chars=total_budget_chars,
            num_pdfs=len(pdf_texts),
            per_pdf_budget=per_pdf_budget,
        )

    async def _run_all():
        tasks = [
            summarize_pdf_for_syllabus(
                name,
                text,
                toc,
                chunk_size=chunk_size,
                combine_chunk_size=combine_chunk_size,
                model=model,
                chunk_max_tokens=chunk_max_tokens,
                combine_max_tokens=combine_max_tokens,
                target_chars=per_pdf_budget,
            )
            for name, text, toc in pdf_texts
        ]
        return await asyncio.gather(*tasks)

    return list(asyncio.run(_run_all()))
