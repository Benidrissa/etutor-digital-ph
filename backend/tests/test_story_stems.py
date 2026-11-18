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


#: The course's words a story stem may use as names (the fixture bible's).
COURSE = ["Grandma", "Mamie", "Awa"]


def test_a_faithful_story_stem_passes():
    for ref in STORY_STEMS:
        assert stem_problems(candidate(ref), allowed=COURSE) == [], ref


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
            "names an option",
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
    found = stem_problems(
        candidate("q3", **change), blocklist=["Aminata", "Bouaké"], allowed=COURSE
    )
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
    assert any("names an option" in p for p in stem_problems(leaked))
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
    assert stem_problems(kept, allowed=COURSE) == []
    assert stem_problems(kept, allowed=["Mamie"]) != []


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
    assert "names an option" in kept["q2"]
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


# --------------------------------------------------------------------------
# The review of #2701: what the checks made in code must refuse
# --------------------------------------------------------------------------

ORGANS = {
    "en": ["The skin", "The liver", "The heart", "The brain"],
    "fr": ["La peau", "Le foie", "Le cœur", "Le cerveau"],
}
ALIVE = {
    "en": ["A pebble", "A snail", "A mango tree", "A goat"],
    "fr": ["Un caillou", "Un escargot", "Un manguier", "Une chèvre"],
}


def _check(original, rewrite, options, correct=0, **kwargs) -> list[str]:
    return stem_problems(
        StemCandidate(
            ref="q1", original=original, rewrite=rewrite, options=options, correct_index=correct
        ),
        allowed=COURSE,
        **kwargs,
    )


@pytest.mark.parametrize(
    ("original", "rewrite", "options", "problem"),
    [
        (  # Guard words, not groups: "largest" is not "smallest".
            {
                "en": "Which is the largest organ of the human body?",
                "fr": "Quel est le plus grand organe du corps humain ?",
            },
            {
                "en": "Grandma rubs her arm. Which is the smallest organ of the human body?",
                "fr": "Mamie frotte son bras. Quel est le plus petit organe du corps humain ?",
            },
            ORGANS,
            "comparison or opposite changed",
        ),
        (  # « le plus » is not « le moins ».
            {
                "en": "Which organ uses the most energy?",
                "fr": "Quel organe utilise le plus d'énergie ?",
            },
            {
                "en": "{friend} yawns. Which organ uses the least energy?",
                "fr": "{friend} bâille. Quel organe utilise le moins d'énergie ?",
            },
            ORGANS,
            "comparison or opposite changed",
        ),
        (  # A guard word in the lead-in is a rejection.
            {
                "en": "Which of these is not alive?",
                "fr": "Lequel de ces éléments n'est pas vivant ?",
            },
            {
                "en": "Grandma does not know. Which of these is alive?",
                "fr": "Mamie ne sait pas. Lequel de ces éléments est vivant ?",
            },
            ALIVE,
            "lead-in has a word",
        ),
        (  # non-living → living.
            {
                "en": "Which of these is non-living?",
                "fr": "Lequel de ces éléments est non vivant ?",
            },
            {
                "en": "{friend} looks at the table. Which of these is living?",
                "fr": "{friend} regarde la table. Lequel de ces éléments est vivant ?",
            },
            ALIVE,
            "restriction",
        ),
        (  # « ne … que » dropped.
            {
                "en": "Which animal eats only plants?",
                "fr": "Quel animal ne mange que des plantes ?",
            },
            {
                "en": "{friend} points at the yard. Which animal eats plants?",
                "fr": "{friend} montre la cour. Quel animal mange des plantes ?",
            },
            ALIVE,
            "restriction",
        ),
        (  # "other than" dropped.
            {
                "en": "Which is a sign of life other than growth?",
                "fr": "Quel est un signe de vie autre que la croissance ?",
            },
            {
                "en": "{friend} thinks. Which is a sign of life, like growth?",
                "fr": "{friend} réfléchit. Quel est un signe de vie, comme la croissance ?",
            },
            {
                "en": ["Breathing", "Growth", "Colour", "Weight"],
                "fr": ["La respiration", "La croissance", "La couleur", "Le poids"],
            },
            "restriction",
        ),
        (  # « à l'exception de » dropped.
            {
                "en": "All of these are alive except which one?",
                "fr": "Tous ces éléments sont vivants, à l'exception duquel ?",
            },
            {
                "en": "Grandma lines them up. All of these are alive except which one?",
                "fr": "Mamie les aligne. Tous ces éléments sont vivants : lequel est vivant ?",
            },
            ALIVE,
            "restriction",
        ),
        (  # A number spelled out gives the answer away.
            {
                "en": "How many chambers does the human heart have?",
                "fr": "Combien de cavités le cœur humain a-t-il ?",
            },
            {
                "en": "{friend} counts four on her fingers. How many chambers does the human heart have?",
                "fr": "{friend} compte quatre sur ses doigts. Combien de cavités le cœur humain a-t-il ?",
            },
            {"en": ["2", "3", "4", "5"], "fr": ["2", "3", "4", "5"]},
            "numbers changed",
        ),
        (  # A multiplier is a number: double is not triple.
            {
                "en": "What happens to the area if you double the side?",
                "fr": "Que devient l'aire si on double le côté ?",
            },
            {
                "en": "{friend} draws a square. What happens to the area if you triple the side?",
                "fr": "{friend} dessine un carré. Que devient l'aire si on triple le côté ?",
            },
            {
                "en": ["It doubles", "It triples", "It is 4 times larger", "It stays"],
                "fr": ["Elle double", "Elle triple", "Elle est 4 fois plus grande", "Elle reste"],
            },
            "numbers changed",
        ),
        (  # A unit word with no number: micrometres are not millimetres.
            {
                "en": "How wide is a cell, in micrometres?",
                "fr": "Quelle est la largeur d'une cellule, en micromètres ?",
            },
            {
                "en": "{friend} squints. How wide is a cell, in millimetres?",
                "fr": "{friend} plisse les yeux. Quelle est la largeur d'une cellule, en millimètres ?",
            },
            {
                "en": ["About 10", "About 100", "About 1000", "About 1"],
                "fr": ["Environ 10", "Environ 100", "Environ 1000", "Environ 1"],
            },
            "units changed",
        ),
        (  # Ruling distractors out names options the original does not.
            {"en": "Which organ pumps blood?", "fr": "Quel organe pompe le sang ?"},
            {
                "en": "{friend} sighs: not the liver, not the skin. Which organ pumps blood?",
                "fr": "{friend} soupire : ni le foie, ni la peau. Quel organe pompe le sang ?",
            },
            {
                "en": ["The heart", "The liver", "The skin", "The lungs"],
                "fr": ["Le cœur", "Le foie", "La peau", "Les poumons"],
            },
            "names an option",
        ),
        (  # A new name, even one that starts the sentence.
            {"en": "Which organ pumps blood?", "fr": "Quel organe pompe le sang ?"},
            {
                "en": "Moussa taps his chest. Which organ pumps blood?",
                "fr": "Moussa tape sa poitrine. Quel organe pompe le sang ?",
            },
            {
                "en": ["The heart", "The liver", "The skin", "The lungs"],
                "fr": ["Le cœur", "Le foie", "La peau", "Les poumons"],
            },
            "a name or place",
        ),
    ],
)
def test_a_rewrite_that_changes_the_question_is_refused_in_code(
    original, rewrite, options, problem
):
    found = _check(original, rewrite, options)
    assert any(problem in p for p in found), found


