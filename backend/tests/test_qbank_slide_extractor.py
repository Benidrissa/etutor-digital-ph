"""Tests for the hybrid PDF slide extractor.

These tests build synthetic PDFs in-memory with colored text so we can verify
Tier 1 (PyMuPDF) behavior without any network calls. Tier 3 (Claude Vision) is
patched out — it is exercised only via confidence-escalation paths.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pymupdf
import pytest

from app.ai.qbank_slide_extractor import (
    CONFIDENCE_THRESHOLD,
    ExtractedSlideQuestion,
    _cluster_into_questions,
    _extract_tier1,
    _flatten_spans,
    _infer_category,
    _is_green,
    _parse_question_cluster,
    _tier1_confidence,
    extract_questions_from_pdf,
)

# PyMuPDF uses RGB floats in (0-1) for insert_text; the stored span color is int.
GREEN = (0, 0.6, 0)
RED = (0.8, 0, 0)
BLACK = (0, 0, 0)


def _build_slide_pdf(path: Path, pages: list[dict]) -> None:
    """Create a minimal PDF where each page has the given question text.

    pages is a list of dicts: {"question": str, "options": [(text, rgb), ...]}.
    """
    doc = pymupdf.open()
    for page_spec in pages:
        page = doc.new_page(width=595, height=842)  # A4
        y = 100
        if page_spec.get("question"):
            page.insert_text(
                (72, y),
                page_spec["question"],
                fontsize=14,
                color=BLACK,
            )
            y += 30  # Gap small enough that question + options cluster together
        for idx, (text, color) in enumerate(page_spec.get("options", [])):
            label = chr(ord("A") + idx)
            page.insert_text(
                (72, y),
                f"{label}. {text}",
                fontsize=12,
                color=color,
            )
            y += 20
    doc.save(str(path))
    doc.close()


class TestColorDetection:
    def test_lime_green_is_green(self):
        assert _is_green(0x00FF00) is True

    def test_dark_green_is_green(self):
        assert _is_green(0x008000) is True

    def test_red_is_not_green(self):
        assert _is_green(0xFF0000) is False

    def test_black_is_not_green(self):
        assert _is_green(0x000000) is False

    def test_yellow_is_not_green(self):
        # Yellow has high G but also high R — the ratio guard should reject it.
        assert _is_green(0xFFFF00) is False


class TestSpanFlattening:
    def test_empty_dict_returns_empty_list(self):
        assert _flatten_spans({"blocks": []}) == []

    def test_skips_empty_text(self):
        fake = {
            "blocks": [
                {
                    "type": 0,
                    "lines": [
                        {
                            "spans": [
                                {"text": "   ", "color": 0, "bbox": (0, 0, 10, 10)},
                                {"text": "hello", "color": 0, "bbox": (0, 20, 10, 30)},
                            ]
                        }
                    ],
                }
            ]
        }
        spans = _flatten_spans(fake)
        assert len(spans) == 1
        assert spans[0]["text"] == "hello"

    def test_sorts_top_to_bottom(self):
        fake = {
            "blocks": [
                {
                    "type": 0,
                    "lines": [
                        {
                            "spans": [
                                {"text": "second", "color": 0, "bbox": (0, 100, 10, 110)},
                                {"text": "first", "color": 0, "bbox": (0, 10, 10, 20)},
                            ]
                        }
                    ],
                }
            ]
        }
        spans = _flatten_spans(fake)
        assert [s["text"] for s in spans] == ["first", "second"]


class TestClusterIntoQuestions:
    @staticmethod
    def _span(text: str, y: float) -> dict:
        return {
            "text": text,
            "color": 0,
            "size": 12,
            "flags": 0,
            "font": "",
            "bbox": (0, y, 10, y + 10),
        }

    def test_empty_returns_empty(self):
        assert _cluster_into_questions([]) == []

    def test_single_cluster(self):
        spans = [self._span("a", 10), self._span("b", 30), self._span("c", 50)]
        clusters = _cluster_into_questions(spans)
        assert len(clusters) == 1
        assert len(clusters[0]) == 3

    def test_large_gap_splits_clusters(self):
        spans = [self._span("q1", 10), self._span("q2", 200)]
        clusters = _cluster_into_questions(spans)
        assert len(clusters) == 2


class TestParseQuestionCluster:
    @staticmethod
    def _span(text: str, color: int = 0) -> dict:
        return {
            "text": text,
            "color": color,
            "size": 12,
            "flags": 0,
            "font": "",
            "bbox": (0, 0, 10, 10),
        }

    def test_missing_options_returns_none(self):
        cluster = [self._span("What is the answer?")]
        assert _parse_question_cluster(cluster) is None

    def test_simple_two_option_question(self):
        cluster = [
            self._span("What should you do at a stop sign?"),
            self._span("A. Slow down"),
            self._span("B. Stop completely", color=0x00FF00),
        ]
        result = _parse_question_cluster(cluster)
        assert result is not None
        question, options, correct = result
        assert "stop sign" in question.lower()
        assert len(options) == 2
        assert correct == [1]

    def test_question_only_too_short(self):
        cluster = [
            self._span("Hi?"),
            self._span("A. Yes"),
            self._span("B. No"),
        ]
        assert _parse_question_cluster(cluster) is None

    def test_numeric_labels_work(self):
        cluster = [
            self._span("Which road sign indicates priority?"),
            self._span("1. Octagonal red"),
            self._span("2. Triangular yellow", color=0x00FF00),
        ]
        result = _parse_question_cluster(cluster)
        assert result is not None
        _, options, correct = result
        assert len(options) == 2
        assert correct == [1]


class TestInferCategory:
    """Keyword-based category classification used by Tier 1."""

    def test_signalisation_panneau_stop(self):
        assert (
            _infer_category("Que signifie ce panneau STOP ?", ["Je passe", "Je m'arrête"])
            == "signalisation"
        )

    def test_priorite_carrefour(self):
        assert (
            _infer_category(
                "Au carrefour, qui a la priorité ?",
                ["Le véhicule de droite", "Moi"],
            )
            == "priorite"
        )

    def test_securite_ceinture(self):
        assert (
            _infer_category(
                "La ceinture de sécurité est-elle obligatoire ?",
                ["Oui", "Non"],
            )
            == "securite"
        )

    def test_stationnement_parking(self):
        assert (
            _infer_category(
                "Où puis-je stationner ?",
                ["Sur le trottoir", "Dans un parking"],
            )
            == "stationnement"
        )

    def test_vitesse_km_h(self):
        assert (
            _infer_category(
                "Quelle est la vitesse maximale en ville ?",
                ["30 km/h", "50 km/h"],
            )
            == "vitesse"
        )

    def test_pieton_passage(self):
        assert (
            _infer_category(
                "Un piéton s'engage sur le passage, que faites-vous ?",
                ["Je le laisse passer", "Je klaxonne"],
            )
            == "pieton"
        )

    def test_cycliste_velo(self):
        assert (
            _infer_category(
                "Vous doublez un cycliste, quelle distance latérale ?",
                ["1 mètre", "50 cm"],
            )
            == "cycliste"
        )

    def test_unknown_falls_back_to_general(self):
        assert _infer_category("Quelle est la capitale ?", ["Paris", "Lyon"]) == "general"

    def test_diacritic_insensitive(self):
        # No diacritics on "priorite" → still matches "priorité" in input
        assert _infer_category("Priorité à droite", ["Oui", "Non"]) == "priorite"

    def test_uppercase_insensitive(self):
        assert _infer_category("PANNEAU STOP", ["A", "B"]) == "signalisation"


class TestTier1Confidence:
    def test_no_questions_is_zero(self):
        assert _tier1_confidence([], has_image=True) == 0.0

    def test_perfect_question_with_image(self):
        questions = [("What should you do?", ["Option A long", "Option B long"], [1])]
        score = _tier1_confidence(questions, has_image=True)
        assert score == pytest.approx(1.0)

    def test_no_correct_answer_detected_lowers_score(self):
        questions = [("What should you do?", ["Option A long", "Option B long"], [])]
        score = _tier1_confidence(questions, has_image=True)
        # Missing the "exactly one correct answer" +0.3 bonus
        assert score < CONFIDENCE_THRESHOLD + 0.2

    def test_partial_parse_is_penalized(self):
        """Cluster scanner saw 2 blocks but only 1 parsed → halve the score."""
        questions = [("What should you do?", ["Option A long", "Option B long"], [1])]
        full = _tier1_confidence(questions, has_image=True)
        partial = _tier1_confidence(questions, has_image=True, cluster_count=2)
        assert partial == pytest.approx(full * 0.5)
        # The halving must drop a "perfect" slide below the escalation threshold
        assert partial < CONFIDENCE_THRESHOLD

    def test_matching_cluster_count_is_not_penalized(self):
        questions = [("What should you do?", ["Option A long", "Option B long"], [1])]
        baseline = _tier1_confidence(questions, has_image=True)
        same = _tier1_confidence(questions, has_image=True, cluster_count=1)
        assert baseline == pytest.approx(same)


class TestExtractTier1EndToEnd:
    """Drive the whole Tier 1 path with a real synthetic PDF."""

    def test_high_confidence_slide(self, tmp_path: Path):
        pdf = tmp_path / "slide.pdf"
        _build_slide_pdf(
            pdf,
            [
                {
                    "question": "What should you do at a stop sign?",
                    "options": [
                        ("Slow down and proceed", RED),
                        ("Come to a complete stop", GREEN),
                    ],
                }
            ],
        )

        doc = pymupdf.open(str(pdf))
        questions, confidence = _extract_tier1(doc[0], doc, page_number=1)
        doc.close()

        assert len(questions) == 1
        q = questions[0]
        assert "stop sign" in q.question_text.lower()
        assert len(q.options) == 2
        assert q.correct_indices == [1]
        # "stop" is a signalisation keyword → category should be set, not None
        assert q.category == "signalisation"
        assert confidence >= CONFIDENCE_THRESHOLD

    def test_blank_page_has_zero_confidence(self, tmp_path: Path):
        pdf = tmp_path / "blank.pdf"
        doc = pymupdf.open()
        doc.new_page(width=595, height=842)
        doc.save(str(pdf))
        doc.close()

        doc = pymupdf.open(str(pdf))
        questions, confidence = _extract_tier1(doc[0], doc, page_number=1)
        doc.close()

        assert questions == []
        assert confidence == 0.0


class TestExtractQuestionsFromPdf:
    """End-to-end tests of the public entry point, with Vision mocked out."""

    @pytest.mark.asyncio
    async def test_tier1_handles_all_pages_without_vision(self, tmp_path: Path):
        pdf = tmp_path / "multi.pdf"
        _build_slide_pdf(
            pdf,
            [
                {
                    "question": "What is the right speed limit in town?",
                    "options": [("30 km/h", RED), ("50 km/h", GREEN), ("90 km/h", RED)],
                },
                {
                    "question": "What should you check before starting your car?",
                    "options": [("Tires and mirrors", GREEN), ("Only fuel", RED)],
                },
            ],
        )

        # If the hybrid pipeline works, ClaudeService must never be instantiated.
        with patch(
            "app.ai.qbank_slide_extractor.ClaudeService",
            side_effect=AssertionError("Should not be called"),
        ):
            results = await extract_questions_from_pdf(pdf)

        assert len(results) == 2
        assert all(isinstance(q, ExtractedSlideQuestion) for q in results)
        assert results[0].correct_indices == [1]
        assert results[1].correct_indices == [0]

    @pytest.mark.asyncio
    async def test_blank_page_escalates_to_vision(self, tmp_path: Path):
        pdf = tmp_path / "blank.pdf"
        doc = pymupdf.open()
        doc.new_page(width=595, height=842)
        doc.save(str(pdf))
        doc.close()

        fake_claude = AsyncMock()
        fake_response = AsyncMock()
        fake_response.content = []

        async def fake_create(**kwargs):
            class _Block:
                text = '[{"question_text": "From vision", "options": ["a long answer", "another"], "correct_indices": [0], "explanation": null, "category": null}]'

            class _Resp:
                content = [_Block()]

            return _Resp()

        fake_claude.client.messages.create = fake_create

        with patch(
            "app.ai.qbank_slide_extractor.ClaudeService",
            return_value=fake_claude,
        ):
            results = await extract_questions_from_pdf(pdf)

        assert len(results) == 1
        assert results[0].question_text == "From vision"

    @pytest.mark.asyncio
    async def test_missing_pdf_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            await extract_questions_from_pdf(tmp_path / "does-not-exist.pdf")
