"""Pydantic V2 schemas for the ``story-course/1`` course file format.

One week of work for a learner is one course file: the story that teaches the
concepts, the questions scored in the app, the paper-and-pen exercises checked
from a photo, a mini-game, and the AI tutor's brief. Appendix A of the format
doc is the normative reference; the field comments below cite its sections.

Strictness is deliberately uneven, mirroring Appendix C.1:

* **Closed** — ``format``, step types, question types, exercise parts, cast
  kinds and mark-scheme codes. A value outside these is a structural error.
* **Open** — visuals, places, character art, mini-game engines and photo-copy
  shapes. The catalogs here are "v1"; a course file may use something new as
  long as it declares it in ``art_requests`` or ``engine_requests``. Membership
  is therefore checked by the validator, which can see those declarations, not
  by the schema.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

FORMAT_VERSION = "story-course/1"

# --- Catalogs (Appendix A.2, A.4-A.9) --------------------------------------

#: Story step kinds (A.4). Closed: the app has a renderer per kind.
STEP_TYPES = ("narrate", "say", "show", "concept", "ask", "game", "photo", "video")

#: Question kinds (A.5). Closed: the app has a scorer per kind.
QUESTION_TYPES = ("number", "exact_text", "list", "choice", "index_form", "time", "multi")

#: Concept-widget catalog (A.8). Open via ``art_requests``.
VISUALS = (
    "place_value",
    "rounding_line",
    "number_line",
    "thermometer",
    "lift",
    "counters",
    "bidmas_ladder",
    "squares",
    "array",
    "hundred_square",
    "factor_tree",
    "division_ladder",
    "venn_primes",
    "timeline",
    "tiles",
    "image",
)

#: The catalog visuals the player draws today, with their exact params
#: (``frontend/components/story/concept-visual.tsx``): ``{param: (required,
#: description)}``. Any other visual shows "this picture is not available
#: yet", so a generated story may only use these (or a lesson figure,
#: ``image``).
DRAWN_VISUALS: dict[str, dict[str, tuple[bool, str]]] = {
    "hundred_square": {"highlight": (True, '"primes" or "multiples:N" (N a whole number)')},
    "factor_tree": {
        "n": (True, "a whole number from 4 to 1000"),
        "first_split": (False, "[a, b], two whole numbers above 1 with a × b = n"),
    },
    "division_ladder": {"n": (True, "a whole number from 4 to 1000")},
    "venn_primes": {
        "a": (True, "a whole number from 2 to 1000"),
        "b": (True, "a whole number from 2 to 1000"),
    },
}

#: Scene backdrops (A.8). Open via ``art_requests``.
PLACES = (
    "home",
    "kitchen",
    "market",
    "classroom",
    "school_yard",
    "mango_farm",
    "bus_station",
    "shop",
    "desk",
    "montreal",
)

#: Character art keys (A.8). Open via ``art_requests``.
ART_KEYS = (
    "nandi",
    "papa_ben",
    "maman_olivia",
    "dodeine",
    "tamobe",
    "friend",
    "mr_kabore",
    "m_sanou",
    "tonton_issouf",
    "margo",
)

#: Character moods (A.2). A ``say`` step's ``mood`` is one of these; the
#: cartoon stage has a pose per mood (contract of #2672).
MOODS = ("idle", "talk", "happy", "think", "sad", "surprised", "walk")

#: A cast member's role in a generated story (contract of #2672). Optional:
#: hand-authored weeks and stories stored before the course bible have none.
CAST_ROLES = ("hero", "friend", "mentor", "family", "tutor")

#: Mini-game engines (A.9). Open via ``engine_requests``.
MINIGAME_ENGINES = ("catch", "hop", "which_first", "pop")

#: Photo-copy shapes (A.6). Open via ``engine_requests``.
COPY_SHAPES = ("final_only", "lines", "steps", "factor_tree", "division_ladder")

#: Mark-scheme codes (A.6). Closed.
MARK_CODES = ("M1", "A1", "B1", "SC1")

#: Length limits in characters, keyed by field then language (A.2).
LENGTH_LIMITS: dict[str, dict[str, int]] = {
    "story": {"en": 100, "fr": 118},
    "prompt": {"en": 160, "fr": 190},
    "hint": {"en": 140, "fr": 160},
}

#: Appendix A.11 reward defaults, applied when ``rewards`` is absent.
REWARD_DEFAULTS: dict[str, Any] = {
    "unit": {"en": "mangoes", "fr": "mangues"},
    "first_try": 2,
    "second_try": 1,
    "streak": {"every": 3, "bonus": 1},
    "stars": {"3": 0.85, "2": 0.6},
}

#: A text object (A.2) maps each declared language code to its string. Modelled
#: as a plain mapping rather than fixed en/fr fields because ``languages`` is
#: part of the file; the validator checks both declared codes are present and
#: reports a precise path when one is missing.
TextObject = dict[str, str]


class _Loose(BaseModel):
    """Base that keeps unknown keys.

    The format is authored by hand and versioned separately from this code, so
    an unrecognised key is preserved and reported by the validator rather than
    silently dropped or treated as fatal.
    """

    model_config = ConfigDict(extra="allow")


# --- Header -----------------------------------------------------------------


class Languages(_Loose):
    target: str = Field(..., description="Language of instruction, e.g. 'en'")
    home: str = Field(..., description="The learner's home language, e.g. 'fr'")


class Learner(_Loose):
    first_name: str
    age: int | None = None
    # Drives French agreement in generated text ("fière", "ta meilleure amie").
    gender: str | None = None


class Source(_Loose):
    kind: Literal["lesson", "test", "worksheet", "booklet"]
    ref: str
    used_for: str | None = None


class Objective(_Loose):
    """A.3: objectives carry flat ``en``/``fr``, not a nested text object."""

    id: str
    en: str
    fr: str
    syllabus: str | None = None


class GlossaryEntry(_Loose):
    en: str
    fr: str
    note: TextObject | None = None


class CalibrationRow(_Loose):
    """One row of the marked-test table that seeds ``misconceptions``."""

    test_q: str
    her_answer: str | None = None
    mark: str | None = None
    correct: str | None = None
    misconception: str | None = None


class Misconception(_Loose):
    id: str
    en: str
    fr: str
    from_test: bool = False


class Voice(_Loose):
    pitch: float = 1.0
    rate: float = 1.0


class CastVariant(_Loose):
    """One look the learner can pick for the hero ("girl"/"boy", "woman"/"man")."""

    id: str
    look: str


class CastMember(_Loose):
    """A character. ``art`` is the placeholder art key (A.8 catalog).

    The course bible (#2674) adds the optional ``role``, ``look`` (one English
    sentence for the image model), ``variants`` (hero only) and, for the
    friend, ``default_name``. Every one is optional, so weeks stored before
    it keep parsing.
    """

    id: str
    name: str
    kind: Literal["child", "adult", "animal", "ai_tutor"]
    art: str
    voice: Voice = Field(default_factory=Voice)
    role: str | None = None
    look: str | None = None
    variants: list[CastVariant] = Field(default_factory=list)
    default_name: str | None = None


class Place(_Loose):
    """A backdrop of the course bible: ``scene.place`` may name its ``id``."""

    id: str
    title: TextObject
    look: str | None = None


class Fact(_Loose):
    """A real local detail, or one marked ``invented``."""

    en: str
    fr: str
    source: str | None = None
    invented: bool = False


# --- Story ------------------------------------------------------------------


class Step(_Loose):
    """One story beat (A.4).

    Fields vary by ``type``, so they are all optional here and the validator
    enforces the per-type requirements.
    """

    type: Literal[STEP_TYPES]  # type: ignore[valid-type]
    # narrate / say
    en: str | list[str] | None = None
    fr: str | list[str] | None = None
    who: str | None = None
    mood: str | None = None
    # show
    visual: str | None = None
    params: dict[str, Any] | None = None
    caption: TextObject | None = None
    # concept
    id: str | None = None
    title: TextObject | None = None
    # ask / game / photo / video
    ref: str | None = None


class Scene(_Loose):
    id: str
    place: str
    objective: str | None = None
    #: The cast ids on stage (two or three), optional (#2672).
    cast: list[str] | None = None
    steps: list[Step] = Field(default_factory=list)


class Chapter(_Loose):
    id: str
    title: TextObject
    scenes: list[Scene] = Field(default_factory=list)


# --- Questions and exercises ------------------------------------------------


class Verify(_Loose):
    """An engine call that recomputes an answer (A.7)."""

    fn: str
    args: list[Any] = Field(default_factory=list)
    kwargs: dict[str, Any] = Field(default_factory=dict)


class Trap(_Loose):
    """A wrong answer she is actually likely to give, with a targeted hint."""

    answer: Any = None
    misconception: str | None = None
    hint: TextObject | None = None


class Choice(_Loose):
    id: str
    en: str
    fr: str
    # Absent on the correct option; required on every wrong one (C.1).
    misconception: str | None = None


class QuestionPart(_Loose):
    label: str | None = None
    type: str | None = None
    answer: Any = None
    verify: Verify | None = None
    marks: int | None = None


class Question(_Loose):
    id: str
    type: Literal[QUESTION_TYPES]  # type: ignore[valid-type]
    objective: str | None = None
    calculator: bool = False
    prompt: TextObject
    answer: Any = None
    verify: Verify | None = None
    traps: list[Trap] = Field(default_factory=list)
    hints: list[TextObject] = Field(default_factory=list)
    explanation: TextObject | None = None
    tutor_notes: str | None = None
    units: str | None = None
    order: Literal["ascending", "any"] | None = None
    choices: list[Choice] = Field(default_factory=list)
    require_index: bool = False
    parts: list[QuestionPart] = Field(default_factory=list)
    review_of: str | int | None = None
    points: int | None = None


class MarkSchemeRow(_Loose):
    code: Literal[MARK_CODES]  # type: ignore[valid-type]
    en: str
    fr: str


class PhotoCheck(_Loose):
    """How the AI copies her handwriting and which code checks it (A.6).

    The format's key is ``copy``; it is aliased here because ``copy`` would
    shadow ``BaseModel.copy``.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    copy_shape: str = Field(..., alias="copy")
    check: dict[str, Any] = Field(default_factory=dict)


