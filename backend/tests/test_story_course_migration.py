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
import uuid
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa

from app.domain.models import Base
from app.domain.models.story_course import StoryCourseRecord
from tests._story_db import create_tables, scratch_database, story_tables, sync_engine

BACKEND = Path(__file__).resolve().parents[1]
VERSIONS = BACKEND / "migrations" / "versions"
MIGRATION_105 = VERSIONS / "105_add_story_courses.py"
MIGRATION_106 = VERSIONS / "106_add_story_unit_binding.py"
MIGRATION_107 = VERSIONS / "107_story_module_binding.py"

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

#: Columns migration 107 adds: a module story's manifest and roster digest.
MODULE_COLUMNS = {"source_rows", "source_units_digest"}

MODULE_STORY_INDEX = "uq_story_courses_module_story"
MODULE_ROWS_DELETE = (
    "DELETE FROM story_courses WHERE module_id IS NOT NULL AND module_unit_id IS NULL"
)


class _RecordingOp:
    """Captures the DDL calls a migration makes instead of executing them."""

    def __init__(self) -> None:
        self.tables: dict[str, list[sa.Column]] = {}
        self.added: dict[str, list[sa.Column]] = {}
        self.indexes: list[tuple[str, str, list[str]]] = []
        #: ``create_index`` keyword arguments by index name (unique, where…).
        self.index_options: dict[str, dict[str, Any]] = {}
        self.unique_constraints: list[tuple[str, str, list[str]]] = []
        #: Every call in order, as ``(operation, first argument)``.
        self.calls: list[tuple[str, Any]] = []

    def create_table(self, name: str, *columns: Any, **_: Any) -> None:
        self.calls.append(("create_table", name))
        self.tables[name] = [c for c in columns if isinstance(c, sa.Column)]

    def add_column(self, table: str, column: sa.Column, **_: Any) -> None:
        self.calls.append(("add_column", column.name))
        self.added.setdefault(table, []).append(column)

    def create_index(self, name: str, table: str, columns: list[str], **kwargs: Any) -> None:
        self.calls.append(("create_index", name))
        self.indexes.append((name, table, columns))
        self.index_options[name] = kwargs

    def create_unique_constraint(self, name: str, table: str, columns: list[str], **_: Any) -> None:
        self.calls.append(("create_unique_constraint", name))
        self.unique_constraints.append((name, table, columns))

    def execute(self, statement: Any, *_a: Any, **_k: Any) -> None:
        self.calls.append(("execute", str(statement)))

    def columns(self, table: str) -> list[sa.Column]:
        return self.tables.get(table, []) + self.added.get(table, [])

    def drop_table(self, name: str, *_a: Any, **_k: Any) -> None:
        self.calls.append(("drop_table", name))

    def drop_index(self, name: str, *_a: Any, **_k: Any) -> None:
        self.calls.append(("drop_index", name))

    def drop_column(self, _table: str, name: str, *_a: Any, **_k: Any) -> None:
        self.calls.append(("drop_column", name))

    def drop_constraint(self, name: str, *_a: Any, **_k: Any) -> None:
        self.calls.append(("drop_constraint", name))

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
    """Replay 105, 106 then 107 into one recorder: the table as the head defines it."""
    recorder = _RecordingOp()
    for path, name in (
        (MIGRATION_105, "migration_105"),
        (MIGRATION_106, "migration_106"),
        (MIGRATION_107, "migration_107"),
    ):
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


@pytest.fixture(scope="module")
def recorded_107() -> _RecordingOp:
    recorder = _RecordingOp()
    module = _load(MIGRATION_107, "migration_107_only")
    module.op = recorder  # type: ignore[attr-defined]
    module.upgrade()
    return recorder


@pytest.fixture(scope="module")
def downgraded_107() -> _RecordingOp:
    recorder = _RecordingOp()
    module = _load(MIGRATION_107, "migration_107_down")
    module.op = recorder  # type: ignore[attr-defined]
    module.downgrade()
    return recorder


def _where(clause: Any) -> str:
    """A partial index's WHERE clause as SQL text."""
    return (
        str(clause.compile(dialect=sa.dialects.postgresql.dialect())) if clause is not None else ""
    )


def _model_index(name: str) -> sa.Index:
    return next(i for i in StoryCourseRecord.__table__.indexes if i.name == name)


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


def test_107_revision_chain():
    module = _load(MIGRATION_107, "migration_107_meta")
    assert module.revision == "107_story_module_binding"
    assert module.down_revision == "106_add_story_unit_binding"
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


