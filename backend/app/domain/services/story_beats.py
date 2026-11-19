"""The slot builder's screenplay, written by code (#2713, phase 5 of #2672).

The model used to write the whole screenplay of a chapter: about 91 % of the
story JSON, every id, every prop, every step order, 140 of 154 KB. Almost none
of that needs a model. This module builds a chapter's scenes from what the code
already knows, and leaves a **slot** wherever only a person can write the words:

* the plan: each beat's place, cast, problem, discovery and card title (both
  languages), the chapter's opening, turn and ending, the voices and the gag;
* the fact sheet: the lesson's IDEAS, from which a card's rows are taken;
* the practice pack and the course questions: which question is asked in
  which beat (``beat["questions"]``, then the pack's ``idea``), the paper task
  and the game;
* the asset catalogue (#2709): a beat is given a picture only when the
  picture's caption or alt text shares words with the beat (the evidence is
  never invented); the builder's own prop book binds the props.

A beat of a chapter plays, in this order (every ``S`` is a slot, the rest is
code)::

    narrate S(set)            the establishing line, at the beat's place
    show figure N             the stimulus, BEFORE anyone says "look" (if any)
    say S(hook)               a friend's hook: a question, never an explanation
    say S(hero)               the learner's first guess (the flaw of the plan)
    predict S(prompt)         the bet, when the beat has a demo spec (see below)
    say <discovery>           the plan's discovery, both languages, from code
    concept <card_title>      title from the plan, rows S(row1), S(row2)
    ask <ref> ...             the beat's questions (the builder adds the
                              lead-in line, the card's picture, the stimulus)
    say S(after)              a reaction that moves the story on

and the chapter closes with ``narrate S(task)`` + ``photo`` (the paper task),
``narrate S(game)`` + ``game`` (the game), ``say S(end_react)`` and
``narrate S(close)`` (the plan's ENDS ON): the last steps are story, never a task.

A **bet** is built only when the plan's beat carries a ``demo`` spec: the data
of what the learner will observe (``compare`` values, ``annotate`` expected
region, ``sort`` / ``timeline`` items). Code never invents data: without one,
the beat is told without a bet, and says so in the script's ``evidence``
report (``bet: false``). The demo, its verdict, the chips of ``compare`` and
``annotate`` come from that data; the model only words the question and the
two reactions (and the labels of a ``compare`` that has none).

The script is **the same JSON the model used to write** (the chapter's
"spine": ``scenes``, ``props_now``, ``recap``...), so it goes through the same
builder, the same checks and the same assembly as a classic chapter. Nothing
here is a second pipeline; the slots are filled by :mod:`story_slots`.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.domain.services import story_assets
from app.domain.services import story_poe as poe
from app.domain.services.story_checks import KIDS_CARD_WORDS, KIDS_LINE_WORDS
from app.domain.services.story_props import names_prop
from app.domain.services.story_repair import repeat_keys

# -- roles ------------------------------------------------------------------

NARRATION = "narration"
HOOK = "hook"
HERO_LINE = "hero-line"
REACTION = "reaction"
CARD_ROW = "card-row"
BET_PROMPT = "bet-prompt"
REACT_RIGHT = "reaction-right"
REACT_WRONG = "reaction-wrong"
LABEL = "label"
LEAD = "lead"
CLOSE = "close"
ROLES = (
    NARRATION,
    HOOK,
    HERO_LINE,
    REACTION,
    CARD_ROW,
    BET_PROMPT,
    REACT_RIGHT,
    REACT_WRONG,
    LABEL,
    LEAD,
    CLOSE,
)

#: The longest a line may be, in words, for a story told to 7-14 year-olds
#: (:data:`story_checks.KIDS_LINE_WORDS`) and for any other audience.
LINE_WORDS = KIDS_LINE_WORDS
ADULT_LINE_WORDS = 16
ADULT_CARD_WORDS = 28
#: A bet's chip, a demo label, a reaction to a bet.
LABEL_WORDS = 4
REACTION_WORDS = 12
#: A card row is never shorter than this cap, however long its title.
MIN_ROW_WORDS = 5

HERO, FRIEND, MENTOR = "hero", "friend", "mentor"

#: Phrasings a chapter leans towards, one per variant; the variant is seeded from
#: the chapter and the plan, so two chapters of a module do not sound alike.
STYLES = (
    "lean on questions and half-finished thoughts",
    "lean on short exclamations and concrete sounds",
    "lean on comparisons with everyday things at home",
    "lean on dry humour and the running gag",
)

#: The lines the code says when a slot could not be filled: neutral, in both
#: languages, never wrong. One is chosen from ``seed`` and the slot number.
FALLBACKS: dict[str, tuple[tuple[str, str], ...]] = {
    NARRATION: (
        (
            "The place is quiet. Something is about to happen.",
            "Le lieu est calme. Quelque chose va arriver.",
        ),
        ("Everyone looks around, curious.", "Tout le monde regarde autour de soi, curieux."),
        (
            "The light changes a little. The friends gather round.",
            "La lumière change un peu. Les amis se rassemblent.",
        ),
        ("A small noise breaks the silence.", "Un petit bruit rompt le silence."),
        (
            "Time passes slowly, and the friends wait.",
            "Le temps passe doucement, et les amis attendent.",
        ),
        ("The friends move closer to see better.", "Les amis s'approchent pour mieux voir."),
    ),
    HOOK: (
        ("Wait. Look at that!", "Attends. Regarde ça !"),
        ("Hey! What is going on here?", "Dis donc ! Que se passe-t-il ici ?"),
        ("Did you see that too?", "Tu as vu ça, toi aussi ?"),
        ("That is strange. Why is it like that?", "C'est étrange. Pourquoi est-ce ainsi ?"),
        ("Come closer, quick!", "Approche, vite !"),
        ("I have a question about this!", "J'ai une question là-dessus !"),
    ),
    HERO_LINE: (
        ("Hmm, let me think about it.", "Hmm, laisse-moi y réfléchir."),
        ("I think I know. Maybe.", "Je crois que je sais. Peut-être."),
        ("It looks easy. Let me try.", "Ça a l'air facile. Je tente."),
        (
            "My first guess is quick, but is it right?",
            "Ma première idée est rapide, mais est-elle juste ?",
        ),
        ("I will look more closely.", "Je vais regarder de plus près."),
        ("Let us check before we decide.", "Vérifions avant de décider."),
    ),
    REACTION: (
        ("Good thinking. Let's go on.", "Bien réfléchi. Continuons."),
        ("Okay! What happens next?", "D'accord ! Et ensuite ?"),
        ("That was a good try. Onward!", "Bel essai. En avant !"),
        ("Interesting. We keep going.", "Intéressant. On continue."),
        ("Right, let's see what comes next.", "Bon, voyons la suite."),
        ("We are getting somewhere.", "On avance."),
    ),
    LEAD: (
        ("Time to put it on paper.", "C'est le moment de le mettre sur papier."),
        ("Now it is time to try it out.", "Maintenant, il faut essayer."),
        ("Everyone gets ready to do the task.", "Chacun se prépare à faire l'exercice."),
    ),
    CLOSE: (
        (
            "The day ends, and the story is not over.",
            "La journée se termine, mais l'histoire continue.",
        ),
        ("Tomorrow, there will be more to find out.", "Demain, il y aura encore à découvrir."),
        ("The friends head home, still curious.", "Les amis rentrent, toujours curieux."),
    ),
    BET_PROMPT: (
        ("What do you think will happen?", "À ton avis, que va-t-il se passer ?"),
        ("Which one do you bet on?", "Sur lequel paries-tu ?"),
        ("Make your guess before we look.", "Fais ton pari avant de regarder."),
    ),
    REACT_RIGHT: (
        ("Well bet!", "Bien parié !"),
        ("You saw it coming!", "Tu l'avais senti !"),
        ("Right on target!", "En plein dans le mille !"),
    ),
    REACT_WRONG: (
        ("Surprising, isn't it?", "Surprenant, non ?"),
        ("Not what you expected!", "Pas ce que tu attendais !"),
        ("Not this time. Look again!", "Pas cette fois. Regarde encore !"),
    ),
    LABEL: (("this one", "celui-ci"), ("that one", "celui-là")),
}


def discovery_pair(beat: dict[str, Any]) -> dict[str, str] | None:
    """The plan's discovery in both languages, when it is told in both (not a lesson copy)."""
    found = beat.get("discovery") or {}
    en, fr = str(found.get("en") or "").strip(), str(found.get("fr") or "").strip()
    return {"en": en, "fr": fr} if en and fr and en != fr else None


