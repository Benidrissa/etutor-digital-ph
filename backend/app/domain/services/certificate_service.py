"""Certificate service — template CRUD, completion check, and certificate issuance."""

from __future__ import annotations

import secrets
import string
import uuid
from datetime import datetime
from uuid import UUID

import structlog
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.models.certificate import Certificate, CertificateTemplate
from app.domain.models.course import Course
from app.domain.models.module import Module
from app.domain.models.quiz import SummativeAssessmentAttempt

logger = structlog.get_logger()


class CertificateService:
    """Core certificate business logic."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── Template CRUD ──────────────────────────────────────────────

    async def create_or_update_template(
        self,
        course_id: UUID,
        expert_id: UUID,
        data: dict,
    ) -> CertificateTemplate:
        """Create or update certificate template. Verifies expert owns the course."""
        course = await self.db.get(Course, course_id)
        if not course:
            raise ValueError("Course not found")
        if course.created_by != expert_id:
            raise PermissionError("Only the course creator can manage certificate templates")

        result = await self.db.execute(
            select(CertificateTemplate).where(CertificateTemplate.course_id == course_id)
        )
        template = result.scalar_one_or_none()

        if template:
            for key, value in data.items():
                if hasattr(template, key):
                    setattr(template, key, value)
            template.updated_at = datetime.utcnow()
        else:
            template = CertificateTemplate(id=uuid.uuid4(), course_id=course_id, **data)
            self.db.add(template)

        await self.db.commit()
        await self.db.refresh(template)
        logger.info("certificate_template_upserted", course_id=str(course_id))
        return template

    async def get_template(self, course_id: UUID) -> CertificateTemplate | None:
        """Return the certificate template for a course, or None."""
        result = await self.db.execute(
            select(CertificateTemplate).where(CertificateTemplate.course_id == course_id)
        )
        return result.scalar_one_or_none()

    # ── Course completion check ────────────────────────────────────

    async def check_course_completion(
        self, user_id: UUID, course_id: UUID
    ) -> tuple[bool, float, dict]:
        """Check if user completed all modules (each has a passing summative).

        Returns: (is_complete, average_score, module_scores_dict)
        """
        result = await self.db.execute(select(Module.id).where(Module.course_id == course_id))
        module_ids = [row[0] for row in result.all()]

        if not module_ids:
            return False, 0.0, {}

        module_scores: dict[str, float] = {}
        for mid in module_ids:
            best = await self.db.execute(
                select(func.max(SummativeAssessmentAttempt.score)).where(
                    SummativeAssessmentAttempt.user_id == user_id,
                    SummativeAssessmentAttempt.module_id == mid,
                    SummativeAssessmentAttempt.passed == True,  # noqa: E712
                )
            )
            best_score = best.scalar()
            if best_score is not None:
                module_scores[str(mid)] = best_score

        is_complete = len(module_scores) == len(module_ids)
        avg_score = sum(module_scores.values()) / len(module_scores) if module_scores else 0.0
        return is_complete, round(avg_score, 1), module_scores

    # ── Certificate issuance ───────────────────────────────────────

    async def issue_certificate(self, user_id: UUID, course_id: UUID) -> Certificate:
        """Issue a certificate for a completed course. Idempotent."""
        # Check existing (idempotent)
        existing_result = await self.db.execute(
            select(Certificate).where(
                Certificate.user_id == user_id,
                Certificate.course_id == course_id,
            )
        )
        existing_cert = existing_result.scalar_one_or_none()
        if existing_cert:
            logger.info(
                "certificate_already_exists", user_id=str(user_id), course_id=str(course_id)
            )
            return existing_cert

        # Check completion
        is_complete, avg_score, module_scores = await self.check_course_completion(
            user_id, course_id
        )
        if not is_complete:
            raise ValueError("Course not yet completed")

        # Get template
        template = await self.get_template(course_id)
        if not template or not template.is_active:
            raise ValueError("No active certificate template for this course")

        verification_code = await self._generate_verification_code()

        certificate = Certificate(
            id=uuid.uuid4(),
            template_id=template.id,
            user_id=user_id,
            course_id=course_id,
            verification_code=verification_code,
            average_score=avg_score,
            completed_at=datetime.utcnow(),
            status="valid",
            metadata_json={"module_scores": module_scores},
        )

        try:
            self.db.add(certificate)
            await self.db.commit()
            await self.db.refresh(certificate)
        except IntegrityError:
            await self.db.rollback()
            result = await self.db.execute(
                select(Certificate).where(
                    Certificate.user_id == user_id,
                    Certificate.course_id == course_id,
                )
            )
            certificate = result.scalar_one()
            logger.info("certificate_race_condition_handled", user_id=str(user_id))

        logger.info(
            "certificate_issued",
            certificate_id=str(certificate.id),
            user_id=str(user_id),
            course_id=str(course_id),
            verification_code=verification_code,
        )
        return certificate

    # ── Retrieval ──────────────────────────────────────────────────

    async def get_user_certificates(self, user_id: UUID) -> list[Certificate]:
        """List all certificates for a user with course + template loaded."""
        result = await self.db.execute(
            select(Certificate)
            .where(Certificate.user_id == user_id)
            .options(selectinload(Certificate.course), selectinload(Certificate.template))
            .order_by(Certificate.issued_at.desc())
        )
        return list(result.scalars().all())

    async def get_certificate(self, certificate_id: UUID) -> Certificate | None:
        """Get a single certificate by ID with relations loaded."""
        result = await self.db.execute(
            select(Certificate)
            .where(Certificate.id == certificate_id)
            .options(selectinload(Certificate.course), selectinload(Certificate.template))
        )
        return result.scalar_one_or_none()

    async def verify_certificate(self, verification_code: str) -> Certificate | None:
        """Public lookup by verification code. No auth needed."""
        result = await self.db.execute(
            select(Certificate)
            .where(Certificate.verification_code == verification_code)
            .options(selectinload(Certificate.course), selectinload(Certificate.template))
        )
        return result.scalar_one_or_none()

    # ── Helpers ────────────────────────────────────────────────────

    async def _generate_verification_code(self) -> str:
        """Generate unique CERT-XXXX-XXXX-XXXX verification code."""
        charset = string.ascii_uppercase + string.digits
        for _ in range(10):
            segments = ["".join(secrets.choice(charset) for _ in range(4)) for _ in range(3)]
            code = f"CERT-{segments[0]}-{segments[1]}-{segments[2]}"
            exists = await self.db.execute(
                select(Certificate.id).where(Certificate.verification_code == code)
            )
            if not exists.scalar_one_or_none():
                return code
        raise RuntimeError("Failed to generate unique verification code after 10 attempts")
