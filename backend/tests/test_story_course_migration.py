"""Guard against drift between the story_courses model and its migration.

The offline ``alembic upgrade --sql`` renderer in this project emits table DDL
without its column list (the production migration 104 renders the same way), so
it cannot verify a migration's columns. This instead runs the migration's
``upgrade()`` against a recording stand-in for ``op`` and compares what it would
create against what the SQLAlchemy model declares — which is the failure that
actually bites: a column present in one and missing from the other.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa

from app.domain.models.story_course import StoryCourseRecord

MIGRATION = (
    Path(__file__).resolve().parents[1] / "migrations" / "versions" / "105_add_story_courses.py"
)


class _RecordingOp:
    """Captures the DDL calls a migration makes instead of executing them."""

    def __init__(self) -> None:
        self.tables: dict[str, list[sa.Column]] = {}
        self.indexes: list[tuple[str, str, list[str]]] = []

    def create_table(self, name: str, *columns: Any, **_: Any) -> None:
        self.tables[name] = [c for c in columns if isinstance(c, sa.Column)]

    def create_index(self, name: str, table: str, columns: list[str], **_: Any) -> None:
        self.indexes.append((name, table, columns))

    # Not exercised by upgrade(), but present so a future edit does not crash.
    def drop_table(self, *_a: Any, **_k: Any) -> None: ...
    def drop_index(self, *_a: Any, **_k: Any) -> None: ...
    def get_bind(self) -> None:
        return None


@pytest.fixture(scope="module")
def recorded() -> _RecordingOp:
    spec = importlib.util.spec_from_file_location("migration_105", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    recorder = _RecordingOp()
    module.op = recorder  # type: ignore[attr-defined]
    module.upgrade()
    return recorder


def test_revision_chain():
    spec = importlib.util.spec_from_file_location("migration_105_meta", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "105_add_story_courses"
    assert module.down_revision == "104_add_ai_usage_events"


def test_creates_the_story_courses_table(recorded):
    assert set(recorded.tables) == {"story_courses"}


def test_migration_columns_match_the_model(recorded):
    migration_columns = {c.name for c in recorded.tables["story_courses"]}
    model_columns = {c.name for c in StoryCourseRecord.__table__.columns}
    assert migration_columns == model_columns, (
        f"only in migration: {sorted(migration_columns - model_columns)}; "
        f"only in model: {sorted(model_columns - migration_columns)}"
    )


def test_nullability_matches_the_model(recorded):
    migration = {c.name: bool(c.nullable) for c in recorded.tables["story_courses"]}
    model = {c.name: bool(c.nullable) for c in StoryCourseRecord.__table__.columns}
    assert migration == model


def test_slug_is_unique(recorded):
    slug = next(c for c in recorded.tables["story_courses"] if c.name == "slug")
    assert slug.unique is True
    assert StoryCourseRecord.__table__.columns["slug"].unique is True


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
    # Both foreign keys must survive compilation.
    assert ddl.count("REFERENCES") == 2