def test_the_faithful_controls_pass():
    heart = {
        "en": ["The heart", "The liver", "The skin", "The lungs"],
        "fr": ["Le cœur", "Le foie", "La peau", "Les poumons"],
    }
    assert (
        _check(
            {"en": "Which organ pumps blood?", "fr": "Quel organe pompe le sang ?"},
            {
                "en": "{friend} taps her chest. Which organ pumps blood?",
                "fr": "{friend} tape sa poitrine. Quel organe pompe le sang ?",
            },
            heart,
        )
        == []
    )
    assert (
        _check(
            {"en": "Why is a pebble not alive?", "fr": "Pourquoi un caillou n’est-il pas vivant ?"},
            {
                "en": "Grandma lifts the stone. Why is a pebble not alive?",
                "fr": "Mamie lève la pierre. Pourquoi un caillou n’est-il pas vivant ?",
            },
            ALIVE,
        )
        == []
    )
    # The same superlative, the same restriction: kept.
    assert (
        _check(
            {
                "en": "Which is the largest organ of the human body?",
                "fr": "Quel est le plus grand organe du corps humain ?",
            },
            {
                "en": "Grandma rubs her arm. Which is the largest organ of the human body?",
                "fr": "Mamie frotte son bras. Quel est le plus grand organe du corps humain ?",
            },
            ORGANS,
        )
        == []
    )


