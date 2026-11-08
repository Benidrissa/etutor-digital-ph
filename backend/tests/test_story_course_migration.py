"""Guard against drift between the story_courses model and its migrations.

The offline ``alembic upgrade --sql`` renderer in this project emits table DDL
without its column list (the production migration 104 renders the same way), so
it cannot verify a migration's columns. This instead runs each migration's
``upgrade()`` against a recording stand-in for ``op`` and compares what the
migrations would create — 105 creates the table, 106 binds it to lesson units —
against what the SQLAlchemy model declares, which is the failure that actually
bites: a column present in one and missing from the other.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa

from app.domain.models.story_course import StoryCourseRecord

VERSIONS = Path(__file__).resolve().parents[1] / "migrations" / "versions"
MIGRATION_105 = VERSIONS / "105_add_story_courses.py"
MIGRATION_106 = VERSIONS / "106_add_story_unit_binding.py"

#: Columns migration 106 adds; every one must stay nullable so hand-authored
#: weeks are untouched.
BINDING_COLUMNS = {
    "module_id",
    "module_unit_id",
    "language",
    "source_lesson_content_id",
    "source_lesson_revision",
    "source_quiz_content_id",
    "source_quiz_revision",
    "source_lesson_digest",
    "source_quiz_digest",
}


class _RecordingOp:
    """Captures the DDL calls a migration makes instead of executing them."""

    def __init__(self) -> None:
        self.tables: dict[str, list[sa.Column]] = {}
        self.added: dict[str, list[sa.Column]] = {}
        self.indexes: list[tuple[str, str, list[str]]] = []
        self.unique_constraints: list[tuple[str, str, list[str]]] = []

    def create_table(self, name: str, *columns: Any, **_: Any) -> None:
        self.tables[name] = [c for c in columns if isinstance(c, sa.Column)]

    def add_column(self, table: str, column: sa.Column, **_: Any) -> None:
        self.added.setdefault(table, []).append(column)

    def create_index(self, name: str, table: str, columns: list[str], **_: Any) -> None:
        self.indexes.append((name, table, columns))

    def create_unique_constraint(self, name: str, table: str, columns: list[str], **_: Any) -> None:
        self.unique_constraints.append((name, table, columns))

    def columns(self, table: str) -> list[sa.Column]:
        return self.tables.get(table, []) + self.added.get(table, [])

    # Not exercised by upgrade(), but present so a future edit does not crash.
    def drop_table(self, *_a: Any, **_k: Any) -> None: ...
    def drop_index(self, *_a: Any, **_k: Any) -> None: ...
    def drop_column(self, *_a: Any, **_k: Any) -> None: ...
    def drop_constraint(self, *_a: Any, **_k: Any) -> None: ...
    def get_bind(self) -> None:
        return None


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def recorded() -> _RecordingOp:
    """Replay 105 then 106 into one recorder: the table as the head defines it."""
    recorder = _RecordingOp()
    for path, name in ((MIGRATION_105, "migration_105"), (MIGRATION_106, "migration_106")):
        module = _load(path, name)
        module.op = recorder  # type: ignore[attr-defined]
        module.upgrade()
    return recorder


@pytest.fixture(scope="module")
def recorded_106() -> _RecordingOp:
    recorder = _RecordingOp()
    module = _load(MIGRATION_106, "migration_106_only")
    module.op = recorder  # type: ignore[attr-defined]
    module.upgrade()
    return recorder


def test_revision_chain():
    module = _load(MIGRATION_105, "migration_105_meta")
    assert module.revision == "105_add_story_courses"
    assert module.down_revision == "104_add_ai_usage_events"


def test_106_revision_chain():
    module = _load(MIGRATION_106, "migration_106_meta")
    assert module.revision == "106_add_story_unit_binding"
    assert module.down_revision == "105_add_story_courses"
    # alembic_version.version_num is VARCHAR(32).
    assert len(module.revision) <= 32


def test_creates_the_story_courses_table(recorded):
    assert set(recorded.tables) == {"story_courses"}
    assert set(recorded.added) == {"story_courses"}


def test_migration_columns_match_the_model(recorded):
    migration_columns = {c.name for c in recorded.columns("story_courses")}
    model_columns = {c.name for c in StoryCourseRecord.__table__.columns}
    assert migration_columns == model_columns, (
        f"only in migration: {sorted(migration_columns - model_columns)}; "
        f"only in model: {sorted(model_columns - migration_columns)}"
    )


def test_106_adds_exactly_the_binding_columns(recorded_106):
    assert {c.name for c in recorded_106.added["story_courses"]} == BINDING_COLUMNS


def test_binding_columns_are_nullable(recorded_106):
    """Hand-authored weeks carry none of them, so none may be NOT NULL."""
    for column in recorded_106.added["story_courses"]:
        assert column.nullable is True, column.name
        assert StoryCourseRecord.__table__.columns[column.name].nullable is True


def test_nullability_matches_the_model(recorded):
    migration = {c.name: bool(c.nullable) for c in recorded.columns("story_courses")}
    model = {c.name: bool(c.nullable) for c in StoryCourseRecord.__table__.columns}
    assert migration == model


def test_column_types_match_the_model(recorded):
    """A type drift (e.g. Integer vs SmallInteger for a revision) is a real bug."""
    migration = {c.name: type(c.type).__name__ for c in recorded.columns("story_courses")}
    for name in BINDING_COLUMNS:
        model_type = type(StoryCourseRecord.__table__.columns[name].type).__name__
        migration_type = migration[name]
        # The model spells UUID columns via the generic Uuid type.
        if model_type in ("Uuid", "UUID"):
            assert migration_type in ("Uuid", "UUID"), name
        else:
            assert migration_type == model_type, name


def test_foreign_keys_match_the_model(recorded):
    def fks(columns):
        out = {}
        for column in columns:
            for fk in column.foreign_keys:
                out[column.name] = (fk.target_fullname, fk.ondelete)
        return out

    migration = fks(recorded.columns("story_courses"))
    model = fks(StoryCourseRecord.__table__.columns)
    assert migration == model
    assert migration["module_unit_id"] == ("module_units.id", "CASCADE")
    assert migration["source_lesson_content_id"] == ("generated_content.id", "SET NULL")
    assert migration["source_quiz_content_id"] == ("generated_content.id", "SET NULL")


def test_slug_is_unique(recorded):
    slug = next(c for c in recorded.columns("story_courses") if c.name == "slug")
    assert slug.unique is True
    assert StoryCourseRecord.__table__.columns["slug"].unique is True


def test_unit_language_unique_constraint_matches_the_model(recorded):
    migration = {(name, tuple(cols)) for name, _table, cols in recorded.unique_constraints}
    model = {
        (constraint.name, tuple(c.name for c in constraint.columns))
        for constraint in StoryCourseRecord.__table__.constraints
        if isinstance(constraint, sa.UniqueConstraint) and constraint.name
    }
    assert (
        migration == model == {("uq_story_courses_unit_language", ("module_unit_id", "language"))}
    )


def test_indexes_match_the_model(recorded):
    migration_indexes = {(name, tuple(cols)) for name, _table, cols in recorded.indexes}
    model_indexes = {
        (index.name, tuple(c.name for c in index.columns))
        for index in StoryCourseRecord.__table__.indexes
    }
    assert migration_indexes == model_indexes


def test_model_ddl_compiles_for_postgres():
    """The model's own CREATE TABLE must render as valid PostgreSQL."""
    ddl = str(
        sa.schema.CreateTable(StoryCourseRecord.__table__).compile(
            dialect=sa.dialects.postgresql.dialect()
        )
    )
    assert "CREATE TABLE story_courses" in ddl
    assert "content JSONB NOT NULL" in ddl
    assert "story_course_status_enum" in ddl
    # course, author, module, unit, lesson source and quiz source.
    assert ddl.count("REFERENCES") == 6
    assert "UNIQUE (module_unit_id, language)" in ddl
