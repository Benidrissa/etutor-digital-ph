"""Question bank service — CRUD for banks, questions, tests, and attempt scoring."""

from __future__ import annotations

import math
import random
import uuid

import structlog
from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.organization import Organization, OrganizationMember, OrgMemberRole
from app.domain.models.qbank import (
    BankQuestion,
    BankTest,
    BankType,
    QuestionBank,
    TestAttempt,
    TestMode,
)
from app.domain.models.user import User, UserRole

logger = structlog.get_logger(__name__)


class QBankService:
    # ------------------------------------------------------------------
    # Authorization helpers
    # ------------------------------------------------------------------

    async def _require_org_admin(
        self, db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID
    ) -> None:
        user = await db.get(User, user_id)
        if user and user.role in (UserRole.admin, UserRole.sub_admin):
            return
        result = await db.execute(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == org_id,
                OrganizationMember.user_id == user_id,
            )
        )
        member = result.scalar_one_or_none()
        if member is None or member.role not in (OrgMemberRole.owner, OrgMemberRole.admin):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Organization admin role required.",
            )

    async def _require_org_member(
        self, db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID
    ) -> None:
        user = await db.get(User, user_id)
        if user and user.role in (UserRole.admin, UserRole.sub_admin):
            return
        result = await db.execute(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == org_id,
                OrganizationMember.user_id == user_id,
            )
        )
        if result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Organization membership required.",
            )

    # ------------------------------------------------------------------
    # Question Bank CRUD
    # ------------------------------------------------------------------

    async def create_question_bank(
        self,
        db: AsyncSession,
        *,
        org_id: uuid.UUID,
        title: str,
        bank_type: str = "mixed",
        description: str | None = None,
        creator_id: uuid.UUID,
    ) -> QuestionBank:
        await self._require_org_admin(db, org_id, creator_id)

        org = await db.get(Organization, org_id)
        if org is None or not org.is_active:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found."
            )

        bank = QuestionBank(
            organization_id=org_id,
            title=title,
            description=description,
            bank_type=BankType(bank_type),
            created_by=creator_id,
        )
        db.add(bank)
        await db.commit()
        await db.refresh(bank)
        logger.info("qbank_created", bank_id=str(bank.id), org_id=str(org_id))
        return bank

    async def get_question_bank(
        self, db: AsyncSession, bank_id: uuid.UUID
    ) -> QuestionBank:
        bank = await db.get(QuestionBank, bank_id)
        if bank is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Question bank not found."
            )
        return bank

    async def list_org_question_banks(
        self, db: AsyncSession, org_id: uuid.UUID
    ) -> list[QuestionBank]:
        result = await db.execute(
            select(QuestionBank)
            .where(
                QuestionBank.organization_id == org_id,
                QuestionBank.is_active.is_(True),
            )
            .order_by(QuestionBank.created_at.desc())
        )
        return list(result.scalars().all())

    async def update_question_bank(
        self,
        db: AsyncSession,
        bank_id: uuid.UUID,
        actor_id: uuid.UUID,
        **fields,
    ) -> QuestionBank:
        bank = await self.get_question_bank(db, bank_id)
        await self._require_org_admin(db, bank.organization_id, actor_id)

        allowed = {"title", "description", "bank_type", "is_active"}
        for key, value in fields.items():
            if key in allowed and value is not None:
                if key == "bank_type":
                    setattr(bank, key, BankType(value))
                else:
                    setattr(bank, key, value)

        await db.commit()
        await db.refresh(bank)
        return bank

    async def delete_question_bank(
        self, db: AsyncSession, bank_id: uuid.UUID, actor_id: uuid.UUID
    ) -> None:
        bank = await self.get_question_bank(db, bank_id)
        await self._require_org_admin(db, bank.organization_id, actor_id)
        bank.is_active = False
        await db.commit()
        logger.info("qbank_archived", bank_id=str(bank_id))

    # ------------------------------------------------------------------
    # Question CRUD
    # ------------------------------------------------------------------

    async def list_questions(
        self,
        db: AsyncSession,
        bank_id: uuid.UUID,
        page: int = 1,
        per_page: int = 20,
    ) -> tuple[list[BankQuestion], int]:
        offset = (page - 1) * per_page

        count_result = await db.execute(
            select(func.count(BankQuestion.id)).where(
                BankQuestion.bank_id == bank_id,
                BankQuestion.is_active.is_(True),
            )
        )
        total = count_result.scalar_one()

        result = await db.execute(
            select(BankQuestion)
            .where(
                BankQuestion.bank_id == bank_id,
                BankQuestion.is_active.is_(True),
            )
            .order_by(BankQuestion.created_at.asc())
            .offset(offset)
            .limit(per_page)
        )
        return list(result.scalars().all()), total

    async def get_question(
        self, db: AsyncSession, question_id: uuid.UUID
    ) -> BankQuestion:
        q = await db.get(BankQuestion, question_id)
        if q is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Question not found."
            )
        return q

    async def update_question(
        self,
        db: AsyncSession,
        question_id: uuid.UUID,
        actor_id: uuid.UUID,
        **fields,
    ) -> BankQuestion:
        question = await self.get_question(db, question_id)
        bank = await self.get_question_bank(db, question.bank_id)
        await self._require_org_admin(db, bank.organization_id, actor_id)

        allowed = {
            "question_text",
            "options",
            "correct_answer",
            "explanation",
            "category",
            "difficulty",
            "image_url",
            "source_ref",
            "is_active",
        }
        for key, value in fields.items():
            if key in allowed and value is not None:
                setattr(question, key, value)

        await db.commit()
        await db.refresh(question)
        return question

    async def delete_question(
        self, db: AsyncSession, question_id: uuid.UUID, actor_id: uuid.UUID
    ) -> None:
        question = await self.get_question(db, question_id)
        bank = await self.get_question_bank(db, question.bank_id)
        await self._require_org_admin(db, bank.organization_id, actor_id)
        question.is_active = False
        await db.commit()

    # ------------------------------------------------------------------
    # Test CRUD
    # ------------------------------------------------------------------

    async def create_test(
        self,
        db: AsyncSession,
        *,
        bank_id: uuid.UUID,
        title: str,
        mode: str = "exam",
        description: str | None = None,
        question_count: int = 20,
        time_limit_minutes: int | None = None,
        passing_score: float = 70.0,
        category_filter: str | None = None,
        difficulty_filter: str | None = None,
        shuffle_questions: bool = True,
        show_answers: bool = False,
        creator_id: uuid.UUID,
    ) -> BankTest:
        bank = await self.get_question_bank(db, bank_id)
        await self._require_org_admin(db, bank.organization_id, creator_id)

        test = BankTest(
            bank_id=bank_id,
            title=title,
            description=description,
            mode=TestMode(mode),
            question_count=question_count,
            time_limit_minutes=time_limit_minutes,
            passing_score=passing_score,
            category_filter=category_filter,
            difficulty_filter=difficulty_filter,
            shuffle_questions=shuffle_questions,
            show_answers=show_answers,
            created_by=creator_id,
        )
        db.add(test)
        await db.commit()
        await db.refresh(test)
        logger.info("bank_test_created", test_id=str(test.id), bank_id=str(bank_id))
        return test

    async def get_test(self, db: AsyncSession, test_id: uuid.UUID) -> BankTest:
        test = await db.get(BankTest, test_id)
        if test is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Test not found."
            )
        return test

    async def list_tests(
        self, db: AsyncSession, bank_id: uuid.UUID
    ) -> list[BankTest]:
        result = await db.execute(
            select(BankTest)
            .where(BankTest.bank_id == bank_id, BankTest.is_active.is_(True))
            .order_by(BankTest.created_at.desc())
        )
        return list(result.scalars().all())

    async def update_test(
        self,
        db: AsyncSession,
        test_id: uuid.UUID,
        actor_id: uuid.UUID,
        **fields,
    ) -> BankTest:
        test = await self.get_test(db, test_id)
        bank = await self.get_question_bank(db, test.bank_id)
        await self._require_org_admin(db, bank.organization_id, actor_id)

        allowed = {
            "title",
            "description",
            "mode",
            "question_count",
            "time_limit_minutes",
            "passing_score",
            "category_filter",
            "difficulty_filter",
            "shuffle_questions",
            "show_answers",
            "is_active",
        }
        for key, value in fields.items():
            if key in allowed and value is not None:
                if key == "mode":
                    setattr(test, key, TestMode(value))
                else:
                    setattr(test, key, value)

        await db.commit()
        await db.refresh(test)
        return test

    async def delete_test(
        self, db: AsyncSession, test_id: uuid.UUID, actor_id: uuid.UUID
    ) -> None:
        test = await self.get_test(db, test_id)
        bank = await self.get_question_bank(db, test.bank_id)
        await self._require_org_admin(db, bank.organization_id, actor_id)
        test.is_active = False
        await db.commit()

    # ------------------------------------------------------------------
    # Test execution
    # ------------------------------------------------------------------

    async def start_test(
        self, db: AsyncSession, test_id: uuid.UUID, user_id: uuid.UUID
    ) -> tuple[BankTest, list[BankQuestion]]:
        """Assemble questions for a test session according to mode and filters."""
        test = await self.get_test(db, test_id)
        bank = await self.get_question_bank(db, test.bank_id)
        await self._require_org_member(db, bank.organization_id, user_id)

        query = select(BankQuestion).where(
            BankQuestion.bank_id == test.bank_id,
            BankQuestion.is_active.is_(True),
        )

        if test.mode == TestMode.training:
            failed_ids = await self.get_failed_question_ids(db, test_id, user_id)
            if failed_ids:
                query = query.where(BankQuestion.id.in_(failed_ids))

        if test.category_filter:
            query = query.where(BankQuestion.category == test.category_filter)
        if test.difficulty_filter:
            query = query.where(BankQuestion.difficulty == test.difficulty_filter)

        result = await db.execute(query)
        all_questions = list(result.scalars().all())

        if not all_questions:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="No questions available for this test configuration.",
            )

        if test.shuffle_questions:
            random.shuffle(all_questions)

        questions = all_questions[: test.question_count]
        return test, questions

    async def submit_test(
        self,
        db: AsyncSession,
        test_id: uuid.UUID,
        user_id: uuid.UUID,
        answers: dict[str, dict],
    ) -> TestAttempt:
        """Score a test submission and store the attempt."""
        test = await self.get_test(db, test_id)
        bank = await self.get_question_bank(db, test.bank_id)
        await self._require_org_member(db, bank.organization_id, user_id)

        question_ids = list(answers.keys())
        if not question_ids:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="No answers submitted.",
            )

        q_uuids = []
        for qid in question_ids:
            try:
                q_uuids.append(uuid.UUID(qid))
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Invalid question id: {qid}",
                )

        result = await db.execute(
            select(BankQuestion).where(BankQuestion.id.in_(q_uuids))
        )
        questions = {str(q.id): q for q in result.scalars().all()}

        correct_count = 0
        category_counts: dict[str, dict[str, int]] = {}
        total_time = 0

        for qid, answer_data in answers.items():
            q = questions.get(qid)
            if q is None:
                continue

            selected = answer_data.get("selected", [])
            time_sec = answer_data.get("time_sec", 0)
            total_time += time_sec

            is_correct = len(selected) == 1 and selected[0] == q.correct_answer
            if is_correct:
                correct_count += 1

            cat = q.category or "uncategorized"
            if cat not in category_counts:
                category_counts[cat] = {"correct": 0, "total": 0}
            category_counts[cat]["total"] += 1
            if is_correct:
                category_counts[cat]["correct"] += 1

        total_q = len(questions)
        score = (correct_count / total_q * 100) if total_q > 0 else 0.0
        passed = score >= test.passing_score

        category_breakdown = {
            cat: {
                "correct": v["correct"],
                "total": v["total"],
                "score": round(v["correct"] / v["total"] * 100, 1) if v["total"] > 0 else 0.0,
            }
            for cat, v in category_counts.items()
        }

        attempt = TestAttempt(
            test_id=test_id,
            user_id=user_id,
            answers=answers,
            question_ids=[str(q) for q in q_uuids],
            score=round(score, 2),
            total_questions=total_q,
            correct_count=correct_count,
            passed=passed,
            category_breakdown=category_breakdown,
            time_taken_sec=total_time if total_time > 0 else None,
        )
        db.add(attempt)
        await db.commit()
        await db.refresh(attempt)
        logger.info(
            "test_attempt_stored",
            attempt_id=str(attempt.id),
            test_id=str(test_id),
            score=score,
        )
        return attempt

    async def get_attempt_history(
        self,
        db: AsyncSession,
        test_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> list[TestAttempt]:
        result = await db.execute(
            select(TestAttempt)
            .where(
                TestAttempt.test_id == test_id,
                TestAttempt.user_id == user_id,
            )
            .order_by(TestAttempt.attempted_at.desc())
        )
        return list(result.scalars().all())

    async def get_failed_question_ids(
        self,
        db: AsyncSession,
        test_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> list[uuid.UUID]:
        """Return question IDs the user has answered incorrectly in past attempts."""
        result = await db.execute(
            select(TestAttempt)
            .where(
                TestAttempt.test_id == test_id,
                TestAttempt.user_id == user_id,
            )
            .order_by(TestAttempt.attempted_at.desc())
        )
        attempts = result.scalars().all()

        failed_ids: set[str] = set()
        correct_ids: set[str] = set()

        for attempt in attempts:
            answers: dict = attempt.answers or {}
            for qid, answer_data in answers.items():
                selected = answer_data.get("selected", [])
                if not selected:
                    continue
                result2 = await db.execute(
                    select(BankQuestion.correct_answer).where(
                        BankQuestion.id == uuid.UUID(qid)
                    )
                )
                correct_ans = result2.scalar_one_or_none()
                if correct_ans is None:
                    continue
                if len(selected) == 1 and selected[0] == correct_ans:
                    correct_ids.add(qid)
                else:
                    failed_ids.add(qid)

        net_failed = failed_ids - correct_ids
        uuids = []
        for qid in net_failed:
            try:
                uuids.append(uuid.UUID(qid))
            except ValueError:
                pass
        return uuids
