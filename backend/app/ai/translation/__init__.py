"""AI-backed translation utilities (issue #1820)."""

from app.ai.translation.figure_translator import (
    FigureTranslation,
    translate_figure_caption,
)

__all__ = ["FigureTranslation", "translate_figure_caption"]
