"""Schemas for content generation endpoints."""

import uuid
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class LessonGenerationRequest(BaseModel):
    """Request schema for lesson generation."""

    module_id: UUID = Field(..., description="UUID of the target module")
    unit_id: str = Field(..., description="Unit identifier within the module")
    language: Literal["fr", "en"] = Field(..., description="Content language")
    country: str = Field(..., description="User's country code (ECOWAS)")
    level: int = Field(..., ge=1, le=4, description="User's competency level (1-4)")

    model_config = {
        "json_schema_extra": {
            "example": {
                "module_id": "550e8400-e29b-41d4-a716-446655440000",
                "unit_id": "1.1",
                "language": "fr",
                "country": "SN",
                "level": 2,
            }
        }
    }


class LessonContent(BaseModel):
    """Structured lesson content."""

    introduction: str = Field(..., description="Lesson introduction (2-3 sentences)")
    concepts: list[str] = Field(..., description="Key concepts paragraphs")
    aof_example: str = Field(..., description="Concrete West African example")
    synthesis: str = Field(..., description="Synthesis paragraph")
    key_points: list[str] = Field(..., description="Key takeaways (max 5 points)")
    sources_cited: list[str] = Field(..., description="Source citations")


class LessonResponse(BaseModel):
    """Response schema for generated lesson."""

    id: UUID = Field(default_factory=uuid.uuid4, description="Generated content ID")
    module_id: UUID = Field(..., description="Module ID")
    unit_id: str = Field(..., description="Unit identifier")
    content_type: Literal["lesson"] = Field(default="lesson", description="Content type")
    language: Literal["fr", "en"] = Field(..., description="Content language")
    level: int = Field(..., description="Target competency level")
    country_context: str = Field(..., description="Country context")
    content: LessonContent = Field(..., description="Structured lesson content")
    generated_at: str = Field(..., description="Generation timestamp (ISO format)")
    cached: bool = Field(default=False, description="Whether content was retrieved from cache")

    model_config = {
        "json_schema_extra": {
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440001",
                "module_id": "550e8400-e29b-41d4-a716-446655440000",
                "unit_id": "1.1",
                "content_type": "lesson",
                "language": "fr",
                "level": 2,
                "country_context": "SN",
                "content": {
                    "introduction": "La surveillance épidémiologique est un pilier fondamental...",
                    "concepts": [
                        "La surveillance épidémiologique consiste en...",
                        "Les systèmes de surveillance en Afrique de l'Ouest...",
                    ],
                    "aof_example": "Au Sénégal, le système de surveillance du paludisme...",
                    "synthesis": "En résumé, la surveillance épidémiologique efficace...",
                    "key_points": [
                        "1. La surveillance permet la détection précoce",
                        "2. Les données doivent être collectées régulièrement",
                        "3. L'analyse rapide guide les interventions",
                        "4. La communication des résultats est cruciale",
                        "5. L'évaluation continue améliore le système",
                    ],
                    "sources_cited": ["Donaldson Ch.4, p.67", "Scutchfield Ch.8, p.145"],
                },
                "generated_at": "2026-03-30T22:45:00Z",
                "cached": False,
            }
        }
    }


class StreamingEvent(BaseModel):
    """Server-Sent Event for streaming lesson generation."""

    event: Literal["chunk", "complete", "error"] = Field(..., description="Event type")
    data: str | dict[str, Any] = Field(..., description="Event data")

    def to_sse_format(self) -> str:
        """Convert to Server-Sent Events format."""
        import json

        if isinstance(self.data, dict):
            data_str = json.dumps(self.data, ensure_ascii=False)
        else:
            data_str = str(self.data)

        return f"event: {self.event}\ndata: {data_str}\n\n"


class FlashcardGenerationRequest(BaseModel):
    """Request schema for flashcard generation."""

    module_id: UUID = Field(..., description="UUID of the target module")
    language: Literal["fr", "en"] = Field(..., description="Content language")
    country: str = Field(..., description="User's country code (ECOWAS)")
    level: int = Field(..., ge=1, le=4, description="User's competency level (1-4)")

    model_config = {
        "json_schema_extra": {
            "example": {
                "module_id": "550e8400-e29b-41d4-a716-446655440000",
                "language": "fr",
                "country": "SN",
                "level": 2,
            }
        }
    }


class FlashcardContent(BaseModel):
    """Individual flashcard content structure."""

    term: str = Field(..., description="Key term or concept")
    definition_fr: str = Field(..., description="French definition (50-100 words)")
    definition_en: str = Field(..., description="English definition (50-100 words)")
    example_aof: str = Field(..., description="West African example (1-2 sentences)")
    formula: str | None = Field(None, description="LaTeX formula if applicable")
    sources_cited: list[str] = Field(..., description="Source citations")

    model_config = {
        "json_schema_extra": {
            "example": {
                "term": "Surveillance épidémiologique",
                "definition_fr": "Collecte systématique et continue de données sur l'état de santé des populations pour guider les actions de santé publique.",
                "definition_en": "Systematic and continuous collection of data on population health status to guide public health actions.",
                "example_aof": "Au Sénégal, le système de surveillance du paludisme collecte des données hebdomadaires dans tous les centres de santé.",
                "formula": None,
                "sources_cited": ["Donaldson Ch.4, p.67"],
            }
        }
    }


class FlashcardSetResponse(BaseModel):
    """Response schema for generated flashcard set."""

    id: UUID = Field(default_factory=uuid.uuid4, description="Generated content ID")
    module_id: UUID = Field(..., description="Module ID")
    content_type: Literal["flashcard"] = Field(default="flashcard", description="Content type")
    language: Literal["fr", "en"] = Field(..., description="Content language")
    level: int = Field(..., description="Target competency level")
    country_context: str = Field(..., description="Country context")
    flashcards: list[FlashcardContent] = Field(..., description="List of flashcards (15-30)")
    generated_at: str = Field(..., description="Generation timestamp (ISO format)")
    cached: bool = Field(default=False, description="Whether content was retrieved from cache")

    model_config = {
        "json_schema_extra": {
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440002",
                "module_id": "550e8400-e29b-41d4-a716-446655440000",
                "content_type": "flashcard",
                "language": "fr",
                "level": 2,
                "country_context": "SN",
                "flashcards": [
                    {
                        "term": "Surveillance épidémiologique",
                        "definition_fr": "Collecte systématique et continue de données...",
                        "definition_en": "Systematic and continuous collection of data...",
                        "example_aof": "Au Sénégal, le système de surveillance...",
                        "formula": None,
                        "sources_cited": ["Donaldson Ch.4, p.67"],
                    }
                ],
                "generated_at": "2026-03-31T02:45:00Z",
                "cached": False,
            }
        }
    }


class ErrorResponse(BaseModel):
    """Error response schema."""

    error: str = Field(..., description="Error type")
    message: str = Field(..., description="Human-readable error message")
    details: dict[str, Any] | None = Field(None, description="Additional error details")

    model_config = {
        "json_schema_extra": {
            "example": {
                "error": "module_not_found",
                "message": "Module with ID 550e8400-e29b-41d4-a716-446655440000 not found",
                "details": {"module_id": "550e8400-e29b-41d4-a716-446655440000"},
            }
        }
    }