def test_a_blocked_name_is_caught_in_any_case_and_without_accents():
    for name in ("Bouaké", "bouake", "BOUAKE"):
        found = _check(
            {"en": "Which organ pumps blood?", "fr": "Quel organe pompe le sang ?"},
            {
                "en": f"Grandma is back from {name}. Which organ pumps blood?",
                "fr": "Mamie tape sa poitrine. Quel organe pompe le sang ?",
            },
            {"en": ["The heart", "The liver"], "fr": ["Le cœur", "Le foie"]},
            blocklist=["Bouaké"],
        )
        assert any("lesson's own examples" in p for p in found), (name, found)


def test_the_judge_judges_both_languages_with_their_options():
    message = build_judge_message([candidate("q3")], "fr")
    assert "Judge BOTH languages" in message and "False if either language differs" in message
    assert "OPTIONS (fr):" in message and "OPTIONS (en):" in message
    assert "a) It never feeds, grows or reproduces  <- correct" in message


class _RaisingJudge:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    async def generate_structured_content(self, *args, **kwargs):
        raise self.exc


@pytest.mark.parametrize("exc", [ValueError("ANTHROPIC_API_KEY is required"), RuntimeError("529")])
def test_an_error_raised_is_never_a_stored_no(exc):
    """Only an answer that came back unreadable is a stored "no" (#2701 review)."""
    assert asyncio.run(approve_stems(chapter_ctx(), stemmed_pack(), _RaisingJudge(exc))) is None


def test_an_unreadable_answer_is_a_stored_no():
    class Unreadable:
        async def generate_structured_content(self, *args, **kwargs):
            return {"raw_response": "not JSON"}

    verdict = asyncio.run(approve_stems(chapter_ctx(), stemmed_pack(), Unreadable()))
    assert verdict["approved"] == {} and verdict["calls"] == 1


def test_approved_stems_are_checked_again_for_free():
    from app.domain.services.story_stems import recheck_stems

    ctx, the_pack = chapter_ctx(), stemmed_pack()
    approved = {ref: dict(stem) for ref, stem in STORY_STEMS.items()}
    assert recheck_stems(ctx, the_pack, approved) == approved
    # A stem approved before a check existed, that fails it now: dropped, no call.
    bad = next(d for d in the_pack["derived"] if d["ref"] == "q3")
    bad["story_stem"] = {
        "en": "Grandma does not know. Why is a pebble not alive?",
        "fr": "Mamie ne sait pas. Pourquoi un caillou n'est-il pas vivant ?",
    }
    approved["q3"] = dict(bad["story_stem"])
    assert set(recheck_stems(ctx, the_pack, approved)) == {"q1", "q2"}
    # A stem that is no longer the pack's: dropped too.
    approved["q1"] = {"en": "Something else?", "fr": "Autre chose ?"}
    assert set(recheck_stems(ctx, the_pack, approved)) == {"q2"}


def test_fidelity_follows_the_approved_stems_never_a_document_key():
    """Only ctx.story_stems decides; the approved stem is re-asserted (#2701 review)."""
    ctx = chapter_ctx()
    ctx.story_stems = {"q3": STORY_STEMS["q3"]}
    result = build(ctx, spine())
    doc = copy.deepcopy(result.doc)
    question = next(q for q in doc["questions"] if q["id"] == "q3")
    question["prompt"] = {"en": "Edited after the build?", "fr": "Modifiée ?"}
    repair.enforce_quiz_fidelity(doc, ctx)
    assert question["prompt"] == STORY_STEMS["q3"]
    assert question["original_stem"]["en"] == quiz("q3")["question"]["en"]
    # Without an approved stem, a stray original_stem key changes nothing.
    plain_ctx = chapter_ctx()
    repair.enforce_quiz_fidelity(doc, plain_ctx)
    assert question["prompt"]["en"] == quiz("q3")["question"]["en"]
    assert "original_stem" not in question


# --------------------------------------------------------------------------
# The re-review of #2701: leaks, opposites, and no over-rejection
# --------------------------------------------------------------------------

HEART = {
    "en": ["The heart", "The liver", "The skin", "The lungs"],
    "fr": ["Le cœur", "Le foie", "La peau", "Les poumons"],
}
PUMPS = {"en": "Which organ pumps blood?", "fr": "Quel organe pompe le sang ?"}
ALIVE_Q = {"en": "Which of these is alive?", "fr": "Lequel de ces éléments est vivant ?"}