def words(text: Any) -> int:
    return len(str(text or "").split())


def seed_of(*parts: Any) -> int:
    """A stable integer from ``parts`` (never ``random``): the variant index of a chapter."""
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big")


# -- the slot ------------------------------------------------------------------


@dataclass
class Slot:
    """One text the code cannot write: where it goes, who says it, how long it may be."""

    id: str
    role: str
    #: A cast id for a line someone says, ``None`` for narration, a label, a card row.
    who: str | None
    cap: int
    #: One line: what the text must do, and the one fact it may use.
    brief: str
    fact: str = ""
    #: Writes the filled text into the screenplay (``None``: leave it out).
    apply: Callable[[dict[str, str] | None], None] = field(default=lambda value: None, repr=False)
    #: The code's own line when the model's cannot be used; ``None``: leave the text out.
    fallback: dict[str, str] | None = None

    def __post_init__(self) -> None:
        if self.role not in ROLES:
            raise ValueError(f"unknown slot role {self.role!r}")


@dataclass
class Script:
    """A chapter's screenplay as code built it: scenes and the slots still to fill."""

    scenes: list[dict[str, Any]]
    slots: list[Slot]
    #: What each beat stands on: its picture, its prop, whether it has a bet.
    evidence: list[dict[str, Any]]
    seed: int
    recap: str = ""
    props_now: list[dict[str, str]] = field(default_factory=list)

    def slot(self, slot_id: str) -> Slot:
        return next(s for s in self.slots if s.id == slot_id)

    def spine(self) -> dict[str, Any]:
        """The model-shaped answer the builder reads (the pack's keys are added by the caller)."""
        return {
            "props": [],
            "scenes": self.scenes,
            "facts": [],
            "recap": self.recap,
            "props_now": self.props_now,
        }


