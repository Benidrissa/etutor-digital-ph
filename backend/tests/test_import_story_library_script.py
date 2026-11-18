"""scripts/import_story_library.py: loading the asset foundry's output (Phase A).

The folder is built in a temporary directory the way the foundry writes it
(``library.json`` and WebP files); the database is faked. The script's own
logic is which entries it refuses, what it does with each slug (insert,
replace with a new id, refresh, prune) and that it clears the cached matches.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "import_story_library.py"
_spec = importlib.util.spec_from_file_location("import_story_library", _SCRIPT)
script = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = script
_spec.loader.exec_module(script)

CREDIT = {"en": "3D model: Quaternius (CC0 1.0)", "fr": "Modèle 3D : Quaternius (CC0 1.0)"}
SOURCE = {"author": "Quaternius", "license": "CC0-1.0", "page": "https://poly.pizza/m/x"}


def _entry(slug, kind="sticker", licence="CC0-1.0", **extra):
    files = {"src": {"file": f"{slug}.webp"}}
    if kind == "closeup":
        files["src_large"] = {"file": f"{slug}@960.webp"}
    entry = {
        "id": slug,
        "kind": kind,
        "label": {"en": slug, "fr": slug},
        "tags": [slug, ""],
        "files": files,
        "width": 300,
        "height": 200,
        "licence": licence,
        "attribution_required": licence != "CC0-1.0",
        "credit": CREDIT,
        "source": SOURCE,
    }
    entry.update(extra)
    return entry


def _folder(tmp_path: Path, entries, *, missing=()) -> Path:
    for entry in entries:
        for file in (entry.get("files") or {}).values():
            if file["file"] not in missing:
                (tmp_path / file["file"]).write_bytes(b"RIFF" + file["file"].encode())
    (tmp_path / "library.json").write_text(
        json.dumps({"library_version": 3, "entries": entries}), encoding="utf-8"
    )
    return tmp_path


@pytest.mark.parametrize(
    ("kind", "licence", "problem"),
    [
        ("sticker", "CC0-1.0", None),
        ("sticker", "PDM", None),
        ("closeup", "CC-BY-4.0", None),
        ("closeup", "CC-BY-SA-4.0", None),
        ("sticker", "CC-BY-SA-4.0", "share-alike is close-up only"),
        ("closeup", "CC-BY-NC-4.0", "licence CC-BY-NC-4.0 is not served"),
        ("sticker", "", "licence (none) is not served"),
    ],
)
def test_licence_rules(kind, licence, problem):
    assert script.licence_problem(kind, licence) == problem


def test_load_folder_refuses_what_the_library_may_not_serve(tmp_path):
    entries = [
        _entry("frog"),
        _entry("heart", kind="closeup", licence="CC-BY-4.0"),
        _entry("mask", kind="closeup", licence="CC-BY-NC-SA-4.0"),
        _entry("rug", licence="CC-BY-SA-4.0"),
        _entry("no_credit", credit={"en": "only English"}),
        _entry("no_page", source={"author": "x"}),
        _entry("lost"),
        _entry("frog"),
        _entry("Bad Id"),
        _entry("odd", kind="poster"),
    ]
    accepted, refused = script.load_folder(_folder(tmp_path, entries, missing={"lost.webp"}))
    assert [entry.slug for entry in accepted] == ["frog", "heart"]
    assert [line.split(":")[0] for line in refused] == [
        "mask",
        "rug",
        "no_credit",
        "no_page",
        "lost",
        "frog",
        "Bad Id",
        "odd",
    ]
    frog, heart = accepted
    assert frog.image == b"RIFFfrog.webp" and frog.image_large is None
    assert heart.image_large == b"RIFFheart@960.webp"
    assert frog.tags == ["frog"] and frog.library_version == 3
    assert frog.sha256 != script.Incoming(**{**frog.__dict__, "image": b"other"}).sha256


def test_plan_import_keeps_ids_of_unchanged_pictures(tmp_path):
    accepted, _ = script.load_folder(
        _folder(tmp_path, [_entry("frog"), _entry("bee"), _entry("new")])
    )
    frog, bee, new = accepted
    frog_id, bee_id, old_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    existing = {"frog": (frog_id, frog.sha256), "bee": (bee_id, "changed"), "old": (old_id, "x")}
    plan = script.plan_import(existing, accepted, prune=True)
    assert [e.slug for e in plan.insert] == ["new"]
    assert [(i, e.slug) for i, e in plan.replace] == [(bee_id, "bee")]
    assert [(i, e.slug) for i, e in plan.refresh] == [(frog_id, "frog")]
    assert plan.prune == [(old_id, "old")]
    assert script.plan_import(existing, accepted, prune=False).prune == []


class FakeSession:
    def __init__(self, existing=()):
        self.existing = list(existing)
        self.statements = []
        self.added = []
        self.committed = False

    async def execute(self, statement):
        self.statements.append(statement)
        if isinstance(statement, sa.Select):
            rows = self.existing
            return type("R", (), {"all": lambda _self: list(rows)})()
        return None

    def add(self, row):
        self.added.append(row)

    async def commit(self):
        self.committed = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _sql(statement) -> str:
    return str(statement.compile(dialect=sa.dialects.postgresql.dialect()))


async def test_main_dry_run_writes_nothing(tmp_path, capsys):
    folder = _folder(tmp_path, [_entry("frog"), _entry("mask", licence="CC-BY-NC-4.0")])
    session = FakeSession()
    code = await script.main([str(folder), "--dry-run"], session_factory=lambda: session)
    assert code == 0 and not session.committed and not session.added
    out = capsys.readouterr().out
    assert "refused mask" in out and "1 accepted, 1 refused: 1 new" in out


async def test_main_imports_replaces_prunes_and_clears_the_matches(tmp_path):
    folder = _folder(tmp_path, [_entry("frog"), _entry("bee")])
    accepted, _ = script.load_folder(folder)
    frog_id, bee_id, old_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    session = FakeSession(
        [("frog", frog_id, accepted[0].sha256), ("bee", bee_id, "x"), ("old", old_id, "y")]
    )
    embedded = []

    async def embed(entries):
        embedded.append([e.slug for e in entries])
        return {e.slug: [0.1, 0.2] for e in entries}

    code = await script.main([str(folder), "--prune"], session_factory=lambda: session, embed=embed)
    assert code == 0 and session.committed
    assert embedded == [["frog", "bee"]]
    (bee,) = session.added
    assert bee.slug == "bee" and bee.id not in (bee_id, old_id) and bee.embedding == [0.1, 0.2]
    assert bee.content_sha256 == accepted[1].sha256 and bee.bytes == len(accepted[1].image)
    sql = [_sql(s) for s in session.statements[1:]]
    assert sql[0].startswith("DELETE FROM story_library_assets")  # replaced bee and pruned old
    assert any(s.startswith("UPDATE story_library_assets") for s in sql)  # frog keeps its id
    assert sql[-1] == "DELETE FROM story_prop_matches"


async def test_main_without_library_json(tmp_path, capsys):
    assert await script.main([str(tmp_path)], session_factory=FakeSession) == 2
    assert "library.json not found" in capsys.readouterr().err


async def test_the_foundry_output_imports_as_is(tmp_path):
    """The foundry's own library.json shape (infrastructure/asset-foundry/postprocess.py)."""
    entries = [
        {
            "id": "heart",
            "kind": "closeup",
            "label": {"en": "the heart", "fr": "le cœur"},
            "tags": ["heart", "organ"],
            "files": {
                "src": {"file": "heart.webp", "bytes": 9},
                "src_large": {"file": "heart@960.webp", "bytes": 9},
            },
            "width": 595,
            "height": 567,
            "licence": "CC-BY-4.0",
            "attribution_required": True,
            "ai_restyle_allowed": True,
            "credit": {
                "en": "“Heart” by X, CC BY 4.0, GitHub.",
                "fr": "« Heart » de X, CC BY 4.0, GitHub.",
            },
            "source": {
                "author": "X",
                "license": "CC-BY-4.0",
                "page": "https://github.com/x",
                "site": "GitHub",
            },
            "model_sha256": "ab" * 32,
            "library_version": 1,
        }
    ]
    accepted, refused = script.load_folder(_folder(tmp_path, entries))
    assert (
        refused == []
        and accepted[0].attribution_required
        and accepted[0].source["site"] == "GitHub"
    )


class _CountSession(FakeSession):
    async def execute(self, statement):
        self.statements.append(statement)
        if isinstance(statement, sa.Select):
            return type("R", (), {"scalar_one": lambda _self: 78})()
        return None


async def test_reset_misses_clears_only_the_misses(capsys):
    session = _CountSession()
    code = await script.main(["--reset-misses"], session_factory=lambda: session)
    assert code == 0 and session.committed
    count, delete = [_sql(s) for s in session.statements]
    assert "count(*)" in count and "asset_id IS NULL" in count
    assert delete.startswith("DELETE FROM story_prop_matches") and "asset_id IS NULL" in delete
    assert "78 cached misses cleared" in capsys.readouterr().out


async def test_reset_misses_dry_run_writes_nothing(capsys):
    session = _CountSession()
    assert await script.main(["--reset-misses", "--dry-run"], session_factory=lambda: session) == 0
    assert not session.committed and len(session.statements) == 1
    assert "78 cached misses would be cleared" in capsys.readouterr().out


async def test_main_needs_a_folder_or_reset_misses():
    assert await script.main([], session_factory=FakeSession) == 2
