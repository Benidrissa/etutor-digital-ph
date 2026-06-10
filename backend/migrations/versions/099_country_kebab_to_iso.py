"""Normalize users.country from kebab slugs to ISO 3166-1 alpha-2 codes

The onboarding flow historically stored country as kebab slugs ("senegal",
"burkina-faso", "other-west-african", "other") while registration/profile and
the AI content pipeline use ISO codes ("SN", "BF", "OWA", "OTH"). The selectors
are now unified on ISO codes (see frontend/lib/countries.ts), so this migration
converts any already-stored kebab values to their ISO equivalents. Rows already
holding ISO codes (or NULL) are untouched.

Revision ID: 099_country_kebab_to_iso
Revises: 098_payment_provider_columns
Create Date: 2026-06-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "099_country_kebab_to_iso"
down_revision: str | None = "098_payment_provider_columns"
branch_labels = None
depends_on = None


# kebab slug -> ISO 3166-1 alpha-2 code (OWA/OTH are the catch-all options)
KEBAB_TO_ISO = {
    "benin": "BJ",
    "burkina-faso": "BF",
    "cabo-verde": "CV",
    "cote-divoire": "CI",
    "gambia": "GM",
    "ghana": "GH",
    "guinea": "GN",
    "guinea-bissau": "GW",
    "liberia": "LR",
    "mali": "ML",
    "niger": "NE",
    "nigeria": "NG",
    "senegal": "SN",
    "sierra-leone": "SL",
    "togo": "TG",
    "other-west-african": "OWA",
    "other": "OTH",
}


def upgrade() -> None:
    conn = op.get_bind()
    stmt = sa.text("UPDATE users SET country = :iso WHERE country = :kebab")
    for kebab, iso in KEBAB_TO_ISO.items():
        conn.execute(stmt, {"iso": iso, "kebab": kebab})


def downgrade() -> None:
    conn = op.get_bind()
    stmt = sa.text("UPDATE users SET country = :kebab WHERE country = :iso")
    for kebab, iso in KEBAB_TO_ISO.items():
        conn.execute(stmt, {"kebab": kebab, "iso": iso})
