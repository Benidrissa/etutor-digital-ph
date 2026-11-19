"""The pictures a module's story may show: the course's own, found by code (#2709).

A story told about a lesson should show what the course already owns — the
figure of its PDF, the illustration its lesson was given — instead of an
emoji or a name tag. This module builds, **before any model call**, a
per-module catalogue ``A1..An`` of those pictures, persists it
(:class:`StoryAssetCatalogue`), numbers it for the plan and chapter prompts
(``FIGURE n [figure|illustration]``), binds the story's educational props to
it, and re-binds a story that is already stored, with no model call at all.

Resolution order (the catalogue lists them in this order, A1 first):

1. the figures the lessons already cite (``source_image_refs``);
2. the figures linked to the same text chunks as those
   (``SemanticRetriever.get_linked_images``);
3. the course's other figures, by embedding (``search_source_images``), kept
   only when they share a word with the lesson's idea (a caption, a tag);
4. the lesson illustrations (``generated_images``, status ``ready``), by
   lesson, then by module.

Three rules hold everywhere:

* **Nothing crosses a course.** A ``source_images`` row enters the catalogue
  only when its ``source`` is the course's ``rag_collection_id``
  (:func:`in_course`); an illustration only when it belongs to one of the
  module's lessons or to the module itself (:func:`illustration_in_scope`).
  Both are checked on every candidate, whichever step found it.
* **No noise.** Mis-extracted body text, decoration and stock thumbnails are
  never offered (:func:`usable_kind`).
* **Nothing is resolved while a learner reads.** The embedding search and
  the binary checks run here, when a story is generated or re-bound, never
  in a GET.

The pure half (entries, scope, dedupe, binding, the re-binding of a story
document) is unit-tested; the half that reads the database is thin.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.story_course import MAX_CLOSEUPS_PER_SCENE
from app.domain.services.story_metrics import DEIXIS_RE
from app.domain.services.story_props import (
    LINE_TYPES,
    _asks_or_sets_up,
    figure_of,
    fold,
    insert_closeup,
)

logger = structlog.get_logger(__name__)

CATALOGUE_VERSION = 1

#: What a picture is: a figure of the course's PDF, or an AI illustration of its lesson.
KIND_FIGURE = "figure"
KIND_ILLUSTRATION = "illustration"
#: How the player credits it: « Tiré du cours » / « Illustration du cours (IA) ».
CREDIT_COURSE = "course"
CREDIT_ILLUSTRATION = "course_illustration"

#: Where a candidate was found, best first.
ORIGINS = ("pinned", "lesson_ref", "linked", "semantic", "generated")

#: ``figure_kind`` values never offered (the same as ``get_linked_images``'s).
EXCLUDED_KINDS = frozenset({"body_text", "decorative"})
STOCK_THUMB_KINDS = frozenset({"photo", "decorative"})
STOCK_THUMB_MAX_WIDTH = 200

#: Cosine similarity under which a figure is not even considered (the diagnostic's threshold).
MIN_SIMILARITY = 0.45
SEARCH_TOP_K = 5
#: A figure found by embedding must share this many words with the lesson's idea.
MIN_SEARCH_OVERLAP = 1
#: Most entries for a module, most a chapter is told about, most binaries checked.
MAX_ENTRIES = 16
MAX_FIGURES_PER_UNIT = 6
MAX_CHECKS = 40
CHECK_TRIES = 2
MAX_ILLUSTRATIONS = 8

_WORD_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    [
        "the",
        "and",
        "for",
        "with",
        "from",
        "that",
        "this",
        "these",
        "those",
        "into",
        "your",
        "their",
        "there",
        "here",
        "what",
        "when",
        "where",
        "which",
        "while",
        "about",
        "over",
        "under",
        "between",
        "les",
        "des",
        "une",
        "aux",
        "pour",
        "avec",
        "dans",
        "sur",
        "sous",
        "par",
        "est",
        "sont",
        "qui",
        "que",
        "quoi",
        "dont",
        "cette",
        "ces",
        "ses",
        "leur",
        "leurs",
        "nos",
        "vos",
        "mon",
        "ton",
        "son",
        "chez",
        "entre",
        "vers",
        "figure",
        "fig",
        "page",
        "tableau",
    ]
)


# -- words -------------------------------------------------------------------------


def _stem(word: str) -> str:
    """ "tables" and "table" are one word; nothing cleverer is needed here."""
    return word[:-1] if len(word) > 4 and word.endswith("s") else word


def words(*texts: Any) -> frozenset[str]:
    """The comparable words of some texts: folded, no stop words, no 1-3 letter words."""
    out: set[str] = set()
    for text in texts:
        if isinstance(text, Mapping):
            out |= words(*text.values())
            continue
        if isinstance(text, list | tuple | set | frozenset):
            out |= words(*text)
            continue
        for word in _WORD_RE.findall(fold(text).replace("'", " ")):
            if (len(word) >= 4 or word.isdigit() and len(word) >= 2) and word not in _STOPWORDS:
                out.add(_stem(word))
    return frozenset(out)


# -- scope and noise: the rules that keep a catalogue clean --------------------------


def usable_kind(figure_kind: Any, width: Any) -> bool:
    """False for body text, decoration and stock thumbnails (never a figure to show)."""
    kind = str(figure_kind or "").lower()
    if kind in EXCLUDED_KINDS:
        return False
    return not (
        kind in STOCK_THUMB_KINDS and (not isinstance(width, int) or width <= STOCK_THUMB_MAX_WIDTH)
    )


def in_course(source: Any, course_source: str | None) -> bool:
    """A ``source_images`` row belongs to the course: its ``source`` is the course's collection."""
    return bool(course_source) and str(source or "") == str(course_source)


