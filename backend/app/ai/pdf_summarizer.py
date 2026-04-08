"""Simplified 1-call-per-PDF summarizer for syllabus generation.

Algorithm (issue #1139):
  1. Each resource (PDF or chapter-split part) fits in one Claude API call
     because oversized PDFs are pre-split at upload time (see admin_courses.py).
  2. If total chars across all resources ≤ context_budget → send raw text directly.
  3. Otherwise: 1 API call per resource (summarize_single_pdf), then combine.
  4. Result: N resources + 1 combine + 1 syllabus = N+2 API calls maximum.

Backward compatibility:
  - _combine_summaries() is kept (used by syllabus_generation.py).
  - _split_into_chunks(), _proportional_budgets(), compute_chunk_plan(),
    PdfChunkPlan, and _compute_defaults() are preserved for tests
    that import them directly.
  - summarize_pdf_for_syllabus() still works (used in old test paths).
  - summarize_pdfs_sync() still works (old call sites remain functional).
"""

from __future__ import annotations

import asyncio
import math
import os
from dataclasses import dataclass

import structlog

from app.ai.model_registry import get_model_caps, tokens_to_chars

logger = structlog.get_logger(__name__)

_SUMMARIZER_MODEL = "gpt-5.4-nano"
_CHARS_PER_WORD = 5

_MAX_PDF_CHARS = 2_500_000

_SYLLABUS_SUMMARY_SYSTEM = (
    "You are an expert instructional designer and curriculum analyst. "
    "Your task is to produce a comprehensive, structured analysis of a textbook "
    "that will be used to design a complete training course with lessons, quizzes, "
    "flashcards, and case studies."
)

