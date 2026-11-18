"""Story props from the shared 3D library (docs/story-mode-3d-assets.md, Phase A).

A story's props (#2681) each carry ``query``, an English search phrase. This
module gives them pictures from the library the asset foundry renders
(:mod:`app.domain.models.story_prop_library`), in the ``art.props`` shape the
player already reads (``PropMedia``: a ``sticker`` on stage, a ``picture``
for "Look closely", with its credit):

* a **sticker** prop gets a library sticker: drawn on stage, and shown with
  its credit when tapped;
* a **real** prop gets a library close-up (a realistic render), unless the
  story already shows a course figure for it (``prop.figure``): the course's
  own picture comes first;
* anything else keeps its emoji or name tag, as today.

Matching never happens while a story is served. A phrase is matched once by
a background task (:func:`resolve_phrases`, dispatched by the story routes)
and the result, a match or a miss, is cached in ``story_prop_matches``; a
view reads that cache in one query (:func:`load_matches`) and builds the map
(:func:`props_media`). With an empty library a phrase is recorded as a miss
with no model call at all.

A phrase matches an asset of the right kind by embeddings
(text-embedding-3-small, cosine at least :data:`EMBED_ACCEPT`), or by its
head noun with a weaker similarity (:data:`EMBED_WITH_HEAD`); without
embeddings, by its head noun alone. The thresholds are first guesses, to be
tuned on the Phase 0 inventory.
"""

from __future__ import annotations

import math
import re
import unicodedata
import uuid
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

import structlog
from sqlalchemy import func, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.story_prop_library import (
    ASSET_CLOSEUP,
    ASSET_STICKER,
    PROP_REAL,
    PROP_STICKER,
    StoryLibraryAsset,
    StoryPropMatch,
)

logger = structlog.get_logger(__name__)

#: Ledger feature for the embedding calls of the matcher.
FEATURE_STORY_PROPS = "story_props"
#: Accept a match on its embedding alone at or above this cosine similarity.
EMBED_ACCEPT = 0.62
#: Accept a match whose head noun is one of the asset's words at or above this.
EMBED_WITH_HEAD = 0.45
#: Phrases are stored in ``story_prop_matches.query`` (VARCHAR 200).
MAX_QUERY_CHARS = 200
#: At most this many phrases are matched by one task (a module declares at most 40 props).
MAX_PHRASES_PER_RUN = 80

#: The library asset kind that serves each prop kind.
ASSET_FOR_PROP = {PROP_STICKER: ASSET_STICKER, PROP_REAL: ASSET_CLOSEUP}

PropsStatus = Literal["ready", "pending", "partial", "none"]
#: ``(normalised phrase, prop kind)``: the key of a match.
PropKey = tuple[str, str]


# -- Words --------------------------------------------------------------------------

_ARTICLES = frozenset({"a", "an", "the", "some"})
#: A search phrase is cut at its first preposition: "bowl of rice" is a bowl.
_PREPOSITIONS = frozenset({"of", "with", "for", "on", "in", "from", "at", "by", "under"})
#: Plurals that only lose their "s" would be mangled by the "es" rule.
_KEEP_ENDINGS = ("ss", "us", "is", "ous")
_IRREGULAR = {
    "leaves": "leaf",
    "knives": "knife",
    "loaves": "loaf",
    "shelves": "shelf",
    "wolves": "wolf",
    "halves": "half",
    "calves": "calf",
    "lives": "life",
    "men": "man",
    "women": "woman",
    "children": "child",
    "people": "person",
    "teeth": "tooth",
    "feet": "foot",
    "mice": "mouse",
    "geese": "goose",
}


