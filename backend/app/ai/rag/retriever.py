"""Semantic retrieval service for the RAG pipeline."""

import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import and_, not_, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.rag.embeddings import EmbeddingService
from app.domain.models.document_chunk import DocumentChunk
from app.domain.models.source_image import SourceImage, SourceImageChunk
from app.domain.services.platform_settings_service import SettingsCache

logger = structlog.get_logger()

# Stock-photo / chapter-opener thumbnails extracted from PDFs come back as
# tiny webp/jpeg crops (~100–200px wide, ~3KB). They have correct caption
# metadata but the binary itself is unrelated to the figure they claim to
# represent (issue #2071). Until the extractor is fixed (#2073), drop them
# at retrieval time so the lesson generator never sees them as candidates.
_STOCK_THUMB_MAX_WIDTH = 200
_STOCK_THUMB_KINDS = ("photo", "decorative")
# Kinds that are never figures and must never surface in a lesson/tutor, even
# at full size — mis-extracted page text. (#2431)
_EXCLUDED_KINDS = ("body_text",)

# High-precision SourceImageChunk reference types. PR #2066 added
# `semantic` (caption-vs-chunk cosine similarity) which expanded the
# candidate pool 3.7× on the Triola collection (109 explicit → 400
# semantic). Lower precision than the others, so semantic links should
# only fill the slate for a chunk when it has no higher-precision link
# (issue #2072).
_HIGH_PRECISION_REF_TYPES = ("explicit", "contextual")


@dataclass
class SearchResult:
    """Result from semantic search."""

    chunk: DocumentChunk
    similarity_score: float

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {"chunk": self.chunk.to_dict(), "similarity_score": self.similarity_score}


# Retrieval diversity + budget (#2635). The generator used to send a blind
# top_k=8 chunks; with 512-token windows and 50-token overlap, adjacent chunks
# are frequently near-duplicates, so the slate carried only ~3-4 distinct
# passages — wasted prompt input and thin grounding. We now over-fetch a
# candidate pool via the HNSW index, MMR-select a distinct slate, then pack it
# to a token budget.
_MMR_LAMBDA = 0.7
_DEFAULT_CONTEXT_TOKEN_BUDGET = 3500
# HNSW recall knob: higher ef_search trades latency for recall, which matters
# because the source/level filters are applied alongside the index scan.
_HNSW_EF_SEARCH = 100


def _candidate_k(top_k: int) -> int:
    """Over-fetch size feeding MMR: enough surplus to prune near-duplicates."""
    return max(top_k * 2, top_k + 8)


def _mmr_select(
    candidates: list[tuple[SearchResult, list[float]]],
    top_k: int,
    lambda_: float = _MMR_LAMBDA,
) -> list[SearchResult]:
    """Maximal Marginal Relevance over query-ranked candidates.

    ``candidates`` is ordered by descending query similarity, each paired with
    its embedding. Greedily picks the item maximizing
    ``λ·sim_query − (1−λ)·max sim_to_already_selected`` so overlapping chunks
    don't all reach the prompt. Candidates missing an embedding contribute a
    redundancy term of 0 (treated as maximally novel) so the path degrades to
    plain ranking rather than failing.
    """
    from app.domain.services.citation_formatter import _cosine_distance

    if not candidates:
        return []
    pool = list(candidates)
    selected: list[tuple[SearchResult, list[float]]] = [pool.pop(0)]
    while pool and len(selected) < top_k:
        best_idx = 0
        best_score = float("-inf")
        for i, (res, emb) in enumerate(pool):
            sims = [
                1.0 - _cosine_distance(emb, sel_emb)
                for _, sel_emb in selected
                if emb and sel_emb
            ]
            max_sim = max(sims) if sims else 0.0
            score = lambda_ * res.similarity_score - (1.0 - lambda_) * max_sim
            if score > best_score:
                best_score = score
                best_idx = i
        selected.append(pool.pop(best_idx))
    return [res for res, _ in selected]