_SYLLABUS_SUMMARY_PROMPT = (
    "Analyze the complete text of '{book_name}' and produce a rich, detailed "
    "educational content map.\n\n"
    "For EACH chapter or major section, provide:\n\n"
    "## 1. Structure & Progression\n"
    "- Chapter/section title and scope\n"
    "- Prerequisites (what the learner must know before this section)\n"
    "- How this section builds on previous ones\n"
    "- Estimated learning time (hours) based on content density\n\n"
    "## 2. Core Knowledge (for LESSONS)\n"
    "- Key concepts, theories, frameworks, and models — with brief definitions\n"
    "- Important terminology and vocabulary (bilingual FR/EN when relevant)\n"
    "- Formulas, processes, or step-by-step methods explained\n"
    "- Real-world examples and illustrations mentioned in the text\n"
    "- Data, statistics, or research findings cited\n\n"
    "## 3. Assessment Material (for QUIZZES & FLASHCARDS)\n"
    "- Factual knowledge points that can be tested (definitions, dates, formulas)\n"
    "- Conceptual understanding questions (compare/contrast, explain why)\n"
    "- Application scenarios (given X situation, what approach?)\n"
    "- Common misconceptions or tricky distinctions\n"
    "- Key term ↔ definition pairs suitable for flashcards\n\n"
    "## 4. Practical Application (for CASE STUDIES)\n"
    "- Case studies, examples, or scenarios from the text\n"
    "- Real-world applications and industry practices described\n"
    "- Decision-making frameworks the learner should practice\n"
    "- Datasets, tools, or methods the learner could apply\n\n"
    "## 5. Bloom's Taxonomy Mapping\n"
    "- Which topics are foundational (remember/understand)?\n"
    "- Which require application (apply/analyze)?\n"
    "- Which demand synthesis or evaluation (evaluate/create)?\n\n"
    "Be EXHAUSTIVE — every topic, concept, and example in the text must appear. "
    "This summary is the ONLY input for course design; anything omitted will be "
    "missing from the final course. Use structured markdown with headers and bullets. "
    "Aim for maximum detail and completeness.\n\n"
    "FULL TEXT:\n{text}"
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


def _compute_defaults(model: str) -> dict:
    """Compute chunk/token defaults dynamically from model capabilities."""
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


@dataclass
class PdfChunkPlan:
    """Optimal chunking strategy for a single PDF given model limits and budget."""

    chunk_count: int
    chunk_size_chars: int
    chunk_max_output_tokens: int
    combine_max_output_tokens: int


def compute_chunk_plan(
    pdf_chars: int,
    num_pdfs: int,
    total_pdf_chars: int,
    context_budget_chars: int,
    model: str = _SUMMARIZER_MODEL,
) -> PdfChunkPlan:
    """Compute the optimal chunk plan for a PDF."""
    caps = get_model_caps(model)
    cpt = caps["chars_per_token"]
    ctx_chars = caps["context_window_tokens"] * cpt
    max_out_tokens = caps["max_output_tokens"]
    max_out_chars = max_out_tokens * cpt

    overhead = 50_000
    available = context_budget_chars - overhead - max_out_chars
    per_pdf_budget = int(available * (pdf_chars / max(total_pdf_chars, 1)))

    prompt_overhead = 5_000
    max_input = ctx_chars - max_out_chars - prompt_overhead
    chunk_count = max(1, math.ceil(pdf_chars / max_input))
    chunk_size = math.ceil(pdf_chars / chunk_count)

    per_chunk_budget_chars = per_pdf_budget / chunk_count
    chunk_out_tokens = min(max_out_tokens, max(1024, int(per_chunk_budget_chars / cpt)))
    combine_out_tokens = min(max_out_tokens, max(1024, int(per_pdf_budget / cpt)))

    logger.debug(
        "Computed chunk plan",
        pdf_chars=pdf_chars,
        num_pdfs=num_pdfs,
        total_pdf_chars=total_pdf_chars,
        context_budget_chars=context_budget_chars,
        model=model,
        chunk_count=chunk_count,
        chunk_size_chars=chunk_size,
        chunk_max_output_tokens=chunk_out_tokens,
        combine_max_output_tokens=combine_out_tokens,
        per_pdf_budget_chars=per_pdf_budget,
    )

    return PdfChunkPlan(
        chunk_count=chunk_count,
        chunk_size_chars=chunk_size,
        chunk_max_output_tokens=chunk_out_tokens,
        combine_max_output_tokens=combine_out_tokens,
    )


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


def split_pdf_by_chapters(text: str, toc: list, max_chars: int) -> list[tuple[str, str]]:
    """Split extracted text at chapter boundaries to fit max_chars per part.

    Falls back to page-based split if TOC is missing or has no page markers.

    Returns:
        List of (part_name, part_text) tuples.
    """
    if not toc:
        parts: list[tuple[str, str]] = []
        chunk_count = math.ceil(len(text) / max_chars)
        size = math.ceil(len(text) / chunk_count)
        for i in range(chunk_count):
            start = i * size
            end = min((i + 1) * size, len(text))
            if end < len(text):
                boundary = text.rfind("\n", start, end)
                if boundary > start:
                    end = boundary
            parts.append((f"Part {i + 1}", text[start:end]))
        return parts

    lines = text.splitlines(keepends=True)
    total_lines = len(lines)

    toc_chapters = [(title, page) for lvl, title, page in toc if lvl == 1 and page > 0]
    if not toc_chapters:
        toc_chapters = [(title, page) for lvl, title, page in toc if page > 0]

    if not toc_chapters:
        return split_pdf_by_chapters(text, [], max_chars)

    chars_per_line = max(1, len(text) / max(total_lines, 1))

    chapter_char_positions: list[tuple[str, int]] = []
    for title, page in toc_chapters:
        approx_char = int((page - 1) * chars_per_line * 45)
        chapter_char_positions.append((title, min(approx_char, len(text))))
    chapter_char_positions.sort(key=lambda x: x[1])

    groups: list[tuple[str, str]] = []
    group_start_idx = 0
    group_start_title = chapter_char_positions[0][0] if chapter_char_positions else "Part 1"
    current_len = 0

    for i, (title, char_pos) in enumerate(chapter_char_positions):
        chapter_text_start = char_pos
        chapter_text_end = (
            chapter_char_positions[i + 1][1] if i + 1 < len(chapter_char_positions) else len(text)
        )
        chapter_len = chapter_text_end - chapter_text_start

        if current_len + chapter_len > max_chars and current_len > 0:
            group_text = text[group_start_idx:char_pos]
            groups.append((group_start_title, group_text))
            group_start_idx = char_pos
            group_start_title = title
            current_len = 0

        current_len += chapter_len

    remaining = text[group_start_idx:]
    if remaining.strip():
        groups.append((group_start_title, remaining))

    return groups if groups else [("Part 1", text)]


def _get_summarizer_client(model: str):
    """Return the appropriate API client based on model name."""
    if model.startswith("gpt-"):
        from openai import AsyncOpenAI

        return AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))
    import anthropic

    return anthropic.AsyncAnthropic(
        api_key=os.getenv("ANTHROPIC_API_KEY", ""),
        timeout=600.0,
    )