def _fold(text: str) -> str:
    """Lower case, accents removed."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


def tokens(text: str) -> list[str]:
    """The words of ``text``: CamelCase and snake_case split, digits dropped."""
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", text or "")
    return [word for word in re.split(r"[^a-z]+", _fold(spaced)) if word]


def singular(word: str) -> str:
    """A rough English singular: berries → berry, boxes → box, leaves → leaf."""
    if word in _IRREGULAR:
        return _IRREGULAR[word]
    if len(word) <= 3 or word.endswith(_KEEP_ENDINGS):
        return word
    if word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith(("ches", "shes", "xes", "ses", "zes", "oes")):
        return word[:-2]
    if word.endswith("s"):
        return word[:-1]
    return word


def normalise_query(query: str) -> str:
    """A search phrase, folded, without a leading article, at most 200 characters."""
    words = tokens(query)
    while words and words[0] in _ARTICLES:
        words = words[1:]
    return " ".join(words)[:MAX_QUERY_CHARS].strip()


def head_noun(query: str) -> str:
    """The thing a search phrase names: its last word before any preposition."""
    words = normalise_query(query).split()
    for index, word in enumerate(words):
        if word in _PREPOSITIONS and index > 0:
            words = words[:index]
            break
    return singular(words[-1]) if words else ""


# -- A story's props ----------------------------------------------------------------


@dataclass(frozen=True)
class DocProp:
    """A prop of a served document that the library may picture."""

    prop_id: str
    key: PropKey
    label: Mapping[str, str]


def document_props(content: Mapping[str, Any]) -> list[DocProp]:
    """The document's props the library may serve.

    Sticker and real props with a search phrase; a prop that already has a
    course figure (``figure``, set by the builder) keeps it.
    """
    out: list[DocProp] = []
    seen: set[str] = set()
    props = content.get("props") if isinstance(content, Mapping) else None
    for prop in props if isinstance(props, list) else []:
        if not isinstance(prop, Mapping):
            continue
        prop_id, kind, query = prop.get("id"), prop.get("kind"), prop.get("query")
        if not isinstance(prop_id, str) or not prop_id or prop_id in seen:
            continue
        if kind not in ASSET_FOR_PROP or prop.get("figure") or not isinstance(query, str):
            continue
        phrase = normalise_query(query)
        if not phrase:
            continue
        seen.add(prop_id)
        label = prop.get("label") if isinstance(prop.get("label"), Mapping) else {}
        out.append(DocProp(prop_id=prop_id, key=(phrase, kind), label=label))
    return out


# -- Matching -----------------------------------------------------------------------


@dataclass(frozen=True)
class Candidate:
    """What the matcher needs of an asset (never its bytes)."""

    id: uuid.UUID
    slug: str
    kind: str
    label: Mapping[str, str]
    tags: Sequence[str]
    embedding: Sequence[float] | None = None

    @property
    def words(self) -> set[str]:
        text = " ".join([self.slug, str(self.label.get("en") or ""), *map(str, self.tags)])
        return {singular(word) for word in tokens(text)}


@dataclass(frozen=True)
class Match:
    asset_id: uuid.UUID | None
    score: float | None
    method: str


def embedding_text(slug: str, label: Mapping[str, Any], tags: Iterable[Any]) -> str:
    """What an asset is embedded from: its English label, then its tags and slug."""
    words = [str(tag) for tag in tags if str(tag).strip()]
    words.append(slug.replace("_", " "))
    return f"{label.get('en') or slug}. {', '.join(words)}"


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def match_phrase(
    phrase: str,
    prop_kind: str,
    candidates: Sequence[Candidate],
    phrase_embedding: Sequence[float] | None = None,
) -> Match:
    """The best asset for one phrase, or a miss.

    Only assets of the kind that serves ``prop_kind`` compete. With
    embeddings: the most similar asset, kept when its similarity reaches
    :data:`EMBED_ACCEPT`, or :data:`EMBED_WITH_HEAD` when the phrase's head
    noun is one of its words. Without: the first asset whose words hold the
    head noun (a lexical match, no score).
    """
    wanted = ASSET_FOR_PROP.get(prop_kind)
    pool = [c for c in candidates if c.kind == wanted]
    if not pool:
        return Match(None, None, "empty" if not candidates else "lexical")
    head = head_noun(phrase)
    if phrase_embedding is not None and any(c.embedding for c in pool):
        best: tuple[float, Candidate] | None = None
        for candidate in pool:
            if not candidate.embedding:
                continue
            score = cosine(phrase_embedding, candidate.embedding)
            threshold = EMBED_WITH_HEAD if head and head in candidate.words else EMBED_ACCEPT
            if score >= threshold and (best is None or score > best[0]):
                best = (score, candidate)
        if best is None:
            return Match(None, None, "embedding")
        return Match(best[1].id, round(best[0], 4), "embedding")
    for candidate in sorted(pool, key=lambda c: c.slug):
        if head and head in candidate.words:
            return Match(candidate.id, None, "lexical")
    return Match(None, None, "lexical")


# -- The art.props map --------------------------------------------------------------


@dataclass(frozen=True)
class AssetView:
    """A matched asset as the map needs it (never its bytes)."""

    id: uuid.UUID
    kind: str
    label: Mapping[str, str]
    width: int
    height: int
    bytes: int
    licence: str
    attribution_required: bool
    credit: Mapping[str, str]
    source: Mapping[str, Any]
    has_large: bool


def asset_url(asset_id: uuid.UUID | str, *, large: bool = False) -> str:
    return f"/api/v1/story-props/{asset_id}/data" + ("?size=large" if large else "")


_LICENCE_URLS = {
    "CC0-1.0": "https://creativecommons.org/publicdomain/zero/1.0/",
    "PDM": "https://creativecommons.org/publicdomain/mark/1.0/",
}


def licence_url(code: str) -> str | None:
    if code in _LICENCE_URLS:
        return _LICENCE_URLS[code]
    found = re.fullmatch(r"CC-(BY(?:-SA)?)-(\d\.\d)", code or "")
    if found:
        return f"https://creativecommons.org/licenses/{found[1].lower()}/{found[2]}/"
    return None


def media_credit(asset: AssetView) -> dict[str, Any]:
    """The ``MediaCredit`` of a library picture (``kind: "web"``, TASL)."""
    source = asset.source
    credit: dict[str, Any] = {
        "kind": "web",
        "license": asset.licence,
        "attribution_required": asset.attribution_required,
        "text": {"en": str(asset.credit.get("en") or ""), "fr": str(asset.credit.get("fr") or "")},
    }
    optional = {
        "title": source.get("title"),
        "author": source.get("author"),
        "author_url": source.get("author_url"),
        "source": source.get("site"),
        "license_url": licence_url(asset.licence),
        "page_url": source.get("page"),
    }
    credit.update(
        {key: value for key, value in optional.items() if isinstance(value, str) and value}
    )
    return credit


def prop_media(asset: AssetView, label: Mapping[str, str]) -> dict[str, Any]:
    """A prop's ``PropMedia`` from a library asset."""
    alt = {
        "en": str(label.get("en") or asset.label.get("en") or ""),
        "fr": str(label.get("fr") or asset.label.get("fr") or ""),
    }
    picture: dict[str, Any] = {
        "src": asset_url(asset.id),
        "width": asset.width,
        "height": asset.height,
        "bytes": asset.bytes,
        "alt": alt,
        "via": "open_3d",
        "credit": media_credit(asset),
    }
    if asset.kind == ASSET_STICKER:
        return {"sticker": asset_url(asset.id), "picture": picture}
    if asset.has_large:
        picture["src_large"] = asset_url(asset.id, large=True)
    return {"picture": picture}