@pytest.mark.parametrize(
    ("original", "rewrite", "options", "correct"),
    [
        (  # The answer's noun with a possessive.
            PUMPS,
            {
                "en": "{friend} feels her heart thumping. Which organ pumps blood?",
                "fr": "{friend} sent son cœur battre. Quel organe pompe le sang ?",
            },
            HEART,
            0,
        ),
        (  # The answer's noun in the plural.
            ALIVE_Q,
            {
                "en": "{friend} sees snails on the bench. Which of these is alive?",
                "fr": "{friend} voit des escargots sur le banc. Lequel de ces éléments est vivant ?",
            },
            ALIVE,
            1,
        ),
        (
            ALIVE_Q,
            {
                "en": "Snails crawl on the bench. Which of these is alive?",
                "fr": "Des escargots rampent sur le banc. Lequel de ces éléments est vivant ?",
            },
            ALIVE,
            1,
        ),
    ],
)
def test_a_rewrite_that_says_the_answers_noun_is_refused(original, rewrite, options, correct):
    assert any("names an option" in p for p in _check(original, rewrite, options, correct))


EGGS = {"en": ["1", "2", "5", "10"], "fr": ["1", "2", "5", "10"]}
SIZES = {
    "en": ["The cell", "The atom", "The molecule", "The organ"],
    "fr": ["La cellule", "L'atome", "La molécule", "L'organe"],
}
TEMP = {
    "en": ["It speeds up", "It slows down", "It stops", "It stays the same"],
    "fr": ["Elle accélère", "Elle ralentit", "Elle s'arrête", "Elle reste pareille"],
}


@pytest.mark.parametrize(
    ("original", "rewrite", "options"),
    [
        (
            {"en": "Which animal has the most legs?", "fr": "Quel animal a le plus de pattes ?"},
            {
                "en": "{friend} counts. Which animal has the fewest legs?",
                "fr": "{friend} compte. Quel animal a le plus de pattes ?",
            },
            ALIVE,
        ),
        (
            {
                "en": "How many eggs does a hen lay per day at most?",
                "fr": "Combien d'œufs une poule pond-elle au maximum par jour ?",
            },
            {
                "en": "Mamie lifts the basket. How many eggs does a hen lay per day at most?",
                "fr": "Mamie soulève le panier. Combien d'œufs une poule pond-elle au minimum par jour ?",
            },
            EGGS,
        ),
        (
            {
                "en": "What is the maximum number of eggs a hen lays per day?",
                "fr": "Quel est le nombre maximum d'œufs pondus par jour ?",
            },
            {
                "en": "Mamie lifts the basket. What is the minimum number of eggs a hen lays per day?",
                "fr": "Mamie soulève le panier. Quel est le nombre maximum d'œufs pondus par jour ?",
            },
            EGGS,
        ),
        (
            {
                "en": "Which is bigger than a molecule?",
                "fr": "Lequel est plus grand qu'une molécule ?",
            },
            {
                "en": "{friend} squints. Which is smaller than a molecule?",
                "fr": "{friend} plisse les yeux. Lequel est plus grand qu'une molécule ?",
            },
            SIZES,
        ),
        (
            {
                "en": "Which is larger than a molecule?",
                "fr": "Lequel a une taille supérieure à une molécule ?",
            },
            {
                "en": "{friend} squints. Which is larger than a molecule?",
                "fr": "{friend} plisse les yeux. Lequel a une taille inférieure à une molécule ?",
            },
            SIZES,
        ),
        (
            {
                "en": "What happens to a lizard's heartbeat when the temperature increases?",
                "fr": "Que devient le cœur du lézard quand la température augmente ?",
            },
            {
                "en": "The sun goes down. What happens to a lizard's heartbeat when the temperature decreases?",
                "fr": "Le soleil se couche. Que devient le cœur du lézard quand la température diminue ?",
            },
            TEMP,
        ),
        (
            {"en": "What must you do before eating?", "fr": "Que dois-tu faire avant de manger ?"},
            {
                "en": "Mamie sets the table. What must you do after eating?",
                "fr": "Mamie met la table. Que dois-tu faire après avoir mangé ?",
            },
            {
                "en": ["Wash your hands", "Sleep", "Run", "Sing"],
                "fr": ["Te laver les mains", "Dormir", "Courir", "Chanter"],
            },
        ),
    ],
)
def test_a_rewrite_that_flips_an_opposite_is_refused(original, rewrite, options):
    found = _check(original, rewrite, options)
    assert any("opposite changed" in p for p in found), found


def _faithful(o_en, o_fr, r_en, r_fr, opts_en, opts_fr, correct=0):
    return StemCandidate(
        ref="q",
        original={"en": o_en, "fr": o_fr},
        rewrite={"en": r_en, "fr": r_fr},
        options={"en": opts_en, "fr": opts_fr},
        correct_index=correct,
    )


