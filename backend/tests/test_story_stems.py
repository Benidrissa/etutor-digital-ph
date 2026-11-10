"""Story-voiced quiz questions with the answer key locked (#2698).

The checks made in code, the judge's strict verdict, and the chapter builder
asking a course question in the story's voice while its options, answer and
explanation stay the quiz's own byte for byte. No model, no database (the
module pipeline is covered in ``test_story_module_service.py``).
"""

from __future__ import annotations

import asyncio
import copy
from typing import Any

import pytest

from app.domain.services import story_repair as repair
from app.domain.services.story_from_lesson_service import validate_document
from app.domain.services.story_stems import (
    STEM_JUDGE_VERSION,
    StemCandidate,
    approve_stems,
    approved_stems,
    build_judge_message,
    read_verdicts,
    stem_candidates,
    stem_problems,
)
from tests.test_story_screenplay_module import data, pack
from tests.test_story_v4_builder import build, chapter_ctx, spine

#: Story stems of chapter 1.1's course questions, as the pack writes them.
STORY_STEMS: dict[str, dict[str, str]] = {
    "q1": {
        "en": "Grandma tips out her basket. Which of these is a sign that something is alive?",
        "fr": "Mamie vide son panier. Lequel de ces signes montre qu'une chose est vivante ?",
    },
    "q2": {
        "en": "{friend} taps the plant. What does a mimosa leaf do when you touch it?",
        "fr": "{friend} tapote la plante. Que fait une feuille de mimosa quand on la touche ?",
    },
    "q3": {
        "en": "Grandma holds up the grey stone. Why is a pebble not alive?",
        "fr": "Mamie lève la pierre grise. Pourquoi un caillou n'est-il pas vivant ?",
    },
}


def quiz(ref: str) -> dict[str, Any]:
    return next(q for q in data()["quiz"] if q["id"] == ref)


def candidate(ref: str = "q3", **rewrite: str) -> StemCandidate:
    q = quiz(ref)
    return StemCandidate(
        ref=ref,
        original=dict(q["question"]),
        rewrite={**STORY_STEMS.get(ref, dict(q["question"])), **rewrite},
        options={lang: list(q["options"][lang]) for lang in ("en", "fr")},
        correct_index=q["correct_answer"],
    )


def stemmed_pack(unit: str = "1.1", language: str = "en") -> dict[str, Any]:
    the_pack = pack(unit, language)
    for item in the_pack["derived"]:
        if item["ref"] in STORY_STEMS:
            item["story_stem"] = copy.deepcopy(STORY_STEMS[item["ref"]])
    return the_pack


# --------------------------------------------------------------------------
# The checks made in code
# --------------------------------------------------------------------------


def test_a_faithful_story_stem_passes():
    for ref in STORY_STEMS:
        assert stem_problems(candidate(ref)) == [], ref


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        ({"en": "Grandma holds up the grey stone. Why is a pebble alive?"}, "negation"),
        ({"fr": "Mamie lève la pierre grise. Pourquoi un caillou est-il vivant ?"}, "negation"),
        ({"en": "Grandma holds up 2 grey stones. Why is a pebble not alive?"}, "numbers"),
        (
            {
                "en": "Grandma holds up the stone: it never feeds, grows or reproduces. Why not alive?"
            },
            "correct answer",
        ),
        ({"en": "In Bouaké, Aminata holds up a stone. Why is a pebble not alive?"}, "name"),
        ({"en": "Grandma meets Doctor Traoré. Why is a pebble not alive?"}, "name or place"),
        ({"en": "Why " + "really " * 30 + "is a pebble not alive?"}, "characters"),
        ({"en": "{teacher} holds up the stone. Why is a pebble not alive?"}, "placeholder"),
        ({"en": "Grandma holds up the grey stone, why is a pebble not alive."}, "question"),
        ({"en": ""}, "no story stem"),
    ],
)
def test_a_story_stem_that_changes_the_question_is_refused(change, problem):
    found = stem_problems(candidate("q3", **change), blocklist=["Aminata", "Bouaké"])
    assert found, change
    assert any(problem in p for p in found), found