async def _call_model(
    client,
    model: str,
    system: str,
    user_content: str,
    max_tokens: int,
) -> str:
    """Call the appropriate model API and return the text response."""
    if model.startswith("gpt-"):
        response = await client.chat.completions.create(
            model=model,
            max_completion_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
        )
        return response.choices[0].message.content.strip()
    async with client.messages.stream(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user_content}],
    ) as stream:
        message = await stream.get_final_message()
    return message.content[0].text.strip()


async def summarize_single_pdf(
    client,
    book_name: str,
    full_text: str,
    toc: list | None = None,
    model: str = _SUMMARIZER_MODEL,
    max_output_tokens: int = 60_000,
) -> str:
    """Summarize a single PDF using the enriched syllabus prompt.

    If the input fits within the model's context window, sends it in one call.
    If the input exceeds the model's context window, splits into chunks, summarizes
    each chunk separately, then combines the results. This allows large PDFs to be
    processed entirely on the same model without fallback.

    Supports both Anthropic (claude-*) and OpenAI (gpt-*) models.
    """
    toc_prefix = ""
    if toc:
        toc_lines = [f"{'  ' * (lvl - 1)}{title}" for lvl, title, _ in toc[:200]]
        toc_prefix = "TABLE OF CONTENTS:\n" + "\n".join(toc_lines) + "\n\n"

    full_input = toc_prefix + full_text

    caps = get_model_caps(model)
    max_input_chars = tokens_to_chars(
        caps["context_window_tokens"] - max_output_tokens - 1000, model
    )

    if len(full_input) <= max_input_chars:
        prompt = _SYLLABUS_SUMMARY_PROMPT.format(book_name=book_name, text=full_input)

        logger.info(
            "Summarizing PDF (single call)",
            book=book_name,
            model=model,
            input_chars=len(full_input),
            max_output_tokens=max_output_tokens,
        )

        result = await _call_model(
            client,
            model=model,
            system=_SYLLABUS_SUMMARY_SYSTEM,
            user_content=prompt,
            max_tokens=max_output_tokens,
        )

        logger.info(
            "PDF summarized",
            book=book_name,
            summary_chars=len(result),
        )
        return result

    chunks = _split_into_chunks(full_input, max_input_chars)
    total_chunks = len(chunks)

    logger.info(
        "Input exceeds model context — splitting into chunks",
        book=book_name,
        model=model,
        input_chars=len(full_input),
        max_input_chars=max_input_chars,
        chunk_count=total_chunks,
        context_window_tokens=caps["context_window_tokens"],
    )

    chunk_max_tokens = min(caps["max_output_tokens"], 16_000)
    combine_chunk_size = max_input_chars

    chunk_summaries: list[str] = []
    for i, chunk in enumerate(chunks):
        summary = await _summarize_chunk(
            client,
            book_name,
            chunk,
            chunk_num=i + 1,
            total_chunks=total_chunks,
            model=model,
            max_tokens=chunk_max_tokens,
        )
        logger.info(
            "Chunk summarized",
            book=book_name,
            chunk=i + 1,
            total=total_chunks,
            summary_chars=len(summary),
        )
        chunk_summaries.append(summary)

    combined = await _combine_summaries(
        client,
        book_name,
        chunk_summaries,
        combine_chunk_size=combine_chunk_size,
        model=model,
        max_tokens=max_output_tokens,
    )

    logger.info(
        "PDF summarized (chunked)",
        book=book_name,
        model=model,
        chunk_count=total_chunks,
        summary_chars=len(combined),
    )
    return combined


