"""Embeddings service for RAG pipeline using OpenAI text-embedding-3-small."""

import asyncio
from typing import Any

import structlog
from openai import AsyncOpenAI

logger = structlog.get_logger()


class EmbeddingService:
    """Service for generating embeddings using OpenAI's text-embedding-3-small model."""

    def __init__(self, api_key: str, model: str = "text-embedding-3-small"):
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model
        self.dimensions = 1536  # text-embedding-3-small dimensions

    async def generate_embedding(self, text: str) -> list[float]:
        """
        Generate embedding for a single text.

        Args:
            text: Text to embed

        Returns:
            List of float values representing the embedding vector
        """
        try:
            response = await self.client.embeddings.create(
                input=text, model=self.model, dimensions=self.dimensions
            )
            return response.data[0].embedding
        except Exception as e:
            logger.error("Failed to generate embedding", text_length=len(text), error=str(e))
            raise

    async def generate_embeddings_batch(
        self, texts: list[str], batch_size: int = 100, max_concurrent: int = 10
    ) -> list[list[float]]:
        """
        Generate embeddings for multiple texts in batches with concurrency control.

        Args:
            texts: List of texts to embed
            batch_size: Number of texts to embed in each API call
            max_concurrent: Maximum number of concurrent API calls

        Returns:
            List of embedding vectors in the same order as input texts
        """
        if not texts:
            return []

        # Split texts into batches
        batches = [texts[i : i + batch_size] for i in range(0, len(texts), batch_size)]

        # Create semaphore to limit concurrency
        semaphore = asyncio.Semaphore(max_concurrent)

        async def process_batch(batch: list[str]) -> list[list[float]]:
            async with semaphore:
                try:
                    response = await self.client.embeddings.create(
                        input=batch, model=self.model, dimensions=self.dimensions
                    )
                    return [data.embedding for data in response.data]
                except Exception as e:
                    logger.error(
                        "Failed to process embedding batch", batch_size=len(batch), error=str(e)
                    )
                    raise

        # Process all batches concurrently
        logger.info(
            "Generating embeddings",
            total_texts=len(texts),
            batches=len(batches),
            batch_size=batch_size,
        )

        batch_results = await asyncio.gather(*[process_batch(batch) for batch in batches])

        # Flatten results while preserving order
        embeddings = []
        for batch_embeddings in batch_results:
            embeddings.extend(batch_embeddings)

        logger.info("Embeddings generated successfully", total_embeddings=len(embeddings))

        return embeddings

    async def similarity_search(
        self, query_embedding: list[float], embeddings: list[list[float]], top_k: int = 8
    ) -> list[tuple[int, float]]:
        """
        Find most similar embeddings using cosine similarity.

        Args:
            query_embedding: Query embedding vector
            embeddings: List of embedding vectors to search through
            top_k: Number of top results to return

        Returns:
            List of (index, similarity_score) tuples, sorted by similarity
        """
        import numpy as np

        if not embeddings:
            return []

        # Convert to numpy arrays
        query_vec = np.array(query_embedding)
        embed_matrix = np.array(embeddings)

        # Calculate cosine similarities
        similarities = np.dot(embed_matrix, query_vec) / (
            np.linalg.norm(embed_matrix, axis=1) * np.linalg.norm(query_vec)
        )

        # Get top-k indices and scores
        top_indices = np.argsort(similarities)[-top_k:][::-1]

        return [(int(idx), float(similarities[idx])) for idx in top_indices]

    def validate_embedding(self, embedding: list[float]) -> bool:
        """
        Validate that an embedding has the correct dimensions and valid values.

        Args:
            embedding: Embedding vector to validate

        Returns:
            True if valid, False otherwise
        """
        if not isinstance(embedding, list):
            return False

        if len(embedding) != self.dimensions:
            return False

        # Check for valid float values (no NaN or infinite values)
        try:
            for value in embedding:
                if not isinstance(value, (int, float)) or not (-1.0 <= value <= 1.0):
                    return False
            return True
        except (TypeError, ValueError):
            return False

    async def health_check(self) -> dict[str, Any]:
        """
        Check if the embedding service is working correctly.

        Returns:
            Health status information
        """
        try:
            # Test with a simple text
            test_embedding = await self.generate_embedding("Health check test")

            is_valid = self.validate_embedding(test_embedding)

            return {
                "status": "healthy" if is_valid else "unhealthy",
                "model": self.model,
                "dimensions": self.dimensions,
                "test_embedding_length": len(test_embedding),
                "test_embedding_valid": is_valid,
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "model": self.model,
                "dimensions": self.dimensions,
            }