@dataclass
class PropsMedia:
    """The ``art.props`` map of one document, and the phrases still to match."""

    props: dict[str, dict[str, Any]] = field(default_factory=dict)
    status: PropsStatus = "none"
    unresolved: list[PropKey] = field(default_factory=list)


#: A cached result: the matched asset, or None for a miss.
Resolved = Mapping[PropKey, AssetView | None]


def props_media(doc_props: Sequence[DocProp], resolved: Resolved) -> PropsMedia:
    """The map for ``doc_props`` given the cached results (a key absent is unresolved).

    ``status``: ``none`` with nothing the library could serve; ``ready`` when
    every phrase has a result (hits or misses); ``pending`` when some have
    none yet and nothing is matched; ``partial`` when some are matched and
    others have no result yet.
    """
    media = PropsMedia()
    if not doc_props:
        return media
    unresolved: list[PropKey] = []
    for prop in doc_props:
        if prop.key not in resolved:
            if prop.key not in unresolved:
                unresolved.append(prop.key)
            continue
        asset = resolved[prop.key]
        if asset is not None and asset.kind == ASSET_FOR_PROP.get(prop.key[1]):
            media.props[prop.prop_id] = prop_media(asset, prop.label)
    media.unresolved = unresolved
    if not unresolved:
        media.status = "ready"
    else:
        media.status = "partial" if media.props else "pending"
    return media


