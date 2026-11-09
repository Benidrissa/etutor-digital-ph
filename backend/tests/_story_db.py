"""A scratch PostgreSQL database for the story-mode tests that need a real one.

The shared ``test_engine`` fixture cannot create the whole schema (issue #554:
the ``certificatestatus`` enum is declared with ``create_type=False``), and
story tests need only a handful of tables. So each test module that needs a
real database creates its own: a fresh database on the server of
``DATABASE_URL`` (CI runs PostgreSQL 16), holding just the tables the story
pipeline touches and the tables they reference, dropped when the module is
done. Without a reachable server the tests are skipped, never failed.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Iterator
from contextlib import contextmanager

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import URL, make_url

import app.domain.models  # noqa: F401 — registers every model on Base.metadata
from app.domain.models import Base
from app.infrastructure.config.settings import settings

#: The tables story mode reads and writes; their foreign-key targets follow.
STORY_TABLE_ROOTS = (
    "story_courses",
    "generated_content",
    "module_units",
    "modules",
    "courses",
    "course_taxonomy",
)


def story_tables(*, without: Iterable[str] = ()) -> list[sa.Table]:
    """:data:`STORY_TABLE_ROOTS` and every table they reference (``create_all`` orders them)."""
    excluded = set(without)
    seen: set[str] = set()
    todo = list(STORY_TABLE_ROOTS)
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        todo.extend(fk.column.table.name for fk in Base.metadata.tables[name].foreign_keys)
    return [t for name, t in Base.metadata.tables.items() if name in seen and name not in excluded]


def _sync(url: URL) -> URL:
    return url.set(drivername="postgresql+psycopg2")


def sync_engine(url: str) -> sa.Engine:
    return sa.create_engine(_sync(make_url(url)), connect_args={"connect_timeout": 3})


@contextmanager
def scratch_database(prefix: str) -> Iterator[str]:
    """Create an empty database next to ``DATABASE_URL``'s; yield its asyncpg URL."""
    server = make_url(settings.database_url)
    name = f"{prefix}_{uuid.uuid4().hex[:12]}"
    admin = sa.create_engine(
        _sync(server), isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 3}
    )
    try:
        with admin.connect() as conn:
            conn.execute(sa.text(f'CREATE DATABASE "{name}"'))
    except sa.exc.SQLAlchemyError as exc:
        admin.dispose()
        pytest.skip(f"no PostgreSQL server to create a scratch database on: {exc}"[:300])
    try:
        yield server.set(drivername="postgresql+asyncpg", database=name).render_as_string(
            hide_password=False
        )
    finally:
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def create_tables(url: str, tables: list[sa.Table]) -> None:
    """``create_all`` of ``tables`` only — and of no enum type of any other table."""
    engine = sync_engine(url)
    wanted = {t.name for t in tables}
    try:
        Base.metadata.create_all(engine, tables=tables)
        # create_all makes every named enum of the metadata's tables it is
        # given and, through the metadata hook, of some others; drop the ones
        # no created table uses, so a migration can create them itself.
        foreign = {
            column.type.name
            for table in Base.metadata.tables.values()
            if table.name not in wanted
            for column in table.columns
            if isinstance(column.type, sa.Enum) and column.type.name
        } - {
            column.type.name
            for table in tables
            for column in table.columns
            if isinstance(column.type, sa.Enum) and column.type.name
        }
        with engine.begin() as conn:
            for name in sorted(foreign):
                conn.execute(sa.text(f'DROP TYPE IF EXISTS "{name}"'))
    finally:
        engine.dispose()
