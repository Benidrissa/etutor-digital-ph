"""Detailed seed data for M01-M03 with units, learning objectives, and comprehensive metadata.

Revision ID: 006_detailed_m01_m03_seed
Revises: 005_lesson_readings_table
Create Date: 2026-03-30
"""

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.sql import column, table

revision: str = "006_detailed_m01_m03_seed"
down_revision: str | None = "005_lesson_readings_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Update M01-M03 modules with detailed metadata including units and learning objectives."""

    # First, let's delete the existing M01-M03 basic entries to replace with detailed ones
    op.execute("DELETE FROM modules WHERE module_number IN (1, 2, 3)")

    modules_table = table(
        "modules",
        column("id", sa.String),
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

    # Generate consistent UUIDs for modules to be referenced elsewhere
    m01_id = str(uuid4())
    m02_id = str(uuid4())
    m03_id = str(uuid4())

    detailed_modules = [
        # === M01 — Foundations of Public Health ===
        {
            "id": m01_id,
            "module_number": 1,
            "level": 1,
            "title_fr": "Fondements de la Santé Publique",
            "title_en": "Foundations of Public Health",
            "description_fr": "Ce que veut dire \"santé publique\" — concepts, histoire et vision globale en contexte AOF. Introduction aux définitions fondamentales, évolution historique de la discipline, grandes épidémies, déterminants de santé selon le modèle de Dahlgren & Whitehead, et les 10 fonctions essentielles de santé publique dans le contexte de l'Afrique de l'Ouest.",
            "description_en": 'What "public health" means — concepts, history and global vision in West African context. Introduction to fundamental definitions, historical evolution of the discipline, major epidemics, health determinants according to Dahlgren & Whitehead model, and the 10 essential public health functions in the West African context.',
            "estimated_hours": 20,
            "bloom_level": "Remember",
            "prereq_modules": "{}",
            "books_sources": sa.text("""'{{
                "donaldson": {{"chapters": ["ch1", "ch13"], "description": "Health in a changing world, History of public health"}},
                "scutchfield": {{"chapters": ["ch1", "ch2", "ch3", "ch4"], "description": "Public health foundations, concepts, determinants, legal framework"}},
                "units": [
                    {{
                        "unit_id": 1,
                        "title_fr": "Définitions et concepts fondamentaux",
                        "title_en": "Fundamental definitions and concepts",
                        "learning_objectives_fr": [
                            "Définir la santé publique et ses dimensions selon l'OMS et Donaldson",
                            "Distinguer santé, bien-être, santé publique et santé globale",
                            "Comprendre l'évolution de la discipline de l'hygiénisme à la santé numérique"
                        ],
                        "learning_objectives_en": [
                            "Define public health and its dimensions according to WHO and Donaldson",
                            "Distinguish between health, well-being, public health and global health",
                            "Understand the evolution of the discipline from hygienism to digital health"
                        ],
                        "duration_minutes": 240
                    }},
                    {{
                        "unit_id": 2,
                        "title_fr": "Histoire de la santé publique en Afrique de l'Ouest",
                        "title_en": "History of public health in West Africa",
                        "learning_objectives_fr": [
                            "Retracer l'histoire de la santé publique en AOF (épidémies coloniales, indépendances, SIDA)",
                            "Analyser les grandes épidémies historiques (choléra, Ebola AOF, COVID-19)",
                            "Comprendre l'épidémie Ebola 2014-2016 en Guinée, Sierra Leone, Libéria"
                        ],
                        "learning_objectives_en": [
                            "Trace the history of public health in West Africa (colonial epidemics, independence, AIDS)",
                            "Analyze major historical epidemics (cholera, Ebola West Africa, COVID-19)",
                            "Understand the 2014-2016 Ebola epidemic in Guinea, Sierra Leone, Liberia"
                        ],
                        "duration_minutes": 300
                    }},
                    {{
                        "unit_id": 3,
                        "title_fr": "Déterminants de la santé et modèle de Dahlgren & Whitehead",
                        "title_en": "Health determinants and Dahlgren & Whitehead model",
                        "learning_objectives_fr": [
                            "Identifier les déterminants de santé selon le modèle de Dahlgren & Whitehead",
                            "Appliquer le modèle des déterminants de santé dans le contexte AOF",
                            "Analyser les inégalités de santé en Afrique de l'Ouest"
                        ],
                        "learning_objectives_en": [
                            "Identify health determinants according to Dahlgren & Whitehead model",
                            "Apply the health determinants model in West African context",
                            "Analyze health inequalities in West Africa"
                        ],
                        "duration_minutes": 240
                    }},
                    {{
                        "unit_id": 4,
                        "title_fr": "Fonctions essentielles et cadre institutionnel",
                        "title_en": "Essential functions and institutional framework",
                        "learning_objectives_fr": [
                            "Comprendre les 10 fonctions essentielles de santé publique",
                            "Identifier le cadre légal et institutionnel : ministères de santé, OMS, OCEAC, WAHO/OOAS",
                            "Analyser le rôle de l'OOAS et de l'ECOWAS dans la gouvernance sanitaire régionale"
                        ],
                        "learning_objectives_en": [
                            "Understand the 10 essential public health functions",
                            "Identify the legal and institutional framework: health ministries, WHO, OCEAC, WAHO",
                            "Analyze the role of WAHO and ECOWAS in regional health governance"
                        ],
                        "duration_minutes": 240
                    }},
                    {{
                        "unit_id": 5,
                        "title_fr": "ODD et priorités de santé en AOF",
                        "title_en": "SDGs and health priorities in West Africa",
                        "learning_objectives_fr": [
                            "Relier les ODD aux priorités de santé en Afrique de l'Ouest",
                            "Analyser les indicateurs de santé CEDEAO 2024",
                            "Comprendre les défis et opportunités du développement durable en santé"
                        ],
                        "learning_objectives_en": [
                            "Link SDGs to health priorities in West Africa",
                            "Analyze ECOWAS 2024 health indicators",
                            "Understand challenges and opportunities for sustainable health development"
                        ],
                        "duration_minutes": 180
                    }}
                ]
            }}'"""),
        },
        # === M02 — Introduction to Health Data & Statistics ===
        {
            "id": m02_id,
            "module_number": 2,
            "level": 1,
            "title_fr": "Introduction aux Données de Santé & Statistiques",
            "title_en": "Introduction to Health Data & Statistics",
            "description_fr": "Comprendre, collecter et lire les données de santé — les bases du raisonnement statistique. Types de données, mesures de tendance centrale et de dispersion, sources de données de santé en AOF (DHIS2, HMIS, recensements), et introduction à l'analyse de données avec Excel/Google Sheets.",
            "description_en": "Understanding, collecting and reading health data — basics of statistical reasoning. Data types, measures of central tendency and dispersion, health data sources in West Africa (DHIS2, HMIS, censuses), and introduction to data analysis with Excel/Google Sheets.",
            "estimated_hours": 22,
            "bloom_level": "Understand",
            "prereq_modules": f'{{"{m01_id}"}}',
            "books_sources": sa.text("""'{{
                "triola": {{"chapters": ["ch1", "ch2", "ch3"], "description": "Introduction to Statistics, Exploration and description of data"}},
                "donaldson": {{"chapters": ["ch2"], "description": "Epidemiology and its uses - introduction"}},
                "scutchfield": {{"chapters": ["ch13"], "description": "Health Data Management"}},
                "units": [
                    {{
                        "unit_id": 1,
                        "title_fr": "Types de données et échelles de mesure",
                        "title_en": "Data types and measurement scales",
                        "learning_objectives_fr": [
                            "Distinguer les types de données (nominales, ordinales, continues, discrètes)",
                            "Comprendre les échelles de mesure et leur importance",
                            "Identifier les types de données appropriés pour différentes analyses"
                        ],
                        "learning_objectives_en": [
                            "Distinguish data types (nominal, ordinal, continuous, discrete)",
                            "Understand measurement scales and their importance",
                            "Identify appropriate data types for different analyses"
                        ],
                        "duration_minutes": 180
                    }},
                    {{
                        "unit_id": 2,
                        "title_fr": "Statistiques descriptives",
                        "title_en": "Descriptive statistics",
                        "learning_objectives_fr": [
                            "Lire et interpréter des tableaux de fréquences et graphiques de santé",
                            "Calculer et interpréter les mesures de tendance centrale (moyenne, médiane, mode)",
                            "Calculer et interpréter les mesures de dispersion (écart-type, variance)",
                            "Créer et interpréter des histogrammes, boxplots et identifier les valeurs aberrantes"
                        ],
                        "learning_objectives_en": [
                            "Read and interpret frequency tables and health graphics",
                            "Calculate and interpret measures of central tendency (mean, median, mode)",
                            "Calculate and interpret measures of dispersion (standard deviation, variance)",
                            "Create and interpret histograms, boxplots and identify outliers"
                        ],
                        "duration_minutes": 300
                    }},
                    {{
                        "unit_id": 3,
                        "title_fr": "Sources de données de santé en AOF",
                        "title_en": "Health data sources in West Africa",
                        "learning_objectives_fr": [
                            "Identifier les sources de données de santé en AOF (DHIS2, HMIS, recensements)",
                            "Comprendre le SNIS (Système National d'Information Sanitaire) et ses lacunes",
                            "Analyser les enquêtes DHS/EDS, MICS et leur utilisation",
                            "Reconnaître les biais dans la collecte de données"
                        ],
                        "learning_objectives_en": [
                            "Identify health data sources in West Africa (DHIS2, HMIS, censuses)",
                            "Understand National Health Information Systems (NHIS) and their gaps",
                            "Analyze DHS, MICS surveys and their use",
                            "Recognize biases in data collection"
                        ],
                        "duration_minutes": 240
                    }},
                    {{
                        "unit_id": 4,
                        "title_fr": "Analyse pratique avec Excel/Google Sheets",
                        "title_en": "Practical analysis with Excel/Google Sheets",
                        "learning_objectives_fr": [
                            "Utiliser Excel/Google Sheets pour l'analyse de données de santé",
                            "Créer des tableaux de fréquences et graphiques",
                            "Calculer des statistiques descriptives avec des formules",
                            "Analyser des données réelles de paludisme Niger 2023"
                        ],
                        "learning_objectives_en": [
                            "Use Excel/Google Sheets for health data analysis",
                            "Create frequency tables and charts",
                            "Calculate descriptive statistics with formulas",
                            "Analyze real malaria data from Niger 2023"
                        ],
                        "duration_minutes": 300
                    }},
                    {{
                        "unit_id": 5,
                        "title_fr": "Exercice pratique DHIS2",
                        "title_en": "DHIS2 practical exercise",
                        "learning_objectives_fr": [
                            "Télécharger et analyser des données DHIS2 du Sénégal, Côte d'Ivoire ou Ghana",
                            "Interpréter les indicateurs clés du RMNCH",
                            "Créer un rapport d'analyse de données de santé",
                            "Comprendre les défis de qualité des données en AOF"
                        ],
                        "learning_objectives_en": [
                            "Download and analyze DHIS2 data from Senegal, Côte d'Ivoire or Ghana",
                            "Interpret RMNCH key indicators",
                            "Create a health data analysis report",
                            "Understand data quality challenges in West Africa"
                        ],
                        "duration_minutes": 300
                    }}
                ]
            }}'"""),
        },
        # === M03 — Health Systems in West Africa ===
        {
            "id": m03_id,
            "module_number": 3,
            "level": 1,
            "title_fr": "Systèmes de Santé en Afrique de l'Ouest",
            "title_en": "Health Systems in West Africa",
            "description_fr": "Architecture, financement et performance des systèmes de santé des pays CEDEAO. Les 6 piliers d'un système de santé selon l'OMS, modèles de financement, couverture santé universelle (CSU/UHC), rôles des différents acteurs, pyramide sanitaire et indicateurs de performance.",
            "description_en": "Architecture, financing and performance of health systems in ECOWAS countries. WHO's 6 pillars of a health system, financing models, universal health coverage (UHC), roles of different actors, health pyramid and performance indicators.",
            "estimated_hours": 18,
            "bloom_level": "Understand",
            "prereq_modules": f'{{"{m01_id}"}}',
            "books_sources": sa.text("""'{{
                "donaldson": {{"chapters": ["ch6"], "description": "Health systems"}},
                "scutchfield": {{"chapters": ["ch6", "ch7", "ch8", "ch28"], "description": "Federal, state, local settings for public health practice, Global health"}},
                "units": [
                    {{
                        "unit_id": 1,
                        "title_fr": "Les 6 piliers des systèmes de santé OMS",
                        "title_en": "WHO's 6 health system building blocks",
                        "learning_objectives_fr": [
                            "Décrire les 6 piliers d'un système de santé (OMS)",
                            "Analyser la gouvernance, financement, ressources humaines, médicaments, SI, prestation",
                            "Comprendre l'interdépendance des piliers et leurs défis en AOF"
                        ],
                        "learning_objectives_en": [
                            "Describe WHO's 6 health system building blocks",
                            "Analyze governance, financing, human resources, medicines, IS, service delivery",
                            "Understand the interdependence of building blocks and their challenges in West Africa"
                        ],
                        "duration_minutes": 240
                    }},
                    {{
                        "unit_id": 2,
                        "title_fr": "Modèles de financement et CSU",
                        "title_en": "Financing models and UHC",
                        "learning_objectives_fr": [
                            "Comparer les modèles de financement de la santé en AOF",
                            "Analyser la couverture santé universelle (CSU/UHC) dans la région",
                            "Étudier le NHIS ghanéen comme modèle d'assurance maladie universelle",
                            "Comprendre les défis du paiement direct et de l'appauvrissement"
                        ],
                        "learning_objectives_en": [
                            "Compare health financing models in West Africa",
                            "Analyze universal health coverage (UHC) in the region",
                            "Study Ghana's NHIS as a universal health insurance model",
                            "Understand out-of-pocket payment challenges and impoverishment"
                        ],
                        "duration_minutes": 300
                    }},
                    {{
                        "unit_id": 3,
                        "title_fr": "Acteurs et pyramide sanitaire",
                        "title_en": "Stakeholders and health pyramid",
                        "learning_objectives_fr": [
                            "Identifier les rôles des acteurs : public, privé, communautaire, ONG",
                            "Comprendre la pyramide sanitaire et les niveaux de soins",
                            "Analyser le rôle du secteur privé et des organisations confessionnelles",
                            "Étudier la complémentarité des différents niveaux de soins"
                        ],
                        "learning_objectives_en": [
                            "Identify roles of stakeholders: public, private, community, NGOs",
                            "Understand the health pyramid and levels of care",
                            "Analyze the role of private sector and faith-based organizations",
                            "Study the complementarity of different levels of care"
                        ],
                        "duration_minutes": 240
                    }},
                    {{
                        "unit_id": 4,
                        "title_fr": "Systèmes de santé comparés en AOF",
                        "title_en": "Comparative health systems in West Africa",
                        "learning_objectives_fr": [
                            "Comparer les systèmes de santé : Ghana (NHIS), Sénégal, Nigeria, Côte d'Ivoire",
                            "Analyser les politiques de santé au Sénégal (CMU), au Nigeria (fragmentation fédérale)",
                            "Comprendre l'impact des crises sécuritaires sur les systèmes de santé (Mali)",
                            "Étudier les réformes et innovations dans chaque pays"
                        ],
                        "learning_objectives_en": [
                            "Compare health systems: Ghana (NHIS), Senegal, Nigeria, Côte d'Ivoire",
                            "Analyze health policies in Senegal (CMU), Nigeria (federal fragmentation)",
                            "Understand the impact of security crises on health systems (Mali)",
                            "Study reforms and innovations in each country"
                        ],
                        "duration_minutes": 240
                    }},
                    {{
                        "unit_id": 5,
                        "title_fr": "Indicateurs de performance et évaluation",
                        "title_en": "Performance indicators and evaluation",
                        "learning_objectives_fr": [
                            "Analyser les indicateurs de performance des systèmes de santé",
                            "Utiliser les indicateurs JCI et WHO de performance hospitalière",
                            "Comprendre les sources de données : WHO AFRO Country Profiles, World Bank",
                            "Évaluer la résilience des systèmes de santé face aux épidémies"
                        ],
                        "learning_objectives_en": [
                            "Analyze health system performance indicators",
                            "Use JCI and WHO hospital performance indicators",
                            "Understand data sources: WHO AFRO Country Profiles, World Bank",
                            "Evaluate health system resilience in face of epidemics"
                        ],
                        "duration_minutes": 220
                    }}
                ]
            }}'"""),
        },
    ]

    op.bulk_insert(modules_table, detailed_modules)


def downgrade() -> None:
    """Remove detailed M01-M03 seed data and restore basic entries."""
    # Delete the detailed entries
    op.execute("DELETE FROM modules WHERE module_number IN (1, 2, 3)")

    # Restore basic entries (same as original 003_seed_modules.py for M01-M03)
    modules_table = table(
        "modules",
        column("id", sa.String),
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

    basic_modules = [
        {
            "id": str(uuid4()),
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
            "id": str(uuid4()),
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
            "id": str(uuid4()),
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
    ]

    op.bulk_insert(modules_table, basic_modules)
