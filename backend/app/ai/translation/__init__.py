"""AI-backed translation utilities (issues #1820, #1844, #1852, #1883)."""

from app.ai.translation.complex_overlay import (
    DiagramLabel,
    DiagramLabels,
    extract_label_positions,
    render_overlay_svg,
    translate_labels,
)
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
    "DiagramLabel",
    "DiagramLabels",
    "FigureClassification",
    "FigureKind",
    "FigureTranslation",
    "FlowchartEdge",
    "FlowchartNode",
    "FlowchartStructure",
    "classify_figure",
    "extract_flowchart_structure",
    "extract_label_positions",
    "render_overlay_svg",
    "render_svg",
    "translate_figure_caption",
    "translate_labels",
    "translate_structure",
]