def illustration_in_scope(
    row: Mapping[str, Any], *, lesson_ids: Iterable[Any], module_id: Any
) -> bool:
    """A lesson illustration belongs to one of the module's lessons, or to the module.

    The module is enough: a unit has one lesson row per language (and sometimes
    per level), and an illustration is drawn for one of them. Staging: the four
    ready illustrations of a module all named a sibling row of the lesson the
    French story reads, and none reached the catalogue.
    """
    if row.get("module_id") is not None and str(row.get("module_id")) == str(module_id):
        return True
    lesson_id = row.get("lesson_id")
    return lesson_id is not None and str(lesson_id) in {str(i) for i in lesson_ids}


# -- entries -----------------------------------------------------------------------


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _pair(fr: Any, en: Any, fallback: Any = "") -> dict[str, str]:
    fr_text, en_text, other = _text(fr), _text(en), _text(fallback)
    return {"fr": fr_text or en_text or other, "en": en_text or fr_text or other}


def _tag_values(tags: Any) -> list[str]:
    if isinstance(tags, Mapping):
        return [str(v) for value in tags.values() for v in _tag_values(value)]
    if isinstance(tags, list | tuple):
        return [str(v) for value in tags for v in _tag_values(value)]
    return [str(tags)] if tags else []


#: A page rendered whole (not a cropped figure): the PDF's text is in the picture.
PAGE_MIN_WIDTH = 800
PAGE_MIN_RATIO = 1.25


def is_page_capture(figure_kind: Any, width: Any, height: Any) -> bool:
    """``complex_diagram``, or a portrait picture as large as a page: a whole page, not a figure."""
    if str(figure_kind or "").lower() == "complex_diagram":
        return True
    return (
        isinstance(width, int)
        and isinstance(height, int)
        and width >= PAGE_MIN_WIDTH
        and height >= PAGE_MIN_RATIO * width
    )


