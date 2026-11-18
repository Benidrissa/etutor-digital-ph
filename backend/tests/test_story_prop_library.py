"""The shared story prop library (Phase A of docs/story-mode-3d-assets.md).

Pure logic first (which props it may serve, how a phrase is matched, the
``art.props`` map), then the database reads and writes against fakes, the
picture route, the serving step of the story routes, the task's dedup key and
the migration against the models.
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient

from app.domain.models.story_prop_library import StoryLibraryAsset, StoryPropMatch
from app.domain.services import story_prop_library as lib
from app.tasks.story_props import story_props_dispatch_key

STICKER_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
CLOSEUP_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")


def _candidate(asset_id, slug, kind, label, tags=(), embedding=None) -> lib.Candidate:
    return lib.Candidate(
        id=asset_id, slug=slug, kind=kind, label={"en": label}, tags=list(tags), embedding=embedding
    )


def _view(asset_id=STICKER_ID, kind="sticker", *, licence="CC0-1.0", has_large=False, **source):
    return lib.AssetView(
        id=asset_id,
        kind=kind,
        label={"en": "a basket", "fr": "un panier"},
        width=300,
        height=280,
        bytes=7300,
        licence=licence,
        attribution_required=licence != "CC0-1.0",
        credit={"en": "3D model: Quaternius (CC0 1.0)", "fr": "Modèle 3D : Quaternius (CC0 1.0)"},
        source={
            "author": "Quaternius",
            "page": "https://poly.pizza/m/x",
            "site": "Poly Pizza",
            **source,
        },
        has_large=has_large,
    )


# -- Which props --------------------------------------------------------------------


def test_document_props_keeps_sticker_and_real_props_with_a_phrase():
    content = {
        "props": [
            {
                "id": "basket",
                "kind": "sticker",
                "query": "The woven straw basket",
                "label": {"en": "b"},
            },
            {"id": "snail", "kind": "real", "query": "garden snail"},
            {"id": "fig", "kind": "figure", "query": "diagram"},
            {
                "id": "seed",
                "kind": "real",
                "query": "néré seed",
                "figure": {"source_image_id": "x"},
            },
            {"id": "blank", "kind": "sticker", "query": "  "},
            {"id": "basket", "kind": "sticker", "query": "again"},
            "junk",
        ]
    }
    props = lib.document_props(content)
    assert [(p.prop_id, p.key) for p in props] == [
        ("basket", ("woven straw basket", "sticker")),
        ("snail", ("garden snail", "real")),
    ]
    assert lib.document_props({}) == [] and lib.document_props({"props": "x"}) == []


def test_normalise_query_is_bounded():
    assert len(lib.normalise_query("word " * 100)) <= lib.MAX_QUERY_CHARS


# -- Matching -----------------------------------------------------------------------


def test_an_empty_library_is_a_miss_without_any_embedding():
    assert lib.match_phrase("woven basket", "sticker", []) == lib.Match(None, None, "empty")


def test_lexical_match_by_head_noun_and_kind():
    pool = [
        _candidate(STICKER_ID, "pebble_round", "sticker", "a pebble", ["stone"]),
        _candidate(CLOSEUP_ID, "heart", "closeup", "the heart", ["organ"]),
    ]
    assert lib.match_phrase("grey river pebbles", "sticker", pool) == lib.Match(
        STICKER_ID, None, "lexical"
    )
    # A real prop is served by close-ups only, never by a sticker.
    assert lib.match_phrase("grey river pebble", "real", pool).asset_id is None
    assert lib.match_phrase("human heart", "real", pool).asset_id == CLOSEUP_ID
    assert lib.match_phrase("woven basket", "sticker", pool) == lib.Match(None, None, "lexical")


def test_embedding_thresholds():
    fan_id = uuid.UUID(int=STICKER_ID.int + 1)
    basket = _candidate(STICKER_ID, "basket", "sticker", "a basket", embedding=[1.0, 0.0])
    fan = _candidate(fan_id, "fan", "sticker", "a fan", embedding=[0.0, 1.0])
    # Cosine 0.8 with the basket: accepted on the embedding alone (>= EMBED_ACCEPT).
    assert (
        lib.match_phrase("wicker container", "sticker", [basket, fan], [0.8, 0.6]).asset_id
        == STICKER_ID
    )
    # The most similar asset wins: cosine 0.87 with the fan, 0.5 with the basket.
    assert (
        lib.match_phrase("hand cooler", "sticker", [basket, fan], [0.5, 0.866]).asset_id == fan_id
    )
    # Cosine 0.5 alone is below EMBED_ACCEPT: a miss...
    miss = lib.match_phrase("hand cooler", "sticker", [basket], [0.5, 0.866])
    assert miss == lib.Match(None, None, "embedding")
    # ...unless the phrase's head noun is one of the asset's words (EMBED_WITH_HEAD).
    hit = lib.match_phrase("old basket", "sticker", [basket], [0.5, 0.866])
    assert hit.asset_id == STICKER_ID and hit.method == "embedding" and hit.score == 0.5


def test_cosine():
    assert lib.cosine([1, 0], [1, 0]) == pytest.approx(1.0)
    assert lib.cosine([1, 0], [0, 1]) == 0.0
    assert lib.cosine([0, 0], [1, 1]) == 0.0


def test_embedding_text_reads_label_tags_and_slug():
    text = lib.embedding_text("tree_palm", {"en": "a palm tree"}, ["tree", "", "tropical"])
    assert text == "a palm tree. tree, tropical, tree palm"


# -- The art.props map --------------------------------------------------------------


def test_a_sticker_match_gives_a_sticker_and_a_credited_picture():
    media = lib.prop_media(_view(), {"en": "Grandma's basket", "fr": "le panier de Mamie"})
    url = f"/api/v1/story-props/{STICKER_ID}/data"
    assert media["sticker"] == url
    picture = media["picture"]
    assert picture["src"] == url and picture["via"] == "open_3d"
    assert picture["alt"] == {"en": "Grandma's basket", "fr": "le panier de Mamie"}
    credit = picture["credit"]
    assert credit["kind"] == "web" and credit["license"] == "CC0-1.0"
    assert credit["license_url"] == "https://creativecommons.org/publicdomain/zero/1.0/"
    assert credit["author"] == "Quaternius" and credit["page_url"] == "https://poly.pizza/m/x"
    assert credit["text"]["fr"].startswith("Modèle 3D")
    assert "title" not in credit  # absent fields are left out, not null


def test_a_closeup_match_gives_a_picture_with_its_large_version():
    media = lib.prop_media(_view(CLOSEUP_ID, "closeup", licence="CC-BY-SA-4.0", has_large=True), {})
    assert "sticker" not in media
    assert media["picture"]["src_large"] == f"/api/v1/story-props/{CLOSEUP_ID}/data?size=large"
    assert (
        media["picture"]["credit"]["license_url"]
        == "https://creativecommons.org/licenses/by-sa/4.0/"
    )
    assert media["picture"]["credit"]["attribution_required"] is True
    assert media["picture"]["alt"]["en"] == "a basket"  # the asset's label when the prop has none


def test_licence_urls():
    assert lib.licence_url("CC-BY-4.0") == "https://creativecommons.org/licenses/by/4.0/"
    assert lib.licence_url("PDM") == "https://creativecommons.org/publicdomain/mark/1.0/"
    assert lib.licence_url("CC-BY-NC-4.0") is None


def _doc_props():
    return [
        lib.DocProp("basket", ("woven straw basket", "sticker"), {"en": "b", "fr": "p"}),
        lib.DocProp("snail", ("garden snail", "real"), {}),
        lib.DocProp("pebble", ("grey pebble", "real"), {}),
    ]


def test_props_media_status():
    doc = _doc_props()
    assert lib.props_media([], {}).status == "none"
    pending = lib.props_media(doc, {})
    assert pending.status == "pending" and pending.props == {}
    assert pending.unresolved == [p.key for p in doc]
    partial = lib.props_media(doc, {doc[0].key: _view()})
    assert partial.status == "partial" and list(partial.props) == ["basket"]
    assert partial.unresolved == [doc[1].key, doc[2].key]
    ready = lib.props_media(doc, {doc[0].key: _view(), doc[1].key: None, doc[2].key: None})
    assert ready.status == "ready" and list(ready.props) == ["basket"] and ready.unresolved == []


def test_props_media_never_serves_an_asset_of_the_wrong_kind():
    doc = _doc_props()
    media = lib.props_media(doc[1:2], {doc[1].key: _view()})  # a sticker for a real prop
    assert media.props == {} and media.status == "ready"


# -- Database -----------------------------------------------------------------------


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class FakeSession:
    """Answers the SELECTs in order and records every statement."""

    def __init__(self, *selects):
        self.selects = list(selects)
        self.statements: list[Any] = []

    async def execute(self, statement):
        self.statements.append(statement)
        if isinstance(statement, sa.Select):
            return _Rows(self.selects.pop(0))
        return None


def _compiled(statement) -> str:
    return str(statement.compile(dialect=sa.dialects.postgresql.dialect()))


async def test_load_matches_reads_hits_and_misses_in_one_query():
    view = _view()
    session = FakeSession(
        [
            (
                "woven straw basket",
                "sticker",
                STICKER_ID,
                view.kind,
                view.label,
                300,
                280,
                7300,
                "CC0-1.0",
                False,
                view.credit,
                view.source,
                False,
            ),
            (
                "garden snail",
                "real",
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                False,
            ),
        ]
    )
    keys = [
        ("woven straw basket", "sticker"),
        ("garden snail", "real"),
        ("woven straw basket", "sticker"),
    ]
    found = await lib.load_matches(session, keys)
    assert found[("garden snail", "real")] is None
    assert found[("woven straw basket", "sticker")] == view
    (statement,) = session.statements
    sql = _compiled(statement)
    assert "LEFT OUTER JOIN story_library_assets" in sql
    assert "(story_prop_matches.query, story_prop_matches.prop_kind) IN" in sql
    assert "image_data" not in sql and "story_library_assets.image_large IS NOT NULL" in sql
    assert await lib.load_matches(FakeSession(), []) == {}


async def test_resolve_phrases_with_an_empty_library_embeds_nothing():
    calls = []

    async def embed(texts):
        calls.append(texts)
        return [[1.0, 0.0] for _ in texts]

    session = FakeSession([])
    results = await lib.resolve_phrases(
        session, [("woven basket", "sticker"), ("x", "figure")], embed
    )
    assert calls == []
    assert results == {("woven basket", "sticker"): lib.Match(None, None, "empty")}
    upsert = _compiled(session.statements[1])
    assert (
        "INSERT INTO story_prop_matches" in upsert
        and "ON CONFLICT (query, prop_kind) DO UPDATE" in upsert
    )
    assert "resolved_at" in upsert


async def test_resolve_phrases_embeds_once_and_falls_back_to_head_nouns():
    rows = [(STICKER_ID, "basket", "sticker", {"en": "a basket"}, ["wicker"], [1.0, 0.0])]
    calls = []

    async def embed(texts):
        calls.append(texts)
        return [[0.9, 0.1] for _ in texts]

    keys = [("woven basket", "sticker"), ("woven basket", "real"), ("old basket", "sticker")]
    results = await lib.resolve_phrases(FakeSession(rows), keys, embed)
    assert calls == [["woven basket", "old basket"]]  # one call, each phrase once
    assert results[("woven basket", "sticker")].method == "embedding"
    assert results[("woven basket", "sticker")].asset_id == STICKER_ID
    assert results[("woven basket", "real")].asset_id is None  # no close-up in the library

    async def broken(_texts):
        raise RuntimeError("no network")

    fallback = await lib.resolve_phrases(FakeSession(rows), keys[:1], broken)
    assert fallback[keys[0]] == lib.Match(STICKER_ID, None, "lexical")


# -- The picture route --------------------------------------------------------------


class _RouteDb:
    def __init__(self, data: bytes | None):
        self.data = data
        self.sql = ""

    async def execute(self, statement):
        self.sql = _compiled(statement)
        return SimpleNamespace(first=lambda: None if self.data is None else (self.data,))


async def _get(db: _RouteDb, url: str):
    from app.api.deps import get_db_session
    from app.main import app

    app.dependency_overrides[get_db_session] = lambda: db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.get(url)
    finally:
        app.dependency_overrides.clear()


async def test_the_route_serves_a_picture_as_immutable():
    db = _RouteDb(b"RIFFwebp")
    resp = await _get(db, f"/api/v1/story-props/{STICKER_ID}/data")
    assert resp.status_code == 200 and resp.content == b"RIFFwebp"
    assert resp.headers["content-type"] == "image/webp"
    assert "immutable" in resp.headers["cache-control"]
    assert "story_library_assets.image_data" in db.sql


async def test_the_route_serves_the_large_version_or_404():
    db = _RouteDb(None)
    resp = await _get(db, f"/api/v1/story-props/{CLOSEUP_ID}/data?size=large")
    assert resp.status_code == 404
    assert resp.json()["detail"]["error"] == "story_prop_not_found"
    assert "story_library_assets.image_large" in db.sql
    assert (
        await _get(_RouteDb(b"x"), f"/api/v1/story-props/{STICKER_ID}/data?size=huge")
    ).status_code == 422


# -- Serving (the story routes) -----------------------------------------------------


class _Savepoint:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _ServeDb(FakeSession):
    def begin_nested(self):
        return _Savepoint()


async def test_story_props_dispatches_the_unresolved_phrases(monkeypatch):
    from app.api.v1 import story_courses

    dispatched = []

    async def dispatch(keys):
        dispatched.append(keys)
        return "task"

    monkeypatch.setattr(story_courses, "dispatch_story_props_resolution", dispatch)
    view = _view()
    db = _ServeDb(
        [
            (
                "woven straw basket",
                "sticker",
                STICKER_ID,
                view.kind,
                view.label,
                300,
                280,
                7300,
                "CC0-1.0",
                False,
                view.credit,
                view.source,
                False,
            )
        ]
    )
    content = {
        "props": [
            {"id": "basket", "kind": "sticker", "query": "woven straw basket"},
            {"id": "snail", "kind": "real", "query": "garden snail"},
        ]
    }
    media = await story_courses._story_props(db, content)
    assert media.status == "partial" and list(media.props) == ["basket"]
    assert dispatched == [[("garden snail", "real")]]
    # The offline download never dispatches.
    dispatched.clear()
    await story_courses._story_props(_ServeDb([]), content, may_dispatch=False)
    assert dispatched == []


async def test_story_props_never_fails_the_story(monkeypatch):
    from app.api.v1 import story_courses

    class Broken(_ServeDb):
        async def execute(self, statement):
            raise RuntimeError("relation does not exist")

    content = {"props": [{"id": "basket", "kind": "sticker", "query": "basket"}]}
    media = await story_courses._story_props(Broken(), content)
    assert media.props == {} and media.status == "none" and media.unresolved == []
    assert (await story_courses._story_props(Broken(), {"props": []})).status == "none"


def test_the_dispatch_key_ignores_order():
    one = story_props_dispatch_key([("a", "sticker"), ("b", "real")])
    two = story_props_dispatch_key([["b", "real"], ["a", "sticker"]])
    assert one == two and one.startswith("story_props_dispatch:")
    assert one != story_props_dispatch_key([("a", "real"), ("b", "sticker")])


# -- Migration ----------------------------------------------------------------------

MIGRATION = (
    Path(__file__).resolve().parents[1] / "migrations" / "versions" / "112_story_prop_library.py"
)


class _RecordingOp:
    def __init__(self):
        self.tables: dict[str, list[Any]] = {}

    def create_table(self, name, *elements, **_kw):
        self.tables[name] = list(elements)


@pytest.fixture(scope="module")
def migration():
    spec = importlib.util.spec_from_file_location("migration_112", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    recorder = _RecordingOp()
    module.op = recorder
    module.upgrade()
    return module, recorder


def test_migration_revision_chain(migration):
    module, _ = migration
    assert module.revision == "112_story_prop_library"
    assert module.down_revision == "111_story_line_audio"
    assert len(module.revision) <= 32


@pytest.mark.parametrize("model", [StoryLibraryAsset, StoryPropMatch])
def test_migration_columns_match_the_models(migration, model):
    _, recorder = migration
    table = model.__table__
    columns = {e.name: e for e in recorder.tables[table.name] if isinstance(e, sa.Column)}
    assert set(columns) == {c.name for c in table.columns}
    dialect = sa.dialects.postgresql.dialect()
    for name, column in columns.items():
        assert column.nullable == table.columns[name].nullable, name
        assert column.primary_key == table.columns[name].primary_key, name
        assert column.type.compile(dialect=dialect) == table.columns[name].type.compile(
            dialect=dialect
        ), name
    checks = {e.name for e in recorder.tables[table.name] if isinstance(e, sa.CheckConstraint)}
    assert checks == {c.name for c in table.constraints if isinstance(c, sa.CheckConstraint)}


def test_a_deleted_asset_turns_its_matches_into_misses(migration):
    _, recorder = migration
    asset = next(
        e for e in recorder.tables["story_prop_matches"] if getattr(e, "name", "") == "asset_id"
    )
    (fk,) = asset.foreign_keys
    assert fk.target_fullname == "story_library_assets.id" and fk.ondelete == "SET NULL"
