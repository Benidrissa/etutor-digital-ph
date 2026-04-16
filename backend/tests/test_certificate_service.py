"""Tests for the certificate service — completion check, issuance, verification."""

import re
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.certificate import Certificate, CertificateTemplate
from app.domain.services.certificate_service import CertificateService


@pytest.fixture
def user_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def course_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def mock_db():
    """Mock async database session."""
    db = AsyncMock(spec=AsyncSession)
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.rollback = AsyncMock()
    return db


@pytest.fixture
def cert_service(mock_db):
    return CertificateService(mock_db)


# ── Verification code format ──────────────────────────────────────


class TestGenerateVerificationCode:
    async def test_format_matches_pattern(self, cert_service, mock_db):
        """Verification code should match CERT-XXXX-XXXX-XXXX format."""
        # Mock no existing code found
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        code = await cert_service._generate_verification_code()
        assert re.match(r"^CERT-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$", code)

    async def test_code_is_uppercase_alphanumeric(self, cert_service, mock_db):
        """Code segments should only contain uppercase letters and digits."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        code = await cert_service._generate_verification_code()
        segments = code.split("-")[1:]  # Skip "CERT" prefix
        for seg in segments:
            assert len(seg) == 4
            assert seg.isalnum()
            assert seg == seg.upper()


# ── Completion check ──────────────────────────────────────────────


class TestCheckCourseCompletion:
    async def test_returns_false_for_empty_course(self, cert_service, mock_db, user_id, course_id):
        """Course with no modules should not be considered complete."""
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        is_complete, avg_score, module_scores = await cert_service.check_course_completion(
            user_id, course_id
        )
        assert is_complete is False
        assert avg_score == 0.0
        assert module_scores == {}

    async def test_returns_true_when_all_modules_passed(
        self, cert_service, mock_db, user_id, course_id
    ):
        """Course is complete when all modules have a passing summative."""
        mod1, mod2 = uuid.uuid4(), uuid.uuid4()

        # First call: get module IDs
        modules_result = MagicMock()
        modules_result.all.return_value = [(mod1,), (mod2,)]

        # Second call: best score for module 1
        score1_result = MagicMock()
        score1_result.scalar.return_value = 90.0

        # Third call: best score for module 2
        score2_result = MagicMock()
        score2_result.scalar.return_value = 85.0

        mock_db.execute = AsyncMock(side_effect=[modules_result, score1_result, score2_result])

        is_complete, avg_score, module_scores = await cert_service.check_course_completion(
            user_id, course_id
        )
        assert is_complete is True
        assert avg_score == 87.5
        assert len(module_scores) == 2

    async def test_returns_false_when_module_not_passed(
        self, cert_service, mock_db, user_id, course_id
    ):
        """Course is not complete if any module lacks a passing summative."""
        mod1, mod2 = uuid.uuid4(), uuid.uuid4()

        modules_result = MagicMock()
        modules_result.all.return_value = [(mod1,), (mod2,)]

        score1_result = MagicMock()
        score1_result.scalar.return_value = 92.0

        # Module 2 has no passing score
        score2_result = MagicMock()
        score2_result.scalar.return_value = None

        mock_db.execute = AsyncMock(side_effect=[modules_result, score1_result, score2_result])

        is_complete, avg_score, module_scores = await cert_service.check_course_completion(
            user_id, course_id
        )
        assert is_complete is False
        assert len(module_scores) == 1


# ── Certificate issuance ──────────────────────────────────────────


class TestIssueCertificate:
    async def test_returns_existing_certificate_if_already_issued(
        self, cert_service, mock_db, user_id, course_id
    ):
        """Issuing a certificate for an already-certified course returns the existing one."""
        existing_cert = Certificate(
            id=uuid.uuid4(),
            user_id=user_id,
            course_id=course_id,
            verification_code="CERT-AAAA-BBBB-CCCC",
            average_score=88.0,
            completed_at=datetime.utcnow(),
            status="valid",
        )

        existing_result = MagicMock()
        existing_result.scalar_one_or_none.return_value = existing_cert
        mock_db.execute = AsyncMock(return_value=existing_result)

        cert = await cert_service.issue_certificate(user_id, course_id)
        assert cert.id == existing_cert.id
        assert cert.verification_code == "CERT-AAAA-BBBB-CCCC"

    async def test_raises_if_course_not_complete(self, cert_service, mock_db, user_id, course_id):
        """Cannot issue certificate if course is not complete."""
        # No existing cert
        no_cert_result = MagicMock()
        no_cert_result.scalar_one_or_none.return_value = None

        # No modules (so completion check fails)
        no_modules_result = MagicMock()
        no_modules_result.all.return_value = []

        mock_db.execute = AsyncMock(side_effect=[no_cert_result, no_modules_result])

        with pytest.raises(ValueError, match="Course not yet completed"):
            await cert_service.issue_certificate(user_id, course_id)

    async def test_raises_if_no_active_template(self, cert_service, mock_db, user_id, course_id):
        """Cannot issue certificate if course has no active template."""
        # No existing cert
        no_cert_result = MagicMock()
        no_cert_result.scalar_one_or_none.return_value = None

        # One module with passing score (course complete)
        mod_id = uuid.uuid4()
        modules_result = MagicMock()
        modules_result.all.return_value = [(mod_id,)]

        score_result = MagicMock()
        score_result.scalar.return_value = 95.0

        # No template
        no_template_result = MagicMock()
        no_template_result.scalar_one_or_none.return_value = None

        mock_db.execute = AsyncMock(
            side_effect=[no_cert_result, modules_result, score_result, no_template_result]
        )

        with pytest.raises(ValueError, match="No active certificate template"):
            await cert_service.issue_certificate(user_id, course_id)


# ── Template CRUD ─────────────────────────────────────────────────


class TestTemplateCRUD:
    async def test_get_template_returns_none_when_missing(self, cert_service, mock_db, course_id):
        """get_template returns None when no template exists for the course."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await cert_service.get_template(course_id)
        assert result is None

    async def test_get_template_returns_template(self, cert_service, mock_db, course_id):
        """get_template returns the template when it exists."""
        template = CertificateTemplate(
            id=uuid.uuid4(),
            course_id=course_id,
            title_fr="Certificat",
            title_en="Certificate",
            is_active=True,
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = template
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await cert_service.get_template(course_id)
        assert result is not None
        assert result.title_en == "Certificate"


# ── Verify certificate ────────────────────────────────────────────


class TestVerifyCertificate:
    async def test_returns_certificate_for_valid_code(self, cert_service, mock_db):
        """verify_certificate returns certificate details for a valid code."""
        cert = Certificate(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            course_id=uuid.uuid4(),
            verification_code="CERT-TEST-CODE-1234",
            average_score=91.5,
            completed_at=datetime.utcnow(),
            status="valid",
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = cert
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await cert_service.verify_certificate("CERT-TEST-CODE-1234")
        assert result is not None
        assert result.verification_code == "CERT-TEST-CODE-1234"
        assert result.average_score == 91.5

    async def test_returns_none_for_invalid_code(self, cert_service, mock_db):
        """verify_certificate returns None for non-existent codes."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await cert_service.verify_certificate("CERT-FAKE-CODE-0000")
        assert result is None
