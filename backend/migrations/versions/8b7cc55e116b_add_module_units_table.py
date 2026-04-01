"""add_module_units_table

Revision ID: 8b7cc55e116b
Revises: 9f4db5f73f90
Create Date: 2026-04-01 02:03:06.646642
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8b7cc55e116b"
down_revision: str | None = "9f4db5f73f90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "module_units",
        sa.Column("id", sa.UUID(), nullable=False, default=sa.text("gen_random_uuid()")),
        sa.Column("module_id", sa.UUID(), nullable=False),
        sa.Column("unit_number", sa.Integer(), nullable=False),
        sa.Column("title_fr", sa.String(), nullable=False),
        sa.Column("title_en", sa.String(), nullable=False),
        sa.Column("description_fr", sa.Text(), nullable=True),
        sa.Column("description_en", sa.Text(), nullable=True),
        sa.Column("estimated_minutes", sa.Integer(), nullable=False, default=30),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["module_id"], ["modules.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("module_id", "unit_number", name="uq_module_units_module_unit"),
    )

    op.create_index("idx_module_units_module_id", "module_units", ["module_id"])
    op.create_index("idx_module_units_order", "module_units", ["module_id", "order_index"])

    # Seed M01-M03 units (Levels 1 foundation modules)
    op.execute("""
        INSERT INTO module_units (module_id, unit_number, title_fr, title_en, description_fr, description_en, estimated_minutes, order_index)
        SELECT
            m.id as module_id,
            unit_data.unit_number,
            unit_data.title_fr,
            unit_data.title_en,
            unit_data.description_fr,
            unit_data.description_en,
            unit_data.estimated_minutes,
            unit_data.order_index
        FROM modules m
        CROSS JOIN (
            VALUES
            -- M01: Foundations of Public Health
            (1, 1, 'Introduction à la santé publique', 'Introduction to Public Health', 'Définitions, concepts fondamentaux et évolution de la santé publique', 'Definitions, fundamental concepts and evolution of public health', 45, 1),
            (1, 2, 'Déterminants sociaux de la santé', 'Social Determinants of Health', 'Facteurs socio-économiques, culturels et environnementaux influençant la santé', 'Socio-economic, cultural and environmental factors influencing health', 45, 2),
            (1, 3, 'Éthique en santé publique', 'Ethics in Public Health', 'Principes éthiques, droits humains et justice sanitaire', 'Ethical principles, human rights and health equity', 30, 3),

            -- M02: Health Information Systems
            (2, 1, 'Systèmes d''information sanitaire', 'Health Information Systems', 'Architecture, composants et fonctions des SIS', 'Architecture, components and functions of HIS', 60, 1),
            (2, 2, 'Collecte et gestion des données', 'Data Collection and Management', 'Méthodes de collecte, qualité et validation des données de santé', 'Collection methods, quality and validation of health data', 60, 2),
            (2, 3, 'Indicateurs de santé publique', 'Public Health Indicators', 'Construction, interprétation et utilisation des indicateurs', 'Construction, interpretation and use of indicators', 45, 3),

            -- M03: West African Health Systems
            (3, 1, 'Panorama des systèmes de santé AOF', 'Overview of West African Health Systems', 'Organisation, financement et défis des systèmes de santé régionaux', 'Organization, financing and challenges of regional health systems', 60, 1),
            (3, 2, 'Politiques de santé en Afrique de l''Ouest', 'Health Policies in West Africa', 'Politiques nationales, stratégies régionales et coopération sanitaire', 'National policies, regional strategies and health cooperation', 60, 2),
            (3, 3, 'Intégration et harmonisation', 'Integration and Harmonization', 'Initiatives d''intégration des systèmes et harmonisation des pratiques', 'System integration initiatives and practice harmonization', 45, 3)
        ) AS unit_data(module_number, unit_number, title_fr, title_en, description_fr, description_en, estimated_minutes, order_index)
        WHERE m.module_number = unit_data.module_number
        AND m.module_number IN (1, 2, 3);
    """)


def downgrade() -> None:
    op.drop_index("idx_module_units_order", table_name="module_units")
    op.drop_index("idx_module_units_module_id", table_name="module_units")
    op.drop_table("module_units")