def _pack_to_token_budget(results: list[SearchResult], token_budget: int) -> list[SearchResult]:
    """Trim an ordered slate so cumulative chunk ``token_count`` ≤ budget.

    Always keeps at least the top chunk. Uses the stored token_count so a few
    large chunks can't bloat the prompt.
    """
    if token_budget <= 0:
        return results
    packed: list[SearchResult] = []
    total = 0
    for r in results:
        tokens = int(getattr(r.chunk, "token_count", 0) or 0)
        if packed and total + tokens > token_budget:
            break
        packed.append(r)
        total += tokens
    return packed


class SemanticRetriever:
    """Service for performing semantic search on document chunks."""

    def __init__(self, embedding_service: EmbeddingService):
        self.embedding_service = embedding_service

    async def search(
        self,
        query: str,
        top_k: int | None = None,
        min_similarity: float = 0.3,
        filters: dict[str, Any] | None = None,
        session: AsyncSession | None = None,
    ) -> list[SearchResult]:
        """
        Perform semantic search on document chunks.

        Args:
            query: Search query text
            top_k: Number of top results to return
            min_similarity: Minimum similarity threshold (0.0-1.0)
            filters: Optional filters (source, level, language, chapter)
            session: Database session

        Returns:
            List of SearchResult objects ordered by similarity
        """
        top_k = top_k or SettingsCache.instance().get("ai-rag-default-top-k", 8)
        if not query.strip():
            return []

        from app.ai.usage_context import ai_usage_context

        # Generate embedding for query. Ledger fallback feature: callers that
        # set a more specific feature (tutor_chat, lesson_generation, ...) win.
        with ai_usage_context("rag_query", only_if_unset=True):
            query_embedding = await self.embedding_service.generate_embedding(query)

        session_provided = session is not None
        if not session_provided:
            from app.infrastructure.persistence.database import async_session_factory

            async with async_session_factory() as session:
                return await self._perform_search(
                    query_embedding, top_k, min_similarity, filters, session
                )
        else:
            return await self._perform_search(
                query_embedding, top_k, min_similarity, filters, session
            )

    async def _perform_search(
        self,
        query_embedding: list[float],
        top_k: int,
        min_similarity: float,
        filters: dict[str, Any] | None,
        session: AsyncSession,
    ) -> list[SearchResult]:
        """Perform the actual search using pgvector.

        Index-backed (#2635): the ``embedding`` column is native ``vector(1536)``
        with an HNSW ``vector_cosine_ops`` index, so ordering by ``<=>`` distance
        and limiting uses the index instead of a per-row cast + sequential scan.
        We over-fetch a candidate pool, filter by ``min_similarity``, then
        MMR-select down to ``top_k`` and pack to a token budget.
        """
        # Vector literal (not a bind param) so asyncpg needs no vector codec and
        # the value stays a query constant the HNSW index can plan against.
        embedding_literal = "[" + ",".join(str(x) for x in query_embedding) + "]"
        vec_expr = f"embedding <=> '{embedding_literal}'::vector"

        where_clauses = ["embedding IS NOT NULL"]
        params: dict[str, Any] = {}

        if filters:
            if "source" in filters:
                if isinstance(filters["source"], list):
                    where_clauses.append("source = ANY(:source_list)")
                    params["source_list"] = filters["source"]
                else:
                    where_clauses.append("source = :source")
                    params["source"] = filters["source"]

            if "level" in filters:
                if isinstance(filters["level"], dict):
                    if "$lte" in filters["level"]:
                        where_clauses.append("(level IS NULL OR level <= :max_level)")
                        params["max_level"] = filters["level"]["$lte"]
                    if "$gte" in filters["level"]:
                        where_clauses.append("(level IS NULL OR level >= :min_level)")
                        params["min_level"] = filters["level"]["$gte"]
                else:
                    where_clauses.append("level = :level")
                    params["level"] = filters["level"]

            if "language" in filters:
                where_clauses.append("language = :language")
                params["language"] = filters["language"]

            if "chapter" in filters:
                if isinstance(filters["chapter"], list):
                    where_clauses.append("chapter = ANY(:chapter_list)")
                    params["chapter_list"] = filters["chapter"]
                else:
                    where_clauses.append("chapter = :chapter")
                    params["chapter"] = filters["chapter"]

            if "rag_collection_id" in filters:
                where_clauses.append("source = :rag_collection_id")
                params["rag_collection_id"] = filters["rag_collection_id"]

        where_sql = " AND ".join(where_clauses)

        # Over-fetch a candidate pool via the HNSW index, then MMR + budget it
        # down to top_k below. ``embedding::real[]`` returns a plain list[float]
        # to asyncpg (no vector codec needed) for the MMR redundancy math.
        # Kill-switch (#2635): when rerank is disabled, fetch exactly top_k and
        # skip MMR/budget — the legacy nearest-top_k behavior, no schema rollback.
        rerank_enabled = bool(
            SettingsCache.instance().get("ai-rag-rerank-enabled", True)
        )
        candidate_k = _candidate_k(top_k) if rerank_enabled else top_k
        query_str = f"""
            SELECT
                id, content, source, chapter, page, level, language,
                token_count, chunk_index, created_at,
                embedding::real[] AS embedding_arr,
                1 - ({vec_expr}) AS similarity
            FROM document_chunks
            WHERE {where_sql}
            ORDER BY {vec_expr}
            LIMIT :limit
        """

        params["limit"] = candidate_k

        # SET LOCAL hnsw.ef_search raises recall for the filtered index scan; it
        # lasts only this transaction.
        try:
            await session.execute(text(f"SET LOCAL hnsw.ef_search = {_HNSW_EF_SEARCH}"))
            query_obj = text(query_str).bindparams(**params)
            result = await session.execute(query_obj)
            rows = result.fetchall()
        except Exception as e:
            logger.error("Semantic search query failed", error=str(e))
            raise

        # Build (result, embedding) candidates, dropping any below threshold.
        candidates: list[tuple[SearchResult, list[float]]] = []
        for row in rows:
            similarity = float(row.similarity)
            if similarity < min_similarity:
                continue
            chunk = DocumentChunk(
                id=row.id,
                content=row.content,
                source=row.source,
                chapter=row.chapter,
                page=row.page,
                level=row.level,
                language=row.language,
                token_count=row.token_count,
                chunk_index=row.chunk_index,
                created_at=row.created_at,
                embedding=None,  # not surfaced to callers; kept separately for MMR
            )
            emb = list(row.embedding_arr) if row.embedding_arr is not None else []
            candidates.append((SearchResult(chunk=chunk, similarity_score=similarity), emb))

        if rerank_enabled:
            # MMR-select a distinct slate, then pack to the token budget.
            selected = _mmr_select(candidates, top_k)
            token_budget = int(
                SettingsCache.instance().get(
                    "ai-rag-context-token-budget", _DEFAULT_CONTEXT_TOKEN_BUDGET
                )
                or 0
            )
            search_results = _pack_to_token_budget(selected, token_budget)
        else:
            # Kill-switch: legacy nearest-top_k, no de-dup/budget. `candidates`
            # is already threshold-filtered and ordered nearest-first by the SQL.
            token_budget = 0
            search_results = [res for res, _ in candidates[:top_k]]

        logger.info(
            "Semantic search completed",
            query_length=len(query_embedding),
            rerank=rerank_enabled,
            candidates=len(candidates),
            results=len(search_results),
            token_budget=token_budget,
            slate_tokens=sum(
                int(getattr(r.chunk, "token_count", 0) or 0) for r in search_results
            ),
            top_similarity=search_results[0].similarity_score if search_results else 0,
        )

        return search_results

    async def search_by_source(
        self,
        query: str,
        sources: list[str],
        top_k: int | None = None,
        session: AsyncSession | None = None,
    ) -> dict[str, list[SearchResult]]:
        """
        Search within specific sources and return results grouped by source.

        Args:
            query: Search query text
            sources: List of source names to search within
            top_k: Number of results per source
            session: Database session

        Returns:
            Dictionary mapping source names to search results
        """
        top_k = top_k or SettingsCache.instance().get("ai-rag-default-top-k", 8)
        results = {}

        for source in sources:
            source_results = await self.search(
                query=query, top_k=top_k, filters={"source": source}, session=session
            )
            results[source] = source_results

        return results

    async def search_for_module(
        self,
        query: str,
        user_level: int,
        user_language: str,
        books_sources: dict[str, list[str]] | None = None,
        top_k: int | None = None,
        session: AsyncSession | None = None,
    ) -> list[SearchResult]:
        """
        Search for chunks relevant to a specific module and user context.

        Args:
            query: Search query text
            user_level: User's current level (1-4)
            user_language: User's preferred language ("fr" or "en")
            books_sources: Module's source books mapping (from module.books_sources)
            top_k: Number of results to return
            session: Database session

        Returns:
            List of SearchResult objects filtered by user context
        """
        top_k = top_k or SettingsCache.instance().get("ai-rag-default-top-k", 8)
        filters = self._build_module_filters(user_level, books_sources)
        return await self.search(query=query, top_k=top_k, filters=filters, session=session)

    @staticmethod
    def _build_module_filters(
        user_level: int, books_sources: dict[str, list[str]] | None
    ) -> dict[str, Any]:
        """Build the level + source filter dict for a module-scoped search.

        Don't filter by language — source books are all English; Claude
        generates content in the user's target language.
        """
        filters: dict[str, Any] = {
            "level": {"$lte": user_level},
        }

        # Filter by module's source books if provided
        if books_sources:
            source_list = list(books_sources.keys())
            if source_list:
                # Detect whether keys are rag_collection_id UUIDs (new-style courses)
                # or named textbook sources like "donaldson" (legacy public health course).
                # UUID pattern: 8-4-4-4-12 hex chars separated by hyphens.
                _uuid_pattern = re.compile(
                    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
                    re.IGNORECASE,
                )
                uuid_keys = [k for k in source_list if _uuid_pattern.match(k)]
                named_keys = [k for k in source_list if not _uuid_pattern.match(k)]

                if uuid_keys and not named_keys:
                    # New-style course: every key is a rag_collection_id; search only
                    # within those collections by matching the source column.
                    filters["source"] = uuid_keys
                elif named_keys:
                    # Legacy public-health course (donaldson / triola / scutchfield)
                    # or a mix — use the named keys as source filters.
                    filters["source"] = named_keys

        return filters

    async def count_source_chunks(self, source_keys: list[str], session: AsyncSession) -> int:
        """Count embedded chunks indexed under the given source keys.

        Used to distinguish a course that is genuinely un-indexed (zero chunks)
        from one that is indexed but whose chunks didn't match a unit's query.
        Returns 0 without querying when ``source_keys`` is empty.
        """
        if not source_keys:
            return 0
        result = await session.execute(
            text(
                "SELECT count(*) FROM document_chunks "
                "WHERE source = ANY(:keys) AND embedding IS NOT NULL"
            ).bindparams(keys=source_keys),
        )
        return int(result.scalar() or 0)

    async def get_linked_images(
        self,
        chunk_ids: list[UUID],
        session: AsyncSession,
        max_per_chunk: int = 3,
        max_total: int = 5,
    ) -> dict[UUID, list[dict]]:
        """
        Fetch source images linked to given document chunk IDs.

        Args:
            chunk_ids: List of document chunk UUIDs
            session: Database session
            max_per_chunk: Maximum images returned per chunk
            max_total: Maximum total images across all chunks

        Returns:
            Mapping {chunk_id: [image_meta_dict, ...]}
        """
        if not chunk_ids:
            return {}

        result: dict[UUID, list[dict]] = {cid: [] for cid in chunk_ids}
        total_collected = 0

        rows = await session.execute(
            select(SourceImageChunk, SourceImage)
            .join(SourceImage, SourceImageChunk.source_image_id == SourceImage.id)
            .where(
                SourceImageChunk.document_chunk_id.in_(chunk_ids),
                not_(
                    and_(
                        SourceImage.figure_kind.in_(_STOCK_THUMB_KINDS),
                        or_(
                            SourceImage.width.is_(None),
                            SourceImage.width <= _STOCK_THUMB_MAX_WIDTH,
                        ),
                    )
                ),
                # Never surface mis-extracted body-text crops, regardless of
                # size (they're large, so the stock-thumb filter misses them).
                # NULL kinds are kept — they're not yet classified. (#2431)
                or_(
                    SourceImage.figure_kind.is_(None),
                    SourceImage.figure_kind.notin_(_EXCLUDED_KINDS),
                ),
            )
            .order_by(
                SourceImageChunk.document_chunk_id,
                (SourceImageChunk.reference_type != "explicit"),
            )
        )
        pairs = rows.all()

        # Demote semantic-only links: when a chunk has any explicit or
        # contextual link, drop semantic rows for that chunk.
        per_chunk: dict[UUID, list] = {}
        for sic, img in pairs:
            per_chunk.setdefault(sic.document_chunk_id, []).append((sic, img))
        filtered_pairs = []
        for group in per_chunk.values():
            has_high_precision = any(
                sic.reference_type in _HIGH_PRECISION_REF_TYPES for sic, _ in group
            )
            if has_high_precision:
                filtered_pairs.extend(
                    (sic, img)
                    for sic, img in group
                    if sic.reference_type in _HIGH_PRECISION_REF_TYPES
                )
            else:
                filtered_pairs.extend(group)

        for sic, img in filtered_pairs:
            if total_collected >= max_total:
                break
            cid = sic.document_chunk_id
            if len(result[cid]) >= max_per_chunk:
                continue
            result[cid].append(img.to_meta_dict())
            total_collected += 1

        logger.info(
            "Linked images fetched",
            chunk_count=len(chunk_ids),
            total_images=total_collected,
        )
        return result

    async def search_source_images(
        self,
        query: str,
        top_k: int = 5,
        source: str | None = None,
        rag_collection_id: str | None = None,
        min_similarity: float = 0.3,
        session: AsyncSession | None = None,
    ) -> list[dict]:
        """
        Semantic search directly on source_images.embedding.

        Args:
            query: Search query text
            top_k: Number of results to return
            source: Optional filter by source book name
            rag_collection_id: Optional filter by RAG collection ID
            min_similarity: Minimum cosine similarity threshold
            session: Database session

        Returns:
            List of image metadata dicts (no binary data)
        """
        if not query.strip():
            return []

        from app.ai.usage_context import ai_usage_context

        with ai_usage_context("rag_query", only_if_unset=True):
            query_embedding = await self.embedding_service.generate_embedding(query)

        session_provided = session is not None
        if not session_provided:
            from app.infrastructure.persistence.database import async_session_factory

            async with async_session_factory() as session:
                return await self._search_source_images(
                    query_embedding, top_k, source, rag_collection_id, min_similarity, session
                )
        return await self._search_source_images(
            query_embedding, top_k, source, rag_collection_id, min_similarity, session
        )

    async def _search_source_images(
        self,
        query_embedding: list[float],
        top_k: int,
        source: str | None,
        rag_collection_id: str | None,
        min_similarity: float,
        session: AsyncSession,
    ) -> list[dict]:
        """Execute cosine similarity search on source_images table.

        Index-backed (#2635): native ``vector(1536)`` column + HNSW index, so
        ``ORDER BY embedding <=> :q LIMIT k`` uses the index. ``min_similarity``
        is applied as a post-filter over the k nearest rows.
        """
        embedding_literal = "[" + ",".join(str(x) for x in query_embedding) + "]"
        vec_expr = f"embedding <=> '{embedding_literal}'::vector"

        where_clauses = ["embedding IS NOT NULL"]
        params: dict[str, Any] = {}

        if source is not None:
            where_clauses.append("source = :source")
            params["source"] = source

        if rag_collection_id is not None:
            where_clauses.append("rag_collection_id = :rag_collection_id")
            params["rag_collection_id"] = rag_collection_id

        where_sql = " AND ".join(where_clauses)

        query_str = f"""
            SELECT
                id, source, rag_collection_id, figure_number, caption, attribution,
                image_type, page_number, chapter, section, surrounding_text,
                storage_key, storage_url, format, width, height, file_size_bytes,
                original_format, alt_text_fr, alt_text_en, semantic_tags, created_at,
                1 - ({vec_expr}) AS similarity
            FROM source_images
            WHERE {where_sql}
            ORDER BY {vec_expr}
            LIMIT :limit
        """

        params["limit"] = top_k

        try:
            await session.execute(text(f"SET LOCAL hnsw.ef_search = {_HNSW_EF_SEARCH}"))
            query_obj = text(query_str).bindparams(**params)
            result = await session.execute(query_obj)
            rows = result.fetchall()
        except Exception as e:
            logger.error("Source image semantic search failed", error=str(e))
            raise

        image_dicts = []
        for row in rows:
            if float(row.similarity) < min_similarity:
                continue
            img = SourceImage(
                id=row.id,
                source=row.source,
                rag_collection_id=row.rag_collection_id,
                figure_number=row.figure_number,
                caption=row.caption,
                attribution=row.attribution,
                image_type=row.image_type,
                page_number=row.page_number,
                chapter=row.chapter,
                section=row.section,
                surrounding_text=row.surrounding_text,
                storage_key=row.storage_key,
                storage_url=row.storage_url,
                format=row.format,
                width=row.width,
                height=row.height,
                file_size_bytes=row.file_size_bytes,
                original_format=row.original_format,
                alt_text_fr=row.alt_text_fr,
                alt_text_en=row.alt_text_en,
                semantic_tags=row.semantic_tags,
                created_at=row.created_at,
            )
            meta = img.to_meta_dict()
            meta["similarity"] = float(row.similarity)
            image_dicts.append(meta)

        logger.info(
            "Source image semantic search completed",
            results=len(image_dicts),
            top_similarity=image_dicts[0]["similarity"] if image_dicts else 0,
        )
        return image_dicts

    async def verify_search_functionality(
        self, session: AsyncSession | None = None
    ) -> dict[str, Any]:
        """
        Verify that semantic search is working correctly.

        Returns:
            Verification results including sample searches
        """
        session_provided = session is not None
        if not session_provided:
            from app.infrastructure.persistence.database import async_session_factory

            async with async_session_factory() as session:
                return await self._verify_search(session)
        else:
            return await self._verify_search(session)

    async def _verify_search(self, session: AsyncSession) -> dict[str, Any]:
        """Perform verification tests."""
        verification_results = {
            "status": "unknown",
            "total_chunks": 0,
            "chunks_with_embeddings": 0,
            "sample_searches": [],
        }

        try:
            # Count total chunks
            total_result = await session.execute(select(DocumentChunk))
            total_chunks = len(total_result.scalars().all())
            verification_results["total_chunks"] = total_chunks

            if total_chunks == 0:
                verification_results["status"] = "no_data"
                return verification_results

            # Count chunks with embeddings
            embedded_result = await session.execute(
                select(DocumentChunk).where(DocumentChunk.embedding.isnot(None))
            )
            embedded_chunks = len(embedded_result.scalars().all())
            verification_results["chunks_with_embeddings"] = embedded_chunks

            if embedded_chunks == 0:
                verification_results["status"] = "no_embeddings"
                return verification_results

            # Test sample searches
            test_queries = [
                "public health surveillance",
                "épidémiologie santé publique",
                "biostatistics data analysis",
                "health systems strengthening",
            ]

            for query in test_queries:
                try:
                    results = await self.search(query, top_k=3, min_similarity=0.0, session=session)

                    verification_results["sample_searches"].append(
                        {
                            "query": query,
                            "results_count": len(results),
                            "top_similarity": results[0].similarity_score if results else 0.0,
                            "sources": list(set(r.chunk.source for r in results))
                            if results
                            else [],
                        }
                    )
                except Exception as e:
                    verification_results["sample_searches"].append(
                        {"query": query, "error": str(e)}
                    )

            # Determine overall status
            successful_searches = sum(
                1
                for search in verification_results["sample_searches"]
                if "error" not in search and search["results_count"] > 0
            )

            if successful_searches >= len(test_queries) // 2:
                verification_results["status"] = "healthy"
            else:
                verification_results["status"] = "degraded"

        except Exception as e:
            verification_results["status"] = "error"
            verification_results["error"] = str(e)

        return verification_results
