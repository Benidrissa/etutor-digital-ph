#!/usr/bin/env python3
"""
Create a new migration for the module_units table.
"""

import os
from datetime import datetime

# Get next migration number
migrations_dir = "migrations/versions"
existing_files = [f for f in os.listdir(migrations_dir) if f.endswith(".py")]
numbers = []
for f in existing_files:
    if f[:3].isdigit():
        numbers.append(int(f[:3]))

next_number = max(numbers) + 1 if numbers else 11

migration_content = f'''"""Create module_units table for unit-level content organization.

Revision ID: {next_number:03d}_create_module_units
Revises: 010_add_placement_test_attempts_table 
Create Date: {datetime.now().strftime('%Y-%m-%d')}
"""

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.sql import column, table

revision: str = "{next_number:03d}_create_module_units"
down_revision: str | None = "010_add_placement_test_attempts_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create module_units table and seed with M01-M03 units."""
    # Create the module_units table
    op.create_table(
        "module_units",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("module_id", sa.String, sa.ForeignKey("modules.id"), nullable=False),
        sa.Column("unit_number", sa.Integer, nullable=False),
        sa.Column("unit_id", sa.String, nullable=False),  # e.g., "1.1", "1.2"
        sa.Column("title_fr", sa.String, nullable=False),
        sa.Column("title_en", sa.String, nullable=False),
        sa.Column("description_fr", sa.String, nullable=False),
        sa.Column("description_en", sa.String, nullable=False),
        sa.Column("learning_objectives", sa.JSON, nullable=True),
        sa.Column("estimated_minutes", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    # Create composite index for efficient queries
    op.create_index("idx_module_units_module_unit", "module_units", ["module_id", "unit_id"], unique=True)

    # Now seed with M01-M03 unit data
    module_units_table = table(
        "module_units",
        column("id", sa.String),
        column("module_id", sa.String), 
        column("unit_number", sa.Integer),
        column("unit_id", sa.String),
        column("title_fr", sa.String),
        column("title_en", sa.String), 
        column("description_fr", sa.String),
        column("description_en", sa.String),
        column("learning_objectives", sa.String),
        column("estimated_minutes", sa.Integer),
    )

    # Get module IDs (we'll need to look these up)
    # For now, we'll use subqueries to find the module IDs by module_number

    units_data = []

    # M01 Units - Foundations of Public Health
    m01_units = [
        {{
            "id": str(uuid4()),
            "unit_number": 1,
            "unit_id": "1.1", 
            "title_fr": "Définition et Histoire de la Santé Publique",
            "title_en": "Definition and History of Public Health",
            "description_fr": "Les concepts fondamentaux, l'évolution historique et les figures marquantes de la santé publique mondiale et en Afrique.",
            "description_en": "Fundamental concepts, historical evolution and key figures in global public health and in Africa.",
            "learning_objectives": '{{"fr": ["Définir la santé publique selon l\'OMS", "Identifier les étapes historiques majeures", "Reconnaître les pionniers AOF"], "en": ["Define public health according to WHO", "Identify major historical stages", "Recognize West African pioneers"]}}',
            "estimated_minutes": 45,
        }},
        {{
            "id": str(uuid4()),
            "unit_number": 2,
            "unit_id": "1.2",
            "title_fr": "Déterminants Sociaux de la Santé",
            "title_en": "Social Determinants of Health",
            "description_fr": "L'impact des facteurs socioéconomiques, culturels et environnementaux sur la santé des populations en Afrique de l'Ouest.",
            "description_en": "The impact of socioeconomic, cultural and environmental factors on population health in West Africa.",
            "learning_objectives": '{{"fr": ["Analyser les inégalités de santé", "Évaluer l\'impact de la pauvreté", "Proposer des interventions sociales"], "en": ["Analyze health inequalities", "Evaluate poverty impact", "Propose social interventions"]}}',
            "estimated_minutes": 50,
        }},
        {{
            "id": str(uuid4()),
            "unit_number": 3,
            "unit_id": "1.3",
            "title_fr": "Approches de la Santé Publique",
            "title_en": "Public Health Approaches",
            "description_fr": "Les stratégies préventives, curatives et promotionnelles de santé publique adaptées au contexte ouest-africain.",
            "description_en": "Preventive, curative and health promotion strategies adapted to the West African context.",
            "learning_objectives": '{{"fr": ["Distinguer prévention primaire/secondaire/tertiaire", "Appliquer l\'approche One Health", "Planifier des interventions communautaires"], "en": ["Distinguish primary/secondary/tertiary prevention", "Apply One Health approach", "Plan community interventions"]}}',
            "estimated_minutes": 55,
        }},
    ]

    # M02 Units - Health Data & Statistics
    m02_units = [
        {{
            "id": str(uuid4()),
            "unit_number": 1,
            "unit_id": "2.1",
            "title_fr": "Types et Sources de Données de Santé",
            "title_en": "Types and Sources of Health Data",
            "description_fr": "Identification, collecte et évaluation des différentes sources de données sanitaires disponibles en AOF.",
            "description_en": "Identification, collection and evaluation of different health data sources available in West Africa.",
            "learning_objectives": '{{"fr": ["Classifier les données de santé", "Évaluer la qualité des sources", "Utiliser DHIS2 et enquêtes DHS"], "en": ["Classify health data", "Evaluate source quality", "Use DHIS2 and DHS surveys"]}}',
            "estimated_minutes": 40,
        }},
        {{
            "id": str(uuid4()),
            "unit_number": 2,
            "unit_id": "2.2",
            "title_fr": "Statistiques Descriptives en Santé",
            "title_en": "Descriptive Statistics in Health",
            "description_fr": "Calcul et interprétation des mesures de tendance centrale, dispersion et distribution pour les données sanitaires.",
            "description_en": "Calculation and interpretation of measures of central tendency, dispersion and distribution for health data.",
            "learning_objectives": '{{"fr": ["Calculer moyenne, médiane, mode", "Interpréter écart-type et percentiles", "Créer des graphiques descriptifs"], "en": ["Calculate mean, median, mode", "Interpret standard deviation and percentiles", "Create descriptive graphs"]}}',
            "estimated_minutes": 60,
        }},
        {{
            "id": str(uuid4()),
            "unit_number": 3,
            "unit_id": "2.3",
            "title_fr": "Introduction aux Probabilités",
            "title_en": "Introduction to Probability", 
            "description_fr": "Concepts de base des probabilités appliqués aux phénomènes de santé et aux tests diagnostiques.",
            "description_en": "Basic probability concepts applied to health phenomena and diagnostic tests.",
            "learning_objectives": '{{"fr": ["Calculer des probabilités simples", "Appliquer le théorème de Bayes", "Évaluer sensibilité/spécificité"], "en": ["Calculate simple probabilities", "Apply Bayes theorem", "Evaluate sensitivity/specificity"]}}',
            "estimated_minutes": 65,
        }},
    ]

    # M03 Units - Health Systems in West Africa  
    m03_units = [
        {{
            "id": str(uuid4()),
            "unit_number": 1,
            "unit_id": "3.1",
            "title_fr": "Architecture des Systèmes de Santé CEDEAO",
            "title_en": "ECOWAS Health Systems Architecture",
            "description_fr": "Structure, organisation et fonctionnement des systèmes de santé dans les pays de la CEDEAO.",
            "description_en": "Structure, organization and functioning of health systems in ECOWAS countries.",
            "learning_objectives": '{{"fr": ["Cartographier les niveaux de soins", "Analyser les flux de patients", "Comparer les modèles nationaux"], "en": ["Map levels of care", "Analyze patient flows", "Compare national models"]}}',
            "estimated_minutes": 50,
        }},
        {{
            "id": str(uuid4()),
            "unit_number": 2,
            "unit_id": "3.2",
            "title_fr": "Financement et Couverture Sanitaire",
            "title_en": "Health Financing and Coverage",
            "description_fr": "Mécanismes de financement, assurance maladie et couverture sanitaire universelle en Afrique de l'Ouest.",
            "description_en": "Financing mechanisms, health insurance and universal health coverage in West Africa.",
            "learning_objectives": '{{"fr": ["Analyser les sources de financement", "Évaluer l\'équité financière", "Planifier la CSU"], "en": ["Analyze financing sources", "Evaluate financial equity", "Plan UHC"]}}',
            "estimated_minutes": 55,
        }},
        {{
            "id": str(uuid4()),
            "unit_number": 3,
            "unit_id": "3.3",
            "title_fr": "Performance et Gouvernance",
            "title_en": "Performance and Governance",
            "description_fr": "Évaluation de la performance des systèmes de santé et mécanismes de gouvernance en AOF.",
            "description_en": "Health systems performance evaluation and governance mechanisms in West Africa.", 
            "learning_objectives": '{{"fr": ["Utiliser le cadre OMS de performance", "Mesurer l\'efficience", "Renforcer la gouvernance"], "en": ["Use WHO performance framework", "Measure efficiency", "Strengthen governance"]}}',
            "estimated_minutes": 60,
        }},
    ]

    # Combine all units
    all_units = []

    # Add M01 units
    for unit in m01_units:
        unit["module_id"] = "(SELECT id FROM modules WHERE module_number = 1 LIMIT 1)"
        all_units.append(unit)

    # Add M02 units  
    for unit in m02_units:
        unit["module_id"] = "(SELECT id FROM modules WHERE module_number = 2 LIMIT 1)"
        all_units.append(unit)

    # Add M03 units
    for unit in m03_units:
        unit["module_id"] = "(SELECT id FROM modules WHERE module_number = 3 LIMIT 1)"
        all_units.append(unit)

    # Insert units using individual INSERT statements with subqueries
    for unit in all_units:
        op.execute(f"""
            INSERT INTO module_units (id, module_id, unit_number, unit_id, title_fr, title_en, description_fr, description_en, learning_objectives, estimated_minutes)
            VALUES (
                '{{unit["id"]}}',
                (SELECT id FROM modules WHERE module_number = {{"1" if unit["unit_id"].startswith("1") else "2" if unit["unit_id"].startswith("2") else "3"}} LIMIT 1),
                {{unit["unit_number"]}},
                '{{unit["unit_id"]}}',
                '{{unit["title_fr"]}}',
                '{{unit["title_en"]}}',
                '{{unit["description_fr"]}}',
                '{{unit["description_en"]}}',
                '{{unit["learning_objectives"]}}',
                {{unit["estimated_minutes"]}}
            )
        """)


def downgrade() -> None:
    """Drop module_units table."""
    op.drop_index("idx_module_units_module_unit")
    op.drop_table("module_units")
'''

with open(f"{migrations_dir}/{next_number:03d}_create_module_units.py", "w") as f:
    f.write(migration_content)

print(f"Created migration: {next_number:03d}_create_module_units.py")