def test_the_correct_answer_and_the_key_terms_are_checked():
    q = quiz("q10")  # "Which of these is NOT alive?"
    base = StemCandidate(
        ref="q10",
        original=dict(q["question"]),
        rewrite={
            "en": "The jury points at the table: which of these is NOT alive?",
            "fr": "Le jury montre la table : lequel de ces éléments n'est PAS vivant ?",
        },
        options={lang: list(q["options"][lang]) for lang in ("en", "fr")},
        correct_index=q["correct_answer"],
    )
    assert stem_problems(base) == []
    leaked = copy.deepcopy(base)
    leaked.rewrite["en"] = "The jury holds a pebble: which of these is NOT alive?"
    assert any("correct answer" in p for p in stem_problems(leaked))
    # The words a stem shares with its options tie it to them: they stay.
    heart = StemCandidate(
        ref="q99",
        original={
            "en": "Which organ pumps blood through the body?",
            "fr": "Quel organe pompe le sang dans le corps ?",
        },
        rewrite={
            "en": "Kaboré taps his chest: which organ pumps blood through the body?",
            "fr": "M. Kaboré tape sur sa poitrine : quel organe pompe le sang dans le corps ?",
        },
        options={
            "en": ["The heart pumps blood", "The lungs", "The stomach", "The skin"],
            "fr": ["Le cœur pompe le sang", "Les poumons", "L'estomac", "La peau"],
        },
        correct_index=0,
    )
    assert stem_problems(heart, allowed=["Kaboré"]) == []
    heart.rewrite["en"] = "Kaboré taps his chest: which organ works hardest in the body?"
    found = stem_problems(heart, allowed=["Kaboré"])
    assert any("key terms left out: blood, pump" in p for p in found), found


def test_a_name_of_the_course_may_be_used():
    kept = candidate("q3", en="Awa holds up the grey stone. Why is a pebble not alive, Awa?")
    assert stem_problems(kept, allowed=["Awa"]) == []
    assert stem_problems(kept) != []


# --------------------------------------------------------------------------
# The judge's verdict: strict JSON, anything else is a no
# --------------------------------------------------------------------------


def _verdict(**overrides: Any) -> dict[str, Any]:
    return {
        "ref": "q1",
        "same_question": True,
        "same_answer": True,
        "gives_away": False,
        **overrides,
    }


@pytest.mark.parametrize(
    ("raw", "approved"),
    [
        ({"verdicts": [_verdict()]}, True),
        ({"verdicts": [_verdict(same_answer=False)]}, False),
        ({"verdicts": [_verdict(same_question=False)]}, False),
        ({"verdicts": [_verdict(gives_away=True)]}, False),
        ({"verdicts": [_verdict(same_answer="true")]}, False),  # a string is not a boolean
        ({"verdicts": [_verdict(gives_away=None)]}, False),
        ({"verdicts": [_verdict(), _verdict()]}, False),  # two entries for one ref
        ({"verdicts": [_verdict(ref="q9")]}, False),
        ({"verdicts": "yes"}, False),
        ({"raw_response": "not JSON"}, False),
        (None, False),
    ],
)
def test_the_judge_approves_only_a_strict_yes(raw, approved):
    assert read_verdicts(raw, ["q1"]) == {"q1": approved}


def test_the_judge_message_shows_both_stems_the_options_and_the_key():
    message = build_judge_message([candidate("q3")], "fr")
    assert "ORIGINAL (fr): Pourquoi un caillou n'est-il pas vivant ?" in message
    assert "REWRITE (fr): Mamie lève la pierre grise." in message
    assert "a) Il ne se nourrit, ne grandit et ne se reproduit jamais  <- correct" in message
    assert '"same_question"' in message and '"gives_away"' in message


class FakeJudge:
    def __init__(self, verdict: Any = "yes") -> None:
        self.verdict = verdict
        self.messages: list[str] = []

    async def generate_structured_content(self, system, user, content_type, max_retries=1):
        self.messages.append(user)
        if isinstance(self.verdict, Exception):
            raise self.verdict
        refs = [line[1:-1] for line in user.splitlines() if line.startswith("[q")]
        ok = self.verdict == "yes"
        return {
            "verdicts": [
                {"ref": r, "same_question": True, "same_answer": ok, "gives_away": False}
                for r in refs
            ],
            "__complete": True,
        }


def test_only_the_stems_that_pass_the_checks_reach_the_judge():
    ctx = chapter_ctx()
    the_pack = stemmed_pack()
    leaked = next(d for d in the_pack["derived"] if d["ref"] == "q2")
    leaked["story_stem"]["en"] = "It folds shut! What does a mimosa leaf do when you touch it?"
    candidates, kept = stem_candidates(ctx, the_pack)
    assert [c.ref for c in candidates] == ["q1", "q3"]
    assert "correct answer" in kept["q2"]
    judge = FakeJudge()
    verdict = asyncio.run(approve_stems(ctx, the_pack, judge))
    assert len(judge.messages) == 1 and "[q2]" not in judge.messages[0]
    assert set(verdict["approved"]) == {"q1", "q3"} and verdict["version"] == STEM_JUDGE_VERSION
    assert approved_stems(verdict)["q3"] == STORY_STEMS["q3"]


