"""Add module_units table with M01-M03 unit definitions

Revision ID: 0d1135672916
Revises: 9f4db5f73f90
Create Date: 2026-04-01 02:12:57.565136
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0d1135672916"
down_revision: str | None = "9f4db5f73f90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Create module_units table
    op.create_table(
        "module_units",
        sa.Column("id", sa.UUID(), primary_key=True, default=sa.text("gen_random_uuid()")),
        sa.Column("module_id", sa.UUID(), sa.ForeignKey("modules.id"), nullable=False),
        sa.Column("unit_number", sa.String(10), nullable=False),
        sa.Column("title_fr", sa.Text(), nullable=False),
        sa.Column("title_en", sa.Text(), nullable=False),
        sa.Column("description_fr", sa.Text()),
        sa.Column("description_en", sa.Text()),
        sa.Column("estimated_minutes", sa.Integer(), server_default="45"),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("NOW()")),
        sa.UniqueConstraint("module_id", "unit_number", name="uq_module_unit_number"),
        sa.Index("idx_module_units_module_id", "module_id"),
    )

    # Seed M01-M03 units (3 units per module as shown in API examples)
    op.execute("""
        WITH module_m01 AS (SELECT id FROM modules WHERE module_number = 1),
             module_m02 AS (SELECT id FROM modules WHERE module_number = 2),
             module_m03 AS (SELECT id FROM modules WHERE module_number = 3)
        INSERT INTO module_units
        (module_id, unit_number, title_fr, title_en, description_fr, description_en, estimated_minutes, order_index)
        VALUES
        -- M01: Fondements de la Santé Publique
        ((SELECT id FROM module_m01), '1.1', 'Histoire et définition de la santé publique', 'History and definition of public health',
         'Evolution de la santé publique, définitions clés, cadre conceptuel moderne',
         'Evolution of public health, key definitions, modern conceptual framework', 45, 1),
        ((SELECT id FROM module_m01), '1.2', 'Principes de prévention et promotion', 'Prevention and promotion principles',
         'Prévention primaire, secondaire, tertiaire et promotion de la santé',
         'Primary, secondary, tertiary prevention and health promotion', 50, 2),
        ((SELECT id FROM module_m01), '1.3', 'Systèmes de santé et déterminants', 'Health systems and determinants',
         'Introduction aux systèmes de santé et déterminants sociaux de la santé',
         'Introduction to health systems and social determinants of health', 50, 3),

        -- M02: Introduction aux Données de Santé & Statistiques
        ((SELECT id FROM module_m02), '2.1', 'Types de données en santé publique', 'Types of public health data',
         'Données quantitatives/qualitatives, sources primaires/secondaires',
         'Quantitative/qualitative data, primary/secondary sources', 40, 1),
        ((SELECT id FROM module_m02), '2.2', 'Statistiques descriptives appliquées', 'Applied descriptive statistics',
         'Mesures de tendance centrale, dispersion, présentation des données',
         'Measures of central tendency, dispersion, data presentation', 55, 2),
        ((SELECT id FROM module_m02), '2.3', 'Indicateurs de santé et interprétation', 'Health indicators and interpretation',
         'Taux, ratios, proportions et interprétation des indicateurs de santé',
         'Rates, ratios, proportions and interpretation of health indicators', 50, 3),

        -- M03: Systèmes de Santé en Afrique de l'Ouest
        ((SELECT id FROM module_m03), '3.1', 'Architecture des systèmes de santé CEDEAO', 'ECOWAS health systems architecture',
         'Structure et organisation des systèmes de santé dans la région',
         'Structure and organization of health systems in the region', 45, 1),
        ((SELECT id FROM module_m03), '3.2', 'Financement et gouvernance', 'Financing and governance',
         'Mécanismes de financement, gouvernance et politiques de santé',
         'Financing mechanisms, governance and health policies', 50, 2),
        ((SELECT id FROM module_m03), '3.3', 'Défis et opportunités', 'Challenges and opportunities',
         'Défis actuels et innovations dans les systèmes de santé AOF',
         'Current challenges and innovations in West African health systems', 40, 3)
    """)


def downgrade() -> None:
    op.drop_table("module_units")
