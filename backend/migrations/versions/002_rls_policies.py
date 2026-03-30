"""Row Level Security policies for user data isolation.

Revision ID: 002_rls_policies
Revises: 001_initial_schema
Create Date: 2026-03-30
"""

from collections.abc import Sequence

from alembic import op

revision: str = "002_rls_policies"
down_revision: str | None = "001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Tables with user-scoped data that need RLS
_USER_TABLES = [
    "users",
    "user_module_progress",
    "quiz_attempts",
    "flashcard_reviews",
    "tutor_conversations",
]


def upgrade() -> None:
    # Users table — can only see own profile
    op.execute("ALTER TABLE users ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY users_isolation ON users
        USING (id = current_setting('app.current_user_id')::uuid)
    """)

    # User-scoped tables — filter by user_id
    for table in _USER_TABLES[1:]:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY {table}_isolation ON {table}
            USING (user_id = current_setting('app.current_user_id')::uuid)
        """)

    # Note: modules and generated_content are shared — no RLS needed


def downgrade() -> None:
    for table in reversed(_USER_TABLES):
        op.execute(f"DROP POLICY IF EXISTS {table}_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