#: Faithful rewrites (the reviewer's over-rejection set): all but one pass.
FAITHFUL = [
    _faithful(
        "Which of these is a characteristic of all living things?",
        "Laquelle de ces caractéristiques est commune à tous les êtres vivants ?",
        "{friend} lines up the jars. Which of these is a characteristic of all living things?",
        "{friend} aligne les bocaux. Laquelle de ces caractéristiques est commune à tous les êtres vivants ?",
        ["They grow", "They are green", "They move fast", "They are big"],
        ["Ils grandissent", "Ils sont verts", "Ils bougent vite", "Ils sont grands"],
    ),
    _faithful(
        "What do plants need to make their own food?",
        "De quoi les plantes ont-elles besoin pour fabriquer leur nourriture ?",
        "Mariam waters the beans by the window. What do plants need to make their own food?",
        "Mariam arrose les haricots près de la fenêtre. De quoi les plantes ont-elles besoin pour fabriquer leur nourriture ?",
        ["Sunlight, water and air", "Only soil", "Sugar", "Darkness"],
        ["Lumière, eau et air", "Seulement de la terre", "Du sucre", "L'obscurité"],
    ),
    _faithful(
        "Which part of the cell controls its activities?",
        "Quelle partie de la cellule contrôle ses activités ?",
        "Kaboré points at the drawing on the board. Which part of the cell controls its activities?",
        "Kaboré montre le dessin au tableau. Quelle partie de la cellule contrôle ses activités ?",
        ["The nucleus", "The membrane", "The cytoplasm", "The wall"],
        ["Le noyau", "La membrane", "Le cytoplasme", "La paroi"],
    ),
    _faithful(
        "How many legs does an insect have?",
        "Combien de pattes a un insecte ?",
        "{friend} watches an ant on the bench. How many legs does an insect have?",
        "{friend} observe une fourmi sur le banc. Combien de pattes a un insecte ?",
        ["4", "6", "8", "10"],
        ["4", "6", "8", "10"],
        1,
    ),
    _faithful(
        "What is the main mode of transmission of cholera?",
        "Quel est le principal mode de transmission du choléra ?",
        "Kaboré looks at the village well. What is the main mode of transmission of cholera?",
        "Kaboré regarde le puits du village. Quel est le principal mode de transmission du choléra ?",
        ["Contaminated water", "Mosquito bites", "The air", "Shaking hands"],
        ["L'eau contaminée", "Les piqûres de moustique", "L'air", "Se serrer la main"],
    ),
    _faithful(
        "Which vaccine is given at birth?",
        "Quel vaccin est donné à la naissance ?",
        "Mariam holds the newborn baby. Which vaccine is given at birth?",
        "Mariam tient le nouveau-né. Quel vaccin est donné à la naissance ?",
        ["BCG", "Measles", "Yellow fever", "Tetanus"],
        ["BCG", "Rougeole", "Fièvre jaune", "Tétanos"],
    ),
    _faithful(
        "What is the first thing to do when a child has diarrhoea?",
        "Quelle est la première chose à faire quand un enfant a la diarrhée ?",
        "Awa's little brother was sick all night. What is the first thing to do when a child has diarrhoea?",
        "Le petit frère d'Awa a été malade toute la nuit. Quelle est la première chose à faire quand un enfant a la diarrhée ?",
        ["Give oral rehydration salts", "Stop all drinks", "Give sweets", "Wait"],
        ["Donner des sels de réhydratation", "Arrêter de boire", "Donner des bonbons", "Attendre"],
    ),
    _faithful(
        "Which of these is NOT a sign of dehydration?",
        "Lequel de ces signes n'est PAS un signe de déshydratation ?",
        "{friend} looks at the baby's lips. Which of these is NOT a sign of dehydration?",
        "{friend} regarde les lèvres du bébé. Lequel de ces signes n'est PAS un signe de déshydratation ?",
        ["Rosy cheeks", "Dry mouth", "Sunken eyes", "Few tears"],
        ["Des joues roses", "La bouche sèche", "Les yeux enfoncés", "Peu de larmes"],
    ),
    _faithful(
        "Which organ lets us breathe?",
        "Quel organe permet de respirer ?",
        "Awa breathes hard after the race. Which organ lets us breathe?",
        "Awa souffle très fort après la course. Quel organe permet de respirer ?",
        ["The lungs", "The heart", "The stomach", "The liver"],
        ["Les poumons", "Le cœur", "L'estomac", "Le foie"],
    ),
    _faithful(
        "Which of these animals is a vertebrate?",
        "Lequel de ces animaux est un vertébré ?",
        "{friend} points at the school yard. Which of these animals is a vertebrate?",
        "{friend} montre la cour de l'école. Lequel de ces animaux est un vertébré ?",
        ["The lizard", "The snail", "The ant", "The worm"],
        ["Le lézard", "L'escargot", "La fourmi", "Le ver"],
    ),
    _faithful(
        "Which food group gives us the most energy?",
        "Quel groupe d'aliments nous donne le plus d'énergie ?",
        "Mariam cooks rice and beans. Which food group gives us the most energy?",
        "Mariam cuisine du riz et des haricots. Quel groupe d'aliments nous donne le plus d'énergie ?",
        ["Carbohydrates", "Vitamins", "Minerals", "Water"],
        ["Les glucides", "Les vitamines", "Les minéraux", "L'eau"],
    ),
    _faithful(
        "How long should you wash your hands?",
        "Combien de temps faut-il se laver les mains ?",
        "Kaboré turns on the tap. How long should you wash your hands?",
        "Kaboré ouvre le robinet. Combien de temps faut-il se laver les mains ?",
        ["20 seconds", "2 seconds", "5 minutes", "1 hour"],
        ["20 secondes", "2 secondes", "5 minutes", "1 heure"],
    ),
    _faithful(
        "Which of these diseases is spread by mosquitoes?",
        "Laquelle de ces maladies est transmise par les moustiques ?",
        "Night falls and the mosquitoes come out. Which of these diseases is spread by mosquitoes?",
        "La nuit tombe et les moustiques sortent. Laquelle de ces maladies est transmise par les moustiques ?",
        ["Malaria", "Cholera", "Measles", "Tuberculosis"],
        ["Le paludisme", "Le choléra", "La rougeole", "La tuberculose"],
    ),
    _faithful(
        "What does a seed need to germinate?",
        "De quoi une graine a-t-elle besoin pour germer ?",
        "After school, {friend} plants a bean. What does a seed need to germinate?",
        "Dans la cour, {friend} plante un haricot. De quoi une graine a-t-elle besoin pour germer ?",
        ["Water and warmth", "Darkness only", "Salt", "Nothing"],
        ["De l'eau et de la chaleur", "Seulement l'obscurité", "Du sel", "Rien"],
    ),
    _faithful(
        "Why do we sweat?",
        "Pourquoi transpirons-nous ?",
        "Suddenly, {friend} wipes her forehead. Why do we sweat?",
        "Soudain, {friend} s'essuie le front. Pourquoi transpirons-nous ?",
        ["To cool the body", "To grow", "To sleep", "To eat"],
        ["Pour refroidir le corps", "Pour grandir", "Pour dormir", "Pour manger"],
    ),
    _faithful(
        "Which part of the plant takes in water?",
        "Quelle partie de la plante absorbe l'eau ?",
        "Under the mango tree, Kaboré digs a little. Which part of the plant takes in water?",
        "Sous le manguier, Kaboré creuse un peu. Quelle partie de la plante absorbe l'eau ?",
        ["The roots", "The leaves", "The flowers", "The fruit"],
        ["Les racines", "Les feuilles", "Les fleurs", "Le fruit"],
    ),
    _faithful(
        "Which of these is a renewable resource?",
        "Laquelle de ces ressources est renouvelable ?",
        "Mariam looks at the sun on the roof. Which of these is a renewable resource?",
        "Mariam regarde le soleil sur le toit. Laquelle de ces ressources est renouvelable ?",
        ["Solar energy", "Oil", "Coal", "Gas"],
        ["L'énergie solaire", "Le pétrole", "Le charbon", "Le gaz"],
    ),
    _faithful(
        "Why do we boil drinking water?",
        "Pourquoi fait-on bouillir l'eau de boisson ?",
        "Mariam puts the pot on the fire. Why do we boil drinking water?",
        "Mariam met la marmite sur le feu. Pourquoi fait-on bouillir l'eau de boisson ?",
        ["To kill germs", "To make it sweet", "To cool it", "To colour it"],
        ["Pour tuer les microbes", "Pour la sucrer", "Pour la refroidir", "Pour la colorer"],
    ),
    _faithful(
        "Which organ filters the blood?",
        "Quel organe filtre le sang ?",
        "Kaboré draws one more organ on the board. Which organ filters the blood?",
        "Kaboré dessine un organe de plus au tableau. Quel organe filtre le sang ?",
        ["The kidneys", "The heart", "The lungs", "The brain"],
        ["Les reins", "Le cœur", "Les poumons", "Le cerveau"],
    ),
]
CAST = ["Kaboré", "Awa", "Mariam", "Margo", "Burkina Faso", "Ouagadougou"]