def test_107_adds_exactly_the_module_columns(recorded_107):
    added = recorded_107.added["story_courses"]
    assert {c.name for c in added} == MODULE_COLUMNS
    for column in added:
        assert column.nullable is True, column.name
        assert StoryCourseRecord.__table__.columns[column.name].nullable is True
    types = {c.name: c.type for c in added}
    assert isinstance(types["source_rows"], sa.dialects.postgresql.JSONB)
    assert isinstance(types["source_units_digest"], sa.String)
    assert types["source_units_digest"].length == 64
    assert StoryCourseRecord.__table__.columns["source_units_digest"].type.length == 64


def test_107_creates_the_partial_unique_index_of_the_model(recorded_107):
    assert recorded_107.indexes == [
        (MODULE_STORY_INDEX, "story_courses", ["module_id", "language"])
    ]
    options = recorded_107.index_options[MODULE_STORY_INDEX]
    assert options["unique"] is True
    assert _where(options["postgresql_where"]) == "module_unit_id IS NULL"

    model = _model_index(MODULE_STORY_INDEX)
    assert [c.name for c in model.columns] == ["module_id", "language"]
    assert model.unique is True
    assert _where(model.dialect_options["postgresql"]["where"]) == "module_unit_id IS NULL"
    # Nothing else: the 106 constraint and index stay as they are.
    assert recorded_107.unique_constraints == []


def test_107_downgrade_deletes_the_module_stories_first(downgraded_107):
    """At 106 a row with no unit is a public hand-authored week: delete them first."""
    assert downgraded_107.calls == [
        ("execute", "LOCK TABLE story_courses IN ACCESS EXCLUSIVE MODE"),
        ("execute", MODULE_ROWS_DELETE),
        ("drop_index", MODULE_STORY_INDEX),
        ("drop_column", "source_units_digest"),
        ("drop_column", "source_rows"),
    ]


def test_the_rollback_runbook_downgrades_107_before_an_older_image_runs():
    """An image rollback runs no downgrade: the runbook must, or module stories leak.

    Before 107, a row with ``module_id`` set and no unit is a hand-authored
    week, listed and served publicly. The documented rollback is an image
    swap, so ``DEPLOY.md`` must say to downgrade (or delete those rows) first.
    """
    deploy = BACKEND.parent / "DEPLOY.md"
    if not deploy.exists():
        pytest.skip("DEPLOY.md is not in this checkout")
    text = deploy.read_text(encoding="utf-8")
    start = text.index("\n## Rollback")
    end = text.index("\n## ", start + 1)
    rollback = text[start:end]
    downgrade = "uv run alembic downgrade 106_add_story_unit_binding"
    assert downgrade in rollback
    assert MODULE_ROWS_DELETE.removeprefix("DELETE FROM story_courses WHERE ") in rollback
    # With the current image, before the older one starts.
    assert "before the swap" in rollback and "before the older image starts" in rollback


def test_nullability_matches_the_model(recorded):
    migration = {c.name: bool(c.nullable) for c in recorded.columns("story_courses")}
    model = {c.name: bool(c.nullable) for c in StoryCourseRecord.__table__.columns}
    assert migration == model


def test_column_types_match_the_model(recorded):
    """A type drift (e.g. Integer vs SmallInteger for a revision) is a real bug."""
    migration = {c.name: type(c.type).__name__ for c in recorded.columns("story_courses")}
    for name in BINDING_COLUMNS | MODULE_COLUMNS:
        model_type = type(StoryCourseRecord.__table__.columns[name].type).__name__
        migration_type = migration[name]
        # The model spells UUID columns via the generic Uuid type.
        if model_type in ("Uuid", "UUID"):
            assert migration_type in ("Uuid", "UUID"), name
        else:
            assert migration_type == model_type, name


def test_timestamp_time_zones_match_the_model(recorded):
    """A naive model column over a TIMESTAMPTZ column drifts in autogenerate
    and round-trips values without their offset."""
    migration = {
        c.name: c.type.timezone
        for c in recorded.columns("story_courses")
        if isinstance(c.type, sa.DateTime)
    }
    model = {
        c.name: c.type.timezone
        for c in StoryCourseRecord.__table__.columns
        if isinstance(c.type, sa.DateTime)
    }
    assert migration == model
    assert model == {"created_at": True, "updated_at": True}


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
    """Names, columns, uniqueness and partial-index predicates alike."""
    migration_indexes = {
        (
            name,
            tuple(cols),
            bool(recorded.index_options[name].get("unique")),
            _where(recorded.index_options[name].get("postgresql_where")),
        )
        for name, _table, cols in recorded.indexes
    }
    model_indexes = {
        (
            index.name,
            tuple(c.name for c in index.columns),
            bool(index.unique),
            _where(index.dialect_options["postgresql"]["where"]),
        )
        for index in StoryCourseRecord.__table__.indexes
    }
    assert migration_indexes == model_indexes
    assert (MODULE_STORY_INDEX, ("module_id", "language"), True, "module_unit_id IS NULL") in (
        model_indexes
    )


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
    assert "source_rows JSONB" in ddl
    assert "source_units_digest VARCHAR(64)" in ddl
    index = str(
        sa.schema.CreateIndex(_model_index(MODULE_STORY_INDEX)).compile(
            dialect=sa.dialects.postgresql.dialect()
        )
    )
    assert index == (
        "CREATE UNIQUE INDEX uq_story_courses_module_story ON story_courses "
        "(module_id, language) WHERE module_unit_id IS NULL"
    )