# -- reading the context ----------------------------------------------------------


def _cast_ids(ctx: Any) -> list[str]:
    bible = ctx.bible_content
    ids = [str(c.get("id")) for c in bible.get("cast") or [] if isinstance(c, dict) and c.get("id")]
    return ids or [HERO, FRIEND]


def _mentor_speaks(ctx: Any) -> bool:
    """Whether the mentor may have a line: only a story with a lead mentor (#2710)."""
    from app.domain.services.story_cast_policy import LEAD, policy_of

    return policy_of(ctx.plan or {}) == LEAD


def _speakers(ctx: Any, beat_cast: list[str], present: list[str]) -> tuple[str, str]:
    """``(a, b)``: the two voices other than the hero a beat leans on (``b`` may be ``a``)."""
    allowed = [c for c in beat_cast if c in present and c not in (HERO, "margo")]
    if not _mentor_speaks(ctx):
        allowed = [c for c in allowed if c != MENTOR]
    if not allowed:
        allowed = [FRIEND] if FRIEND in present else [HERO]
    return allowed[0], allowed[1] if len(allowed) > 1 else allowed[0]


def _place_title(ctx: Any, place: str) -> str:
    for p in ctx.bible_content.get("places") or []:
        if isinstance(p, dict) and p.get("id") == place:
            title = p.get("title") or {}
            return str(title.get("en") or place)
    return place


def _line_cap(ctx: Any) -> int:
    return LINE_WORDS if ctx.is_kids else ADULT_LINE_WORDS


def _card_cap(ctx: Any) -> int:
    return KIDS_CARD_WORDS if ctx.is_kids else ADULT_CARD_WORDS


def _voice(plan: dict[str, Any], who: str) -> str:
    voices = plan.get("voices") if isinstance(plan.get("voices"), dict) else {}
    return str(voices.get(who) or "").strip()


