"""Unit tests for the video-summary script helpers in MediaSummaryService.

Covers the pure helpers that don't need a DB session:

* ``_build_video_system_prompt`` — the actual taxonomy-aware prompt
  is what tailors the output to audience + course field; this test
  proves the key inputs survive into the prompt.
* ``_truncate_at_sentence`` — the last-resort fallback after the
  Claude re-prompt path. The re-prompt path itself is covered by
  integration tests against a mocked ClaudeService elsewhere.
"""

from __future__ import annotations

from app.domain.services.media_summary_service import (
    _build_video_system_prompt,
    _truncate_at_sentence,
)


def test_prompt_includes_domain_audience_and_level():
    prompt = _build_video_system_prompt(
        language="en",
        domain_labels=["Health Sciences"],
        audience_labels=["Nursing Student"],
        level_labels=["Beginner"],
        course_title="Introduction to Public Health",
        max_chars=2000,
    )
    assert "Health Sciences" in prompt
    assert "Nursing Student" in prompt
    assert "Beginner" in prompt
    # Max-chars cap must be stated explicitly so the model can respect it.
    assert "2000" in prompt
    # Explicit failure-mode language on domain + audience (the prompt
    # is non-negotiably audience- and course-field-aware).
    assert "Ignoring the domain" in prompt
    assert "audience" in prompt.lower()


def test_prompt_uses_french_label_when_language_fr():
    prompt = _build_video_system_prompt(
        language="fr",
        domain_labels=["Sciences de la santé"],
        audience_labels=["Étudiant"],
        level_labels=["Débutant"],
        course_title="Introduction à la santé publique",
        max_chars=2500,
    )
    assert "Output language: French" in prompt
    assert "Sciences de la santé" in prompt
    assert "Étudiant" in prompt
    assert "2500" in prompt


def test_prompt_falls_back_to_course_title_when_no_domain():
    prompt = _build_video_system_prompt(
        language="en",
        domain_labels=[],
        audience_labels=[],
        level_labels=[],
        course_title="Biostatistics 101",
        max_chars=1500,
    )
    # Even without taxonomy labels we still pass a domain hint so the
    # model has something concrete to anchor examples on.
    assert "Biostatistics 101" in prompt


def test_truncate_noop_when_under_cap():
    text = "Short sentence. Another short one."
    assert _truncate_at_sentence(text, max_chars=100) == text


def test_truncate_at_sentence_boundary():
    text = (
        "Sentence one. Sentence two is longer. Sentence three "
        "goes well past the cap and should be dropped entirely."
    )
    out = _truncate_at_sentence(text, max_chars=40)
    # Must not exceed the cap.
    assert len(out) <= 40
    # Should end on a sentence terminator we chose.
    assert out.endswith(".")
    # The dropped sentence must not be in the output.
    assert "past the cap" not in out


def test_truncate_falls_back_to_ellipsis_when_no_terminator():
    text = "a" * 200
    out = _truncate_at_sentence(text, max_chars=50)
    assert len(out) <= 51  # + ellipsis char
    assert out.endswith("…")