@pytest.mark.parametrize("candidate", FAITHFUL, ids=[c.rewrite["en"][:30] for c in FAITHFUL])
def test_a_faithful_rewrite_is_not_refused(candidate):
    assert stem_problems(candidate, allowed=CAST) == []


def test_a_lead_in_negation_the_original_does_not_have_is_still_refused():
    lead = _faithful(
        "What is the role of red blood cells?",
        "Quel est le rôle des globules rouges ?",
        "{friend} is not sure. What is the role of red blood cells?",
        "{friend} n'est pas sûre. Quel est le rôle des globules rouges ?",
        ["To carry oxygen", "To fight germs", "To clot blood", "To digest food"],
        ["Transporter l'oxygène", "Combattre les microbes", "Coaguler le sang", "Digérer"],
    )
    assert any("lead-in" in p for p in stem_problems(lead, allowed=CAST))


@pytest.mark.parametrize(
    ("rewrite_en", "rewrite_fr"),
    [
        (  # The scenario kept in the lead-in: its negation is the original's.
            "Mariam's son is 3 years old. He has had diarrhoea for 3 days and is not drinking well. What should be done first?",
            "Le fils de Mariam a 3 ans. Il a la diarrhée depuis 3 jours et ne boit pas bien. Que faut-il faire en premier ?",
        ),
        (  # The scenario folded into one question.
            "What should be done first for Mariam's son, 3 years old, who has had diarrhoea for 3 days and is not drinking well?",
            "Que faut-il faire en premier pour le fils de Mariam, 3 ans, qui a la diarrhée depuis 3 jours et ne boit pas bien ?",
        ),
    ],
)
def test_a_faithful_scenario_stem_passes(rewrite_en, rewrite_fr):
    scenario = _faithful(
        "A 3-year-old child has had diarrhoea for 3 days and is not drinking well. What should be done first?",
        "Un enfant de 3 ans a la diarrhée depuis 3 jours et ne boit pas bien. Que faut-il faire en premier ?",
        rewrite_en,
        rewrite_fr,
        ["Give oral rehydration salts", "Give antibiotics", "Stop breastfeeding", "Wait and see"],
        [
            "Donner des sels de réhydratation orale",
            "Donner des antibiotiques",
            "Arrêter l'allaitement",
            "Attendre",
        ],
    )
    assert stem_problems(scenario, allowed=CAST) == []