# --------------------------------------------------------------------------
# The real migrations on a scratch PostgreSQL database
# --------------------------------------------------------------------------


def _alembic_config():
    from alembic.config import Config

    # No ini file: env.py then leaves the test run's logging alone.
    config = Config()
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    return config


def _story_row(**values: Any) -> dict[str, Any]:
    row = {
        "id": uuid.uuid4(),
        "course_label": "Course",
        "week": 1,
        "title": {"en": "T", "fr": "T"},
        "languages": {"target": "en", "home": "fr"},
        "format_version": "story-course/1",
        "content": {},
    }
    row.update(values)
    return row


def test_107_on_postgres_upgrades_enforces_and_downgrades(monkeypatch):
    """Upgrade 106 -> 107, one module story per (module, language), downgrade, re-upgrade."""
    from alembic import command

    from app.infrastructure.config.settings import settings

    with scratch_database("story_mig") as url:
        # pgvector is not needed: the tables 105-107 reference are created from
        # the models, the history before 105 is stamped, and 105, 106 and 107
        # then run for real.
        create_tables(url, story_tables(without={"story_courses"}))
        monkeypatch.setattr(settings, "database_url", url)
        config = _alembic_config()
        command.stamp(config, "104_add_ai_usage_events")
        command.upgrade(config, "106_add_story_unit_binding")
        command.upgrade(config, "head")

        engine = sync_engine(url)
        tables = Base.metadata.tables
        story = tables["story_courses"]
        module_id, other_module_id = uuid.uuid4(), uuid.uuid4()
        units = [uuid.uuid4(), uuid.uuid4()]
        try:
            with engine.begin() as conn:
                version = conn.execute(sa.text("SELECT version_num FROM alembic_version"))
                assert version.scalar_one() == "107_story_module_binding"
                index = conn.execute(
                    sa.text("SELECT indexdef FROM pg_indexes WHERE indexname = :name"),
                    {"name": MODULE_STORY_INDEX},
                ).scalar_one()
                assert index == (
                    "CREATE UNIQUE INDEX uq_story_courses_module_story ON public.story_courses "
                    "USING btree (module_id, language) WHERE (module_unit_id IS NULL)"
                )
                for number, mid in ((901, module_id), (902, other_module_id)):
                    conn.execute(
                        tables["modules"]
                        .insert()
                        .values(id=mid, module_number=number, level=1, title_fr="M", title_en="M")
                    )
                for index_, uid in enumerate(units):
                    conn.execute(
                        tables["module_units"]
                        .insert()
                        .values(
                            id=uid,
                            module_id=module_id,
                            unit_number=f"1.{index_ + 1}",
                            title_fr="U",
                            title_en="U",
                            order_index=index_,
                        )
                    )
                rows = [
                    _story_row(slug="authored-w1"),
                    *(
                        _story_row(
                            slug=f"lesson-{uid.hex}-en",
                            module_id=module_id,
                            module_unit_id=uid,
                            language="en",
                        )
                        for uid in units
                    ),
                    _story_row(
                        slug=f"module-{module_id.hex}-en",
                        module_id=module_id,
                        language="en",
                        source_rows={"assembler": 1, "units": []},
                        source_units_digest="0" * 64,
                    ),
                    # The other language, and another module: both allowed.
                    _story_row(
                        slug=f"module-{module_id.hex}-fr", module_id=module_id, language="fr"
                    ),
                    _story_row(
                        slug=f"module-{other_module_id.hex}-en",
                        module_id=other_module_id,
                        language="en",
                    ),
                ]
                for row in rows:  # one by one: an executemany takes the first row's keys
                    conn.execute(story.insert().values(**row))

            # A second module story for the same module and language is refused.
            with (
                pytest.raises(sa.exc.IntegrityError, match=MODULE_STORY_INDEX),
                engine.begin() as conn,
            ):
                conn.execute(
                    story.insert().values(
                        **_story_row(slug="another-module-row", module_id=module_id, language="en")
                    )
                )

            def kinds() -> dict[str, str]:
                """slug -> row kind, read back from the table."""
                query = sa.text(
                    "SELECT slug, CASE WHEN module_id IS NULL THEN 'authored'"
                    " WHEN module_unit_id IS NOT NULL THEN 'chapter' ELSE 'module' END"
                    " FROM story_courses"
                )
                with engine.connect() as conn:
                    return dict(conn.execute(query).tuples().all())

            before = kinds()
            assert sorted(before.values()) == ["authored", "chapter", "chapter"] + ["module"] * 3

            def slugs() -> set[str]:
                return set(kinds())

            command.downgrade(config, "106_add_story_unit_binding")
            module_slugs = {slug for slug, kind in before.items() if kind == "module"}
            assert {slug for slug in module_slugs if slug.startswith("module-")} == module_slugs
            # Only the module stories went; authored and chapter rows are untouched.
            assert kinds() == {s: k for s, k in before.items() if k != "module"}
            columns = {c["name"] for c in sa.inspect(engine).get_columns("story_courses")}
            assert not MODULE_COLUMNS & columns
            assert MODULE_STORY_INDEX not in {
                i["name"] for i in sa.inspect(engine).get_indexes("story_courses")
            }

            command.upgrade(config, "head")
            inspector = sa.inspect(engine)
            columns = {c["name"] for c in inspector.get_columns("story_courses")}
            assert columns >= MODULE_COLUMNS
            assert MODULE_STORY_INDEX in {i["name"] for i in inspector.get_indexes("story_courses")}
            assert slugs() == set(before) - module_slugs
        finally:
            engine.dispose()