def test_a_judge_that_says_no_keeps_the_original_and_is_not_asked_again():
    verdict = asyncio.run(approve_stems(chapter_ctx(), stemmed_pack(), FakeJudge("no")))
    assert verdict["approved"] == {} and set(verdict["kept"]) == {"q1", "q2", "q3"}
    assert verdict["calls"] == 1  # a verdict: kept with the pack


def test_a_provider_error_or_no_judge_decides_nothing():
    ctx, the_pack = chapter_ctx(), stemmed_pack()
    assert asyncio.run(approve_stems(ctx, the_pack, FakeJudge(RuntimeError("529")))) is None
    assert asyncio.run(approve_stems(ctx, the_pack, None)) is None
    # No story stem at all: nothing to judge, decided without a call.
    plain = asyncio.run(approve_stems(ctx, pack("1.1", "en"), None))
    assert plain["approved"] == {} and plain["calls"] == 0


# --------------------------------------------------------------------------
# The chapter: the question in the story's voice, the answer key locked
# --------------------------------------------------------------------------


def _question(result, ref: str) -> dict[str, Any]:
    return next(q for q in result.doc["questions"] if q["id"] == ref)


def test_an_approved_story_stem_is_asked_and_the_answer_key_stays_byte_for_byte():
    plain = build(chapter_ctx(), spine())
    ctx = chapter_ctx()
    ctx.story_stems = copy.deepcopy(STORY_STEMS)
    result = build(ctx, spine())
    for ref, stem in STORY_STEMS.items():
        before, after = _question(plain, ref), _question(result, ref)
        q = quiz(ref)
        assert after["prompt"] == stem
        assert after["original_stem"]["en"] == q["question"]["en"]  # the quiz's own
        assert after["original_stem"]["fr"] == q["question"]["fr"]  # the pack's translation
        # Locked: options, answer, explanation, the quiz it comes from.
        for key in ("choices", "answer", "explanation", "derived_from", "traps", "hints"):
            assert after[key] == before[key], key
        assert [c["en"] for c in after["choices"]] == q["options"]["en"]
        assert after["answer"] == "abcd"[q["correct_answer"]]
    report = repair.with_generator_issues(validate_document(result.doc), result)
    assert repair.publishable(report, result.doc).ok


def test_an_approved_story_stem_replaces_the_on_the_card_wrapper():
    """A long textbook stem was shown on « On the card »; its rewrite needs no card."""
    long_stem = "In the market of a faraway town, " + "a very long story about a grey pebble " * 6
    ctx = chapter_ctx()
    mcq = next(m for m in ctx.mcqs if m.ref == "q3")
    mcq.stem = long_stem + "— why is a pebble not alive?"
    carded = build(ctx, spine())
    steps = [s for sc in carded.doc["chapters"][0]["scenes"] for s in sc["steps"]]
    assert any(s.get("id") == "situation-q3" for s in steps)
    ctx = chapter_ctx()
    next(m for m in ctx.mcqs if m.ref == "q3").stem = long_stem + "— why is a pebble not alive?"
    ctx.story_stems = {"q3": STORY_STEMS["q3"]}
    result = build(ctx, spine())
    steps = [s for sc in result.doc["chapters"][0]["scenes"] for s in sc["steps"]]
    assert not any(s.get("id") == "situation-q3" for s in steps)
    question = _question(result, "q3")
    assert question["prompt"] == STORY_STEMS["q3"] and "stem" not in question
    assert question["original_stem"]["en"] == long_stem + "— why is a pebble not alive?"


def test_the_screenwriter_sees_the_story_stem():
    from app.ai.prompts.story_from_lesson import build_chapter_story_message

    ctx = chapter_ctx()
    ctx.story_stems = {"q3": STORY_STEMS["q3"]}
    message = build_chapter_story_message(ctx, pack("1.1", "en"))
    assert "[q3] tests IDEA" in message and STORY_STEMS["q3"]["en"] in message


def test_the_pack_asks_for_story_stems():
    from app.ai.prompts.story_from_lesson import build_pack_message

    message = build_pack_message(chapter_ctx())
    assert '"story_stem"' in message and "Only this sentence changes" in message


def test_a_question_asked_in_the_story_voice_is_still_the_quiz_question_for_dedup():
    """The assembler drops a later copy by what the quiz says, not by the rewrite."""
    from app.domain.services.story_module_assembly import derived_key

    plain = build(chapter_ctx(), spine())
    ctx = chapter_ctx()
    ctx.story_stems = {"q3": STORY_STEMS["q3"]}
    voiced = build(ctx, spine())
    for language in ("en", "fr"):
        key = derived_key(_question(voiced, "q3"), language)
        assert key is not None and key == derived_key(_question(plain, "q3"), language)
