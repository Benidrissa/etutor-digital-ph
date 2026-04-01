"""Add module_units table for unit-level organization

Revision ID: 827be8454e47
Revises: 9f4db5f73f90
Create Date: 2026-04-01 01:53:05.684677
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '827be8454e47'
down_revision: Union[str, None] = '9f4db5f73f90'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create module_units table
    op.create_table(
        'module_units',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('module_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('modules.id'), nullable=False),
        sa.Column('unit_id', sa.String(), nullable=False),  # e.g., "1.1", "1.2", "summative"
        sa.Column('title_fr', sa.String(), nullable=False),
        sa.Column('title_en', sa.String(), nullable=False),
        sa.Column('description_fr', sa.Text(), nullable=True),
        sa.Column('description_en', sa.Text(), nullable=True),
        sa.Column('order_index', sa.Integer(), nullable=False),  # For ordering within module
        sa.Column('estimated_minutes', sa.Integer(), nullable=False, server_default='60'),
        sa.Column('learning_objectives_fr', postgresql.JSONB(), nullable=True),
        sa.Column('learning_objectives_en', postgresql.JSONB(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), onupdate=sa.text('now()'))
    )
    
    # Create indexes
    op.create_index('idx_module_units_module_id', 'module_units', ['module_id'])
    op.create_index('idx_module_units_unit_id', 'module_units', ['unit_id'])
    op.create_unique_index('idx_module_units_unique', 'module_units', ['module_id', 'unit_id'])
    
    # Seed units for M01-M03 based on the curriculum structure
    op.execute("""
        WITH modules_with_numbers AS (
            SELECT id, module_number FROM modules WHERE module_number IN (1, 2, 3)
        )
        INSERT INTO module_units (module_id, unit_id, title_fr, title_en, description_fr, description_en, order_index, estimated_minutes)
        VALUES
        -- M01: Fondements de la Santé Publique
        ((SELECT id FROM modules_with_numbers WHERE module_number = 1), '1.1', 
         'Histoire et Évolution de la Santé Publique', 'History and Evolution of Public Health',
         'Origines et développement de la santé publique mondiale et en Afrique de l''Ouest',
         'Origins and development of global public health and in West Africa', 1, 90),
        
        ((SELECT id FROM modules_with_numbers WHERE module_number = 1), '1.2', 
         'Concepts Fondamentaux', 'Fundamental Concepts',
         'Définitions, principes de base et approches de la santé publique moderne',
         'Definitions, basic principles and approaches of modern public health', 2, 120),
         
        ((SELECT id FROM modules_with_numbers WHERE module_number = 1), '1.3', 
         'Santé Publique en Contexte AOF', 'Public Health in West African Context',
         'Spécificités, défis et opportunités de la santé publique en Afrique de l''Ouest',
         'Specificities, challenges and opportunities of public health in West Africa', 3, 90),
         
        -- M02: Introduction aux Données de Santé & Statistiques
        ((SELECT id FROM modules_with_numbers WHERE module_number = 2), '2.1', 
         'Types de Données de Santé', 'Types of Health Data',
         'Sources, formats et qualité des données de santé en contexte africain',
         'Sources, formats and quality of health data in African context', 1, 100),
         
        ((SELECT id FROM modules_with_numbers WHERE module_number = 2), '2.2', 
         'Collecte et Gestion des Données', 'Data Collection and Management',
         'Méthodes de collecte, stockage et traitement des données sanitaires',
         'Methods for collecting, storing and processing health data', 2, 110),
         
        ((SELECT id FROM modules_with_numbers WHERE module_number = 2), '2.3', 
         'Statistiques Descriptives', 'Descriptive Statistics',
         'Mesures de tendance centrale, dispersion et visualisation des données',
         'Measures of central tendency, dispersion and data visualization', 3, 120),
         
        -- M03: Systèmes de Santé en Afrique de l'Ouest
        ((SELECT id FROM modules_with_numbers WHERE module_number = 3), '3.1', 
         'Architecture des Systèmes de Santé', 'Health Systems Architecture',
         'Structure, organisation et gouvernance des systèmes de santé CEDEAO',
         'Structure, organization and governance of ECOWAS health systems', 1, 90),
         
        ((SELECT id FROM modules_with_numbers WHERE module_number = 3), '3.2', 
         'Financement et Performance', 'Financing and Performance',
         'Mécanismes de financement et indicateurs de performance des systèmes',
         'Financing mechanisms and performance indicators of health systems', 2, 100),
         
        ((SELECT id FROM modules_with_numbers WHERE module_number = 3), '3.3', 
         'Défis et Innovations', 'Challenges and Innovations',
         'Obstacles actuels et solutions innovantes pour renforcer les systèmes',
         'Current obstacles and innovative solutions to strengthen health systems', 3, 80)
    """)


def downgrade() -> None:
    op.drop_table('module_units')
