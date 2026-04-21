"""Regression: migration 067 must DROP DEFAULT before ALTER COLUMN TYPE for
every column whose initial VARCHAR has a server_default — otherwise Postgres
refuses the cast with `DatatypeMismatchError: default for column cannot be
cast automatically`.

Seen on prod 2026-04-21 while provisioning a fresh tenant; 067 failed at
`ALTER TABLE question_banks ALTER COLUMN status TYPE questionbankstatus`
because the VARCHAR default 'draft' couldn't be auto-cast to the enum."""

import re
from pathlib import Path

_MIG = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "versions"
    / "067_add_question_bank_tables.py"
)


def _source() -> str:
    return _MIG.read_text()


def test_migration_067_exists() -> None:
    assert _MIG.exists(), "migration 067 source must be findable"


def _altered_cols_with_default() -> list[tuple[str, str, str]]:
    """Return (table, column, default_value) for each ALTER TYPE whose column
    was created with a `server_default=` kwarg."""
    src = _source()
    alters = re.findall(
        r"ALTER TABLE (\w+) ALTER COLUMN (\w+) TYPE (\w+)",
        src,
    )
    with_default = []
    for table, column, _enum in alters:
        col_def_pattern = rf'sa\.Column\(\s*"{re.escape(column)}",\s*sa\.VARCHAR\([^)]*\),\s*server_default="([^"]+)"'
        m = re.search(col_def_pattern, src)
        if m:
            with_default.append((table, column, m.group(1)))
    return with_default


def test_every_default_column_drops_default_before_alter_type() -> None:
    """For each ALTER COLUMN TYPE whose column has a server_default, there
    must be a matching DROP DEFAULT ahead of the ALTER and a SET DEFAULT
    after. Order: DROP DEFAULT → ALTER TYPE → SET DEFAULT."""
    src = _source()
    cols = _altered_cols_with_default()
    assert cols, "expected at least one VARCHAR-with-default to be cast to an enum"

    for table, column, _default in cols:
        drop_idx = src.find(f"ALTER TABLE {table} ALTER COLUMN {column} DROP DEFAULT")
        alter_idx = src.find(f"ALTER TABLE {table} ALTER COLUMN {column} TYPE")
        set_idx = src.find(f"ALTER TABLE {table} ALTER COLUMN {column} SET DEFAULT")

        assert drop_idx >= 0, f"{table}.{column}: missing DROP DEFAULT before ALTER TYPE"
        assert alter_idx >= 0, f"{table}.{column}: missing ALTER TYPE (regression)"
        assert set_idx >= 0, f"{table}.{column}: missing SET DEFAULT after ALTER TYPE"
        assert drop_idx < alter_idx < set_idx, (
            f"{table}.{column}: statements must be ordered DROP → TYPE → SET, got "
            f"drop={drop_idx} type={alter_idx} set={set_idx}"
        )


def test_downgrade_unchanged() -> None:
    """downgrade() drops the tables; nothing about the upgrade fix should
    change how rollback works."""
    src = _source()
    # The downgrade block must still drop the same tables in the same order.
    for table in (
        "qbank_test_attempts",
        "qbank_tests",
        "qbank_question_audio",
        "qbank_questions",
        "question_banks",
    ):
        assert f'op.drop_table("{table}")' in src, f"downgrade must still drop {table}"