def test_short_options_are_matched_by_word_never_inside_another():
    from app.domain.services.story_stems import _names_option

    assert not _names_option("Rien", "{friend} plante un haricot.")
    assert not _names_option("Eau", "Mamie remplit le seau.")
    assert not _names_option("Air", "{friend} sits on the chair.")
    assert not _names_option("It is grey", "Grandma holds up the grey stone.")
    assert _names_option("The liver", "Forget the liver and the skin.")
    assert _names_option("Le foie", "Ni le foie ni la peau.", "Quel organe pompe le sang ?")


def test_a_name_starting_a_sentence_is_a_name_only_if_the_other_language_keeps_it():
    moussa = _faithful(
        PUMPS["en"],
        PUMPS["fr"],
        "Moussa taps his chest. Which organ pumps blood?",
        "Moussa tape sa poitrine. Quel organe pompe le sang ?",
        HEART["en"],
        HEART["fr"],
    )
    assert any("name or place" in p for p in stem_problems(moussa, allowed=CAST))
    night = _faithful(
        PUMPS["en"],
        PUMPS["fr"],
        "Night falls on the village. Which organ pumps blood?",
        "La nuit tombe sur le village. Quel organe pompe le sang ?",
        HEART["en"],
        HEART["fr"],
    )
    assert stem_problems(night, allowed=CAST) == []


# --------------------------------------------------------------------------
# The final review of #2701: plural forms, unit words, word-level negations
# --------------------------------------------------------------------------

ANIMALS = {
    "en": ["The goat", "The lion", "The mango tree", "The pebble"],
    "fr": ["La chèvre", "Le lion", "Le manguier", "Le caillou"],
}
MILK = {
    "en": "Which of these feeds its young with milk?",
    "fr": "Lequel de ces êtres nourrit ses petits avec du lait ?",
}
LAYERS = {
    "en": ["The bat", "The hen", "The crocodile", "The tortoise"],
    "fr": ["La chauve-souris", "La poule", "Le crocodile", "La tortue"],
}
NUCLEUS = {
    "en": ["The red blood cell", "The skin cell", "The nerve cell", "The muscle cell"],
    "fr": [
        "Le globule rouge",
        "La cellule de la peau",
        "La cellule nerveuse",
        "La cellule musculaire",
    ],
}


