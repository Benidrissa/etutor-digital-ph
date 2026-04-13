"""Unit tests for ActivationCodeService — all 5 methods."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.models.activation_code import ActivationCode
from app.domain.models.user import User, UserRole
from app.domain.services.activation_code_service import ActivationCodeService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(
    role: UserRole = UserRole.expert,
    uid: uuid.UUID | None = None,
) -> SimpleNamespace:
    u = SimpleNamespace(
        id=uid or uuid.uuid4(),
        email=f"user_{uuid.uuid4().hex[:8]}@example.com",
        name="Test User",
        role=role,
        is_active=True,
    )
    return u


def _make_course(
    created_by: uuid.UUID,
    status: str = "published",
    price_credits: int = 0,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        title_fr="Cours FR",
        title_en="Course EN",
        description_fr="Description FR",
        description_en="Description EN",
        cover_image_url=None,
        status=status,
        created_by=created_by,
        price_credits=price_credits,
    )


def _make_activation_code(
    course_id: uuid.UUID,
    created_by: uuid.UUID,
    code: str = "SIRA-testcode123",
    max_uses: int | None = None,
    times_used: int = 0,
    is_active: bool = True,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        code=code,
        course_id=course_id,
        curriculum_id=None,
        organization_id=None,
        created_by=created_by,
        max_uses=max_uses,
        times_used=times_used,
        is_active=is_active,
    )


def _make_credit_account(user_id: uuid.UUID, balance: int = 100) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        user_id=user_id,
        balance=balance,
        total_earned=0,
    )


def _make_db() -> AsyncMock:
    db = AsyncMock()
    db.get = AsyncMock()
    db.execute = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.refresh = AsyncMock()
    return db


def _scalar_result(value):
    mock = MagicMock()
    mock.scalar_one_or_none.return_value = value
    mock.scalars.return_value.all.return_value = [value] if value else []
    mock.all.return_value = []
    return mock


# ---------------------------------------------------------------------------
# generate_codes tests
# ---------------------------------------------------------------------------


class TestGenerateCodes:
    @pytest.fixture
    def service(self):
        return ActivationCodeService()

    @pytest.mark.asyncio
    async def test_raises_403_for_non_expert_user(self, service):
        db = _make_db()
        expert = _make_user(role=UserRole.user)
        db.get.return_value = expert
        with pytest.raises(Exception) as exc:
            await service.generate_codes(db, expert.id, uuid.uuid4())
        assert "403" in str(exc.value.status_code)

    @pytest.mark.asyncio
    async def test_raises_403_if_expert_does_not_own_course(self, service):
        db = _make_db()
        expert = _make_user(role=UserRole.expert)
        other_owner = uuid.uuid4()
        course = _make_course(created_by=other_owner, status="published")
        db.get.return_value = expert
        db.execute.return_value = _scalar_result(course)
        with pytest.raises(Exception) as exc:
            await service.generate_codes(db, expert.id, course.id)
        assert "403" in str(exc.value.status_code)

    @pytest.mark.asyncio
    async def test_raises_409_for_unpublished_course(self, service):
        db = _make_db()
        expert = _make_user(role=UserRole.expert)
        course = _make_course(created_by=expert.id, status="draft")
        db.get.return_value = expert
        db.execute.return_value = _scalar_result(course)
        with pytest.raises(Exception) as exc:
            await service.generate_codes(db, expert.id, course.id)
        assert "409" in str(exc.value.status_code)

    @pytest.mark.asyncio
    async def test_generates_correct_number_of_codes(self, service):
        db = _make_db()
        expert = _make_user(role=UserRole.expert)
        course = _make_course(created_by=expert.id, status="published")
        db.get.return_value = expert
        db.execute.return_value = _scalar_result(course)
        codes = await service.generate_codes(db, expert.id, course.id, count=3)
        assert len(codes) == 3
        assert all(c.code.startswith("SIRA-") for c in codes)

    @pytest.mark.asyncio
    async def test_admin_can_generate_for_any_course(self, service):
        db = _make_db()
        admin = _make_user(role=UserRole.admin)
        course = _make_course(created_by=uuid.uuid4(), status="published")
        db.get.return_value = admin
        db.execute.return_value = _scalar_result(course)
        codes = await service.generate_codes(db, admin.id, course.id, count=1)
        assert len(codes) == 1


# ---------------------------------------------------------------------------
# preview_code tests
# ---------------------------------------------------------------------------


class TestPreviewCode:
    @pytest.fixture
    def service(self):
        return ActivationCodeService()

    @pytest.mark.asyncio
    async def test_returns_invalid_for_unknown_code(self, service):
        db = _make_db()
        db.execute.return_value = _scalar_result(None)
        result = await service.preview_code(db, "SIRA-doesnotexist")
        assert result["valid"] is False

    @pytest.mark.asyncio
    async def test_returns_valid_true_for_active_code(self, service):
        db = _make_db()
        expert = _make_user(role=UserRole.expert)
        course = _make_course(created_by=expert.id)
        ac = _make_activation_code(course_id=course.id, created_by=expert.id, is_active=True)

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _scalar_result(ac)
            elif call_count == 2:
                return _scalar_result(course)
            else:
                r = MagicMock()
                r.scalar_one_or_none.return_value = expert.name
                return r

        db.execute.side_effect = side_effect
        result = await service.preview_code(db, ac.code)
        assert result["valid"] is True
        assert result["title_fr"] == course.title_fr

    @pytest.mark.asyncio
    async def test_returns_invalid_when_code_exhausted(self, service):
        db = _make_db()
        expert = _make_user(role=UserRole.expert)
        course = _make_course(created_by=expert.id)
        ac = _make_activation_code(
            course_id=course.id, created_by=expert.id, max_uses=5, times_used=5, is_active=True
        )

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _scalar_result(ac)
            elif call_count == 2:
                return _scalar_result(course)
            else:
                r = MagicMock()
                r.scalar_one_or_none.return_value = expert.name
                return r

        db.execute.side_effect = side_effect
        result = await service.preview_code(db, ac.code)
        assert result["valid"] is False


# ---------------------------------------------------------------------------
# redeem_code tests
# ---------------------------------------------------------------------------


class TestRedeemCode:
    @pytest.fixture
    def service(self):
        return ActivationCodeService()

    @pytest.mark.asyncio
    async def test_raises_404_for_unknown_code(self, service):
        db = _make_db()
        db.execute.return_value = _scalar_result(None)
        with pytest.raises(Exception) as exc:
            await service.redeem_code(db, "SIRA-bad", uuid.uuid4())
        assert "404" in str(exc.value.status_code)

    @pytest.mark.asyncio
    async def test_raises_409_for_inactive_code(self, service):
        db = _make_db()
        expert = _make_user(role=UserRole.expert)
        course = _make_course(created_by=expert.id)
        ac = _make_activation_code(course_id=course.id, created_by=expert.id, is_active=False)
        db.execute.return_value = _scalar_result(ac)
        with pytest.raises(Exception) as exc:
            await service.redeem_code(db, ac.code, uuid.uuid4())
        assert "409" in str(exc.value.status_code)

    @pytest.mark.asyncio
    async def test_raises_409_when_usage_limit_reached(self, service):
        db = _make_db()
        expert = _make_user(role=UserRole.expert)
        course = _make_course(created_by=expert.id)
        ac = _make_activation_code(
            course_id=course.id, created_by=expert.id, max_uses=3, times_used=3, is_active=True
        )
        db.execute.return_value = _scalar_result(ac)
        with pytest.raises(Exception) as exc:
            await service.redeem_code(db, ac.code, uuid.uuid4())
        assert "409" in str(exc.value.status_code)

    @pytest.mark.asyncio
    async def test_raises_409_when_already_enrolled(self, service):
        db = _make_db()
        expert = _make_user(role=UserRole.expert)
        course = _make_course(created_by=expert.id)
        ac = _make_activation_code(course_id=course.id, created_by=expert.id)
        enrollment = SimpleNamespace(
            user_id=uuid.uuid4(),
            course_id=course.id,
            status="active",
        )

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _scalar_result(ac)
            return _scalar_result(enrollment)

        db.execute.side_effect = side_effect
        with pytest.raises(Exception) as exc:
            await service.redeem_code(db, ac.code, uuid.uuid4())
        assert "409" in str(exc.value.status_code)

    @pytest.mark.asyncio
    async def test_increments_times_used_on_success(self, service):
        db = _make_db()
        expert = _make_user(role=UserRole.expert)
        course = _make_course(created_by=expert.id, price_credits=0)
        user_id = uuid.uuid4()
        ac = _make_activation_code(course_id=course.id, created_by=expert.id, times_used=0)

        enrollment = SimpleNamespace(
            user_id=user_id,
            course_id=course.id,
            status="active",
            enrolled_at=__import__("datetime").datetime.now(),
            completion_pct=0.0,
        )

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            # 1: select ActivationCode (with_for_update)
            # 2: select ActivationCodeRedemption (dup check)
            # 3: select UserCourseEnrollment (existing enrollment check)
            # 4: select Course (revenue)
            if call_count == 1:
                return _scalar_result(ac)
            elif call_count in (2, 3):
                return _scalar_result(None)
            elif call_count == 4:
                return _scalar_result(course)
            return _scalar_result(None)

        db.execute.side_effect = side_effect

        with patch(
            "app.domain.services.activation_code_service.enroll_user_in_course",
            new=AsyncMock(return_value=enrollment),
        ):
            result = await service.redeem_code(db, ac.code, user_id)

        assert ac.times_used == 1
        assert isinstance(result, list)
        assert enrollment in result

    @pytest.mark.asyncio
    async def test_deactivates_code_when_max_uses_reached(self, service):
        db = _make_db()
        expert = _make_user(role=UserRole.expert)
        course = _make_course(created_by=expert.id, price_credits=0)
        user_id = uuid.uuid4()
        ac = _make_activation_code(
            course_id=course.id, created_by=expert.id, max_uses=1, times_used=0
        )

        enrollment = SimpleNamespace(
            user_id=user_id,
            course_id=course.id,
            status="active",
            enrolled_at=__import__("datetime").datetime.now(),
            completion_pct=0.0,
        )

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _scalar_result(ac)
            elif call_count == 2 or call_count == 3:
                return _scalar_result(None)
            elif call_count == 4:
                return _scalar_result(course)
            return _scalar_result(None)

        db.execute.side_effect = side_effect

        with patch(
            "app.domain.services.activation_code_service.enroll_user_in_course",
            new=AsyncMock(return_value=enrollment),
        ):
            await service.redeem_code(db, ac.code, user_id)

        assert ac.is_active is False

    @pytest.mark.asyncio
    async def test_creates_revenue_transaction_for_paid_course(self, service):
        db = _make_db()
        expert = _make_user(role=UserRole.expert)
        course = _make_course(created_by=expert.id, price_credits=50)
        user_id = uuid.uuid4()
        ac = _make_activation_code(course_id=course.id, created_by=expert.id, times_used=0)
        credit_account = _make_credit_account(user_id=expert.id, balance=0)

        enrollment = SimpleNamespace(
            user_id=user_id,
            course_id=course.id,
            status="active",
            enrolled_at=__import__("datetime").datetime.now(),
            completion_pct=0.0,
        )

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _scalar_result(ac)
            elif call_count == 2 or call_count == 3:
                return _scalar_result(None)
            elif call_count == 4:
                return _scalar_result(course)
            elif call_count == 5:
                return _scalar_result(credit_account)
            return _scalar_result(None)

        db.execute.side_effect = side_effect

        with patch(
            "app.domain.services.activation_code_service.enroll_user_in_course",
            new=AsyncMock(return_value=enrollment),
        ):
            await service.redeem_code(db, ac.code, user_id)

        assert credit_account.balance == 50
        assert credit_account.total_earned == 50
        db.add.assert_called()


# ---------------------------------------------------------------------------
# manual_activate tests
# ---------------------------------------------------------------------------


class TestManualActivate:
    @pytest.fixture
    def service(self):
        return ActivationCodeService()

    @pytest.mark.asyncio
    async def test_raises_403_for_non_expert(self, service):
        db = _make_db()
        caller = _make_user(role=UserRole.user)
        db.get.return_value = caller
        with pytest.raises(Exception) as exc:
            await service.manual_activate(db, caller.id, uuid.uuid4(), "learner@example.com")
        assert "403" in str(exc.value.status_code)

    @pytest.mark.asyncio
    async def test_raises_404_when_learner_not_found(self, service):
        db = _make_db()
        expert = _make_user(role=UserRole.expert)
        db.get.return_value = expert
        db.execute.return_value = _scalar_result(None)
        with pytest.raises(Exception) as exc:
            await service.manual_activate(db, expert.id, uuid.uuid4(), "missing@example.com")
        assert "404" in str(exc.value.status_code)

    @pytest.mark.asyncio
    async def test_raises_403_when_expert_does_not_own_code_course(self, service):
        db = _make_db()
        expert = _make_user(role=UserRole.expert)
        learner = _make_user(role=UserRole.user)
        ac = _make_activation_code(course_id=uuid.uuid4(), created_by=uuid.uuid4())

        call_count = 0

        def get_side_effect(model, pk):
            if model == User:
                return expert
            if model == ActivationCode:
                return ac
            return None

        db.get.side_effect = get_side_effect

        def execute_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _scalar_result(learner)
            elif call_count == 2:
                return _scalar_result(ac)
            else:
                return _scalar_result(None)

        db.execute.side_effect = execute_side_effect

        with pytest.raises(Exception) as exc:
            await service.manual_activate(db, expert.id, ac.id, learner.email)
        assert "403" in str(exc.value.status_code)


# ---------------------------------------------------------------------------
# get_code_redemptions tests
# ---------------------------------------------------------------------------


class TestGetCodeRedemptions:
    @pytest.fixture
    def service(self):
        return ActivationCodeService()

    @pytest.mark.asyncio
    async def test_raises_403_when_expert_does_not_own_course(self, service):
        db = _make_db()
        expert = _make_user(role=UserRole.expert)
        db.get.return_value = expert
        db.execute.return_value = _scalar_result(None)
        with pytest.raises(Exception) as exc:
            await service.get_code_redemptions(db, expert.id, uuid.uuid4())
        assert "403" in str(exc.value.status_code)

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_redemptions(self, service):
        db = _make_db()
        expert = _make_user(role=UserRole.expert)
        course = _make_course(created_by=expert.id)
        db.get.return_value = expert

        call_count = 0

        def execute_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _scalar_result(course)
            result = MagicMock()
            result.all.return_value = []
            return result

        db.execute.side_effect = execute_side_effect

        results = await service.get_code_redemptions(db, expert.id, course.id)
        assert results == []

    @pytest.mark.asyncio
    async def test_admin_can_view_any_course_redemptions(self, service):
        db = _make_db()
        admin = _make_user(role=UserRole.admin)
        course_id = uuid.uuid4()
        db.get.return_value = admin

        result_mock = MagicMock()
        result_mock.all.return_value = []
        db.execute.return_value = result_mock

        results = await service.get_code_redemptions(db, admin.id, course_id)
        assert results == []