class Exercise(_Loose):
    id: str
    part: Literal["A", "B", "C", "D"]
    objective: str | None = None
    marks: int = 0
    calculator: bool = False
    prompt: TextObject
    answer: Any = None
    verify: Verify | None = None
    parts: list[QuestionPart] = Field(default_factory=list)
    working: dict[str, list[str]] = Field(default_factory=dict)
    mark_scheme: list[MarkSchemeRow] = Field(default_factory=list)
    traps: list[Trap] = Field(default_factory=list)
    explanation: TextObject | None = None
    photo_check: PhotoCheck | None = None


# --- Mini-games, videos, tutor, rewards ------------------------------------


class Minigame(_Loose):
    id: str
    engine: str
    objective: str | None = None
    title: TextObject
    instruction: TextObject
    rule: dict[str, Any] | None = None
    rounds: list[Any] = Field(default_factory=list)
    traps: dict[str, str] = Field(default_factory=dict)
    hint_after_wrong: TextObject | None = None
    points: dict[str, int] = Field(default_factory=dict)
    timer_s: int | None = None
    speed: float | None = None
    min: int | None = None
    max: int | None = None


class Video(_Loose):
    id: str
    provider: str
    lang: str
    title: str
    url: str


class TutorScope(_Loose):
    this_week: list[str] = Field(default_factory=list)
    earlier_weeks: str | None = None