def _beat_text(beat: dict[str, Any]) -> str:
    return " ".join(
        [
            str(beat.get("problem") or ""),
            *(
                str((beat.get(k) or {}).get(lang) or "")
                for k in ("discovery", "card_title")
                for lang in ("en", "fr")
            ),
        ]
    )


def _figure_words(ref: dict[str, Any]) -> frozenset[str]:
    return story_assets.words(
        ref.get("caption_en"),
        ref.get("caption_fr"),
        ref.get("caption"),
        ref.get("alt_text_en"),
        ref.get("alt_text_fr"),
    )


def assign_figures(ctx: Any) -> dict[int, int]:
    """Beat number (1-based) → FIGURE number (1-based) the beat stands on, by evidence.

    A figure belongs to the beat whose text (problem, discovery, card title)
    shares at least two content words with its caption and alt text, or one with
    the card title; each figure to one beat, the best match first. A beat with no
    such figure has none: it is never given a picture that does not show its idea.
    """
    refs = ctx.figure_refs()
    scored: list[tuple[int, int, int]] = []
    for number, beat in enumerate(ctx.beats, start=1):
        beat_words = story_assets.words(_beat_text(beat))
        title_words = story_assets.words(beat.get("card_title"))
        for index, ref in enumerate(refs, start=1):
            shared = beat_words & _figure_words(ref)
            if len(shared) >= 2 or (shared & title_words):
                scored.append((len(shared), number, index))
    scored.sort(key=lambda t: (-t[0], t[1], t[2]))
    out: dict[int, int] = {}
    used: set[int] = set()
    for _score, number, index in scored:
        if number in out or index in used:
            continue
        out[number] = index
        used.add(index)
    return out


def place_questions(ctx: Any, pack: dict[str, Any]) -> list[list[str]]:
    """The refs each beat asks, in order: the plan's, then the pack's own by IDEA.

    Every question of the chapter is asked exactly once. A question the plan
    did not place and whose IDEA no beat covers goes to the last beat.
    """
    beats = ctx.beats
    placed: list[list[str]] = [[] for _ in beats]
    wanted = list(ctx.assigned_refs)
    own = [
        (str(q.get("id") or f"x{n}"), q.get("idea"))
        for n, q in enumerate(pack.get("questions") or [], start=1)
        if isinstance(q, dict)
    ]
    ideas_of = {
        str(d.get("ref")): d.get("idea")
        for d in pack.get("derived") or []
        if isinstance(d, dict) and d.get("ref")
    }
    taken: set[str] = set()
    for index, beat in enumerate(beats):
        for ref in beat.get("questions") or []:
            if ref in wanted and ref not in taken:
                placed[index].append(ref)
                taken.add(ref)
    for ref, idea in [(r, ideas_of.get(r)) for r in wanted] + own:
        if ref in taken:
            continue
        home = next(
            (
                i
                for i, b in enumerate(beats)
                if isinstance(idea, int) and idea in (b.get("ideas") or [])
            ),
            len(beats) - 1,
        )
        if home >= 0:
            placed[home].append(ref)
            taken.add(ref)
    return placed


# -- the builder -----------------------------------------------------------------------