def test_a_french_plural_of_a_noun_in_e_is_the_same_term():
    from app.domain.services.story_stems import _forms, _same_term

    for plural, singular in (
        ("chevres", "chevre"),
        ("cellules", "cellule"),
        ("proprietes", "propriete"),
        ("boxes", "box"),
        ("snails", "snail"),
    ):
        assert _same_term(plural, [singular]) and _same_term(singular, [plural]), plural
    assert not _same_term("seau", ["eau"])
    assert _forms("cellules") == {"cellules", "cellule", "cellul"}


def test_the_answers_noun_in_the_french_plural_is_a_leak():
    leak = _faithful(
        MILK["en"],
        MILK["fr"],
        "Mariam milks the goats. Which of these feeds its young with milk?",
        "Mariam trait les chèvres. Lequel de ces êtres nourrit ses petits avec du lait ?",
        ANIMALS["en"],
        ANIMALS["fr"],
    )
    found = stem_problems(leak, allowed=CAST)
    assert "en: the rewrite names an option" in found
    assert "fr: the rewrite names an option" in found


def test_a_key_term_kept_in_the_singular_is_kept():
    kept = _faithful(
        "Which of these cells have a nucleus?",
        "Lesquelles de ces cellules ont un noyau ?",
        "Kaboré adjusts the microscope. Which of these cells have a nucleus?",
        "Kaboré règle le microscope. Laquelle de ces cellule a un noyau ?",
        ["Skin cells", "Red blood cells", "Both", "None"],
        ["Les cellules de la peau", "Les globules rouges", "Les deux", "Aucune"],
    )
    assert stem_problems(kept, allowed=CAST) == []


@pytest.mark.parametrize(
    ("rewrite_en", "rewrite_fr"),
    [
        (
            "One day, Kaboré taps his chest. Which organ pumps blood?",
            "Un jour, Kaboré tape sur sa poitrine. Quel organe pompe le sang ?",
        ),
        (
            "It beats day and night in your chest. Which organ pumps blood?",
            "Il bat jour et nuit dans ta poitrine. Quel organe pompe le sang ?",
        ),
    ],
)
def test_a_time_word_of_the_story_is_no_unit(rewrite_en, rewrite_fr):
    story = _faithful(PUMPS["en"], PUMPS["fr"], rewrite_en, rewrite_fr, HEART["en"], HEART["fr"])
    assert not any("units" in p for p in stem_problems(story, allowed=CAST))


def test_a_unit_word_next_to_a_number_or_after_in_is_a_unit():
    from app.domain.services.story_stems import _units

    assert _units("He has had diarrhoea for 3 days.", "en") == {"day"}
    assert _units("Un enfant de 3 ans, depuis trois jours.", "fr") == {"an", "jour"}
    assert _units("How wide is a cell, in micrometres?", "en") == {"micrometre"}
    assert _units("Combien d'œufs par jour ?", "fr") == {"jour"}
    assert _units("Un jour, il bat jour et nuit.", "fr") == set()


@pytest.mark.parametrize(
    ("original", "rewrite", "options", "correct"),
    [
        (  # "lacks" / « dépourvue de »: a negation carried by a word.
            {
                "en": "Which of these cells has a nucleus?",
                "fr": "Laquelle de ces cellules possède un noyau ?",
            },
            {
                "en": "Kaboré adjusts the microscope. Which of these cells lacks a nucleus?",
                "fr": "Kaboré règle le microscope. Laquelle de ces cellules est dépourvue de noyau ?",
            },
            NUCLEUS,
            1,
        ),
        (  # often → rarely, souvent → rarement.
            {
                "en": "Which of these animals often lives in water?",
                "fr": "Lequel de ces animaux vit souvent dans l'eau ?",
            },
            {
                "en": "Awa looks at the river. Which of these animals rarely lives in water?",
                "fr": "Awa regarde la rivière. Lequel de ces animaux vit rarement dans l'eau ?",
            },
            LAYERS,
            2,
        ),
        (  # "hardly" / « ne … guère ».
            {
                "en": "Which of these animals moves fast?",
                "fr": "Lequel de ces animaux se déplace vite ?",
            },
            {
                "en": "Awa waits by the path. Which of these animals hardly moves fast?",
                "fr": "Awa attend près du chemin. Lequel de ces animaux ne se déplace guère vite ?",
            },
            LAYERS,
            3,
        ),
    ],
)
def test_a_word_level_negation_or_opposite_is_refused(original, rewrite, options, correct):
    found = _check(original, rewrite, options, correct)
    assert any(p.startswith("en: a negation") for p in found), found
    assert any(p.startswith("fr: a negation") for p in found), found