async def _combine_summaries(
    client,
    book_name: str,
    summaries: list[str],
    combine_chunk_size: int,
    model: str = _SUMMARIZER_MODEL,
    max_tokens: int = 64_000,
    target_words: int | None = None,
    max_concurrent: int = 5,
    _shared_semaphore: asyncio.Semaphore | None = None,  # kept for backward compat, unused
) -> str:
    """Combine per-resource summaries into one unified summary.

    If the concatenated summaries are too large for one call, they are
    combined hierarchically (in groups) before the final merge.
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
        return await _call_model(
            client,
            model=model,
            system=_COMBINE_SYSTEM,
            user_content=prompt,
            max_tokens=adjusted_max_tokens,
        )

    intermediate: list[str] = []
    for i, batch in enumerate(batches):
        prompt = _COMBINE_PROMPT.format(
            book_name=book_name,
            analyses=batch,
            word_limit_instruction=word_limit_instruction,
        )
        result = await _call_model(
            client,
            model=model,
            system=_COMBINE_SYSTEM,
            user_content=prompt,
            max_tokens=adjusted_max_tokens,
        )
        logger.debug(
            "Intermediate combine done",
            book=book_name,
            batch=i + 1,
            total_batches=len(batches),
        )
        intermediate.append(result)

    final_joined = "\n\n---\n\n".join(f"[Group {i + 1}]\n{s}" for i, s in enumerate(intermediate))
    prompt = _COMBINE_PROMPT.format(
        book_name=book_name,
        analyses=final_joined,
        word_limit_instruction=word_limit_instruction,
    )
    return await _call_model(
        client,
        model=model,
        system=_COMBINE_SYSTEM,
        user_content=prompt,
        max_tokens=adjusted_max_tokens,
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
    """Generate a structured summary for a single chunk using Claude (legacy path)."""
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
    return await _call_model(
        client,
        model=model,
        system=_CHUNK_SUMMARY_SYSTEM,
        user_content=prompt,
        max_tokens=adjusted_max_tokens,
    )


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
    num_pdfs: int | None = None,
    total_pdf_chars: int | None = None,
    context_budget_chars: int | None = None,
    summary_max_output_tokens: int | None = None,
) -> str:
    """Produce a rich educational content map summary of one PDF.

    Uses the new enriched summarization prompt when called without chunk overrides
    (single-call mode). Falls back to the legacy multi-chunk path when explicit
    chunk_size_chars is provided (backward compatibility).
    """
    if model.startswith("gpt-"):
        api_key = os.getenv("OPENAI_API_KEY", "")
        key_var = "OPENAI_API_KEY"
    else:
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        key_var = "ANTHROPIC_API_KEY"

    if not api_key:
        logger.warning(
            f"{key_var} not set — returning TOC-only summary",
            book=book_name,
        )
        if toc:
            toc_lines = [f"{'  ' * (lvl - 1)}{title}" for lvl, title, _ in toc]
            return "Table of Contents:\n" + "\n".join(toc_lines[:200])
        return f"[No API key — full text not summarized for {book_name}]"

    client = _get_summarizer_client(model)

    use_single_call = chunk_size_chars is None and chunk_max_output_tokens is None

    if use_single_call:
        caps = get_model_caps(model)
        max_out = caps["max_output_tokens"]
        effective_max = (
            summary_max_output_tokens if summary_max_output_tokens else min(max_out, 60_000)
        )
        return await summarize_single_pdf(
            client,
            book_name,
            full_text,
            toc=toc,
            model=model,
            max_output_tokens=effective_max,
        )

    use_dynamic_plan = (
        num_pdfs is not None
        and total_pdf_chars is not None
        and context_budget_chars is not None
        and chunk_size_chars is None
        and chunk_max_output_tokens is None
    )

    if use_dynamic_plan:
        plan = compute_chunk_plan(
            pdf_chars=len(full_text),
            num_pdfs=num_pdfs,
            total_pdf_chars=total_pdf_chars,
            context_budget_chars=context_budget_chars,
            model=model,
        )
        chunk_size = plan.chunk_size_chars
        combine_chunk_size = plan.chunk_size_chars
        chunk_max_tokens = plan.chunk_max_output_tokens
        combine_max_tokens = plan.combine_max_output_tokens
    else:
        defaults = _compute_defaults(model)
        chunk_size = (
            chunk_size_chars if chunk_size_chars is not None else defaults["chunk_size_chars"]
        )
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
        "Starting multi-pass summarization (legacy path)",
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
        summaries.append(result)

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
    chunk_size_chars: int | None = None,
    combine_chunk_size_chars: int | None = None,
    model: str = _SUMMARIZER_MODEL,
    chunk_max_output_tokens: int | None = None,
    combine_max_output_tokens: int | None = None,
    total_budget_chars: int | None = None,
    context_budget_chars: int | None = None,
    max_concurrent: int = 5,
    summary_max_output_tokens: int | None = None,
) -> list[str]:
    """Synchronous wrapper — summarize a list of (book_name, full_text, toc) tuples.

    When called without explicit chunk/token overrides, uses the new single-call
    enriched summarization path (one API call per PDF).

    Used from Celery tasks that call asyncio.run() explicitly.
    """
    effective_budget = (
        context_budget_chars if context_budget_chars is not None else total_budget_chars
    )
    per_pdf_budgets: list[int | None] = _proportional_budgets(pdf_texts, effective_budget)

    total_chars = sum(len(txt) for _, txt, _ in pdf_texts)
    use_dynamic_plan = (
        effective_budget is not None
        and chunk_size_chars is None
        and chunk_max_output_tokens is None
        and combine_max_output_tokens is None
    )

    if effective_budget is not None:
        logger.info(
            "Budget-aware summarization",
            context_budget_chars=effective_budget,
            num_pdfs=len(pdf_texts),
            total_pdf_chars=total_chars,
            per_pdf_budgets=per_pdf_budgets,
            use_dynamic_plan=use_dynamic_plan,
        )

    async def _run_all():
        results = []
        for (name, text, toc), budget in zip(pdf_texts, per_pdf_budgets, strict=True):
            summary = await summarize_pdf_for_syllabus(
                name,
                text,
                toc,
                chunk_size_chars=chunk_size_chars,
                combine_chunk_size_chars=combine_chunk_size_chars,
                model=model,
                chunk_max_output_tokens=chunk_max_output_tokens,
                combine_max_output_tokens=combine_max_output_tokens,
                target_chars=budget,
                num_pdfs=len(pdf_texts) if use_dynamic_plan else None,
                total_pdf_chars=total_chars if use_dynamic_plan else None,
                context_budget_chars=effective_budget if use_dynamic_plan else None,
                summary_max_output_tokens=summary_max_output_tokens,
            )
            logger.info("PDF summarized", book=name, summary_chars=len(summary))
            results.append(summary)
        return results

    loop = asyncio.new_event_loop()
    try:
        return list(loop.run_until_complete(_run_all()))
    finally:
        loop.close()


def _proportional_budgets(
    pdf_texts: list[tuple[str, str, list]],
    total_budget_chars: int | None,
) -> list[int | None]:
    """Compute per-PDF character budgets proportional to each PDF's text size."""
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
