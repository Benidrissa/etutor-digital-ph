"""Update modules with prerequisite chains for 80% unlock logic.

Revision ID: 008_update_module_prerequisites
Revises: 007_add_totp_mfa_auth_tables
Create Date: 2026-03-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "008_update_module_prerequisites"
down_revision: str | None = "007_add_totp_mfa_auth_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """
    Update module prerequisite chains based on curriculum structure.

    Prerequisites are designed to ensure progressive skill building:
    - Level 1 (M01-M03): Foundation modules, M01 always unlocked
    - Level 2 (M04-M07): Build on Level 1 foundations
    - Level 3 (M08-M12): Build on Level 2 skills
    - Level 4 (M13-M15): Advanced synthesis requiring Level 3 completion
    """

    # Get module IDs by module_number for reference
    conn = op.get_bind()

    # Fetch all modules to build ID mappings
    result = conn.execute(sa.text("SELECT id, module_number FROM modules ORDER BY module_number"))
    module_ids = {row[1]: str(row[0]) for row in result.fetchall()}

    # Define prerequisite chains
    prerequisites = {
        # Level 1: M01 always unlocked, M02-M03 require M01
        2: [module_ids[1]],  # M02 requires M01 (foundations before data)
        3: [module_ids[1]],  # M03 requires M01 (foundations before systems)
        # Level 2: Require completion of Level 1
        4: [module_ids[1], module_ids[2]],  # Epidemiology requires foundations + data intro
        5: [module_ids[2]],  # Biostatistics requires data intro
        6: [module_ids[1], module_ids[4]],  # Diseases require foundations + epidemiology
        7: [module_ids[3]],  # Tools require health systems knowledge
        # Level 3: Require key Level 2 modules
        8: [module_ids[4], module_ids[6]],  # Surveillance requires epidemiology + diseases
        9: [module_ids[5]],  # Advanced stats requires biostatistics
        10: [module_ids[2], module_ids[7]],  # Digital health requires data + tools
        11: [module_ids[6]],  # Environmental health requires diseases knowledge
        12: [module_ids[4], module_ids[6]],  # MCH requires epidemiology + diseases
        # Level 4: Require completion of key Level 3 modules
        13: [module_ids[7], module_ids[8]],  # Leadership requires tools + surveillance
        14: [module_ids[9], module_ids[8]],  # Research requires advanced stats + surveillance
        15: [module_ids[13], module_ids[14]],  # Capstone requires leadership + research
    }

    # Update each module with its prerequisites
    for module_number, prereq_ids in prerequisites.items():
        prereq_array = "{" + ",".join(prereq_ids) + "}"

        conn.execute(
            sa.text("""
                UPDATE modules 
                SET prereq_modules = :prereq_array 
                WHERE module_number = :module_number
            """),
            {"prereq_array": prereq_array, "module_number": module_number},
        )


def downgrade() -> None:
    """Reset all prerequisites to empty arrays."""
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE modules SET prereq_modules = '{}'"))
