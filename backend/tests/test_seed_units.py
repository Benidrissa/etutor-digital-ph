"""Tests for the module_units seeder."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.data.seed_units import UNITS_SEED
from app.data.seeder import seed_module_units
from app.domain.models.module import Module
from app.domain.models.module_unit import ModuleUnit


@pytest.fixture
def mock_db():
    db = AsyncMock(spec=AsyncSession)
    db.add = MagicMock()
    db.commit = AsyncMock()
    return db


class TestSeedData:
    def test_total_unit_count(self):
        assert len(UNITS_SEED) == 75

    def test_all_15_modules_represented(self):
        module_numbers = {u["module_number"] for u in UNITS_SEED}
        assert module_numbers == set(range(1, 16))

    def test_each_module_has_5_units(self):
        for module_number in range(1, 16):
            module_units = [u for u in UNITS_SEED if u["module_number"] == module_number]
            assert len(module_units) == 5, f"module {module_number} has {len(module_units)} units"

    def test_each_module_has_3_lessons_1_quiz_1_case(self):
        for module_number in range(1, 16):
            module_units = [u for u in UNITS_SEED if u["module_number"] == module_number]
            unit_numbers = [u["unit_number"] for u in module_units]
            quiz_units = [n for n in unit_numbers if n.endswith(".Q")]
            case_units = [n for n in unit_numbers if n.endswith(".C")]
            lesson_units = [
                n for n in unit_numbers if not n.endswith(".Q") and not n.endswith(".C")
            ]
            assert len(quiz_units) == 1, f"module {module_number} has {len(quiz_units)} quizzes"
            assert len(case_units) == 1, f"module {module_number} has {len(case_units)} cases"
            assert len(lesson_units) == 3, f"module {module_number} has {len(lesson_units)} lessons"

    def test_all_units_have_required_fields(self):
        required_fields = {
            "module_number",
            "unit_number",
            "title_fr",
            "title_en",
            "description_fr",
            "description_en",
            "estimated_minutes",
            "order_index",
            "unit_type",
        }
        for unit in UNITS_SEED:
            for field in required_fields:
                assert field in unit, f"unit {unit.get('unit_number')} missing field {field}"
                assert unit[field] is not None, (
                    f"unit {unit.get('unit_number')} field {field} is None"
                )

    def test_order_index_per_module(self):
        for module_number in range(1, 16):
            module_units = sorted(
                [u for u in UNITS_SEED if u["module_number"] == module_number],
                key=lambda u: u["order_index"],
            )
            indices = [u["order_index"] for u in module_units]
            assert indices == list(range(1, 6)), (
                f"module {module_number} order_indices are {indices}"
            )

    def test_unit_numbers_are_unique_per_module(self):
        for module_number in range(1, 16):
            module_units = [u for u in UNITS_SEED if u["module_number"] == module_number]
            unit_numbers = [u["unit_number"] for u in module_units]
            assert len(unit_numbers) == len(set(unit_numbers)), (
                f"module {module_number} has duplicate unit_numbers"
            )

    def test_estimated_minutes_positive(self):
        for unit in UNITS_SEED:
            assert unit["estimated_minutes"] > 0

    def test_unit_type_values_valid(self):
        valid_types = {"lesson", "quiz", "case-study"}
        for unit in UNITS_SEED:
            assert unit["unit_type"] in valid_types, (
                f"unit {unit.get('unit_number')} has invalid unit_type '{unit.get('unit_type')}'"
            )

    def test_unit_type_matches_unit_number_suffix(self):
        for unit in UNITS_SEED:
            un = unit["unit_number"]
            if un.endswith(".Q"):
                assert unit["unit_type"] == "quiz", f"{un} should be quiz"
            elif un.endswith(".C"):
                assert unit["unit_type"] == "case-study", f"{un} should be case-study"
            else:
                assert unit["unit_type"] == "lesson", f"{un} should be lesson"


class TestSeeder:
    async def test_skips_if_already_seeded(self, mock_db):
        mock_db.execute = AsyncMock(return_value=MagicMock(scalar_one=MagicMock(return_value=75)))
        await seed_module_units(mock_db)
        mock_db.commit.assert_not_called()

    async def test_skips_if_no_modules_in_db(self, mock_db):
        call_count = 0

        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one = MagicMock(return_value=0)
            else:
                result.scalars.return_value.all.return_value = []
            return result

        mock_db.execute = mock_execute
        await seed_module_units(mock_db)
        mock_db.commit.assert_not_called()

    async def test_seeds_when_empty(self, mock_db):
        module_id = uuid.uuid4()
        modules = [
            Module(
                id=module_id,
                module_number=n,
                level=1,
                title_fr=f"M{n:02d}",
                title_en=f"M{n:02d}",
                estimated_hours=20,
            )
            for n in range(1, 16)
        ]

        call_count = 0

        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one = MagicMock(return_value=0)
            elif call_count == 2:
                result.scalars.return_value.all.return_value = modules
            else:
                result.scalar_one_or_none = MagicMock(return_value=None)
            return result

        mock_db.execute = mock_execute
        await seed_module_units(mock_db)
        assert mock_db.add.call_count == 75
        mock_db.commit.assert_called_once()

    async def test_idempotent_skips_existing_units(self, mock_db):
        module_id = uuid.uuid4()
        modules = [
            Module(
                id=module_id,
                module_number=1,
                level=1,
                title_fr="M01",
                title_en="M01",
                estimated_hours=20,
            )
        ]
        existing_unit = ModuleUnit(
            id=uuid.uuid4(),
            module_id=module_id,
            unit_number="1.1",
            title_fr="Test",
            title_en="Test",
            estimated_minutes=45,
            order_index=1,
        )

        call_count = 0

        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one = MagicMock(return_value=0)
            elif call_count == 2:
                result.scalars.return_value.all.return_value = modules
            else:
                result.scalar_one_or_none = MagicMock(return_value=existing_unit)
            return result

        mock_db.execute = mock_execute
        await seed_module_units(mock_db)
        assert mock_db.add.call_count == 0