def human_source(value: Any, limit: int = 60) -> str:
    """A file name made readable: no extension, underscores and hyphen runs as spaces, ~60 characters."""
    name = _text(value)
    name = re.sub(r"\.(pdf|docx?|pptx?|epub|csv|txt)\b", "", name, flags=re.IGNORECASE)
    name = re.sub(r"_+|-{2,}", " ", name)
    name = " ".join(name.split())
    if len(name) > limit:
        cut = name[:limit]
        space = cut.rfind(" ")
        name = (cut[:space] if space > limit // 2 else cut).rstrip(" ,;:.-") + "…"
    return name


def figure_entry(row: Mapping[str, Any], *, origin: str, unit_id: str | None) -> dict[str, Any]:
    """A catalogue entry for a ``source_images`` row (its columns, as a mapping)."""
    page = row.get("page_number")
    attribution = _text(row.get("attribution"))
    if not attribution:
        # Fallback credit: the resource's title and the page.
        parts = [human_source(row.get("resource_title")), f"p.{page}" if page else ""]
        attribution = ", ".join(p for p in parts if p)
    entry: dict[str, Any] = {
        "asset_id": str(row["id"]),
        "kind": KIND_FIGURE,
        "credit": CREDIT_COURSE,
        "origin": origin,
        "units": [unit_id] if unit_id else [],
        "caption": _pair(row.get("caption_fr"), row.get("caption_en"), row.get("caption")),
        "alt": _pair(row.get("alt_text_fr"), row.get("alt_text_en")),
        "tags": sorted(words(_tag_values(row.get("semantic_tags")))),
        "source": str(row.get("source") or ""),
    }
    for key in ("figure_number", "image_hash", "figure_kind"):
        if row.get(key):
            entry[key] = _text(row[key])
    if page:
        entry["page"] = int(page)
    if is_page_capture(row.get("figure_kind"), row.get("width"), row.get("height")):
        entry["page_capture"] = True
    if row.get("width"):
        entry["width"] = row["width"]
    if attribution:
        entry["attribution"] = attribution[:200]
    return entry


def illustration_entry(
    row: Mapping[str, Any], *, unit_id: str | None, origin: str = "generated"
) -> dict[str, Any]:
    """A catalogue entry for a ``generated_images`` row (its columns, as a mapping)."""
    title = _pair(row.get("title_fr"), row.get("title_en"), row.get("concept"))
    entry: dict[str, Any] = {
        "asset_id": str(row["id"]),
        "kind": KIND_ILLUSTRATION,
        "credit": CREDIT_ILLUSTRATION,
        "origin": origin,
        "units": [unit_id] if unit_id else [],
        "caption": title,
        "alt": _pair(row.get("alt_text_fr"), row.get("alt_text_en"), row.get("concept")),
        "tags": sorted(words(_tag_values(row.get("semantic_tags")), row.get("concept"))),
        "lesson_id": str(row["lesson_id"]) if row.get("lesson_id") else None,
        "module_id": str(row["module_id"]) if row.get("module_id") else None,
    }
    return {k: v for k, v in entry.items() if v is not None}


def entry_words(entry: Mapping[str, Any]) -> frozenset[str]:
    return words(
        entry.get("caption"), entry.get("alt"), entry.get("tags"), entry.get("figure_number")
    )


def _origin_rank(entry: Mapping[str, Any]) -> int:
    origin = str(entry.get("origin"))
    return ORIGINS.index(origin) if origin in ORIGINS else len(ORIGINS)


def _twin_key(entry: Mapping[str, Any]) -> tuple[Any, ...] | None:
    """(page, figure number, caption) of a course figure: what two rows of one picture share."""
    caption = entry.get("caption") or {}
    text = fold(caption.get("en") or caption.get("fr"))
    if entry.get("kind") != KIND_FIGURE or not entry.get("page") or not text:
        return None
    return (entry["page"], fold(entry.get("figure_number")), text)


def assemble(
    candidates: Iterable[dict[str, Any]],
    *,
    course_source: str | None,
    lesson_ids: Iterable[Any] = (),
    module_id: Any = None,
    pins: Iterable[str] = (),
    exclusions: Iterable[str] = (),
    max_entries: int = MAX_ENTRIES,
) -> list[dict[str, Any]]:
    """The catalogue: the candidates that pass every rule, deduped, numbered A1..An.

    A candidate is dropped when it is from another course (a figure whose
    ``source`` is not the course's) or another module (an illustration), is
    excluded by an admin, or is noise. A picture found twice (the same
    ``image_hash`` or id) is one entry that remembers every unit it serves.
    Pinned ones go first, then by where they were found, figures before
    illustrations; the order of the candidates breaks ties.
    """
    pinned = {str(p) for p in pins}
    excluded = {str(e) for e in exclusions}
    lesson_ids = list(lesson_ids)
    seen: dict[str, dict[str, Any]] = {}
    twins: dict[tuple[Any, ...], str] = {}
    for candidate in candidates:
        entry = copy.deepcopy(candidate)
        asset_id = str(entry.get("asset_id") or "")
        if not asset_id or asset_id in excluded:
            continue
        if entry.get("kind") == KIND_ILLUSTRATION:
            if not illustration_in_scope(entry, lesson_ids=lesson_ids, module_id=module_id):
                continue
        elif not in_course(entry.get("source"), course_source) or not usable_kind(
            entry.get("figure_kind"), entry.get("width")
        ):
            continue
        if asset_id in pinned:
            entry["origin"] = "pinned"
            entry["pinned"] = True
        key = str(entry.get("image_hash") or asset_id)
        # The same picture indexed twice has two hashes (a re-index, a translated
        # copy): same page, figure number and caption is the same picture too.
        twin = _twin_key(entry)
        if key not in seen and twin is not None and twin in twins:
            key = twins[twin]
        known = seen.get(key)
        if known is None:
            seen[key] = entry
            if twin is not None:
                twins.setdefault(twin, key)
            continue
        for unit in entry.get("units") or []:
            if unit not in known["units"]:
                known["units"].append(unit)
        # The twin rows serve the same bytes: a page capture is one whichever row says so.
        if entry.get("page_capture"):
            known["page_capture"] = True
        if _origin_rank(entry) < _origin_rank(known):
            known.update({k: entry[k] for k in ("origin", "pinned") if k in entry})
    ordered = sorted(
        enumerate(seen.values()),
        key=lambda item: (_origin_rank(item[1]), item[1]["kind"] != KIND_FIGURE, item[0]),
    )
    entries = [entry for _index, entry in ordered][:max_entries]
    for number, entry in enumerate(entries, start=1):
        entry["id"] = f"A{number}"
        entry.pop("width", None)
    return entries


def ref_of(entry: Mapping[str, Any]) -> dict[str, Any]:
    """An entry in the shape of a lesson's figure ref (what the chapter builder takes)."""
    caption, alt = entry.get("caption") or {}, entry.get("alt") or {}
    ref: dict[str, Any] = {
        "id": entry["asset_id"],
        "caption_en": caption.get("en"),
        "caption_fr": caption.get("fr"),
        "alt_text_en": alt.get("en"),
        "alt_text_fr": alt.get("fr"),
        "asset_ref": entry.get("id"),
        "asset_kind": entry.get("kind"),
    }
    if entry.get("kind") == KIND_ILLUSTRATION:
        ref["generated"] = True
    else:
        # The localised variant can be a smaller render: the original is asked for.
        ref["original"] = True
    if entry.get("page_capture"):
        ref["page_capture"] = True
    for key in ("figure_number", "image_hash", "figure_kind", "attribution"):
        if entry.get(key):
            ref[key] = entry[key]
    return {k: v for k, v in ref.items() if v}


def entry_of_ref(ref: Mapping[str, Any]) -> dict[str, Any]:
    """The inverse of :func:`ref_of`, for a lesson's own refs (no catalogue entry for them)."""
    entry: dict[str, Any] = {
        "id": str(ref.get("asset_ref") or ref.get("id")),
        "asset_id": str(ref.get("id")),
        "kind": KIND_ILLUSTRATION if ref.get("generated") else KIND_FIGURE,
        "caption": _pair(ref.get("caption_fr"), ref.get("caption_en"), ref.get("caption")),
        "alt": _pair(ref.get("alt_text_fr"), ref.get("alt_text_en")),
        "tags": [],
    }
    for key in ("figure_number", "image_hash", "figure_kind", "attribution"):
        if ref.get(key):
            entry[key] = ref[key]
    return entry


def figures_for_unit(
    catalogue: Mapping[str, Any] | None, unit_id: Any, *, limit: int = MAX_FIGURES_PER_UNIT
) -> list[dict[str, Any]]:
    """The refs a lesson's chapter is offered (FIGURE 1 is the first), best first."""
    unit = str(unit_id)
    entries = [
        e
        for e in (catalogue or {}).get("entries") or []
        if not e.get("units") or unit in e["units"]
    ]
    own = [e for e in entries if e.get("units")]
    shared = [e for e in entries if not e.get("units")]
    return [ref_of(e) for e in [*own, *shared][:limit]]


def entry_by_ref(catalogue: Mapping[str, Any] | None, ref: Any) -> dict[str, Any] | None:
    """An entry by its number ("A1") or its asset id."""
    key = str(ref or "").strip()
    return next(
        (
            e
            for e in (catalogue or {}).get("entries") or []
            if key and key in (e.get("id"), e.get("asset_id"))
        ),
        None,
    )


def plan_figures_block(catalogue: Mapping[str, Any] | None) -> str:
    """The catalogue as the plan prompt lists it: ``FIGURE A1 [figure]: caption | légende``."""
    entries = (catalogue or {}).get("entries") or []
    if not entries:
        return ""
    rows = ['FIGURES of the course a prop may stand for (kind "figure", "figure": "A1"):']
    for entry in entries:
        caption = entry.get("caption") or {}
        rows.append(
            f"FIGURE {entry['id']} [{entry['kind']}]: {caption.get('en', '')} | "
            f"{caption.get('fr', '')}"
        )
    return "\n".join(rows)


# -- binding props to the catalogue ----------------------------------------------------


#: A prop is shown with a picture only on strong evidence: this score, in shared
#: content words (a single shared word counts as 2 when it is the prop's head
#: noun, rare in the catalogue and confirmed by the prop's query).
STRONG_SCORE = 2.0

#: Words that name a container, a format, a look or a place, not the thing: two
#: props that share only these have nothing in common. Both languages.
_GENERIC_WORDS = frozenset(
    [
        "diagram",
        "diagramme",
        "schema",
        "scheme",
        "model",
        "modele",
        "card",
        "carte",
        "fiche",
        "paper",
        "papier",
        "sheet",
        "feuille",
        "list",
        "liste",
        "label",
        "etiquette",
        "strip",
        "bande",
        "hand",
        "main",
        "drawn",
        "dessine",
        "dessin",
        "drawing",
        "crumpled",
        "froisse",
        "stained",
        "tache",
        "picture",
        "image",
        "photo",
        "illustration",
        "figure",
        "poster",
        "affiche",
        "board",
        "notebook",
        "cahier",
        "note",
        "simple",
        "small",
        "large",
        "clear",
        "big",
        "little",
        "old",
        "new",
        "tiny",
        "wooden",
        "bois",
        "metal",
        "plastic",
        "concrete",
        "beton",
        "glass",
        "verre",
        "petit",
        "grand",
        "clair",
        "vieux",
        "nouveau",
        "child",
        "children",
        "enfant",
        "kid",
        "student",
        "eleve",
        "outdoor",
        "indoor",
        "exterieur",
        "interieur",
        "africa",
        "afrique",
        "west",
        "ouest",
        "african",
        "africain",
        "courtyard",
        "cour",
        "school",
        "ecole",
        "village",
        "colorful",
        "colourful",
        "couleur",
        "handwritten",
        "manuscrit",
        "paper",
        "thing",
        "chose",
        "example",
        "exemple",
        "type",
        "kind",
        "sort",
        "used",
        "utilise",
        "made",
        "fait",
        "one",
        "two",
        "three",
        "four",
        "five",
        "six",
        "seven",
        "eight",
        "nine",
        "ten",
        "zero",
        "un",
        "deux",
        "trois",
        "quatre",
        "cinq",
        "sept",
        "huit",
        "neuf",
        "dix",
        "first",
        "premier",
        "second",
        "deuxieme",
    ]
)


def _cstem(word: str) -> str:
    """ "tables" ~ "table", "atome" ~ "atom": plural and a final "e" fold away."""
    word = word[:-1] if len(word) > 4 and word.endswith("s") else word
    return word[:-1] if len(word) > 4 and word.endswith("e") else word


_GENERIC = frozenset(_cstem(w) for w in _GENERIC_WORDS)


def name_words(*texts: Any) -> list[str]:
    """The content words naming a thing, in order, once each: no generic or number word."""
    out: list[str] = []
    for text in texts:
        for word in _WORD_RE.findall(fold(text).replace("'", " ")):
            if len(word) < 3 or word.isdigit() or word in _STOPWORDS:
                continue
            stem = _cstem(word)
            if stem not in _GENERIC and word not in _GENERIC_WORDS and stem not in out:
                out.append(stem)
    return out


def _caption_sides(entry: Mapping[str, Any]) -> tuple[bool, list[str], list[str]]:
    """``(one language, fr words, en words)`` of the entry's caption (its title, for an illustration)."""
    caption = entry.get("caption") or {}
    fr, en = _text(caption.get("fr")), _text(caption.get("en"))
    return fr == en, name_words(fr), name_words(en)


def _prop_sides(prop: Mapping[str, Any]) -> tuple[list[str], list[str], list[str]]:
    """``(label fr, label en, query)`` as content words."""
    label = prop.get("label") if isinstance(prop.get("label"), Mapping) else {}
    return (
        name_words(label.get("fr")),
        name_words(label.get("en")),
        name_words(prop.get("query")),
    )


def prop_words(prop: Mapping[str, Any]) -> frozenset[str]:
    fr, en, query = _prop_sides(prop)
    return frozenset([*fr, *en, *query])


def match_prop(
    prop: Mapping[str, Any], entry: Mapping[str, Any], catalogue: Sequence[Mapping[str, Any]]
) -> dict[str, Any] | None:
    """How strongly ``entry``'s caption names ``prop``, or ``None`` when it does not.

    Only the prop's own name (label fr and en, query) against the caption or
    title is compared, never alt text, tags or surrounding text, and generic
    container, format, look and place words never count. Each language is
    matched against the same language of the caption; a caption written in one
    language only is matched against all the prop's words. Strong evidence is
    at least 2 shared content words, or 1 that is the head (first or last
    content word) of the prop's label, appears in at most one caption of the
    catalogue, and is confirmed by the prop's query (a shared 5-letter start).
    """
    label_fr, label_en, query = _prop_sides(prop)
    one_language, cap_fr, cap_en = _caption_sides(entry)
    if one_language:
        sides = [([*label_fr, *label_en, *query], cap_fr)]
    else:
        sides = [([*label_fr], cap_fr), ([*label_en, *query], cap_en)]
    shared: list[str] = []
    for prop_side, cap_side in sides:
        found = [w for w in dict.fromkeys(prop_side) if w in cap_side]
        if len(found) > len(shared):
            shared = found
    if not shared:
        return None
    if len(shared) >= 2:
        return {"score": float(len(shared)), "words": shared}
    word = shared[0]
    heads = {w for lab in (label_fr, label_en) if lab for w in (lab[0], lab[-1])}
    seen_in = sum(1 for e in catalogue if word in {*_caption_sides(e)[1], *_caption_sides(e)[2]})
    confirmed = (
        any(word[:5] == q[:5] and min(len(word), len(q)) >= 5 for q in query) or word in query
    )
    if word in heads and seen_in <= 1 and confirmed:
        return {"score": STRONG_SCORE, "words": shared}
    return None


def bind_props(
    props: Iterable[Mapping[str, Any]],
    entries: Sequence[Mapping[str, Any]],
    *,
    taken: Iterable[str] = (),
    min_score: float = STRONG_SCORE,
    evidence: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Each educational prop without a picture → the entry that shows it, on strong evidence only.

    Decor props (``educational`` false) never bind. A picture serves one prop
    and a prop takes one picture: when two props tie for a picture, or two
    pictures tie for a prop, neither binds (a wrong picture shown as evidence
    is worse than none). ``evidence`` (optional) receives, per bound prop id,
    ``{"score", "words", "prop", "caption"}`` for the report.
    """
    eligible = [
        p
        for p in props
        if p.get("educational") and not p.get("figure") and p.get("kind") in ("real", "figure")
    ]
    # The same object declared twice (a chapter's ``poster`` and another's
    # ``poster_2``: same name in both languages) is one prop: it competes once
    # and every copy shows the picture. Otherwise the copies tie and none binds.
    twins: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for prop in eligible:
        twins.setdefault(_same_object_key(prop), []).append(prop)
    candidates = [group[0] for group in twins.values()]
    copies = {str(group[0]["id"]): [str(p["id"]) for p in group[1:]] for group in twins.values()}
    used = {str(t) for t in taken}
    pool = [e for e in entries if str(e.get("asset_id")) not in used]
    pairs: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in pool:
        for prop in candidates:
            hit = match_prop(prop, entry, entries)
            if hit is not None and hit["score"] >= min_score:
                pairs[(str(prop["id"]), str(entry["asset_id"]))] = hit

    by_id = {str(e["asset_id"]): e for e in pool}

    def rank(key: tuple[str, str]) -> tuple[float, int]:
        # Score first; on a tie a cropped figure, then an illustration, then a page
        # capture (the PDF's page rendered whole, its text in the picture).
        entry = by_id[key[1]]
        kind = (
            2 if entry.get("page_capture") else 1 if entry.get("kind") == KIND_ILLUSTRATION else 0
        )
        return pairs[key]["score"], -kind

    def best_unique(
        keys: list[tuple[str, str]], *, by_kind: bool = False
    ) -> tuple[str, str] | None:
        if not keys:
            return None
        top = max(rank(k) if by_kind else (pairs[k]["score"], 0) for k in keys)
        leaders = [k for k in keys if (rank(k) if by_kind else (pairs[k]["score"], 0)) == top]
        return leaders[0] if len(leaders) == 1 else None

    # One prop per picture, then one picture per prop; a tie on either side binds nothing.
    by_entry = {}
    for entry in pool:
        eid = str(entry["asset_id"])
        pick = best_unique([k for k in pairs if k[1] == eid])
        if pick is not None:
            by_entry[eid] = pick
    bound: dict[str, dict[str, Any]] = {}
    for prop in candidates:
        pid = str(prop["id"])
        pick = best_unique([k for k in by_entry.values() if k[0] == pid], by_kind=True)
        if pick is not None:
            entry = by_id[pick[1]]
            bound[pid] = dict(entry)
            if evidence is not None:
                label = prop.get("label") if isinstance(prop.get("label"), Mapping) else {}
                evidence[pid] = {
                    **pairs[pick],
                    "prop": _text(label.get("fr") or label.get("en") or pid),
                    "caption": _text((entry.get("caption") or {}).get("fr")),
                }
            for copy in copies.get(pid, ()):
                bound[copy] = dict(entry)
                if evidence is not None:
                    evidence[copy] = dict(evidence[pid])
    return bound


def _same_object_key(prop: Mapping[str, Any]) -> tuple[str, str]:
    """Two props with this key are one object: the same name in both languages.

    A prop with no name at all is only ever itself.
    """
    label = prop.get("label") if isinstance(prop.get("label"), Mapping) else {}
    fr = " ".join(_text(label.get("fr")).casefold().split())
    en = " ".join(_text(label.get("en")).casefold().split())
    if not fr and not en:
        return (f"#{prop.get('id')}", "")
    return (fr, en)


# -- re-binding a story document (no model, no database) ----------------------------------


class RebindResult:
    """What :func:`rebind_document` did."""

    def __init__(self) -> None:
        self.bound: dict[str, str] = {}  # prop id → asset id
        self.inserted: list[dict[str, str]] = []
        self.moved: list[dict[str, Any]] = []
        #: prop id → ``{"score", "words", "prop", "caption"}`` for the props bound by words.
        self.evidence: dict[str, dict[str, Any]] = {}

    @property
    def changed(self) -> bool:
        return bool(self.bound or self.inserted or self.moved)


def _shows(chapter: Mapping[str, Any], pid: str) -> list[tuple[int, int]]:
    return [
        (s, i)
        for s, scene in enumerate(chapter.get("scenes") or [])
        for i, step in enumerate(scene.get("steps") or [])
        if step.get("type") == "show"
        and step.get("visual") == "prop"
        and (step.get("params") or {}).get("prop") == pid
    ]


def _named(chapter: Mapping[str, Any], pid: str, *, looking: bool) -> tuple[int, int] | None:
    """The first line of the chapter that names ``pid`` (and, if ``looking``, says "look")."""
    for s, scene in enumerate(chapter.get("scenes") or []):
        for i, step in enumerate(scene.get("steps") or []):
            if step.get("type") not in LINE_TYPES or pid not in (step.get("props") or []):
                continue
            if str(step.get("id", "")).startswith("situation-"):
                continue
            if not looking or any(
                DEIXIS_RE.search(str(step.get(lang) or "")) for lang in ("en", "fr")
            ):
                return s, i
    return None


def _room_before(scene: Mapping[str, Any], index: int) -> bool:
    """A close-up may go at ``index``: after the scene's first step, not after a question."""
    steps = scene["steps"]
    if index < 1 or index > len(steps):
        return False
    if _asks_or_sets_up(steps[index - 1]) or (
        index < len(steps) and _asks_or_sets_up(steps[index])
    ):
        return False
    return sum(1 for s in steps if s.get("visual") == "prop") < MAX_CLOSEUPS_PER_SCENE


def _show_step(pid: str) -> dict[str, Any]:
    return {"type": "show", "visual": "prop", "params": {"prop": pid}}


def _place_closeup(doc: dict[str, Any], pid: str, result: RebindResult) -> None:
    """Show ``pid`` close up before the line that says "look" at it (else after its first mention)."""
    chapters = [c for c in doc.get("chapters") or [] if isinstance(c, dict)]
    shown = next((c for c in chapters if _shows(c, pid)), None)
    if shown is not None:
        # Already shown: only moved up when it sits after the "look" line of its scene.
        look = _named(shown, pid, looking=True)
        for s, i in _shows(shown, pid)[:1]:
            if look is None or look[0] != s or look[1] >= i:
                continue
            scene = shown["scenes"][s]
            step = scene["steps"].pop(i)
            if not _room_before(scene, look[1]):
                scene["steps"].insert(i, step)
                continue
            scene["steps"].insert(look[1], step)
            result.moved.append(
                {
                    "chapter": str(shown.get("id")),
                    "scene": str(scene.get("id")),
                    "prop": pid,
                    "from": i,
                    "to": look[1],
                }
            )
        return
    for chapter in chapters:
        scenes = chapter.get("scenes") or []
        look = _named(chapter, pid, looking=True)
        if look is not None and _room_before(scenes[look[0]], look[1]):
            scenes[look[0]]["steps"].insert(look[1], _show_step(pid))
            result.inserted.append(
                {
                    "chapter": str(chapter.get("id")),
                    "scene": str(scenes[look[0]].get("id")),
                    "prop": pid,
                }
            )
            return
        first = _named(chapter, pid, looking=False)
        if first is None:
            continue
        before = [len(s["steps"]) for s in scenes]
        if insert_closeup(scenes, pid, {pid: first}, _show_step(pid)):
            at = next(
                (n for n, scene in enumerate(scenes) if len(scene["steps"]) != before[n]),
                first[0],
            )
            result.inserted.append(
                {
                    "chapter": str(chapter.get("id")),
                    "scene": str(scenes[at].get("id")),
                    "prop": pid,
                }
            )
            return


def _revision(before: Any, result: RebindResult) -> str:
    raw = json.dumps(
        [before, result.bound, result.inserted, result.moved], sort_keys=True, ensure_ascii=False
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def rebind_document(
    doc: dict[str, Any],
    entries: Sequence[Mapping[str, Any]],
    *,
    binding: Mapping[str, str] | None = None,
    min_score: float = STRONG_SCORE,
) -> RebindResult:
    """Bind a stored module story's props to the catalogue, in place. No model call.

    ``binding`` (prop id → asset id) is the persisted one and wins; props it
    does not name are bound by :func:`bind_props`. A bound prop becomes a
    ``figure`` prop carrying its picture (``prop.figure``) and gets its
    close-up before the line that says "look" at it (an existing close-up
    after that line is moved up). Idempotent: a story already bound is left
    as it is (``changed`` False). The previous kind of each prop, the close-ups
    added and those moved are recorded in ``module_story.assets``
    (:func:`revert_document`), and ``module_story.revision`` moves, so an
    offline copy is refreshed.
    """
    result = RebindResult()
    props = [p for p in doc.get("props") or [] if isinstance(p, dict) and p.get("id")]
    by_asset = {str(e.get("asset_id")): e for e in entries}
    wanted: dict[str, dict[str, Any]] = {}
    already = {
        str(
            (p.get("figure") or {}).get("source_image_id")
            or (p.get("figure") or {}).get("generated_image_id")
        )
        for p in props
        if p.get("figure")
    }
    for pid, asset_id in (binding or {}).items():
        entry = by_asset.get(str(asset_id))
        prop = next((p for p in props if p["id"] == pid), None)
        if entry is not None and prop is not None and not prop.get("figure"):
            wanted[pid] = dict(entry)
    rest = [p for p in props if p["id"] not in wanted]
    taken = {*already, *(str(e["asset_id"]) for e in wanted.values())}
    wanted.update(
        bind_props(rest, entries, taken=taken, min_score=min_score, evidence=result.evidence)
    )

    module_story = doc.setdefault("module_story", {})
    record = module_story.setdefault("assets", {"version": CATALOGUE_VERSION, "bound": {}})
    for pid, entry in wanted.items():
        prop = next(p for p in props if p["id"] == pid)
        record["bound"][pid] = {"asset_id": entry["asset_id"], "was": prop.get("kind")}
        prop["kind"] = KIND_FIGURE
        prop["educational"] = True
        prop["figure"] = figure_of(ref_of(entry))
        result.bound[pid] = str(entry["asset_id"])
    # Every figure prop (bound now or by generation) is shown close up.
    for prop in props:
        if prop.get("kind") == KIND_FIGURE and prop.get("figure"):
            _place_closeup(doc, str(prop["id"]), result)
    if not result.changed:
        if not record["bound"] and "revision_before" not in record:
            module_story.pop("assets", None)
        return result
    record.setdefault("revision_before", module_story.get("revision"))
    record["inserted"] = [*record.get("inserted", []), *result.inserted]
    record["moved"] = [*record.get("moved", []), *result.moved]
    module_story["revision"] = _revision(module_story.get("revision"), result)
    return result


def revert_document(doc: dict[str, Any]) -> bool:
    """Undo :func:`rebind_document`, in place: the props' kinds, the close-ups, the revision."""
    module_story = doc.get("module_story") or {}
    record = module_story.get("assets")
    if not isinstance(record, dict):
        return False
    chapters = {str(c.get("id")): c for c in doc.get("chapters") or [] if isinstance(c, dict)}

    def scene_of(item: Mapping[str, Any]) -> dict[str, Any] | None:
        chapter = chapters.get(str(item.get("chapter"))) or {}
        return next(
            (s for s in chapter.get("scenes") or [] if str(s.get("id")) == str(item.get("scene"))),
            None,
        )

    for item in reversed(record.get("moved") or []):
        scene = scene_of(item)
        if scene is None:
            continue
        positions = [
            n
            for n, st in enumerate(scene["steps"])
            if st.get("visual") == "prop" and (st.get("params") or {}).get("prop") == item["prop"]
        ]
        if positions:
            step = scene["steps"].pop(positions[0])
            scene["steps"].insert(int(item["from"]), step)
    for item in record.get("inserted") or []:
        scene = scene_of(item)
        if scene is None:
            continue
        scene["steps"] = [
            st
            for st in scene["steps"]
            if not (
                st.get("visual") == "prop" and (st.get("params") or {}).get("prop") == item["prop"]
            )
        ]
    for prop in doc.get("props") or []:
        was = (record.get("bound") or {}).get(prop.get("id"))
        if was is not None:
            prop.pop("figure", None)
            if was.get("was"):
                prop["kind"] = was["was"]
    if record.get("revision_before") is not None:
        module_story["revision"] = record["revision_before"]
    module_story.pop("assets", None)
    return True


# -- the gap report -----------------------------------------------------------------------


def gap_report(
    units: Sequence[Mapping[str, Any]], entries: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Each lesson idea no catalogue entry of its chapter talks about: ``evidence: none``.

    ``units``: ``{"unit_id", "unit_number", "ideas": [str]}``.
    """
    gaps: list[dict[str, Any]] = []
    for unit in units:
        own = [e for e in entries if not e.get("units") or str(unit["unit_id"]) in e["units"]]
        known = frozenset().union(*(entry_words(e) for e in own)) if own else frozenset()
        for number, idea in enumerate(unit.get("ideas") or [], start=1):
            if not (words(idea) & known):
                gaps.append(
                    {
                        "unit": unit["unit_number"],
                        "idea": number,
                        "text": _text(idea)[:140],
                        "evidence": "none",
                    }
                )
    return gaps


# -- the database half --------------------------------------------------------------------

_SOURCE_COLUMNS = (
    "id",
    "source",
    "image_hash",
    "figure_kind",
    "width",
    "height",
    "storage_key",
    "figure_number",
    "caption",
    "caption_fr",
    "caption_en",
    "alt_text_fr",
    "alt_text_en",
    "attribution",
    "page_number",
    "semantic_tags",
)


async def _source_rows(
    session: AsyncSession, ids: Sequence[uuid.UUID]
) -> dict[str, dict[str, Any]]:
    if not ids:
        return {}
    from app.domain.models.course_resource import CourseResource  # noqa: PLC0415
    from app.domain.models.source_image import SourceImage  # noqa: PLC0415

    columns = [getattr(SourceImage, name) for name in _SOURCE_COLUMNS]
    rows = (
        await session.execute(
            select(*columns, CourseResource.filename.label("resource_title"))
            .select_from(SourceImage)
            .outerjoin(CourseResource, CourseResource.id == SourceImage.course_resource_id)
            .where(SourceImage.id.in_(list(ids)))
        )
    ).all()
    return {str(r.id): dict(r._mapping) for r in rows}


def _uuid(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


async def build_catalogue(
    session: AsyncSession,
    *,
    module_id: uuid.UUID,
    course_source: str | None,
    course_id: uuid.UUID | None,
    units: Sequence[Mapping[str, Any]],
    storage: Any,
    retriever: Any | None,
    previous: Mapping[str, Any] | None = None,
    searcher: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Build a module's catalogue (and its gap report); the caller persists it.

    ``units``: one per lesson, ``{"unit_id", "unit_number", "title": {en, fr},
    "lesson_id", "content"}`` (``content`` is the lesson's JSON). ``storage``
    answers ``object_exists(key)``. ``retriever`` (a ``SemanticRetriever``) is
    optional: without it only steps 1, 2 and 4 run. Admin pins and
    exclusions of ``previous`` are carried over.
    """
    from app.ai.prompts.story_from_lesson import build_fact_sheet  # noqa: PLC0415

    previous = previous or {}
    pins, exclusions = list(previous.get("pins") or []), list(previous.get("exclusions") or [])
    candidates: list[dict[str, Any]] = []
    wanted: list[tuple[uuid.UUID, str, str | None]] = []  # (image id, origin, unit id)

    # 1. the figures the lessons cite
    for unit in units:
        refs = (unit.get("content") or {}).get("source_image_refs") or []
        for ref in refs:
            image_id = _uuid(ref.get("id")) if isinstance(ref, dict) else None
            if image_id is not None:
                wanted.append((image_id, "lesson_ref", str(unit["unit_id"])))
    cited = {w[0] for w in wanted}

    # 2. the figures linked to the same text chunks
    if retriever is not None and cited:
        try:
            from app.domain.models.source_image import SourceImageChunk  # noqa: PLC0415

            chunk_ids = list(
                (
                    await session.execute(
                        select(SourceImageChunk.document_chunk_id).where(
                            SourceImageChunk.source_image_id.in_(list(cited))
                        )
                    )
                ).scalars()
            )
            linked = await retriever.get_linked_images(
                chunk_ids, session, max_per_chunk=3, max_total=8
            )
            for metas in linked.values():
                for meta in metas:
                    image_id = _uuid(meta.get("id"))
                    if image_id is not None and image_id not in cited:
                        wanted.append((image_id, "linked", None))
        except Exception as exc:
            logger.warning("Story catalogue: linked figures unavailable", error=str(exc)[:200])

    # 3. the course's other figures, by embedding, kept when a word is shared
    searches: list[tuple[str | None, frozenset[str], list[Mapping[str, Any]]]] = []
    if retriever is not None and course_source:
        search = searcher or retriever.search_source_images
        for unit in units:
            sheet = build_fact_sheet(unit.get("content"))
            title = unit.get("title") or {}
            query = " ".join(
                [str(title.get("en") or ""), str(title.get("fr") or ""), *sheet.ideas[:2]]
            ).strip()
            idea_words = words(query, sheet.key_facts[:3])
            try:
                found = await search(
                    query,
                    top_k=SEARCH_TOP_K,
                    source=course_source,
                    min_similarity=MIN_SIMILARITY,
                    session=session,
                    exclude_noise=True,
                )
            except Exception as exc:
                logger.warning("Story catalogue: figure search failed", error=str(exc)[:200])
                continue
            searches.append((str(unit["unit_id"]), idea_words, list(found)))
            for meta in found:
                image_id = _uuid(meta.get("id"))
                if image_id is not None:
                    wanted.append((image_id, "semantic", str(unit["unit_id"])))

    rows = await _source_rows(session, [w[0] for w in wanted])
    idea_words_of = {unit_id: idea for unit_id, idea, _found in searches}
    checks, alive = 0, {}
    for image_id, origin, unit_id in wanted:
        row = rows.get(str(image_id))
        if row is None or not row.get("storage_key"):
            continue
        entry = figure_entry(row, origin=origin, unit_id=unit_id)
        entry["width"] = row.get("width")
        if (
            origin == "semantic"
            and len(entry_words(entry) & idea_words_of.get(unit_id or "", frozenset()))
            < MIN_SEARCH_OVERLAP
        ):
            continue
        # Cheap rules first, so a binary is only checked for a picture that may stay.
        if not in_course(row.get("source"), course_source) or not usable_kind(
            row.get("figure_kind"), row.get("width")
        ):
            continue
        key = row["storage_key"]
        if key not in alive:
            if checks >= MAX_CHECKS:
                continue
            checks += 1
            alive[key] = False
            for _attempt in range(CHECK_TRIES):
                if await storage.object_exists(key):
                    alive[key] = True
                    break
        if not alive[key]:
            logger.warning("Story catalogue: figure binary missing", source_image_id=str(image_id))
            continue
        candidates.append(entry)

    # 4. the lesson illustrations
    candidates.extend(await _illustration_candidates(session, module_id, units))

    entries = assemble(
        candidates,
        course_source=course_source,
        lesson_ids=[u.get("lesson_id") for u in units if u.get("lesson_id")],
        module_id=module_id,
        pins=pins,
        exclusions=exclusions,
    )
    gaps = gap_report(
        [
            {
                "unit_id": str(u["unit_id"]),
                "unit_number": u["unit_number"],
                "ideas": list(build_fact_sheet(u.get("content")).ideas),
            }
            for u in units
        ],
        entries,
    )
    return {
        "version": CATALOGUE_VERSION,
        "course_id": str(course_id) if course_id else None,
        "source": course_source,
        "entries": entries,
        "gaps": gaps,
        "pins": pins,
        "exclusions": exclusions,
        "binding": dict(previous.get("binding") or {}),
    }


async def _illustration_candidates(
    session: AsyncSession, module_id: uuid.UUID, units: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Ready illustrations of the module's lessons first, then of the module itself."""
    from sqlalchemy import or_  # noqa: PLC0415

    from app.domain.models.generated_image import GeneratedImage  # noqa: PLC0415

    lesson_ids = [u["lesson_id"] for u in units if u.get("lesson_id")]
    unit_of = {str(u["lesson_id"]): str(u["unit_id"]) for u in units if u.get("lesson_id")}
    clauses = [GeneratedImage.module_id == module_id]
    if lesson_ids:
        clauses.append(GeneratedImage.lesson_id.in_(lesson_ids))
    rows = (
        await session.execute(
            select(
                GeneratedImage.id,
                GeneratedImage.lesson_id,
                GeneratedImage.module_id,
                GeneratedImage.concept,
                GeneratedImage.title_fr,
                GeneratedImage.title_en,
                GeneratedImage.alt_text_fr,
                GeneratedImage.alt_text_en,
                GeneratedImage.semantic_tags,
                GeneratedImage.image_data.isnot(None).label("has_data"),
                GeneratedImage.image_url,
            )
            .where(GeneratedImage.status == "ready", or_(*clauses))
            .order_by(GeneratedImage.created_at, GeneratedImage.id)
        )
    ).all()
    out: list[dict[str, Any]] = []
    for row in rows:
        data = dict(row._mapping)
        if not (data.get("has_data") or data.get("image_url")):
            continue
        entry = illustration_entry(data, unit_id=unit_of.get(str(data.get("lesson_id"))))
        out.append(entry)
    # By lesson first, then the module's own.
    out.sort(key=lambda e: not e.get("units"))
    return out[:MAX_ILLUSTRATIONS]


async def load_catalogue(session: AsyncSession, module_id: uuid.UUID) -> dict[str, Any] | None:
    from app.domain.models.story_asset import StoryAssetCatalogue  # noqa: PLC0415

    row = await session.get(StoryAssetCatalogue, module_id)
    return dict(row.content) if row is not None and isinstance(row.content, dict) else None


async def save_catalogue(
    session: AsyncSession, module_id: uuid.UUID, content: Mapping[str, Any]
) -> None:
    """Upsert a module's catalogue. Does not commit."""
    from app.domain.models.story_asset import StoryAssetCatalogue  # noqa: PLC0415

    statement = pg_insert(StoryAssetCatalogue).values(
        module_id=module_id, version=CATALOGUE_VERSION, content=dict(content)
    )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[StoryAssetCatalogue.module_id],
            set_={"version": CATALOGUE_VERSION, "content": dict(content)},
        )
    )