class Tutor(_Loose):
    """The brief the app turns into instructions for whichever model it uses.

    The course file never names a model (A.10): the relay picks the provider.
    """

    persona: str
    intro: TextObject
    scope: TutorScope = Field(default_factory=TutorScope)
    style: list[str] = Field(default_factory=list)
    never: list[str] = Field(default_factory=list)
    off_topic: TextObject | None = None
    worry: TextObject | None = None
    max_turns_per_item: int = 6


class ArtRequest(_Loose):
    name: str
    kind: Literal["place", "prop", "visual", "character"]
    description: str


class EngineRequest(_Loose):
    engine: str
    rules: str | None = None
    controls: str | None = None
    scoring: str | None = None
    end: str | None = None


class Checks(_Loose):
    """Written by the validator (A.11); ``errors`` must be 0 to ship."""

    validator: str | None = None
    date: str | None = None
    questions: int = 0
    exercises: int = 0
    paper_marks: int = 0
    minigame_rounds: int = 0
    max_points: int = 0
    errors: int = 0
    warnings: int = 0
    predicted_typical: dict[str, Any] | None = None


# --- The course file --------------------------------------------------------


class StoryCourse(_Loose):
    """A whole week: one ``course.json`` in the ``story-course/1`` format."""

    format: Literal[FORMAT_VERSION] = FORMAT_VERSION  # type: ignore[valid-type]
    id: str
    course: str
    unit: str | None = None
    week: int
    title: TextObject
    languages: Languages
    learner: Learner
    sources: list[Source] = Field(default_factory=list)
    objectives: list[Objective] = Field(default_factory=list)
    glossary: list[GlossaryEntry] = Field(default_factory=list)
    calibration: list[CalibrationRow] = Field(default_factory=list)
    misconceptions: list[Misconception] = Field(default_factory=list)
    cast: list[CastMember] = Field(default_factory=list)
    #: The course's backdrops (#2672); a scene's ``place`` names one of these
    #: ids or a key of the :data:`PLACES` catalog.
    places: list[Place] = Field(default_factory=list)
    facts: list[Fact] = Field(default_factory=list)
    chapters: list[Chapter] = Field(default_factory=list)
    questions: list[Question] = Field(default_factory=list)
    exercises: list[Exercise] = Field(default_factory=list)
    minigames: list[Minigame] = Field(default_factory=list)
    videos: list[Video] = Field(default_factory=list)
    tutor: Tutor | None = None
    rewards: dict[str, Any] = Field(default_factory=lambda: dict(REWARD_DEFAULTS))
    art_requests: list[ArtRequest] = Field(default_factory=list)
    engine_requests: list[EngineRequest] = Field(default_factory=list)
    checks: Checks = Field(default_factory=Checks)

    @property
    def language_codes(self) -> tuple[str, str]:
        """``(target, home)`` — the keys every text object must carry."""
        return self.languages.target, self.languages.home


# --- API payloads -----------------------------------------------------------


class ValidationIssue(BaseModel):
    """One validator finding, addressed to whoever authors the course file."""

    severity: Literal["error", "warning"]
    code: str = Field(..., description="Stable machine code, e.g. 'answer_mismatch'")
    path: str = Field(..., description="Where it is, e.g. 'questions[q2].verify'")
    message: str


class ValidationReport(BaseModel):
    """Appendix C outcome. ``ok`` is true only when there are zero errors."""

    ok: bool
    errors: list[ValidationIssue] = Field(default_factory=list)
    warnings: list[ValidationIssue] = Field(default_factory=list)
    checks: Checks = Field(default_factory=Checks)


class StoryCourseListItem(BaseModel):
    """Catalog row (A.1 ``catalog.json``)."""

    id: str
    course: str
    unit: str | None = None
    week: int
    title: TextObject
    languages: Languages
    objective_count: int = 0
    question_count: int = 0
    exercise_count: int = 0
    max_points: int = 0
    is_valid: bool = True


class StoryCourseListResponse(BaseModel):
    items: list[StoryCourseListItem] = Field(default_factory=list)
    total: int = 0
