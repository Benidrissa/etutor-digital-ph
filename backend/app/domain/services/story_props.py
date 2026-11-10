"""The props of a chapter's screenplay: the things the cartoon shows (#2681, phase 1).

A line that names a concrete thing — a snail, the néré tree, a pebble — makes
that thing appear on stage. The model declares each prop once (``props``),
lists those present in a scene (``scene.props``) and points a ``say``,
``narrate`` or ``concept`` line at what it names (``step.props``); a close-up
(``{"type": "show", "prop": id}``) shows an educational prop "for real".

This module checks and settles all of it, deterministically, inside the
chapter builder (:mod:`story_repair`). Every fix is recorded with
:func:`story_repair.builder_issue` under a code of
:data:`story_repair.PROP_CODES`; a prop issue alone never costs a repair
call (it is reported as a warning of the build, see
:func:`story_repair.with_generator_issues`).

No picture is resolved here: the document only ever stores a course figure
the builder resolved (``prop.figure``). Photos and stickers are served next
to the story by a later phase (#2683, #2684).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from app.api.v1.schemas.story_course import (
    MAX_CLOSEUPS_PER_SCENE,
    MAX_NEW_PROPS_PER_CHAPTER,
    MAX_PROPS_PER_LINE,
    MAX_PROPS_PER_MODULE,
    MAX_PROPS_PER_SCENE,
    PROP_KINDS,
    PROP_LABEL_LIMIT,
    PROP_PLACEMENTS,
    PROP_QUERY_LIMIT,
    PROP_SIZES,
)

#: The steps a prop reference may sit on.
LINE_TYPES = ("say", "narrate", "concept")

_PROP_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,39}$")

#: A query naming a person: the picture must never show one.
PEOPLE_WORDS = frozenset(
    {
        "man",
        "men",
        "woman",
        "women",
        "child",
        "children",
        "boy",
        "boys",
        "girl",
        "girls",
        "people",
        "person",
        "persons",
        "doctor",
        "teacher",
        "femme",
        "femmes",
        "homme",
        "hommes",
        "enfant",
        "enfants",
        "fille",
        "filles",
        "garcon",
        "garcons",
        "gens",
        "personne",
        "personnes",
        "medecin",
    }
)

_ARTICLES = (
    "de la ",
    "de l'",
    "le ",
    "la ",
    "les ",
    "l'",
    "l’",
    "un ",
    "une ",
    "des ",
    "du ",
    "the ",
    "a ",
    "an ",
)
#: A French noun's complement ("le panier de Grand-mère" → "panier").
_FR_COMPLEMENT_RE = re.compile(r"\s+(?:de|d'|d’|du|des|à|au|aux)\b.*$")
#: French elision, opened so "l'arbre" and "d'oignon" match word by word.
_ELISION_RE = re.compile(r"\b([ldjmnst]|qu)'")
#: What follows a French head that has a complement of its own ("graine de haricot").
_FR_OWN_COMPLEMENT = r"(?!\s+(?:de|du|des|d)\s)"


def fold(text: Any) -> str:
    """Lower case, no accents, one space: what the matcher compares."""
    value = unicodedata.normalize("NFKD", str(text or "")).casefold()
    value = "".join(c for c in value if not unicodedata.combining(c))
    value = value.replace("’", "'")
    return " ".join(value.split())


def _strip_article(text: str) -> str:
    value = fold(text)
    changed = True
    while changed:
        changed = False
        for article in _ARTICLES:
            if value.startswith(article):
                value = value[len(article) :].strip()
                changed = True
    return value


def head_phrase(label: str, lang: str) -> str:
    """The words of a label a line must name: no article, no complement, no possessive.

    ``"Grandma's basket"`` → ``"basket"``; ``"le panier de Grand-mère"`` →
    ``"panier"``; ``"the mimosa leaf"`` → ``"mimosa leaf"`` (matched whole).
    """
    value = _strip_article(label)
    if lang == "en" and "'s " in value:
        value = value.split("'s ", 1)[1]
    if lang == "fr":
        value = _FR_COMPLEMENT_RE.sub("", value)
    value = re.sub(r"[^\w\s'-]", " ", value)
    return " ".join(value.split())


def full_phrase(label: str) -> str:
    """The whole label a line may name: no article, its complement kept, elision opened.

    ``"la graine de néré"`` → ``"graine de nere"``; ``"des cellules d'oignon"``
    → ``"cellules d oignon"``.
    """
    value = _ELISION_RE.sub(r"\1 ", _strip_article(label))
    value = re.sub(r"[^\w\s'-]", " ", value)
    return " ".join(value.split())


def _phrase_re(phrase: str, *, own_complement: bool = False) -> re.Pattern[str] | None:
    words = [w for w in phrase.split() if w]
    if not words or len("".join(words)) < 3:
        return None
    # Each word may take a plural s or x ("cailloux", "leaves" is not handled);
    # a French "de" is any of its forms, with or without an article ("les
    # graines du néré", "les cellules de l'oignon", "le panier de la grand-mère").
    body = r"\s+".join(
        r"(?:de|du|des|d)(?:\s+(?:la|le|les|l))?"
        if w in ("de", "du", "des", "d")
        else re.escape(w) + r"(?:s|x|es)?"
        for w in words
    )
    tail = _FR_OWN_COMPLEMENT if own_complement else ""
    return re.compile(rf"(?<![\w]){body}(?![\w]){tail}")


def names_prop(
    text: Any,
    prop: dict[str, Any],
    lang: str,
    *,
    shared_heads: frozenset[str] | set[str] = frozenset(),
    names: frozenset[str] | set[str] = frozenset(),
) -> bool:
    """Whether ``text`` (in ``lang``) names the prop.

    By its whole label first ("graine de néré", French elision opened), then
    by the label's head alone ("graine") — only when no other prop of the
    chapter has that head (``shared_heads``), and in French only when the
    head carries no complement of its own in the line ("la graine de haricot"
    names another thing). A phrase that is a cast member's name (``names``,
    folded) never matches: "Pierre, viens !" is not "une pierre".
    """
    label = (prop.get("label") or {}).get(lang)
    if not isinstance(label, str):
        return False
    haystack = _ELISION_RE.sub(r"\1 ", fold(text))
    full = full_phrase(label)
    if full and full not in names:
        pattern = _phrase_re(full)
        if pattern is not None and pattern.search(haystack):
            return True
    head = head_phrase(label, lang)
    if not head or head == full or head in shared_heads or head in names:
        return False
    pattern = _phrase_re(head, own_complement=lang == "fr")
    return bool(pattern is not None and pattern.search(haystack))


def default_size(at: str) -> str:
    return {"held": "s", "sky": "s", "ground": "m", "table": "m", "back": "l"}.get(at, "m")


def is_one_emoji(value: Any) -> bool:
    """One pictographic grapheme (with its modifiers or joiners), nothing else."""
    if not isinstance(value, str) or not value or len(value) > 12:
        return False
    bases = 0
    joined = "‍" in value
    for char in value:
        code = ord(char)
        if char in "‍️︎⃣" or 0x1F3FB <= code <= 0x1F3FF:
            continue
        if 0xE0020 <= code <= 0xE007F:  # tag sequences (flags)
            continue
        category = unicodedata.category(char)
        if category != "So" and not (0x1F1E6 <= code <= 0x1F1FF):
            return False
        bases += 1
    if bases == 0:
        return False
    if bases == 2 and all(0x1F1E6 <= ord(c) <= 0x1F1FF for c in value):
        return True  # a flag: two regional indicators
    return bases == 1 or joined


def prop_slug(value: Any) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", fold(value)).strip("_")[:40].strip("_")
    if slug and not slug[0].isalpha():
        slug = f"p_{slug}"[:40]
    return slug if _PROP_ID_RE.match(slug) else ""


def query_key(prop: dict[str, Any]) -> tuple[str, str]:
    """What makes two declarations the same thing: kind and normalised query."""
    query = _strip_article(prop.get("query") or "")
    query = " ".join(w[:-1] if len(w) > 3 and w.endswith("s") else w for w in query.split())
    return str(prop.get("kind")), query


def _str(value: Any) -> str:
    if value is None or isinstance(value, dict | list):
        return ""
    return " ".join(str(value).split())


def _wordset(words: str) -> frozenset[str]:
    """The words of a space-separated list."""
    return frozenset(words.split())


#: Words a long label is cut before: where its description starts — a
#: relative, a preposition of place or purpose, an agent, a participle
#: ("dessiné par l'ami", "drawn by", "holding", "devant").
_LABEL_BREAKS = _wordset(
    # French: relatives and prepositions.
    "avec qui que dont pour sur sous dans contre entre devant derriere pres par"
    " plein pleine pleins pleines contenant"
    # French: participles that describe the thing.
    " dessine dessinee dessines dessinees fait faite faits faites peint peinte"
    " peints peintes ecrit ecrite ecrits ecrites rempli remplie remplis remplies"
    " vu vue vus vues pose posee poses posees trouve trouvee trouves trouvees"
    " offert offerte donne donnee achete achetee ramasse ramassee"
    # English: relatives and prepositions.
    " with that which who whose for on under inside near from full containing"
    " holding beside behind next by"
    # English: participles that describe the thing.
    " drawn made painted written filled seen found picked bought given kept"
    " lying sitting standing hanging"
)
#: Words a shortened label never ends on.
_LABEL_TAILS = _wordset(
    "de du des d l la le les un une au aux à a avec et ou en par sur sous dans pour"
    " contenant qui que of the an and or with in on at to for by from into near"
    " under holding"
)


def _label_word(word: str) -> str:
    """A label word as the cut rules read it: folded, without its punctuation."""
    return fold(word).strip('.,;:!?()«»"')


def _elided(word: str) -> bool:
    """A first word that holds its article: "l'escargot", "d'eau"."""
    return "'" in fold(word)[:3]


def _is_tail(word: str) -> bool:
    """A word a label never ends on; a capital letter is never one ("la vitamine A")."""
    if word[:1].isupper():
        return False
    return fold(word).strip(".,;:!?()«»\"'") in _LABEL_TAILS


def _drop_tail(words: list[str]) -> list[str]:
    while len(words) > 1 and _is_tail(words[-1]):
        words = words[:-1]
    return words


def short_label(value: Any, limit: int = PROP_LABEL_LIMIT) -> str:
    """A prop label of at most ``limit`` characters, never cut mid-phrase, never with "…".

    A label is what a name tag shows: a short noun with its article. One that
    fits is kept whole (only a dangling small word goes). A longer one is cut
    at the first word where its description starts, when what comes before
    fits ("le diagramme des niveaux du vivant dessiné par l'ami" → "le
    diagramme des niveaux du vivant"; "the closed jar with something grey
    inside" → "the closed jar"); else it keeps the longest run of whole words
    that fits and does not end on an article or a preposition. A label the
    model cut itself ("le bocal fermé avec quelque chose de…") is cut where
    its description starts, else kept whole without its "…".
    """
    text = _str(value)
    clipped = text.endswith(("…", "..."))
    text = text.rstrip(".…").rstrip(" ,;:-–—").strip()
    words = text.split(" ") if text else []
    if not words:
        return ""
    if len(text) <= limit and not clipped:
        return " ".join(_drop_tail(words))
    first = 1 if _elided(words[0]) else 2
    for n in range(first, len(words)):
        if _label_word(words[n]) in _LABEL_BREAKS:
            head = " ".join(_drop_tail(words[:n])).rstrip(" ,;:-–—")
            if len(head) <= limit:
                return head
            break
    if len(text) <= limit:
        return " ".join(_drop_tail(words))
    for n in range(len(words) - 1, 0, -1):
        head = " ".join(words[:n]).rstrip(" ,;:-–—")
        if len(head) <= limit and not _is_tail(words[n - 1]):
            return head
    return text[:limit].rstrip(" ,;:-–—")


def _cut(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit]
    space = cut.rfind(" ")
    return (cut[:space] if space > limit // 2 else cut).rstrip(" ,;:-")


class PropBook:
    """The props a chapter may use, and every reference made to them.

    ``known`` are the props already in the story (the episode plan's, then
    those earlier chapters declared): the model reuses their ids and never
    declares them again. ``figures`` are the lesson's figures the prompt
    listed (FIGURE 1 is ``figures[0]``).
    """

    def __init__(
        self,
        raw_props: Any,
        *,
        known: list[dict[str, Any]],
        figures: list[dict[str, Any]],
        cast_ids: list[str],
        issue: Any,
        cast_names: list[str] | None = None,
    ) -> None:
        self.issue = issue
        self.figures = figures
        self.cast_ids = set(cast_ids)
        #: The cast's ids and names, folded: never taken for a prop's name.
        self.cast_names = frozenset(fold(n) for n in [*cast_ids, *(cast_names or [])] if n)
        #: Every usable prop by id; ``origin`` says where a known one came from.
        self.props: dict[str, dict[str, Any]] = {}
        self.known_ids: set[str] = set()
        #: A declared id (or a duplicate's) → the id it stands for.
        self.alias: dict[str, str] = {}
        self.dropped: set[str] = set()
        self.closeups: list[dict[str, Any]] = []
        for prop in known:
            if isinstance(prop, dict) and prop.get("id"):
                clean = {k: v for k, v in prop.items() if k != "origin"}
                self.props[str(prop["id"])] = clean
                self.known_ids.add(str(prop["id"]))
        self.new_ids: list[str] = []
        items = raw_props if isinstance(raw_props, list) else []
        for index, raw in enumerate(items):
            if isinstance(raw, dict):
                self._declare(raw, f"props[{index}]")

    # -- declarations --------------------------------------------------------

    def _declare(self, raw: dict[str, Any], path: str) -> None:
        raw_id = _str(raw.get("id"))
        pid = prop_slug(raw_id) or prop_slug((raw.get("label") or {}).get("en") or raw.get("en"))
        if not pid:
            self.issue("prop_invalid", path, 'a prop needs an id: snake_case, like "snail"')
            return
        if pid in self.known_ids:
            # Already in the story: a reuse, never a second declaration.
            self.alias[raw_id or pid] = pid
            return
        if raw_id and raw_id != pid:
            self.issue("prop_invalid", f"{path}.id", f"{raw_id!r} is not snake_case: {pid!r}")
        label = self._label(raw, path)
        if label is None:
            self.dropped.add(raw_id or pid)
            return
        kind = _str(raw.get("kind")).lower()
        kind = "real" if kind == "photo" else kind
        if kind not in PROP_KINDS:
            if kind:
                self.issue("prop_invalid", f"{path}.kind", f"{kind!r} is not a prop kind")
            kind = "sticker"
        query = _str(raw.get("query"))
        if not query:
            query = head_phrase(label["en"], "en")
            self.issue("prop_invalid", f"{path}.query", "no query: 2 to 5 English words")
        if len(query) > PROP_QUERY_LIMIT:
            self.issue("prop_invalid", f"{path}.query", f"at most {PROP_QUERY_LIMIT} characters")
            query = _cut(query, PROP_QUERY_LIMIT)
        if set(fold(query).replace("-", " ").split()) & PEOPLE_WORDS:
            self.issue(
                "prop_query_people",
                f"{path}.query",
                f"{query!r} names a person: people are the cast, never a prop",
            )
            self.dropped.add(raw_id or pid)
            return
        prop: dict[str, Any] = {
            "id": pid,
            "label": label,
            "query": query,
            "kind": kind,
            "educational": kind in ("real", "figure"),
        }
        emoji = raw.get("emoji")
        if emoji is not None and _str(emoji):
            if is_one_emoji(_str(emoji)):
                prop["emoji"] = _str(emoji)
            else:
                self.issue("prop_invalid", f"{path}.emoji", "not one emoji: left out")
        at = _str(raw.get("at")).lower() or "ground"
        if at not in PROP_PLACEMENTS:
            self.issue("prop_invalid", f"{path}.at", f"{at!r} is not a placement")
            at = "ground"
        holder = _str(raw.get("holder"))
        if at == "held":
            if holder in self.cast_ids:
                prop["holder"] = holder
            else:
                self.issue("prop_invalid", f"{path}.holder", "a held prop needs its holder's id")
                at = "ground"
        prop["at"] = at
        size = _str(raw.get("size")).lower()
        if size not in PROP_SIZES:
            size = default_size(at)
        if at == "held":
            size = "s"
        if size == "l" and at != "back":
            size = "m"
        prop["size"] = size
        if kind == "figure":
            figure = self._figure(raw.get("figure"))
            if figure is None:
                self.issue(
                    "figure_prop_dangling",
                    f"{path}.figure",
                    "no FIGURE listed has this number: the prop is shown as a real thing",
                )
                prop["kind"], prop["educational"] = "real", True
            else:
                prop["figure"] = figure
        duplicate = next((p for p in self.props.values() if query_key(p) == query_key(prop)), None)
        if duplicate is not None:
            self.issue(
                "duplicate_prop",
                path,
                f"{pid!r} is the same thing as {duplicate['id']!r}: use one id",
            )
            self.alias[raw_id or pid] = duplicate["id"]
            self.alias[pid] = duplicate["id"]
            return
        if pid in self.props:
            self.issue("duplicate_prop", f"{path}.id", f"{pid!r} is declared twice")
            return
        self.props[pid] = prop
        self.new_ids.append(pid)
        if raw_id:
            self.alias[raw_id] = pid

    def _label(self, raw: dict[str, Any], path: str) -> dict[str, str] | None:
        value = raw.get("label")
        if isinstance(value, str) and value.strip():
            label = {"en": _str(value), "fr": _str(value)}
        else:
            value = value if isinstance(value, dict) else raw
            label = {lang: _str(value.get(lang)) for lang in ("en", "fr")}
        if not label["en"] or not label["fr"]:
            self.issue(
                "prop_invalid",
                f"{path}.label",
                'a prop label needs "en" and "fr": the prop was left out',
            )
            return None
        for lang in ("en", "fr"):
            short = short_label(label[lang])
            if short != label[lang]:
                self.issue(
                    "prop_invalid",
                    f"{path}.label.{lang}",
                    f"a label is a short noun with its article, at most {PROP_LABEL_LIMIT}"
                    " characters, never a description of the thing: it is now"
                    f" «{short}»",
                )
                label[lang] = short
        return label

    def _figure(self, number: Any) -> dict[str, Any] | None:
        if isinstance(number, str) and number.strip().isdigit():
            number = int(number.strip())
        if (
            not isinstance(number, int)
            or isinstance(number, bool)
            or not 1 <= number <= len(self.figures)
        ):
            return None
        return figure_of(self.figures[number - 1])

    # -- references ----------------------------------------------------------

    def resolve(self, value: Any) -> str | None:
        key = _str(value)
        if not key:
            return None
        if key in self.alias:
            return self.alias[key]
        if key in self.props:
            return key
        slug = prop_slug(key)
        if slug in self.alias:
            return self.alias[slug]
        return slug if slug in self.props else None

    def refs(self, value: Any, path: str) -> list[str]:
        """The prop ids ``value`` names, resolved; unknown ones dropped."""
        out: list[str] = []
        items = value if isinstance(value, list) else [value] if _str(value) else []
        for item in items:
            pid = self.resolve(item)
            if pid is None:
                if _str(item) not in self.dropped:
                    self.issue(
                        "prop_ref_unknown",
                        path,
                        f'{_str(item)!r} is not a declared prop: declare it in "props"',
                    )
                continue
            if pid not in out:
                out.append(pid)
        return out

    def closeup(self, raw: dict[str, Any], path: str) -> dict[str, Any] | None:
        pid = self.resolve(raw.get("prop"))
        if pid is None:
            if _str(raw.get("prop")) not in self.dropped:
                self.issue("prop_ref_unknown", f"{path}.prop", "this close-up names no prop")
            return None
        step: dict[str, Any] = {"type": "show", "visual": "prop", "params": {"prop": pid}}
        caption = raw.get("caption")
        if isinstance(caption, dict) and _str(caption.get("en")) and _str(caption.get("fr")):
            step["caption"] = {lang: _cut(_str(caption[lang]), 140) for lang in ("en", "fr")}
        return step

    # -- the finished scenes -------------------------------------------------

    def finish(self, scenes: list[dict[str, Any]], *, module_count: int) -> list[dict[str, Any]]:
        """Settle every reference in ``scenes`` and return the chapter's ``props``."""
        self._match_lines(scenes)
        self._cap_new(scenes, module_count=module_count)
        for index, scene in enumerate(scenes):
            self._scene_props(scene, f"scenes[{index}]")
        self._closeups(scenes)
        used = self._used(scenes)
        for pid in self.new_ids:
            if pid in self.props and pid not in used:
                self.issue(
                    "prop_unused",
                    "props",
                    f"{pid!r} is declared but no line names it: it was left out",
                )
        self._holders(scenes)
        return [self.props[pid] for pid in self._order(scenes) if pid in used]

    def _lines(self, scenes: list[dict[str, Any]]):
        for scene in scenes:
            for step in scene["steps"]:
                if step.get("type") in LINE_TYPES and not str(step.get("id", "")).startswith(
                    "situation-"
                ):
                    yield scene, step

    def _shared_heads(self) -> dict[str, frozenset[str]]:
        """Per language, the label heads two props or more share: never matched alone."""
        out: dict[str, frozenset[str]] = {}
        for lang in ("en", "fr"):
            seen: set[str] = set()
            shared: set[str] = set()
            for prop in self.props.values():
                label = (prop.get("label") or {}).get(lang)
                head = head_phrase(label, lang) if isinstance(label, str) else ""
                if head:
                    (shared if head in seen else seen).add(head)
            out[lang] = frozenset(shared)
        return out

    def _match_lines(self, scenes: list[dict[str, Any]]) -> None:
        shared = self._shared_heads()
        for _scene, step in self._lines(scenes):
            refs = list(step.get("props") or [])
            for pid, prop in self.props.items():
                if pid in refs:
                    continue
                text = {lang: step.get(lang) for lang in ("en", "fr")}
                if any(
                    names_prop(
                        " ".join(t) if isinstance(t, list) else t,
                        prop,
                        lang,
                        shared_heads=shared[lang],
                        names=self.cast_names,
                    )
                    for lang, t in text.items()
                ):
                    if len(refs) >= MAX_PROPS_PER_LINE:
                        break
                    refs.append(pid)
                    self.issue(
                        "prop_named_unreferenced",
                        step.get("_src") or "scenes",
                        f'this line names {pid!r}: add "props": ["{pid}"] to it',
                    )
            if len(refs) > MAX_PROPS_PER_LINE:
                self.issue(
                    "line_props_too_many",
                    step.get("_src") or "scenes",
                    f"a line points at {MAX_PROPS_PER_LINE} props at most",
                )
                refs = refs[:MAX_PROPS_PER_LINE]
            if refs:
                step["props"] = refs
            else:
                step.pop("props", None)

    def _mentions(self, scenes: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for _scene, step in self._lines(scenes):
            for pid in step.get("props") or []:
                counts[pid] = counts.get(pid, 0) + 1
        for scene in scenes:
            for step in scene["steps"]:
                if step.get("visual") == "prop":
                    pid = step["params"]["prop"]
                    counts[pid] = counts.get(pid, 0) + 1
        return counts

    def _cap_new(self, scenes: list[dict[str, Any]], *, module_count: int) -> None:
        counts = self._mentions(scenes)
        new = [pid for pid in self.new_ids if pid in self.props]
        room = min(MAX_NEW_PROPS_PER_CHAPTER, max(MAX_PROPS_PER_MODULE - module_count, 0))
        if len(new) <= room:
            return
        keep = set(sorted(new, key=lambda pid: (-counts.get(pid, 0), new.index(pid)))[:room])
        gone = [pid for pid in new if pid not in keep]
        self.issue(
            "chapter_props_too_many",
            "props",
            f"{len(new)} new props: at most {room} here; left out: {', '.join(gone)}",
        )
        for pid in gone:
            self.props.pop(pid, None)
        self._drop_refs(scenes, set(gone))

    def _drop_refs(self, scenes: list[dict[str, Any]], gone: set[str]) -> None:
        for scene in scenes:
            if scene.get("props"):
                scene["props"] = [p for p in scene["props"] if p not in gone]
            kept = []
            for step in scene["steps"]:
                if step.get("visual") == "prop" and step["params"]["prop"] in gone:
                    continue
                if step.get("props"):
                    step["props"] = [p for p in step["props"] if p not in gone]
                    if not step["props"]:
                        step.pop("props")
                kept.append(step)
            scene["steps"] = kept

    def _scene_props(self, scene: dict[str, Any], path: str) -> None:
        listed = [p for p in scene.get("props") or [] if p in self.props]
        order: list[str] = []
        for step in scene["steps"]:
            refs = list(step.get("props") or [])
            if step.get("visual") == "prop":
                refs.append(step["params"]["prop"])
            for pid in refs:
                if pid not in order:
                    order.append(pid)
                if pid not in listed:
                    listed.append(pid)
                    self.issue(
                        "prop_put_in_scene",
                        f"{path}.props",
                        f"a line of this scene points at {pid!r}: it is now on stage",
                    )
        # Props no line points at keep their place after those that are pointed at.
        ranked = order + [p for p in listed if p not in order]
        if len(ranked) > MAX_PROPS_PER_SCENE:
            self.issue(
                "scene_props_cut",
                f"{path}.props",
                f"{len(ranked)} props: a scene shows {MAX_PROPS_PER_SCENE} at most",
            )
            gone = set(ranked[MAX_PROPS_PER_SCENE:])
            ranked = ranked[:MAX_PROPS_PER_SCENE]
            self._drop_refs([scene], gone)
        if ranked:
            scene["props"] = ranked
        else:
            scene.pop("props", None)

    def _closeups(self, scenes: list[dict[str, Any]]) -> None:
        """Close-ups: one per educational prop, after its first mention, at most 2 a scene.

        A close-up the model put before any line names its prop, as a third
        one in a scene, between a question and its lead-in or reaction, or
        after the chapter's last line, is moved once every scene is read — so
        the step it becomes is never taken for a second close-up of that prop —
        to a place :meth:`_insert_closeup` allows.
        """
        first_line: dict[str, tuple[int, int]] = {}
        for s_index, scene in enumerate(scenes):
            for index, step in enumerate(scene["steps"]):
                if step.get("type") in LINE_TYPES:
                    for pid in step.get("props") or []:
                        first_line.setdefault(pid, (s_index, index))
        shown: set[str] = set()
        moved: list[dict[str, Any]] = []
        for s_index, scene in enumerate(scenes):
            kept: list[dict[str, Any]] = []
            here = 0
            steps = scene["steps"]
            for index, step in enumerate(steps):
                if step.get("visual") != "prop":
                    kept.append(step)
                    continue
                pid = step["params"]["prop"]
                prop = self.props.get(pid, {})
                where = step.get("_src") or f"scenes[{s_index}]"
                if not prop.get("educational"):
                    self.issue("closeup_invalid", where, f"{pid!r} is a sticker: no close-up")
                    continue
                if pid in shown:
                    self.issue("closeup_invalid", where, f"{pid!r} is already shown close up")
                    continue
                first = first_line.get(pid)
                if first is None or first > (s_index, index):
                    self.issue(
                        "closeup_invalid",
                        where,
                        f"the close-up of {pid!r} comes before any line names it: moved",
                    )
                    moved.append(step)
                    continue
                before = steps[index - 1] if index > 0 else None
                after = steps[index + 1] if index + 1 < len(steps) else None
                if (
                    _asks_or_sets_up(before)
                    or _asks_or_sets_up(after)
                    or (after is None and s_index == len(scenes) - 1)
                ):
                    self.issue(
                        "closeup_invalid",
                        where,
                        f"the close-up of {pid!r} sits between a question and its lines, or"
                        " after the last line: moved",
                    )
                    moved.append(step)
                    continue
                if here >= MAX_CLOSEUPS_PER_SCENE:
                    self.issue(
                        "closeup_invalid",
                        where,
                        f"a scene shows {MAX_CLOSEUPS_PER_SCENE} close-ups at most: the close-up"
                        f" of {pid!r} is moved to another line naming it",
                    )
                    moved.append(step)
                    continue
                here += 1
                shown.add(pid)
                kept.append(step)
            scene["steps"] = kept
        for step in moved:
            pid = step["params"]["prop"]
            if (
                pid not in shown
                and pid in first_line
                and self._insert_closeup(scenes, pid, first_line, step)
            ):
                shown.add(pid)
        for pid, prop in self.props.items():
            if prop.get("educational") and pid in first_line and pid not in shown:
                if self._insert_closeup(scenes, pid, first_line, None):
                    self.issue(
                        "closeup_missing",
                        "scenes",
                        f'after the line that first names {pid!r}, add {{"type": "show",'
                        f' "prop": "{pid}"}}',
                    )
                shown.add(pid)

    def _insert_closeup(
        self,
        scenes: list[dict[str, Any]],
        pid: str,
        first_line: dict[str, tuple[int, int]],
        step: dict[str, Any] | None,
    ) -> bool:
        """Put a close-up after a line naming ``pid``, where it breaks nothing.

        Never between a lead-in and its question, nor between a question and
        its reaction (:func:`_closeup_slot`); never after the chapter's last
        line, which lands the hook; at most :data:`MAX_CLOSEUPS_PER_SCENE` a
        scene. ``False`` when no line naming the prop has such a place.
        """
        closeup = step or {"type": "show", "visual": "prop", "params": {"prop": pid}}
        closeup = {k: v for k, v in closeup.items() if k != "_src"}
        start_scene, _start = first_line[pid]
        for s_index in range(start_scene, len(scenes)):
            scene = scenes[s_index]
            steps = scene["steps"]
            if sum(1 for s in steps if s.get("visual") == "prop") >= MAX_CLOSEUPS_PER_SCENE:
                continue
            for index, line in enumerate(steps):
                if line.get("type") in LINE_TYPES and pid in (line.get("props") or []):
                    position = _closeup_slot(steps, index + 1, last=s_index == len(scenes) - 1)
                    if position is not None:
                        steps.insert(position, closeup)
                        return True
        return False

    def _used(self, scenes: list[dict[str, Any]]) -> set[str]:
        used: set[str] = set()
        for scene in scenes:
            used.update(scene.get("props") or [])
            for step in scene["steps"]:
                used.update(step.get("props") or [])
                if step.get("visual") == "prop":
                    used.add(step["params"]["prop"])
        return used

    def _order(self, scenes: list[dict[str, Any]]) -> list[str]:
        order: list[str] = []
        for scene in scenes:
            for pid in scene.get("props") or []:
                if pid not in order:
                    order.append(pid)
        return order

    def _holders(self, scenes: list[dict[str, Any]]) -> None:
        """A held prop whose holder is off stage in a scene that shows it goes to the ground."""
        for scene in scenes:
            cast = set(scene.get("cast") or [])
            for pid in scene.get("props") or []:
                prop = self.props.get(pid)
                if prop and prop.get("at") == "held" and prop.get("holder") not in cast:
                    self.issue(
                        "prop_invalid",
                        "props",
                        f"{pid!r} is held by {prop.get('holder')!r}, who is not in every"
                        " scene that shows it: it is put on the ground",
                    )
                    prop["at"] = "ground"
                    prop.pop("holder", None)


def _asks_or_sets_up(step: dict[str, Any] | None) -> bool:
    """A question, or the situation card that belongs to it."""
    return step is not None and (
        step.get("type") == "ask"
        or (step.get("type") == "concept" and str(step.get("id", "")).startswith("situation-"))
    )


def _closeup_slot(steps: list[dict[str, Any]], start: int, *, last: bool) -> int | None:
    """The first position from ``start`` where a close-up breaks nothing, if any.

    Not right before a question (between its lead-in and the ask), not right
    after one (before its reaction), and — in the last scene — not after the
    last step: the chapter ends on its hook line.
    """
    for position in range(max(start, 1), len(steps) + 1):
        before = steps[position - 1]
        after = steps[position] if position < len(steps) else None
        if _asks_or_sets_up(before) or _asks_or_sets_up(after):
            continue
        if after is None and last:
            continue
        return position
    return None


def figure_of(ref: dict[str, Any]) -> dict[str, Any]:
    """``prop.figure`` from a lesson figure ref (with its facts, when checked)."""
    figure: dict[str, Any] = {"source_image_id": _str(ref.get("id"))}
    if ref.get("figure_number"):
        figure["figure_number"] = _str(ref.get("figure_number"))
    if ref.get("image_hash"):
        figure["image_hash"] = _str(ref.get("image_hash"))
    alt = {"en": _str(ref.get("alt_text_en")), "fr": _str(ref.get("alt_text_fr"))}
    if alt["en"] and alt["fr"]:
        figure["alt"] = alt
    caption = {
        "en": _str(ref.get("caption_en") or ref.get("caption")),
        "fr": _str(ref.get("caption_fr") or ref.get("caption")),
    }
    if caption["en"] and caption["fr"]:
        figure["caption"] = {lang: _cut(caption[lang], 140) for lang in ("en", "fr")}
    if ref.get("attribution"):
        figure["attribution"] = _str(ref.get("attribution"))[:200]
    return figure


def plan_props(plan: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The episode plan's props in the chapter prop shape, marked ``origin`` "module"."""
    out: list[dict[str, Any]] = []
    for raw in (plan or {}).get("props") or []:
        if not isinstance(raw, dict) or not raw.get("id"):
            continue
        label = raw.get("label") if isinstance(raw.get("label"), dict) else raw
        # A plan stored before #2697 may hold a label cut with "…".
        en, fr = short_label(label.get("en")), short_label(label.get("fr"))
        if not en or not fr:
            continue
        kind = _str(raw.get("kind")).lower()
        kind = kind if kind in ("sticker", "real") else "sticker"
        at = _str(raw.get("at")).lower()
        at = at if at in PROP_PLACEMENTS and at != "held" else "ground"
        size = _str(raw.get("size")).lower()
        size = size if size in PROP_SIZES else default_size(at)
        if size == "l" and at != "back":
            size = "m"
        prop: dict[str, Any] = {
            "id": str(raw["id"]),
            "label": {"en": _cut(en, PROP_LABEL_LIMIT), "fr": _cut(fr, PROP_LABEL_LIMIT)},
            "query": _cut(_str(raw.get("query")) or head_phrase(en, "en"), PROP_QUERY_LIMIT),
            "kind": kind,
            "educational": kind == "real",
            "at": at,
            "size": size,
            "origin": "module",
        }
        if is_one_emoji(_str(raw.get("emoji"))):
            prop["emoji"] = _str(raw.get("emoji"))
        out.append(prop)
    return out