class _Builder:
    def __init__(self, ctx: Any, pack: dict[str, Any]) -> None:
        self.ctx = ctx
        self.pack = pack
        self.plan = ctx.plan or {}
        self.entry = ctx.plan_entry or {}
        self.target = ctx.target
        self.seed = seed_of(ctx.module_unit_id, self.plan.get("episode_title"), ctx.chapter_index)
        self.slots: list[Slot] = []
        self.count = 0
        self.used: dict[str, int] = {}
        self.line_cap = _line_cap(ctx)
        self.present = _cast_ids(ctx)
        self.hero_flaw = str(self.plan.get("hero_flaw") or "").strip()

    # -- slots -------------------------------------------------------------------------

    def fallback(self, role: str) -> dict[str, str] | None:
        options = FALLBACKS.get(role)
        if not options:
            return None
        # The n-th slot of a role takes the n-th line from a chapter-seeded start,
        # so two slots of a chapter never share a line (the builder drops a repeat).
        turn = self.used[role] = self.used.get(role, -1) + 1
        earlier = self.ctx.earlier_line_keys or {}
        for shift in range(len(options)):
            en, fr = options[(self.seed + turn + shift) % len(options)]
            if not repeat_keys({"type": "say", "en": en, "fr": fr}) & earlier.keys():
                break
        return {"en": en, "fr": fr}

    def slot(
        self,
        slot_id: str,
        role: str,
        who: str | None,
        cap: int,
        brief: str,
        fact: str,
        apply: Callable[[dict[str, str] | None], None],
        *,
        fallback: bool = True,
    ) -> Slot:
        self.count += 1
        made = Slot(
            slot_id,
            role,
            who,
            cap,
            brief,
            fact.strip(),
            apply,
            self.fallback(role) if fallback else None,
        )
        self.slots.append(made)
        return made

    def line(
        self,
        slot_id: str,
        role: str,
        who: str | None,
        mood: str,
        brief: str,
        fact: str = "",
        cap: int | None = None,
    ) -> dict[str, Any]:
        """A ``say`` (``who``) or ``narrate`` step whose text is a slot."""
        step: dict[str, Any] = (
            {"type": "say", "who": who, "mood": mood, "en": "", "fr": ""}
            if who
            else {"type": "narrate", "en": "", "fr": ""}
        )

        def apply(value: dict[str, str] | None, step: dict[str, Any] = step) -> None:
            if value is not None:
                step["en"], step["fr"] = value["en"], value["fr"]

        self.slot(slot_id, role, who, cap or self.line_cap, brief, fact, apply)
        return step

    # -- one beat ------------------------------------------------------------------------

    def beat(
        self,
        number: int,
        beat: dict[str, Any],
        *,
        figure: int | None,
        refs: list[str],
        first: bool,
    ) -> dict[str, Any]:
        ctx = self.ctx
        cast = [c for c in beat.get("cast") or [] if c in self.present]
        if HERO not in cast:
            cast.insert(0, HERO)
        a, b = _speakers(ctx, cast, self.present)
        pid = f"b{number}"
        place = _place_title(ctx, str(beat.get("place") or ""))
        problem = str(beat.get("problem") or "").strip()
        opens = str(self.entry.get("opens_on") or "").strip()
        steps: list[dict[str, Any]] = []

        steps.append(
            self.line(
                f"{pid}.set",
                NARRATION,
                None,
                "talk",
                f"Open the scene at «{place}» in one sentence, present tense, third person."
                + (f" It continues where the story stopped: {opens}" if first and opens else ""),
                problem,
            )
        )
        if figure is not None:
            steps.append({"type": "show", "figure": figure})
        steps.append(
            self.line(
                f"{pid}.hook",
                HOOK,
                a,
                "surprised",
                f"{a} notices the problem on stage and asks or exclaims, so that {{child}} wants"
                " to know. A hook, never an explanation, never the answer."
                + (" It reacts to the picture just shown." if figure is not None else ""),
                problem,
            )
        )
        steps.append(
            self.line(
                f"{pid}.hero",
                HERO_LINE,
                HERO,
                "think",
                "{child} gives a first guess in their own words, rushing a little"
                + (f" ({self.hero_flaw})" if self.hero_flaw else "")
                + ". Do not say the lesson's rule.",
                problem,
            )
        )
        if poe_spec := beat.get("demo"):
            steps.extend(self.bet(pid, beat, poe_spec, a, b, figure))
        discovery = beat.get("discovery") or {}
        d_en, d_fr = str(discovery.get("en") or "").strip(), str(discovery.get("fr") or "").strip()
        if d_en and d_fr and d_en != d_fr and words(d_en) <= self.line_cap * 2:
            steps.append({"type": "say", "who": HERO, "mood": "happy", "en": d_en, "fr": d_fr})
        else:
            idea_text = self.idea_text(beat)
            steps.append(
                self.line(
                    f"{pid}.find",
                    REACTION,
                    HERO,
                    "happy",
                    "{child} finds out, in their own words, what the scene showed. Plain words,"
                    " the discovery of this scene only.",
                    idea_text or problem,
                )
            )
        steps.append(self.card(pid, beat))
        for ref in refs:
            steps.append({"type": "ask", "ref": ref})
        if refs:
            steps.append(
                self.line(
                    f"{pid}.after",
                    REACTION,
                    b,
                    "talk",
                    f"{b} reacts to {{child}}'s choice and the story moves on to what happens"
                    " next. Never say whether the choice was right.",
                    problem,
                )
            )
        props = self.scene_props(beat)
        scene: dict[str, Any] = {"place": beat.get("place"), "cast": cast, "steps": steps}
        if props:
            scene["props"] = props
        return scene

    def idea_text(self, beat: dict[str, Any]) -> str:
        ideas = self.ctx.lesson_list("concepts")
        picked = [
            ideas[i - 1]
            for i in beat.get("ideas") or []
            if isinstance(i, int) and 1 <= i <= len(ideas)
        ]
        return " ".join(picked)

    def card(self, pid: str, beat: dict[str, Any]) -> dict[str, Any]:
        """The concept card: the plan's title, two rows that restate the lesson's IDEA."""
        title = beat.get("card_title") or {}
        t_en, t_fr = str(title.get("en") or "").strip(), str(title.get("fr") or "").strip()
        title_words = max(words(t_en), words(t_fr))
        room = max(_card_cap(self.ctx) - title_words, 2 * MIN_ROW_WORDS)
        first = max(MIN_ROW_WORDS, room // 2)
        second = max(MIN_ROW_WORDS, room - first)
        fact = self.idea_text(beat)
        step: dict[str, Any] = {
            "type": "concept",
            "teaches": [i for i in beat.get("ideas") or [] if isinstance(i, int)] or [1],
            "title": {"en": t_en, "fr": t_fr},
            "en": ["", ""],
            "fr": ["", ""],
        }

        def row(index: int) -> Callable[[dict[str, str] | None], None]:
            def apply(value: dict[str, str] | None) -> None:
                if value is not None:
                    step["en"][index], step["fr"][index] = value["en"], value["fr"]

            return apply

        self.slot(
            f"{pid}.row1",
            CARD_ROW,
            None,
            first,
            "Card row 1: the new word of this idea, with what it means. A label, not a"
            " sentence of dialogue; do not repeat what the characters said.",
            fact,
            row(0),
            fallback=False,
        )
        if discovery_pair(beat):
            self.slots[-1].fallback = discovery_pair(beat)
        self.slot(
            f"{pid}.row2",
            CARD_ROW,
            None,
            second,
            "Card row 2: the rule of this idea in plain words, from the fact only. Never"
            " repeat a line of the dialogue.",
            fact,
            row(1),
            fallback=False,
        )
        return step

    def scene_props(self, beat: dict[str, Any]) -> list[str]:
        """The plan's props this beat's own words name (the builder binds them, art first)."""
        text = _beat_text(beat)
        out: list[str] = []
        for prop in self.ctx.known_props or []:
            pid = prop.get("id") if isinstance(prop, dict) else None
            if not pid or pid in out or prop.get("origin") not in (None, "module"):
                continue
            if names_prop(text, prop, "en") or names_prop(text, prop, "fr"):
                out.append(str(pid))
        # A prop with art (a bound figure) is listed first: the close-up is worth showing.
        by_id = {str(p.get("id")): p for p in self.ctx.known_props or [] if isinstance(p, dict)}
        out.sort(key=lambda i: 0 if by_id.get(i, {}).get("figure") else 1)
        return out[:3]

    # -- a bet -------------------------------------------------------------------------------

    def bet(
        self,
        pid: str,
        beat: dict[str, Any],
        spec: Any,
        a: str,
        b: str,
        figure: int | None,
    ) -> list[dict[str, Any]]:
        """The ``predict`` step of a beat that carries a demo spec; ``[]`` when it cannot be built."""
        if not isinstance(spec, dict):
            return []
        visual = str(spec.get("visual") or "")
        if visual not in poe.DEMO_KINDS:
            return []
        ideas = [i for i in beat.get("ideas") or [] if isinstance(i, int)]
        params = dict(spec.get("params") or {})
        step: dict[str, Any] = {
            "type": "predict",
            "teaches": ideas[0] if ideas else 1,
            "en": "",
            "fr": "",
            "demo": {"visual": visual, "params": params},
            "react_right": {"en": "", "fr": ""},
            "react_wrong": {"en": "", "fr": ""},
        }
        if isinstance(spec.get("options"), list):
            step["options"] = [dict(o) for o in spec["options"] if isinstance(o, dict)]
        if spec.get("expected") is not None:
            step["expected"] = spec["expected"]
        if visual == "compare":
            labels = params.get("labels")
            have = (
                isinstance(labels, list)
                and len(labels) == 2
                and all(poe._text(label, poe.LABEL_LIMIT) for label in labels)
            )
            if not have:
                params["labels"] = [{"en": "", "fr": ""}, {"en": "", "fr": ""}]
                for n in (0, 1):
                    self.slot(
                        f"{pid}.label{n + 1}",
                        LABEL,
                        None,
                        LABEL_WORDS,
                        f"Name of the {'first' if n == 0 else 'second'} thing compared in the"
                        " demo, two or three words, a noun phrase.",
                        str(beat.get("problem") or ""),
                        self._label_apply(params, n),
                    )
            if "options" not in step:
                step["options"] = [
                    {"en": "", "fr": "", "is": "a"},
                    {"en": "", "fr": "", "is": "b"},
                    {"en": "Same", "fr": "Pareil", "is": "equal"},
                ]
                step["_chips"] = params["labels"]

        def prompt(value: dict[str, str] | None, step: dict[str, Any] = step) -> None:
            if value is not None:
                step["en"], step["fr"] = value["en"], value["fr"]

        self.slot(
            f"{pid}.bet",
            BET_PROMPT,
            None,
            self.line_cap,
            "The bet's question: what will happen, or which is more, about what is on stage."
            " A learner can answer without knowing the lesson. Never the lesson's rule.",
            str(beat.get("problem") or ""),
            prompt,
        )
        for role, key, brief in (
            (REACT_RIGHT, "react_right", "the bet was right"),
            (REACT_WRONG, "react_wrong", "the bet was wrong"),
        ):
            self.slot(
                f"{pid}.{'right' if role == REACT_RIGHT else 'wrong'}",
                role,
                a,
                REACTION_WORDS,
                f"{a} reacts when {brief}, at most {REACTION_WORDS} words. Never the lesson's rule.",
                str(beat.get("problem") or ""),
                self._react_apply(step, key),
            )
        return [step]

    @staticmethod
    def _label_apply(params: dict[str, Any], n: int) -> Callable[[dict[str, str] | None], None]:
        def apply(value: dict[str, str] | None) -> None:
            if value is not None:
                params["labels"][n].update(value)

        return apply

    @staticmethod
    def _react_apply(step: dict[str, Any], key: str) -> Callable[[dict[str, str] | None], None]:
        def apply(value: dict[str, str] | None) -> None:
            if value is not None:
                step[key].update(value)

        return apply

    # -- the whole chapter ---------------------------------------------------------------------------

    def chapter(self) -> Script:
        ctx = self.ctx
        beats = ctx.beats
        figures = assign_figures(ctx)
        asked = place_questions(ctx, self.pack)
        scenes: list[dict[str, Any]] = []
        evidence: list[dict[str, Any]] = []
        for number, beat in enumerate(beats, start=1):
            scene = self.beat(
                number,
                beat,
                figure=figures.get(number),
                refs=asked[number - 1],
                first=number == 1,
            )
            scenes.append(scene)
            evidence.append(
                {
                    "beat": number,
                    "figure": figures.get(number),
                    "bet": any(s.get("type") == "predict" for s in scene["steps"]),
                    "props": scene.get("props", []),
                    "questions": asked[number - 1],
                }
            )
        tail = scenes[-1]["steps"] if scenes else []
        entry = self.entry
        exercises = [e for e in self.pack.get("exercises") or [] if isinstance(e, dict)]
        for n, _exercise in enumerate(exercises, start=1):
            tail.append(
                self.line(
                    f"task{n}",
                    LEAD,
                    None,
                    "talk",
                    "Someone hands over the paper task, in one line that sets it up. Do not"
                    " describe the answer.",
                    str(entry.get("paper_task") or ""),
                )
            )
            tail.append({"type": "photo", "ref": f"E{n}"})
        if ctx.has_game:
            tail.append(
                self.line(
                    "game",
                    LEAD,
                    None,
                    "talk",
                    "A challenge begins: one line that sets the game up, in the story's voice.",
                    str(entry.get("game") or entry.get("goal") or ""),
                )
            )
            tail.append({"type": "game"})
        tail.append(
            self.line(
                "end.react",
                REACTION,
                HERO,
                "happy",
                "{child} reacts to how this chapter turned out, in their own voice.",
                str(entry.get("turn") or ""),
            )
        )
        tail.append(
            self.line(
                "end.close",
                CLOSE,
                None,
                "talk",
                "Close the chapter on this image or hook, one warm sentence, never a lesson:"
                f" {entry.get('ends_on') or ''}".strip(),
                str(entry.get("ends_on") or ""),
            )
        )
        recap = " ".join(
            str(entry.get(k) or "").strip() for k in ("goal", "turn", "ends_on") if entry.get(k)
        )
        script = Script(
            scenes=scenes,
            slots=self.slots,
            evidence=evidence,
            seed=self.seed,
            recap=re.sub(r"\s+", " ", recap)[:600],
            props_now=[
                {"id": pid, "state": "seen in this chapter"}
                for pid in dict.fromkeys(p for e in evidence for p in e["props"])
            ],
        )
        return script


def build_script(ctx: Any, pack: dict[str, Any]) -> Script:
    """The screenplay of a lesson chapter as code builds it, its slots still empty."""
    return _Builder(ctx, pack).chapter()


def attach_props(script: Script, ctx: Any) -> None:
    """``props`` on each line that names a plan prop, and on its scene, art first.

    The builder wants a line that names a prop to list it (and puts the prop on
    stage and its close-up after the first line that names it). The lines are
    only known once the slots are filled, so this runs after them: the same
    rule the model was asked to follow, applied by code.
    """
    known = [p for p in ctx.known_props or [] if isinstance(p, dict) and p.get("id")]
    known = [p for p in known if p.get("origin") in (None, "module")]
    by_id = {str(p["id"]): p for p in known}
    for number, scene in enumerate(script.scenes):
        listed: list[str] = []
        for step in scene["steps"]:
            if step.get("type") not in ("say", "narrate"):
                continue
            named = [
                str(p["id"])
                for p in known
                if any(names_prop(step.get(lang), p, lang) for lang in ("en", "fr"))
            ][:3]
            if named:
                step["props"] = named
                listed += [pid for pid in named if pid not in listed]
        listed.sort(key=lambda i: 0 if by_id[i].get("figure") else 1)
        if listed:
            scene["props"] = listed[:4]
        else:
            scene.pop("props", None)
        if number < len(script.evidence):
            script.evidence[number]["props"] = scene.get("props", [])
    script.props_now = [
        {"id": pid, "state": "seen in this chapter"}
        for pid in dict.fromkeys(p for e in script.evidence for p in e["props"])
    ]


def finalize(script: Script, ctx: Any | None = None) -> None:
    """Tidy the script once its slots are filled: empty card rows, chips, props.

    The chips of a ``compare`` bet are the labels the model gave, so they are
    copied once those exist; a card row that stayed empty is dropped.
    """
    if ctx is not None:
        attach_props(script, ctx)
    for scene in script.scenes:
        for step in scene["steps"]:
            if step.get("type") == "concept":
                keep = [i for i, row in enumerate(step["en"]) if row and step["fr"][i]]
                step["en"] = [step["en"][i] for i in keep]
                step["fr"] = [step["fr"][i] for i in keep]
            chips = step.pop("_chips", None)
            if chips is None:
                continue
            for option in step.get("options") or []:
                index = {"a": 0, "b": 1}.get(option.get("is"))
                if index is not None and not option.get("en"):
                    option["en"] = chips[index].get("en", "")
                    option["fr"] = chips[index].get("fr", "")
