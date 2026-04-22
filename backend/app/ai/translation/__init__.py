"""AI-backed translation utilities (issue #1820, #1844)."""

from app.ai.translation.figure_classifier import (
    FigureClassification,
    FigureKind,
    classify_figure,
)
from app.ai.translation.figure_translator import (
    FigureTranslation,
    translate_figure_caption,
)

__all__ = [
    "FigureClassification",
    "FigureKind",
    "FigureTranslation",
    "classify_figure",
    "translate_figure_caption",
]