def test_107_downgrade_deletes_a_module_story_a_merge_commits_meanwhile(monkeypatch):
    """The downgrade runs with the current image still serving (DEPLOY.md).

    A module story merge holds its transaction open from its first read of
    the chapter rows to the commit of the module row it inserts. A DELETE that
    took its snapshot before that commit would miss the row, and the
    downgrade would still succeed: at 106 the row is a public hand-authored
    week. The downgrade must wait for the merge, then delete.
    """
    import threading
    import time

    from alembic import command

    from app.infrastructure.config.settings import settings

    with scratch_database("story_mig_race") as url:
        create_tables(url, story_tables(without={"story_courses"}))
        monkeypatch.setattr(settings, "database_url", url)
        config = _alembic_config()
        command.stamp(config, "104_add_ai_usage_events")
        command.upgrade(config, "head")

        database = url.rsplit("/", 1)[1]
        engine = sync_engine(url)
        tables = Base.metadata.tables
        story = tables["story_courses"]
        module_id = uuid.uuid4()
        failures: list[BaseException] = []

        def downgrade() -> None:
            try:
                command.downgrade(config, "106_add_story_unit_binding")
            except BaseException as exc:  # reported by the test, not the thread
                failures.append(exc)

        rollback = threading.Thread(target=downgrade, daemon=True)
        try:
            with engine.begin() as conn:
                conn.execute(
                    tables["modules"]
                    .insert()
                    .values(id=module_id, module_number=903, level=1, title_fr="M", title_en="M")
                )
            with engine.connect() as merge, engine.connect() as monitor:
                transaction = merge.begin()
                # The merge reads the chapter rows first (its table lock is held
                # until it commits)...
                merge.execute(sa.text("SELECT count(*) FROM story_courses")).scalar_one()
                rollback.start()
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    waiting = monitor.execute(
                        sa.text(
                            "SELECT count(*) FROM pg_stat_activity"
                            " WHERE datname = :name AND wait_event_type = 'Lock'"
                        ),
                        {"name": database},
                    ).scalar_one()
                    monitor.commit()
                    if waiting:
                        break
                    time.sleep(0.02)
                else:
                    pytest.fail("the downgrade never waited on the merge")
                # ...then, with the downgrade under way, stores the module story.
                merge.execute(
                    story.insert().values(
                        **_story_row(
                            slug=f"module-{module_id.hex}-en",
                            module_id=module_id,
                            language="en",
                            status="published",
                            is_valid=True,
                            source_rows={"assembler": 1, "units": []},
                            source_units_digest="0" * 64,
                        )
                    )
                )
                transaction.commit()
            rollback.join(timeout=30)
            assert not rollback.is_alive() and failures == []

            with engine.connect() as conn:
                version = conn.execute(sa.text("SELECT version_num FROM alembic_version"))
                assert version.scalar_one() == "106_add_story_unit_binding"
                leaked = conn.execute(
                    sa.text(
                        "SELECT slug FROM story_courses"
                        " WHERE module_id IS NOT NULL AND module_unit_id IS NULL"
                    )
                ).all()
            assert leaked == []
        finally:
            engine.dispose()
