"""Startup seeder for module_units table.

Checks if any module has zero units and seeds all 75 units if needed.
Safe to run multiple times (idempotent via ON CONFLICT DO NOTHING).
"""

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.data.seed_units import UNITS_SEED
from app.domain.models.module import Module
from app.domain.models.module_unit import ModuleUnit

logger = structlog.get_logger(__name__)


async def seed_module_units(session: AsyncSession) -> None:
    """Seed module_units if any module has 0 units.

    Uses ON CONFLICT DO NOTHING to remain idempotent.
    """
    result = await session.execute(
        text("SELECT COUNT(*) FROM module_units mu JOIN modules m ON mu.module_id = m.id")
    )
    total_units: int = result.scalar_one()

    if total_units >= 75:
        logger.info("module_units already seeded", total=total_units)
        return

    logger.info("seeding module_units", existing=total_units)

    modules_result = await session.execute(select(Module).order_by(Module.module_number))
    modules = modules_result.scalars().all()

    if not modules:
        logger.warning("no modules found, skipping unit seed")
        return

    module_by_number: dict[int, Module] = {m.module_number: m for m in modules}

    inserted = 0
    for unit_data in UNITS_SEED:
        module_number = unit_data["module_number"]
        module = module_by_number.get(module_number)
        if module is None:
            logger.warning("module not found, skipping unit", module_number=module_number)
            continue

        existing = await session.execute(
            select(ModuleUnit).where(
                ModuleUnit.module_id == module.id,
                ModuleUnit.unit_number == unit_data["unit_number"],
            )
        )
        if existing.scalar_one_or_none() is not None:
            continue

        unit = ModuleUnit(
            module_id=module.id,
            unit_number=unit_data["unit_number"],
            title_fr=unit_data["title_fr"],
            title_en=unit_data["title_en"],
            description_fr=unit_data["description_fr"],
            description_en=unit_data["description_en"],
            estimated_minutes=unit_data["estimated_minutes"],
            order_index=unit_data["order_index"],
        )
        session.add(unit)
        inserted += 1

    await session.commit()
    logger.info("module_units seeded", inserted=inserted)
