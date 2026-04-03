"""Semantic retrieval service for the RAG pipeline."""

from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.rag.embeddings import EmbeddingService
from app.domain.models.document_chunk import DocumentChunk

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
        top_k: int = 8,
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
            filters: Optional filters (rag_collection_id, source, level, language, chapter)
            session: Database session

        Returns:
            List of SearchResult objects ordered by similarity
        """
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
            if "rag_collection_id" in filters:
                where_clauses.append("rag_collection_id = :rag_collection_id")
                params["rag_collection_id"] = filters["rag_collection_id"]

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
        self, query: str, sources: list[str], top_k: int = 8, session: AsyncSession | None = None
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
        top_k: int = 8,
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
        # Don't filter by language — source books are all English,
        # Claude generates content in the user's target language
        filters: dict[str, Any] = {
            "level": {"$lte": user_level},
        }

        # Filter by module's source books if provided
        if books_sources:
            source_list = list(books_sources.keys())
            if source_list:
                filters["source"] = source_list

        return await self.search(query=query, top_k=top_k, filters=filters, session=session)

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
