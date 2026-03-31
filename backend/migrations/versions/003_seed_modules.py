"""Seed 15 learning modules M01-M15 from syllabus.

Revision ID: 003_seed_modules
Revises: 002_rls_policies
Create Date: 2026-03-30
"""

from collections.abc import Sequence

from alembic import op

revision: str = "003_seed_modules"
down_revision: str | None = "002_rls_policies"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO modules (id, module_number, level, title_fr, title_en, description_fr, description_en, estimated_hours, bloom_level)
        VALUES
        (gen_random_uuid(), 1, 1, 'Fondements de la Sante Publique', 'Foundations of Public Health', 'Concepts, histoire et vision globale de la sante publique en contexte AOF', 'Concepts, history and global vision of public health in West African context', 20, 'Remember'),
        (gen_random_uuid(), 2, 1, 'Introduction aux Donnees de Sante & Statistiques', 'Introduction to Health Data & Statistics', 'Comprendre, collecter et lire les donnees de sante — bases du raisonnement statistique', 'Understanding, collecting and reading health data — basics of statistical reasoning', 22, 'Understand'),
        (gen_random_uuid(), 3, 1, 'Systemes de Sante en Afrique de l''Ouest', 'Health Systems in West Africa', 'Architecture, financement et performance des systemes de sante des pays CEDEAO', 'Architecture, financing and performance of health systems in ECOWAS countries', 18, 'Understand'),
        (gen_random_uuid(), 4, 2, 'Epidemiologie Appliquee', 'Applied Epidemiology', 'Mesurer la maladie dans les populations — methodes et indicateurs pour la sante publique en AOF', 'Measuring disease in populations — methods and indicators for public health in West Africa', 25, 'Apply'),
        (gen_random_uuid(), 5, 2, 'Biostatistiques pour la Sante Publique', 'Biostatistics for Public Health', 'Probabilites, distributions, estimation et tests d''hypothese appliques a la sante', 'Probabilities, distributions, estimation and hypothesis testing applied to health', 28, 'Apply'),
        (gen_random_uuid(), 6, 2, 'Maladies et Determinants en AOF', 'Diseases & Health Determinants in West Africa', 'Profil epidemiologique, maladies prioritaires et determinants sociaux en Afrique de l''Ouest', 'Epidemiological profile, priority diseases and social determinants in West Africa', 22, 'Analyze'),
        (gen_random_uuid(), 7, 2, 'Outils et Pratiques de Sante Publique', 'Public Health Tools & Practice', 'Leadership, evaluation communautaire, performance, gestion des donnees de sante', 'Leadership, community assessment, performance, health data management', 20, 'Apply'),
        (gen_random_uuid(), 8, 3, 'Surveillance Epidemiologique Numerique', 'Digital Epidemiological Surveillance', 'Systemes de surveillance, alerte precoce et donnees en temps reel pour la riposte en AOF', 'Surveillance systems, early warning and real-time data for response in West Africa', 22, 'Analyze'),
        (gen_random_uuid(), 9, 3, 'Statistiques Avancees et Analyse de Donnees', 'Advanced Statistics & Data Analysis', 'Regression, ANOVA, tests non-parametriques, analyse de survie pour la recherche en sante', 'Regression, ANOVA, non-parametric tests, survival analysis for health research', 28, 'Analyze'),
        (gen_random_uuid(), 10, 3, 'Sante Numerique et Systemes d''Information Sanitaire', 'Digital Health & Health Information Systems', 'Technologies numeriques pour la sante en AOF : DHIS2, mHealth, IA, interoperabilite', 'Digital technologies for health in West Africa: DHIS2, mHealth, AI, interoperability', 20, 'Apply'),
        (gen_random_uuid(), 11, 3, 'Sante Environnementale et One Health', 'Environmental Health & One Health', 'Changement climatique, eau, assainissement, interface animal-humain-environnement en AOF', 'Climate change, water, sanitation, animal-human-environment interface in West Africa', 16, 'Analyze'),
        (gen_random_uuid(), 12, 3, 'Sante Maternelle, Infantile et Communautaire', 'Maternal, Child & Community Health', 'Reduire la mortalite maternelle et infantile — SMNI et sante communautaire en AOF', 'Reducing maternal and child mortality — MCH and community health in West Africa', 20, 'Apply'),
        (gen_random_uuid(), 13, 4, 'Leadership, Politique et Gouvernance', 'Leadership, Policy & Governance', 'Elaborer et influencer des politiques de sante publique en Afrique de l''Ouest', 'Developing and influencing public health policies in West Africa', 22, 'Evaluate'),
        (gen_random_uuid(), 14, 4, 'Recherche et Evaluation Avancees', 'Advanced Research & Evaluation', 'Concevoir, conduire et evaluer la recherche en sante publique et les programmes de sante', 'Designing, conducting and evaluating public health research and health programs', 24, 'Evaluate'),
        (gen_random_uuid(), 15, 4, 'Projet Integratif Capstone', 'Integrative Capstone Project', 'Synthese de toutes les competences — projet de sante publique numerique pour un district AOF reel', 'Synthesis of all skills — digital public health project for a real West African district', 24, 'Create')
    """)


def downgrade() -> None:
    op.execute("DELETE FROM modules WHERE module_number BETWEEN 1 AND 15")
