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
            "comparison changed",
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
            "comparison changed",
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
