"""Unit tests for the video-summary script helpers in LessonVideoService.

Covers the pure helpers that don't need a DB session:

* ``_build_video_system_prompt`` — the lesson-scoped prompt with a
  kids-register branch. Adult path takes ``course_title`` +
  ``level``; kids path takes the same plus ``age_range``. Tests
  prove each input flows through.
* ``_truncate_at_sentence`` — the last-resort fallback after the
  Claude re-prompt path.
"""

from __future__ import annotations

from app.domain.services.lesson_video_service import (
    _build_video_system_prompt,
    _truncate_at_sentence,
)


def test_prompt_includes_course_title_and_level_and_cap():
    prompt = _build_video_system_prompt(
        language="en",
        course_title="Introduction to Public Health",
        max_chars=2000,
        level=2,
    )
    assert "Introduction to Public Health" in prompt
    assert "level 2/4" in prompt
    assert "2000" in prompt
    assert "Output language: English" in prompt
    # Domain-grounding requirement must be explicit.
    assert "Ignoring the domain" in prompt


def test_prompt_uses_french_label_when_language_fr():
    prompt = _build_video_system_prompt(
        language="fr",
        course_title="Introduction à la santé publique",
        max_chars=2500,
        level=3,
    )
    assert "Output language: French" in prompt
    assert "Introduction à la santé publique" in prompt
    assert "2500" in prompt


def test_prompt_falls_back_to_generic_domain_when_no_course_title():
    prompt = _build_video_system_prompt(
        language="en",
        course_title=None,
        max_chars=1500,
        level=1,
    )
    # Generic placeholder surfaces so the prompt never ships a
    # template hole; the model still gets something to anchor on.
    assert "the subject area" in prompt


def test_truncate_noop_when_under_cap():
    text = "Short sentence. Another short one."
    assert _truncate_at_sentence(text, max_chars=100) == text


def test_truncate_at_sentence_boundary():
    text = (
        "Sentence one. Sentence two is longer. Sentence three "
        "goes well past the cap and should be dropped entirely."
    )
    out = _truncate_at_sentence(text, max_chars=40)
    assert len(out) <= 40
    assert out.endswith(".")
    assert "past the cap" not in out


def test_truncate_falls_back_to_ellipsis_when_no_terminator():
    text = "a" * 200
    out = _truncate_at_sentence(text, max_chars=50)
    assert len(out) <= 51  # + ellipsis char
    assert out.endswith("…")


def test_kids_prompt_differs_from_adult():
    """A kids video must not read like an adult-register video.

    The kids branch surfaces child-appropriate cues (age range,
    encouragement, 'Try this at home', 'warm-educator' tone pin)
    that the adult branch never emits.
    """
    adult = _build_video_system_prompt(
        language="en",
        course_title="Clinical epidemiology",
        max_chars=2000,
        level=4,
    )
    kids = _build_video_system_prompt(
        language="en",
        course_title="Clinical epidemiology",
        max_chars=2000,
        is_kids=True,
        age_range="6-10",
    )
    assert adult != kids
    # Kids-only markers.
    assert "children aged 6-10" in kids
    assert "Try this at home" in kids
    assert "'Let's remember'" in kids
    assert "warm-educator" in kids
    # Adult-only marker must not leak into kids.
    assert "level 4/4" not in kids


def test_kids_prompt_defaults_age_range_when_unset():
    """Missing age_range falls back to a sensible 6-12 default."""
    kids = _build_video_system_prompt(
        language="fr",
        course_title="Maths",
        max_chars=1500,
        is_kids=True,
        age_range="",
    )
    assert "6-12" in kids
    assert "French" in kids
