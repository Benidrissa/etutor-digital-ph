"""RAG pipeline for processing documents into searchable chunks with embeddings."""

import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.rag.chunker import (
    TextChunker,
    detect_language,
    extract_pages_from_pdf,
)
from app.ai.rag.embeddings import EmbeddingService
from app.ai.rag.image_extractor import PDFImageExtractor
from app.ai.rag.image_linker import ImageLinker
from app.ai.translation import (
    classify_figure,
    extract_flowchart_structure,
    extract_label_positions,
    read_figure_caption,
    render_overlay_svg,
    render_svg,
    translate_figure_caption,
    translate_labels,
    translate_structure,
)
from app.domain.models.document_chunk import DocumentChunk
from app.domain.models.source_image import SourceImage
from app.infrastructure.persistence.database import async_session_factory
from app.infrastructure.storage.s3 import S3StorageService

logger = structlog.get_logger()


class RAGPipeline:
    """Main pipeline for processing documents and populating the vector database."""

    def __init__(
        self, embedding_service: EmbeddingService, chunk_size: int = 512, overlap_size: int = 50
    ):
        self.embedding_service = embedding_service
        self.chunker = TextChunker(chunk_size=chunk_size, overlap_size=overlap_size)

    async def process_pdf_document(
        self,
        pdf_path: str | Path,
        source: str,
        level: int | None = None,
        session: AsyncSession | None = None,
        course_resource_id: UUID | None = None,
        content_hash: str | None = None,
    ) -> int:
        """
        Process a single PDF document through the complete RAG pipeline.

        Args:
            pdf_path: Path to the PDF file
            source: Source identifier (e.g., "donaldson", "triola")
            level: Optional difficulty level (1-4)
            session: Database session (will create one if not provided)
            course_resource_id: FK back to ``course_resources.id`` (#2186) so
                stored chunks know their originating PDF.
            content_hash: SHA-256 of the resource's extracted text. When set,
                the pipeline checks if another course already has chunks for
                this content and clones them instead of re-embedding.

        Returns:
            Number of chunks processed
        """
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        # Idempotent re-index: drop this resource's existing chunks first so a
        # re-run replaces rather than appends. _store_chunks' (source, chunk_index,
        # content) guard isn't stable across runs (chunk_index resets per page) and
        # the clone path has no guard at all, so without this a re-index doubles the
        # chunk count. Scoped strictly by course_resource_id — siblings untouched. #2534
        if course_resource_id:
            async with async_session_factory() as _clear_session:
                await self.clear_resource_chunks(source, course_resource_id, _clear_session)

        # Content-hash dedup: clone from a donor course instead of re-embedding.
        if content_hash and course_resource_id:
            async with async_session_factory() as _dedup_session:
                donors = await self._find_donor_chunks(
                    content_hash, course_resource_id, _dedup_session
                )
                if donors:
                    cloned = await self._clone_chunks(
                        donors, source, course_resource_id, _dedup_session
                    )
                    logger.info(
                        "Cloned chunks from donor — skipped embedding API",
                        cloned=cloned,
                        source=source,
                        content_hash=content_hash,
                    )
                    return cloned

        logger.info("Starting PDF processing", pdf_path=str(pdf_path), source=source)

        # Extract text per page so each chunk can record its page number.
        # The image linker's contextual matching joins on chunk.page == image.page_number;
        # before #2038 this was always None and that match path was dead.
        try:
            pages = extract_pages_from_pdf(str(pdf_path))
        except Exception as e:
            logger.error("Failed to extract text from PDF", pdf_path=str(pdf_path), error=str(e))
            raise

        if not pages:
            logger.warning("No text extracted from PDF", pdf_path=str(pdf_path))
            return 0

        # Sample first 5 pages for language detection — full document join would
        # waste memory on a 600-page textbook for the same answer.
        sample = " ".join(t for _, t in pages[:5])
        language = detect_language(sample)
        total_chars = sum(len(t) for _, t in pages)
        logger.info(
            "Detected language",
            language=language,
            text_length=total_chars,
            page_count=len(pages),
        )

        # Chunk page-by-page so each emitted DocumentChunk inherits its page.
        chunks = []
        for page_num, page_text in pages:
            if not page_text.strip():
                continue
            chunks.extend(
                self.chunker.chunk_document(
                    text=page_text,
                    source=source,
                    level=level,
                    language=language,
                    page=page_num,
                    course_resource_id=course_resource_id,
                )
            )

        if not chunks:
            logger.warning("No chunks created from document", pdf_path=str(pdf_path))
            return 0

        logger.info("Created chunks", chunk_count=len(chunks))

        # Generate embeddings
        chunk_texts = [chunk.content for chunk in chunks]
        embeddings = await self.embedding_service.generate_embeddings_batch(chunk_texts)

        # Store in database
        session_provided = session is not None
        if not session_provided:
            async with async_session_factory() as session:
                return await self._store_chunks(chunks, embeddings, session)
        else:
            return await self._store_chunks(chunks, embeddings, session)

    async def _store_chunks(
        self,
        chunks: list[Any],  # DocumentChunk from chunker
        embeddings: list[list[float]],
        session: AsyncSession,
    ) -> int:
        """Store chunks and embeddings in the database."""
        if len(chunks) != len(embeddings):
            raise ValueError("Mismatch between chunks and embeddings count")

        stored_count = 0

        for chunk_data, embedding in zip(chunks, embeddings, strict=False):
            # Check if this chunk already exists (idempotent)
            existing = await session.execute(
                select(DocumentChunk).where(
                    DocumentChunk.source == chunk_data.source,
                    DocumentChunk.chunk_index == chunk_data.chunk_index,
                    DocumentChunk.content == chunk_data.content,
                )
            )

            if existing.scalar_one_or_none():
                logger.debug(
                    "Chunk already exists, skipping",
                    source=chunk_data.source,
                    chunk_index=chunk_data.chunk_index,
                )
                continue

            # Create database model
            db_chunk = DocumentChunk(
                id=uuid4(),
                content=chunk_data.content,
                embedding=embedding,
                source=chunk_data.source,
                chapter=chunk_data.chapter,
                page=chunk_data.page,
                level=chunk_data.level,
                language=chunk_data.language,
                token_count=chunk_data.token_count,
                chunk_index=chunk_data.chunk_index,
                course_resource_id=getattr(chunk_data, "course_resource_id", None),
            )

            session.add(db_chunk)
            stored_count += 1

        await session.commit()
        logger.info("Stored chunks in database", stored_count=stored_count)

        return stored_count

    async def _find_donor_chunks(
        self,
        content_hash: str,
        new_resource_id: UUID,
        session: AsyncSession,
    ) -> list[DocumentChunk]:
        """Return existing chunks from exactly ONE other course resource sharing content_hash.

        A source PDF may have been indexed in several prior courses — each keeps its own
        `document_chunks` rows. Matching donors across *all* of them and cloning the union
        multiplies the new collection by the number of prior courses (e.g. a file indexed
        in 2 courses yields 2× the chunks). So pick a single donor resource and clone only
        its chunks. #2542

        Uses ix_course_resources_content_hash + ix_document_chunks_course_resource_id.
        """
        from app.domain.models.course_resource import CourseResource

        # Choose one donor resource deterministically (lowest id) so a re-run clones from
        # the same donor. Restricting to a single resource_id — not just content_hash — is
        # what prevents the cross-course multiplication.
        donor_resource_id = (
            await session.execute(
                select(DocumentChunk.course_resource_id)
                .join(CourseResource, CourseResource.id == DocumentChunk.course_resource_id)
                .where(
                    CourseResource.content_hash == content_hash,
                    DocumentChunk.course_resource_id != new_resource_id,
                    DocumentChunk.course_resource_id.is_not(None),
                )
                .order_by(DocumentChunk.course_resource_id)
                .limit(1)
            )
        ).scalar_one_or_none()

        if donor_resource_id is None:
            return []

        result = await session.execute(
            select(DocumentChunk)
            .where(DocumentChunk.course_resource_id == donor_resource_id)
            .order_by(DocumentChunk.chunk_index)
            .limit(5000)
        )
        return list(result.scalars().all())

    async def _clone_chunks(
        self,
        donor_chunks: list[DocumentChunk],
        new_source: str,
        new_resource_id: UUID,
        session: AsyncSession,
    ) -> int:
        """Insert copies of donor_chunks under new_source/new_resource_id without re-embedding.

        Deduplicates on ``(content, page, chunk_index)`` while cloning: a donor collection
        may itself hold duplicate rows (historical over-cloning compounded the count across
        course generations), and we must not carry that into the new collection. The key
        uniquely identifies a logical chunk within one document, so collapsing it is safe.
        #2542
        """
        cloned = 0
        seen: set[tuple[str, int | None, int]] = set()
        for donor in donor_chunks:
            key = (donor.content, donor.page, donor.chunk_index)
            if key in seen:
                continue
            seen.add(key)
            db_chunk = DocumentChunk(
                id=uuid.uuid4(),
                content=donor.content,
                embedding=donor.embedding,
                source=new_source,
                chapter=donor.chapter,
                page=donor.page,
                level=donor.level,
                language=donor.language,
                token_count=donor.token_count,
                chunk_index=donor.chunk_index,
                course_resource_id=new_resource_id,
            )
            session.add(db_chunk)
            cloned += 1
        await session.commit()
        return cloned

    async def process_pdf_images(
        self,
        pdf_path: str | Path,
        source: str,
        rag_collection_id: str | None = None,
        session: AsyncSession | None = None,
        progress_callback: "Callable[[int, int, str | None], None] | None" = None,
    ) -> int:
        """Extract images from a PDF, upload to MinIO, store metadata, and link to chunks.

        Args:
            pdf_path: Path to the PDF file.
            source: Source identifier (e.g., "donaldson").
            rag_collection_id: Optional RAG collection identifier.
            session: Database session (will create one if not provided).
            progress_callback: Optional `(images_done, images_total, current_figure_label)`
                callback invoked after each image is committed. Used by the celery
                task wrapper to update task.meta so the UI can show live progress
                instead of freezing at the start of the image-extraction phase
                (#2029).

        Returns:
            Number of images processed and stored.
        """
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        session_provided = session is not None
        if not session_provided:
            async with async_session_factory() as session:
                return await self._process_images(
                    pdf_path, source, rag_collection_id, session, progress_callback
                )
        else:
            return await self._process_images(
                pdf_path, source, rag_collection_id, session, progress_callback
            )

    async def _translate_figure_locales(
        self,
        *,
        caption: str | None,
        surrounding_text: str | None,
        figure_number: str | None,
        image_type: str,
        source: str,
    ) -> tuple[str | None, str | None, str | None, str | None]:
        """Translate a figure caption into FR/EN captions + alt text.

        Mirrors the #2272 fallback chain (caption → surrounding_text →
        figure_number) so caption-less figures still get usable locale text.
        Returns ``(None, None, None, None)`` when there is nothing to translate
        or translation fails after a bounded retry.
        """
        # Broader gate than "caption is non-empty" (#2272): figures whose
        # caption block didn't survive extraction still have a figure number +
        # surrounding text, and that's enough for Claude to write a usable
        # FR/EN caption + alt text. Without this fallback the locale columns
        # stayed NULL and the frontend dropped to the English caption.
        translator_input = (caption or "").strip()
        if not translator_input and surrounding_text:
            translator_input = surrounding_text.strip()[:200]
        if not translator_input and figure_number:
            translator_input = figure_number
        if not translator_input:
            return None, None, None, None

        last_exc: Exception | None = None
        for _ in range(2):
            try:
                translation = await translate_figure_caption(
                    caption=translator_input,
                    image_type=image_type,
                    figure_number=figure_number,
                )
                return (
                    translation.caption_fr,
                    translation.caption_en,
                    translation.alt_text_fr,
                    translation.alt_text_en,
                )
            except Exception as exc:
                last_exc = exc
        logger.warning(
            "Failed to translate figure caption after retry; storing NULL locales",
            source=source,
            figure_number=figure_number,
            error=str(last_exc),
        )
        return None, None, None, None

    async def _process_images(
        self,
        pdf_path: Path,
        source: str,
        rag_collection_id: str | None,
        session: AsyncSession,
        progress_callback: "Callable[[int, int, str | None], None] | None" = None,
    ) -> int:
        """Internal: extract, upload, store, and link images."""
        extractor = PDFImageExtractor(pdf_path.parent)
        images = extractor.extract_images_from_pdf(pdf_path, source)

        if not images:
            logger.info("No images extracted from PDF", pdf_path=str(pdf_path), source=source)
            return 0

        storage = S3StorageService()
        linker = ImageLinker()
        stored_count = 0

        for idx, img in enumerate(images):
            figure_label = img.figure_number or str(idx)
            safe_label = figure_label.replace(" ", "_").replace(".", "_")
            readable_name = pdf_path.stem.replace("_", " ")
            prefix = rag_collection_id or source
            key = f"source-images/{prefix}/{readable_name}/{img.page_number}_{safe_label}.webp"

            # Cross-course image dedup: reuse existing storage + computed fields.
            if img.image_hash:
                donor_result = await session.execute(
                    select(SourceImage)
                    .where(SourceImage.image_hash == img.image_hash)
                    # Prefer a donor that already carries a French caption so we
                    # don't clone NULL locales (which silently fall back to the
                    # English caption on the frontend). NULLs sort last. (#2428)
                    .order_by(SourceImage.caption_fr.is_(None))
                    .limit(1)
                )
                donor_img = donor_result.scalar_one_or_none()
                if donor_img is not None:
                    cloned_img = SourceImage(
                        id=uuid4(),
                        source=source,
                        rag_collection_id=rag_collection_id,
                        image_hash=img.image_hash,
                        # Reuse all expensive computed fields from donor:
                        storage_key=donor_img.storage_key,
                        storage_url=donor_img.storage_url,
                        storage_key_fr=donor_img.storage_key_fr,
                        storage_url_fr=donor_img.storage_url_fr,
                        embedding=donor_img.embedding,
                        caption_fr=donor_img.caption_fr,
                        caption_en=donor_img.caption_en,
                        alt_text_fr=donor_img.alt_text_fr,
                        alt_text_en=donor_img.alt_text_en,
                        # A text-dominant crop must stay body_text even when its
                        # hash matches a legacy donor row that predates the
                        # geometric guard — cloning would bypass it (#2502).
                        figure_kind="body_text" if img.is_text_dominant else donor_img.figure_kind,
                        image_type=donor_img.image_type,
                        width=donor_img.width,
                        height=donor_img.height,
                        file_size_bytes=donor_img.file_size_bytes,
                        original_format=donor_img.original_format,
                        format=donor_img.format,
                        # Keep per-document positional metadata:
                        page_number=img.page_number,
                        chapter=img.chapter,
                        section=img.section,
                        surrounding_text=img.surrounding_text,
                        figure_number=img.figure_number,
                        caption=img.caption,
                        attribution=img.attribution,
                    )
                    # If even the best donor lacked FR/EN captions, translate
                    # now rather than persisting NULL locales — otherwise the
                    # frontend shows the English caption to FR learners (#2428).
                    if cloned_img.caption_fr is None or cloned_img.caption_en is None:
                        (
                            cloned_img.caption_fr,
                            cloned_img.caption_en,
                            cloned_img.alt_text_fr,
                            cloned_img.alt_text_en,
                        ) = await self._translate_figure_locales(
                            caption=cloned_img.caption,
                            surrounding_text=cloned_img.surrounding_text,
                            figure_number=cloned_img.figure_number,
                            image_type=cloned_img.image_type,
                            source=source,
                        )
                    session.add(cloned_img)
                    await session.commit()
                    stored_count += 1
                    logger.debug(
                        "Reused image from donor — skipped MinIO upload and Claude API",
                        source=source,
                        image_hash=img.image_hash,
                        figure=img.figure_number,
                    )
                    if progress_callback is not None:
                        try:
                            progress_callback(stored_count, len(images), figure_label)
                        except Exception as cb_exc:
                            logger.debug(
                                "image progress_callback raised, ignoring",
                                error=str(cb_exc),
                            )
                    continue

            try:
                storage_url = await storage.upload_bytes(
                    key=key,
                    data=img.image_bytes,
                    content_type="image/webp",
                )
            except Exception as exc:
                logger.warning(
                    "Failed to upload image to MinIO, skipping",
                    key=key,
                    source=source,
                    error=str(exc),
                )
                continue

            # Read the real caption from the image + detect body-text crops
            # (#2435). The PyMuPDF extractor often leaves caption empty (the
            # translator then echoes the bare figure number, e.g. "Figure 4.2")
            # or rasterizes a page of body text as a figure. A cheap vision call
            # recovers the printed caption and flags non-figures.
            vision_body_text = False
            try:
                cap_read = await read_figure_caption(image_bytes=img.image_bytes)
                if cap_read.is_body_text:
                    vision_body_text = True
                elif cap_read.caption:
                    img.caption = cap_read.caption
            except RuntimeError:
                pass  # vision disabled (kill-switch) — keep the heuristic caption
            except Exception as exc:
                logger.warning(
                    "Failed to read figure caption via vision, keeping heuristic",
                    source=source,
                    figure_number=img.figure_number,
                    error=str(exc),
                )

            caption_text = " ".join(filter(None, [img.caption, img.surrounding_text]))
            embedding: list[float] | None = None
            if caption_text.strip():
                try:
                    embedding = await self.embedding_service.generate_embedding(caption_text)
                except Exception as exc:
                    logger.warning(
                        "Failed to generate caption embedding, storing without embedding",
                        source=source,
                        error=str(exc),
                    )

            caption_fr, caption_en, alt_text_fr, alt_text_en = await self._translate_figure_locales(
                caption=img.caption,
                surrounding_text=img.surrounding_text,
                figure_number=img.figure_number,
                image_type=img.image_type,
                source=source,
            )

            figure_kind: str | None = None
            if vision_body_text:
                # The caption reader already determined this crop is page text,
                # not a figure (#2435). Tag it so the retriever excludes it and
                # purge_body_text_figures (#2431) can remove it; skip the extra
                # classification call.
                figure_kind = "body_text"
            else:
                try:
                    classification = await classify_figure(image_bytes=img.image_bytes)
                    figure_kind = classification.kind
                except Exception as exc:
                    logger.warning(
                        "Failed to classify figure, storing without figure_kind",
                        source=source,
                        figure_number=img.figure_number,
                        error=str(exc),
                    )

            storage_key_fr: str | None = None
            storage_url_fr: str | None = None
            if figure_kind == "clean_flowchart":
                try:
                    structure = await extract_flowchart_structure(image_bytes=img.image_bytes)
                    translated = await translate_structure(structure, target_lang="fr")
                    svg_bytes = render_svg(translated)
                    svg_key = (
                        f"source-images/{prefix}/{readable_name}/"
                        f"{img.page_number}_{safe_label}.fr.svg"
                    )
                    storage_url_fr = await storage.upload_bytes(
                        key=svg_key,
                        data=svg_bytes,
                        content_type="image/svg+xml",
                    )
                    storage_key_fr = svg_key
                except Exception as exc:
                    logger.warning(
                        "Failed to re-derive flowchart as FR SVG, leaving fr variant NULL",
                        source=source,
                        figure_number=img.figure_number,
                        error=str(exc),
                    )
            elif figure_kind == "complex_diagram":
                try:
                    positions = await extract_label_positions(image_bytes=img.image_bytes)
                    if not positions.labels:
                        # Vision found no text labels — treat as a photo so
                        # Phase 1 caption translation covers it and the
                        # overlay backfill doesn't re-process this row.
                        figure_kind = "photo"
                    else:
                        translated_positions = await translate_labels(positions, target_lang="fr")
                        svg_bytes = render_overlay_svg(
                            image_bytes=img.image_bytes,
                            width_px=img.width or 1024,
                            height_px=img.height or 768,
                            labels=translated_positions,
                        )
                        svg_key = (
                            f"source-images/{prefix}/{readable_name}/"
                            f"{img.page_number}_{safe_label}.fr.svg"
                        )
                        storage_url_fr = await storage.upload_bytes(
                            key=svg_key,
                            data=svg_bytes,
                            content_type="image/svg+xml",
                        )
                        storage_key_fr = svg_key
                except Exception as exc:
                    logger.warning(
                        "Failed to build FR overlay for complex_diagram, leaving fr variant NULL",
                        source=source,
                        figure_number=img.figure_number,
                        error=str(exc),
                    )

            db_image = SourceImage(
                id=uuid4(),
                source=source,
                rag_collection_id=rag_collection_id,
                image_hash=img.image_hash,
                figure_number=img.figure_number,
                caption=img.caption,
                caption_fr=caption_fr,
                caption_en=caption_en,
                attribution=img.attribution,
                image_type=img.image_type,
                page_number=img.page_number,
                chapter=img.chapter,
                section=img.section,
                surrounding_text=img.surrounding_text,
                storage_key=key,
                storage_url=storage_url,
                storage_key_fr=storage_key_fr,
                storage_url_fr=storage_url_fr,
                format="webp",
                width=img.width,
                height=img.height,
                file_size_bytes=img.file_size_bytes,
                original_format=img.original_format,
                embedding=embedding,
                alt_text_fr=alt_text_fr,
                alt_text_en=alt_text_en,
                figure_kind=figure_kind,
            )

            session.add(db_image)
            # Commit per image so /index-status reflects progress live and
            # so a hang on a later image doesn't lose previously-extracted
            # work. Was a single batch commit at end-of-PDF (#2029).
            await session.commit()
            stored_count += 1

            if progress_callback is not None:
                try:
                    progress_callback(stored_count, len(images), figure_label)
                except Exception as cb_exc:  # never let callbacks break extraction
                    logger.debug(
                        "image progress_callback raised, ignoring",
                        error=str(cb_exc),
                    )

        logger.info("Stored source images", source=source, count=stored_count)

        links = await linker.link_images_to_chunks(source, session)
        await session.commit()
        logger.info("Linked images to chunks", source=source, links=links)

        return stored_count

    async def clear_source_images(self, source: str, session: AsyncSession | None = None) -> int:
        """Delete all source images for a given source from DB and MinIO.

        Args:
            source: Source identifier to clear.
            session: Database session.

        Returns:
            Number of images removed.
        """
        session_provided = session is not None
        if not session_provided:
            async with async_session_factory() as session:
                return await self._delete_source_images(source, session)
        else:
            return await self._delete_source_images(source, session)

    async def _delete_source_images(self, source: str, session: AsyncSession) -> int:
        """Delete source images from DB and MinIO."""
        result = await session.execute(select(SourceImage).where(SourceImage.source == source))
        images = result.scalars().all()

        if not images:
            logger.info("No source images to delete", source=source)
            return 0

        storage = S3StorageService()

        for image in images:
            if image.storage_key:
                try:
                    await storage.delete_object(image.storage_key)
                except Exception as exc:
                    logger.warning(
                        "Failed to delete MinIO object",
                        key=image.storage_key,
                        source=source,
                        error=str(exc),
                    )

        await session.execute(delete(SourceImage).where(SourceImage.source == source))
        await session.commit()
        deleted_count = len(images)

        logger.info("Cleared source images", source=source, count=deleted_count)
        return deleted_count

    async def process_resources_directory(
        self, resources_dir: str | Path, source_mappings: dict[str, str] | None = None
    ) -> dict[str, int]:
        """
        Process all PDF files in the resources directory.

        Args:
            resources_dir: Path to directory containing PDF files
            source_mappings: Optional mapping of filename patterns to source names

        Returns:
            Dictionary mapping source names to chunk counts
        """
        resources_dir = Path(resources_dir)

        if not resources_dir.exists():
            raise FileNotFoundError(f"Resources directory not found: {resources_dir}")

        # Default source mappings based on filename patterns
        if source_mappings is None:
            source_mappings = {
                "donaldson": "donaldson",
                "triola": "triola",
                "scutchfield": "scutchfield",
                "biostatistics": "triola",  # Alternative pattern
                "essential": "donaldson",  # Alternative pattern
                "principles": "scutchfield",  # Alternative pattern
            }

        results = {}
        pdf_files = list(resources_dir.glob("*.pdf"))

        if not pdf_files:
            logger.warning(
                "No PDF files found in resources directory", directory=str(resources_dir)
            )
            return results

        logger.info("Found PDF files", count=len(pdf_files), directory=str(resources_dir))

        for pdf_file in pdf_files:
            # Determine source name from filename
            source = self._determine_source_name(pdf_file.name, source_mappings)

            try:
                chunk_count = await self.process_pdf_document(pdf_path=pdf_file, source=source)
                results[source] = chunk_count
                logger.info(
                    "Processed PDF successfully",
                    file=pdf_file.name,
                    source=source,
                    chunks=chunk_count,
                )
            except Exception as e:
                logger.error(
                    "Failed to process PDF", file=pdf_file.name, source=source, error=str(e)
                )
                results[source] = 0

        return results

    def _determine_source_name(self, filename: str, source_mappings: dict[str, str]) -> str:
        """Determine source name from filename using pattern matching."""
        filename_lower = filename.lower()

        for pattern, source in source_mappings.items():
            if pattern.lower() in filename_lower:
                return source

        # Fallback: use filename without extension
        return filename.rsplit(".", 1)[0].lower().replace(" ", "_")

    async def clear_source_chunks(self, source: str, session: AsyncSession | None = None) -> int:
        """
        Remove all chunks for a specific source (useful for reprocessing).

        Args:
            source: Source identifier to clear
            session: Database session

        Returns:
            Number of chunks removed
        """
        session_provided = session is not None
        if not session_provided:
            async with async_session_factory() as session:
                return await self._clear_chunks(source, session)
        else:
            return await self._clear_chunks(source, session)

    async def _clear_chunks(self, source: str, session: AsyncSession) -> int:
        """Clear chunks from database."""
        # Count existing chunks
        count_result = await session.execute(
            select(DocumentChunk).where(DocumentChunk.source == source)
        )
        existing_count = len(count_result.scalars().all())

        if existing_count == 0:
            logger.info("No existing chunks found for source", source=source)
            return 0

        # Delete chunks
        await session.execute(delete(DocumentChunk).where(DocumentChunk.source == source))
        await session.commit()

        logger.info("Cleared existing chunks", source=source, count=existing_count)
        return existing_count

    async def clear_resource_chunks(
        self,
        source: str,
        course_resource_id: UUID,
        session: AsyncSession | None = None,
    ) -> int:
        """Delete one resource's chunks, scoped by (source, course_resource_id).

        Makes (re)indexing idempotent: callers clear a resource's existing chunks
        before storing/cloning fresh ones, so a re-run replaces rather than
        appends. Scoped strictly by ``course_resource_id`` so sibling resources in
        the same RAG collection are untouched. See #2534.
        """
        session_provided = session is not None
        if not session_provided:
            async with async_session_factory() as session:
                return await self._clear_resource_chunks(source, course_resource_id, session)
        return await self._clear_resource_chunks(source, course_resource_id, session)

    async def _clear_resource_chunks(
        self, source: str, course_resource_id: UUID, session: AsyncSession
    ) -> int:
        result = await session.execute(
            delete(DocumentChunk).where(
                DocumentChunk.source == source,
                DocumentChunk.course_resource_id == course_resource_id,
            )
        )
        await session.commit()
        deleted = result.rowcount or 0
        if deleted:
            logger.info(
                "Cleared resource chunks before re-index",
                source=source,
                course_resource_id=str(course_resource_id),
                count=deleted,
            )
        return deleted

    async def get_pipeline_stats(self, session: AsyncSession | None = None) -> dict[str, Any]:
        """Get statistics about the current state of the pipeline."""
        session_provided = session is not None
        if not session_provided:
            async with async_session_factory() as session:
                return await self._get_stats(session)
        else:
            return await self._get_stats(session)

    async def _get_stats(self, session: AsyncSession) -> dict[str, Any]:
        """Get pipeline statistics."""
        # Get all chunks
        result = await session.execute(select(DocumentChunk))
        chunks = result.scalars().all()

        if not chunks:
            return {"total_chunks": 0, "sources": {}, "languages": {}, "total_tokens": 0}

        # Calculate stats
        sources = {}
        languages = {}
        total_tokens = 0

        for chunk in chunks:
            # Source stats
            if chunk.source not in sources:
                sources[chunk.source] = {"count": 0, "tokens": 0}
            sources[chunk.source]["count"] += 1
            sources[chunk.source]["tokens"] += chunk.token_count

            # Language stats
            if chunk.language not in languages:
                languages[chunk.language] = 0
            languages[chunk.language] += 1

            total_tokens += chunk.token_count

        return {
            "total_chunks": len(chunks),
            "sources": sources,
            "languages": languages,
            "total_tokens": total_tokens,
            "avg_tokens_per_chunk": total_tokens / len(chunks) if chunks else 0,
        }
