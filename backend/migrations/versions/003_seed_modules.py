"""Seed 15 learning modules M01-M15 from syllabus.

Revision ID: 003_seed_modules
Revises: 002_rls_policies
Create Date: 2026-03-30
"""

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.sql import column, table

revision: str = "003_seed_modules"
down_revision: str | None = "002_rls_policies"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    modules_table = table(
        "modules",
        column("id", sa.Uuid),
        column("module_number", sa.Integer),
        column("level", sa.Integer),
        column("title_fr", sa.String),
        column("title_en", sa.String),
        column("description_fr", sa.String),
        column("description_en", sa.String),
        column("estimated_hours", sa.Integer),
        column("bloom_level", sa.String),
        column("prereq_modules", sa.String),
        column("books_sources", sa.String),
    )

    modules = [
        # === Level 1 — Beginner (60h) ===
        {
            "id": uuid4(),
            "module_number": 1,
            "level": 1,
            "title_fr": "Fondements de la Sante Publique",
            "title_en": "Foundations of Public Health",
            "description_fr": "Concepts, histoire et vision globale de la sante publique en contexte AOF",
            "description_en": "Concepts, history and global vision of public health in West African context",
            "estimated_hours": 20,
            "bloom_level": "Remember",
            "prereq_modules": "{}",
            "books_sources": '{"donaldson": ["ch1", "ch13"], "scutchfield": ["ch1", "ch2", "ch3", "ch4"]}',
        },
        {
            "id": uuid4(),
            "module_number": 2,
            "level": 1,
            "title_fr": "Introduction aux Donnees de Sante & Statistiques",
            "title_en": "Introduction to Health Data & Statistics",
            "description_fr": "Comprendre, collecter et lire les donnees de sante — bases du raisonnement statistique",
            "description_en": "Understanding, collecting and reading health data — basics of statistical reasoning",
            "estimated_hours": 22,
            "bloom_level": "Understand",
            "prereq_modules": "{}",
            "books_sources": '{"triola": ["ch1", "ch2", "ch3"], "donaldson": ["ch2"], "scutchfield": ["ch13"]}',
        },
        {
            "id": uuid4(),
            "module_number": 3,
            "level": 1,
            "title_fr": "Systemes de Sante en Afrique de l'Ouest",
            "title_en": "Health Systems in West Africa",
            "description_fr": "Architecture, financement et performance des systemes de sante des pays CEDEAO",
            "description_en": "Architecture, financing and performance of health systems in ECOWAS countries",
            "estimated_hours": 18,
            "bloom_level": "Understand",
            "prereq_modules": "{}",
            "books_sources": '{"donaldson": ["ch6"], "scutchfield": ["ch6", "ch7", "ch8", "ch28"]}',
        },
        # === Level 2 — Intermediate (90h) ===
        {
            "id": uuid4(),
            "module_number": 4,
            "level": 2,
            "title_fr": "Epidemiologie Appliquee",
            "title_en": "Applied Epidemiology",
            "description_fr": "Mesurer la maladie dans les populations — methodes et indicateurs pour la sante publique en AOF",
            "description_en": "Measuring disease in populations — methods and indicators for public health in West Africa",
            "estimated_hours": 25,
            "bloom_level": "Apply",
            "prereq_modules": "{}",
            "books_sources": '{"donaldson": ["ch2"], "scutchfield": ["ch11", "ch13"]}',
        },
        {
            "id": uuid4(),
            "module_number": 5,
            "level": 2,
            "title_fr": "Biostatistiques pour la Sante Publique",
            "title_en": "Biostatistics for Public Health",
            "description_fr": "Probabilites, distributions, estimation et tests d'hypothese appliques a la sante",
            "description_en": "Probabilities, distributions, estimation and hypothesis testing applied to health",
            "estimated_hours": 28,
            "bloom_level": "Apply",
            "prereq_modules": "{}",
            "books_sources": '{"triola": ["ch4", "ch5", "ch6", "ch7", "ch8", "ch9"]}',
        },
        {
            "id": uuid4(),
            "module_number": 6,
            "level": 2,
            "title_fr": "Maladies et Determinants en AOF",
            "title_en": "Diseases & Health Determinants in West Africa",
            "description_fr": "Profil epidemiologique, maladies prioritaires et determinants sociaux en Afrique de l'Ouest",
            "description_en": "Epidemiological profile, priority diseases and social determinants in West Africa",
            "estimated_hours": 22,
            "bloom_level": "Analyze",
            "prereq_modules": "{}",
            "books_sources": '{"donaldson": ["ch3", "ch4", "ch5"], "scutchfield": ["ch17", "ch18", "ch22", "ch25"]}',
        },
        {
            "id": uuid4(),
            "module_number": 7,
            "level": 2,
            "title_fr": "Outils et Pratiques de Sante Publique",
            "title_en": "Public Health Tools & Practice",
            "description_fr": "Leadership, evaluation communautaire, performance, gestion des donnees de sante",
            "description_en": "Leadership, community assessment, performance, health data management",
            "estimated_hours": 20,
            "bloom_level": "Apply",
            "prereq_modules": "{}",
            "books_sources": '{"scutchfield": ["ch9", "ch10", "ch11", "ch12", "ch14", "ch15", "ch16"]}',
        },
        # === Level 3 — Advanced (100h) ===
        {
            "id": uuid4(),
            "module_number": 8,
            "level": 3,
            "title_fr": "Surveillance Epidemiologique Numerique",
            "title_en": "Digital Epidemiological Surveillance",
            "description_fr": "Systemes de surveillance, alerte precoce et donnees en temps reel pour la riposte en AOF",
            "description_en": "Surveillance systems, early warning and real-time data for response in West Africa",
            "estimated_hours": 22,
            "bloom_level": "Analyze",
            "prereq_modules": "{}",
            "books_sources": '{"donaldson": ["ch2", "ch3"], "scutchfield": ["ch13"]}',
        },
        {
            "id": uuid4(),
            "module_number": 9,
            "level": 3,
            "title_fr": "Statistiques Avancees et Analyse de Donnees",
            "title_en": "Advanced Statistics & Data Analysis",
            "description_fr": "Regression, ANOVA, tests non-parametriques, analyse de survie pour la recherche en sante",
            "description_en": "Regression, ANOVA, non-parametric tests, survival analysis for health research",
            "estimated_hours": 28,
            "bloom_level": "Analyze",
            "prereq_modules": "{}",
            "books_sources": '{"triola": ["ch10", "ch11", "ch12", "ch13", "ch14"]}',
        },
        {
            "id": uuid4(),
            "module_number": 10,
            "level": 3,
            "title_fr": "Sante Numerique et Systemes d'Information Sanitaire",
            "title_en": "Digital Health & Health Information Systems",
            "description_fr": "Technologies numeriques pour la sante en AOF : DHIS2, mHealth, IA, interoperabilite",
            "description_en": "Digital technologies for health in West Africa: DHIS2, mHealth, AI, interoperability",
            "estimated_hours": 20,
            "bloom_level": "Apply",
            "prereq_modules": "{}",
            "books_sources": '{"scutchfield": ["ch13"]}',
        },
        {
            "id": uuid4(),
            "module_number": 11,
            "level": 3,
            "title_fr": "Sante Environnementale et One Health",
            "title_en": "Environmental Health & One Health",
            "description_fr": "Changement climatique, eau, assainissement, interface animal-humain-environnement en AOF",
            "description_en": "Climate change, water, sanitation, animal-human-environment interface in West Africa",
            "estimated_hours": 16,
            "bloom_level": "Analyze",
            "prereq_modules": "{}",
            "books_sources": '{"donaldson": ["ch12"], "scutchfield": ["ch23"]}',
        },
        {
            "id": uuid4(),
            "module_number": 12,
            "level": 3,
            "title_fr": "Sante Maternelle, Infantile et Communautaire",
            "title_en": "Maternal, Child & Community Health",
            "description_fr": "Reduire la mortalite maternelle et infantile — SMNI et sante communautaire en AOF",
            "description_en": "Reducing maternal and child mortality — MCH and community health in West Africa",
            "estimated_hours": 20,
            "bloom_level": "Apply",
            "prereq_modules": "{}",
            "books_sources": '{"donaldson": ["ch8"], "scutchfield": ["ch25"]}',
        },
        # === Level 4 — Expert (70h) ===
        {
            "id": uuid4(),
            "module_number": 13,
            "level": 4,
            "title_fr": "Leadership, Politique et Gouvernance",
            "title_en": "Leadership, Policy & Governance",
            "description_fr": "Elaborer et influencer des politiques de sante publique en Afrique de l'Ouest",
            "description_en": "Developing and influencing public health policies in West Africa",
            "estimated_hours": 22,
            "bloom_level": "Evaluate",
            "prereq_modules": "{}",
            "books_sources": '{"scutchfield": ["ch9", "ch16", "ch19", "ch29"], "donaldson": ["ch6", "ch7"]}',
        },
        {
            "id": uuid4(),
            "module_number": 14,
            "level": 4,
            "title_fr": "Recherche et Evaluation Avancees",
            "title_en": "Advanced Research & Evaluation",
            "description_fr": "Concevoir, conduire et evaluer la recherche en sante publique et les programmes de sante",
            "description_en": "Designing, conducting and evaluating public health research and health programs",
            "estimated_hours": 24,
            "bloom_level": "Evaluate",
            "prereq_modules": "{}",
            "books_sources": '{"triola": ["ch7", "ch8", "ch9", "ch10", "ch14"], "scutchfield": ["ch17", "ch12"]}',
        },
        {
            "id": uuid4(),
            "module_number": 15,
            "level": 4,
            "title_fr": "Projet Integratif Capstone",
            "title_en": "Integrative Capstone Project",
            "description_fr": "Synthese de toutes les competences — projet de sante publique numerique pour un district AOF reel",
            "description_en": "Synthesis of all skills — digital public health project for a real West African district",
            "estimated_hours": 24,
            "bloom_level": "Create",
            "prereq_modules": "{}",
            "books_sources": '{"donaldson": ["all"], "scutchfield": ["all"], "triola": ["all"]}',
        },
    ]

    op.bulk_insert(modules_table, modules)


def downgrade() -> None:
    op.execute("DELETE FROM modules WHERE module_number BETWEEN 1 AND 15")