# -- Database -----------------------------------------------------------------------


async def load_matches(
    session: AsyncSession, keys: Iterable[PropKey]
) -> dict[PropKey, AssetView | None]:
    """The cached results of ``keys``, with each matched asset's metadata (one query)."""
    keys = list(dict.fromkeys(keys))
    if not keys:
        return {}
    statement = (
        select(
            StoryPropMatch.query,
            StoryPropMatch.prop_kind,
            StoryLibraryAsset.id,
            StoryLibraryAsset.kind,
            StoryLibraryAsset.label,
            StoryLibraryAsset.width,
            StoryLibraryAsset.height,
            StoryLibraryAsset.bytes,
            StoryLibraryAsset.licence,
            StoryLibraryAsset.attribution_required,
            StoryLibraryAsset.credit,
            StoryLibraryAsset.source,
            StoryLibraryAsset.image_large.is_not(None),
        )
        .outerjoin(StoryLibraryAsset, StoryLibraryAsset.id == StoryPropMatch.asset_id)
        .where(tuple_(StoryPropMatch.query, StoryPropMatch.prop_kind).in_(keys))
    )
    out: dict[PropKey, AssetView | None] = {}
    for row in (await session.execute(statement)).all():
        query, prop_kind, asset_id, *rest = row
        out[(query, prop_kind)] = (
            AssetView(asset_id, *rest[:9], has_large=bool(rest[9])) if asset_id else None
        )
    return out


async def load_candidates(session: AsyncSession) -> list[Candidate]:
    """Every library asset as the matcher sees it (no bytes)."""
    rows = await session.execute(
        select(
            StoryLibraryAsset.id,
            StoryLibraryAsset.slug,
            StoryLibraryAsset.kind,
            StoryLibraryAsset.label,
            StoryLibraryAsset.tags,
            StoryLibraryAsset.embedding,
        )
    )
    return [
        Candidate(id=i, slug=s, kind=k, label=l or {}, tags=t or [], embedding=e)
        for i, s, k, l, t, e in rows.all()  # noqa: E741
    ]


#: Embeds a list of texts (in order); the task passes the RAG embedding service.
Embedder = Callable[[list[str]], Awaitable[list[list[float]]]]


async def resolve_phrases(
    session: AsyncSession, keys: Sequence[PropKey], embed: Embedder | None = None
) -> dict[PropKey, Match]:
    """Match ``keys`` against the library and store the results (matches and misses).

    One embedding call for all the phrases, only when the library has
    embedded assets of a kind they need; without ``embed``, or when it fails,
    the head-noun match is used instead. Commits nothing: the caller does.
    """
    keys = [key for key in dict.fromkeys(keys) if key[1] in ASSET_FOR_PROP and key[0]]
    keys = keys[:MAX_PHRASES_PER_RUN]
    if not keys:
        return {}
    candidates = await load_candidates(session)
    vectors: dict[str, Sequence[float]] = {}
    if embed is not None and any(c.embedding for c in candidates):
        phrases = list(dict.fromkeys(phrase for phrase, _kind in keys))
        try:
            vectors = dict(zip(phrases, await embed(phrases), strict=True))
        except Exception as exc:
            logger.warning(
                "Story prop embeddings unavailable; head-noun match only", error=str(exc)
            )
    results = {key: match_phrase(key[0], key[1], candidates, vectors.get(key[0])) for key in keys}
    for (phrase, kind), match in results.items():
        values = {
            "asset_id": match.asset_id,
            "score": match.score,
            "method": match.method,
        }
        await session.execute(
            insert(StoryPropMatch)
            .values(query=phrase, prop_kind=kind, **values)
            .on_conflict_do_update(
                index_elements=[StoryPropMatch.query, StoryPropMatch.prop_kind],
                set_={**values, "resolved_at": func.now()},
            )
        )
    logger.info(
        "Story prop phrases matched",
        phrases=len(results),
        matched=sum(1 for m in results.values() if m.asset_id),
        library=len(candidates),
    )
    return results
