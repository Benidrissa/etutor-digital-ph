"""AI-backed translation utilities (issue #1820, #1844, #1852)."""

from app.ai.translation.figure_classifier import (
    FigureClassification,
    FigureKind,
    classify_figure,
)
from app.ai.translation.figure_translator import (
    FigureTranslation,
    translate_figure_caption,
)
from app.ai.translation.svg_rederiver import (
    FlowchartEdge,
    FlowchartNode,
    FlowchartStructure,
    extract_flowchart_structure,
    render_svg,
    translate_structure,
)

__all__ = [
    "FigureClassification",
    "FigureKind",
    "FigureTranslation",
    "FlowchartEdge",
    "FlowchartNode",
    "FlowchartStructure",
    "classify_figure",
    "extract_flowchart_structure",
    "render_svg",
    "translate_figure_caption",
    "translate_structure",
]
