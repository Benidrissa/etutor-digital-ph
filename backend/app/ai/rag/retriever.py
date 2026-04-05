"""Semantic retrieval service for the RAG pipeline."""

import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.rag.embeddings import EmbeddingService
from app.domain.models.document_chunk import DocumentChunk
from app.domain.services.platform_settings_service import SettingsCache

logger = structlog.get_logger()


@dataclass
class SearchResult:
    """Result from semantic search."""

    chunk: DocumentChunk
    similarity_score: float

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {"chunk": self.chunk.to_dict(), "similarity_score": self.similarity_score}


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

        # Generate embedding for query
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
        """Perform the actual search using pgvector."""
        # Build the base query with cosine similarity
        # Convert embedding to PostgreSQL vector literal to avoid asyncpg binding issues
        embedding_literal = "[" + ",".join(str(x) for x in query_embedding) + "]"
        vec_expr = f"embedding::vector <=> '{embedding_literal}'::vector"

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

        query_str = f"""
        SELECT * FROM (
            SELECT
                id, content, source, chapter, page, level, language,
                token_count, chunk_index, created_at,
                1 - ({vec_expr}) as similarity
            FROM document_chunks
            WHERE {where_sql}
        ) sub
        WHERE similarity >= :min_similarity
        ORDER BY similarity DESC
        LIMIT :limit
        """

        params["min_similarity"] = min_similarity
        params["limit"] = top_k

        # Execute query
        try:
            query_obj = text(query_str).bindparams(**params)
            result = await session.execute(query_obj)
            rows = result.fetchall()
        except Exception as e:
            logger.error("Semantic search query failed", error=str(e))
            raise

        # Convert results to SearchResult objects
        search_results = []
        for row in rows:
            # Create DocumentChunk object from row data
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
                embedding=None,  # Don't load embeddings for results
            )

            search_results.append(SearchResult(chunk=chunk, similarity_score=float(row.similarity)))

        logger.info(
            "Semantic search completed",
            query_length=len(query_embedding),
            results=len(search_results),
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
        # Don't filter by language — source books are all English,
        # Claude generates content in the user's target language
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

        return await self.search(query=query, top_k=top_k, filters=filters, session=session)

    async def get_linked_images(
        self,
        chunk_ids: list[UUID],
        session: AsyncSession,
    ) -> dict[UUID, list[dict[str, Any]]]:
        """Return images linked to the given chunk IDs via source_image_chunks.

        Args:
            chunk_ids: List of document chunk UUIDs to look up.
            session: Database session.

        Returns:
            Mapping of chunk_id → list of image metadata dicts (to_meta_dict()).
            Prioritises ``explicit`` references over ``contextual``.
            At most 3 images per chunk and 5 images total are returned.
        """
        if not chunk_ids:
            return {}

        chunk_id_literals = ", ".join(f"'{cid}'::uuid" for cid in chunk_ids)

        query_str = f"""
        SELECT
            sic.chunk_id,
            sic.reference_type,
            si.id,
            si.source,
            si.rag_collection_id,
            si.figure_number,
            si.caption,
            si.attribution,
            si.image_type,
            si.page_number,
            si.chapter,
            si.width,
            si.height,
            si.file_size_bytes,
            si.storage_url,
            si.alt_text_fr,
            si.alt_text_en
        FROM source_image_chunks sic
        JOIN source_images si ON si.id = sic.image_id
        WHERE sic.chunk_id IN ({chunk_id_literals})
        ORDER BY
            sic.chunk_id,
            CASE sic.reference_type WHEN 'explicit' THEN 0 ELSE 1 END,
            si.created_at
        """

        try:
            result = await session.execute(text(query_str))
            rows = result.fetchall()
        except Exception as exc:
            logger.error("get_linked_images query failed", error=str(exc))
            raise

        per_chunk: dict[UUID, list[dict[str, Any]]] = {cid: [] for cid in chunk_ids}
        total_added = 0

        for row in rows:
            if total_added >= 5:
                break
            chunk_id = row.chunk_id
            if len(per_chunk[chunk_id]) >= 3:
                continue
            per_chunk[chunk_id].append(
                {
                    "id": str(row.id),
                    "source": row.source,
                    "rag_collection_id": row.rag_collection_id,
                    "figure_number": row.figure_number,
                    "caption": row.caption,
                    "attribution": row.attribution,
                    "image_type": row.image_type,
                    "page_number": row.page_number,
                    "chapter": row.chapter,
                    "width": row.width,
                    "height": row.height,
                    "file_size_bytes": row.file_size_bytes,
                    "storage_url": row.storage_url,
                    "alt_text_fr": row.alt_text_fr,
                    "alt_text_en": row.alt_text_en,
                    "reference_type": row.reference_type,
                }
            )
            total_added += 1

        logger.info(
            "get_linked_images completed",
            chunk_count=len(chunk_ids),
            total_images=total_added,
        )
        return per_chunk

    async def search_source_images(
        self,
        query: str,
        source: str | None = None,
        rag_collection_id: str | None = None,
        top_k: int = 5,
        session: AsyncSession | None = None,
    ) -> list[dict[str, Any]]:
        """Semantic search on source_images.embedding (cosine similarity).

        Args:
            query: Natural-language query.
            source: Filter by source book (e.g. "donaldson").
            rag_collection_id: Filter by RAG collection UUID string.
            top_k: Maximum number of results.
            session: Database session.

        Returns:
            List of image metadata dicts ordered by similarity (no binary data).
        """
        if not query.strip():
            return []

        query_embedding = await self.embedding_service.generate_embedding(query)

        session_provided = session is not None
        if not session_provided:
            from app.infrastructure.persistence.database import async_session_factory

            async with async_session_factory() as _session:
                return await self._search_source_images(
                    query_embedding, source, rag_collection_id, top_k, _session
                )
        else:
            return await self._search_source_images(
                query_embedding, source, rag_collection_id, top_k, session
            )

    async def _search_source_images(
        self,
        query_embedding: list[float],
        source: str | None,
        rag_collection_id: str | None,
        top_k: int,
        session: AsyncSession,
    ) -> list[dict[str, Any]]:
        """Execute cosine-similarity search on source_images table."""
        embedding_literal = "[" + ",".join(str(x) for x in query_embedding) + "]"
        vec_expr = f"embedding::vector <=> '{embedding_literal}'::vector"

        where_clauses = ["embedding IS NOT NULL"]
        params: dict[str, Any] = {}

        if source is not None:
            where_clauses.append("source = :source")
            params["source"] = source
        if rag_collection_id is not None:
            where_clauses.append("rag_collection_id = :rag_collection_id")
            params["rag_collection_id"] = rag_collection_id

        where_sql = " AND ".join(where_clauses)
        params["limit"] = top_k

        query_str = f"""
        SELECT
            id, source, rag_collection_id, figure_number, caption, attribution,
            image_type, page_number, chapter, width, height,
            file_size_bytes, storage_url, alt_text_fr, alt_text_en,
            1 - ({vec_expr}) AS similarity
        FROM source_images
        WHERE {where_sql}
        ORDER BY similarity DESC
        LIMIT :limit
        """

        try:
            result = await session.execute(text(query_str).bindparams(**params))
            rows = result.fetchall()
        except Exception as exc:
            logger.error("search_source_images query failed", error=str(exc))
            raise

        images = [
            {
                "id": str(row.id),
                "source": row.source,
                "rag_collection_id": row.rag_collection_id,
                "figure_number": row.figure_number,
                "caption": row.caption,
                "attribution": row.attribution,
                "image_type": row.image_type,
                "page_number": row.page_number,
                "chapter": row.chapter,
                "width": row.width,
                "height": row.height,
                "file_size_bytes": row.file_size_bytes,
                "storage_url": row.storage_url,
                "alt_text_fr": row.alt_text_fr,
                "alt_text_en": row.alt_text_en,
                "similarity": float(row.similarity),
            }
            for row in rows
        ]

        logger.info(
            "search_source_images completed",
            results=len(images),
            top_similarity=images[0]["similarity"] if images else 0,
        )
        return images

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
