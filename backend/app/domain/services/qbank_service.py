"""Question Bank service — CRUD for banks, questions, tests, attempts."""

from __future__ import annotations

import random
import uuid
from collections import defaultdict

import structlog
from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.organization import OrgMemberRole
from app.domain.models.question_bank import (
    QBankQuestion,
    QBankTest,
    QBankTestAttempt,
    QuestionBank,
)
from app.domain.services.organization_service import OrganizationService

logger = structlog.get_logger(__name__)

_org_svc = OrganizationService()


async def _enqueue_pregenerate_audio(db: AsyncSession, bank_id: uuid.UUID) -> None:
    """Fan-out Celery tasks to translate + synthesize audio (#1708).

    Per-question fan-out: for each non-FR target language, enqueue one
    ``translate_and_synthesize_question_task`` per question. NLLB still
    serializes (single sidecar worker), but MMS synthesis for question
    K can now run in parallel with NLLB translating question K+1, and
    different languages can progress concurrently rather than waiting
    for a bank-level chain. French skips translation and uses the
    existing bank-level audio task.

    Imports are local so this module stays safe to import in contexts
    where Celery isn't wired up (tests that patch the task).
    """
    from app.domain.services.qbank_audio_service import SUPPORTED_LANGUAGES
    from app.domain.services.qbank_translation_service import TARGET_LANGUAGES
    from app.tasks.qbank_processing import (
        generate_qbank_audio_task,
        translate_and_synthesize_question_task,
    )

    bank_id_str = str(bank_id)
    question_ids = (
        (
            await db.execute(
                select(QBankQuestion.id).where(QBankQuestion.question_bank_id == bank_id)
            )
        )
        .scalars()
        .all()
    )

    for language in SUPPORTED_LANGUAGES:
        try:
            if language in TARGET_LANGUAGES:
                for qid in question_ids:
                    translate_and_synthesize_question_task.delay(str(qid), language)
            else:
                generate_qbank_audio_task.delay(bank_id_str, language)
        except Exception as exc:
            logger.warning(
                "failed to enqueue qbank audio pregeneration",
                bank_id=bank_id_str,
                language=language,
                error=str(exc),
            )


class QBankService:
    # ------------------------------------------------------------------
    # Question Bank CRUD
    # ------------------------------------------------------------------

    async def create_bank(
        self,
        db: AsyncSession,
        *,
        organization_id: uuid.UUID | None,
        title: str,
        bank_type: str,
        created_by: uuid.UUID,
        description: str | None = None,
        language: str = "fr",
        time_per_question_sec: int = 60,
        passing_score: float = 80.0,
        visibility: str = "org_restricted",
    ) -> QuestionBank:
        if visibility == "org_restricted":
            await _org_svc.require_org_role(
                db,
                organization_id,
                created_by,
                OrgMemberRole.owner,
                OrgMemberRole.admin,
            )
        bank = QuestionBank(
            organization_id=organization_id,
            visibility=visibility,
            title=title,
            description=description,
            bank_type=bank_type,
            language=language,
            time_per_question_sec=time_per_question_sec,
            passing_score=passing_score,
            created_by=created_by,
        )
        db.add(bank)
        await db.commit()
        await db.refresh(bank)
        return bank

    async def get_bank(self, db: AsyncSession, bank_id: uuid.UUID) -> QuestionBank:
        bank = await db.get(QuestionBank, bank_id)
        if bank is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Question bank not found.",
            )
        return bank

    async def list_org_banks(self, db: AsyncSession, organization_id: uuid.UUID) -> list[dict]:
        result = await db.execute(
            select(QuestionBank)
            .where(QuestionBank.organization_id == organization_id)
            .order_by(QuestionBank.created_at.desc())
        )
        banks = result.scalars().all()
        return await self._enrich_banks(db, banks)

    async def list_accessible_banks(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        *,
        include_drafts: bool = False,
    ) -> list[dict]:
        """Return all banks the user can access (#1692, #1782).

        Combines:
        - Public banks (visible to all authenticated users)
        - Org-restricted banks from every org the user is a member of

        Defaults to published-only; set ``include_drafts=True`` for admin UIs.
        """
        from sqlalchemy.orm import selectinload

        from app.domain.models.organization import OrganizationMember
        from app.domain.models.question_bank import QBankVisibility, QuestionBankStatus

        user_orgs = (
            (
                await db.execute(
                    select(OrganizationMember.organization_id).where(
                        OrganizationMember.user_id == user_id
                    )
                )
            )
            .scalars()
            .all()
        )

        public_filters = [QuestionBank.visibility == QBankVisibility.public]
        org_filters = [
            QuestionBank.visibility == QBankVisibility.org_restricted,
            QuestionBank.organization_id.in_(user_orgs),
        ]
        if not include_drafts:
            public_filters.append(QuestionBank.status == QuestionBankStatus.published)
            org_filters.append(QuestionBank.status == QuestionBankStatus.published)

        public_banks = (
            (
                await db.execute(
                    select(QuestionBank)
                    .where(*public_filters)
                    .options(selectinload(QuestionBank.organization))
                    .order_by(QuestionBank.created_at.desc())
                )
            )
            .scalars()
            .all()
        )

        org_banks: list[QuestionBank] = []
        if user_orgs:
            org_banks = (
                (
                    await db.execute(
                        select(QuestionBank)
                        .where(*org_filters)
                        .options(selectinload(QuestionBank.organization))
                        .order_by(QuestionBank.created_at.desc())
                    )
                )
                .scalars()
                .all()
            )

        # Merge, preserving order (public first) and deduplicating by id.
        seen: set[uuid.UUID] = set()
        merged: list[QuestionBank] = []
        for bank in list(public_banks) + list(org_banks):
            if bank.id not in seen:
                seen.add(bank.id)
                merged.append(bank)

        return await self._enrich_banks(db, merged)

    async def list_accessible_tests(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
    ) -> list[dict]:
        """Return tests the user can take, flattened across accessible banks.

        Uses ``list_accessible_banks`` (published-only) to find every bank
        the user has org-level access to, then loads the tests under each.
        Returns one dict per test with enough bank context for the
        learner-facing "Tests I can take" page (#1732) to render without a
        drill-through.
        """
        from sqlalchemy.orm import selectinload

        bank_rows = await self.list_accessible_banks(db, user_id)
        if not bank_rows:
            return []

        bank_ids = [row["bank"].id for row in bank_rows]
        banks_by_id = {row["bank"].id: row["bank"] for row in bank_rows}

        tests = (
            (
                await db.execute(
                    select(QBankTest)
                    .where(QBankTest.question_bank_id.in_(bank_ids))
                    .options(
                        selectinload(QBankTest.question_bank).selectinload(
                            QuestionBank.organization
                        )
                    )
                    .order_by(QBankTest.created_at.desc())
                )
            )
            .scalars()
            .all()
        )

        out: list[dict] = []
        for test in tests:
            bank = test.question_bank or banks_by_id.get(test.question_bank_id)
            org = getattr(bank, "organization", None) if bank else None
            out.append(
                {
                    "test": test,
                    "bank_title": bank.title if bank else None,
                    "bank_language": bank.language if bank else None,
                    "bank_org_name": org.name if org else None,
                    "bank_org_slug": org.slug if org else None,
                }
            )
        return out

    async def _enrich_banks(self, db: AsyncSession, banks: list[QuestionBank]) -> list[dict]:
        """Attach question + test counts to a list of banks."""
        out = []
        for bank in banks:
            q_count = await db.scalar(
                select(func.count())
                .select_from(QBankQuestion)
                .where(QBankQuestion.question_bank_id == bank.id)
            )
            t_count = await db.scalar(
                select(func.count())
                .select_from(QBankTest)
                .where(QBankTest.question_bank_id == bank.id)
            )
            out.append(
                {
                    "bank": bank,
                    "question_count": q_count or 0,
                    "test_count": t_count or 0,
                }
            )
        return out

    async def update_bank(
        self,
        db: AsyncSession,
        bank_id: uuid.UUID,
        actor_id: uuid.UUID,
        **fields,
    ) -> QuestionBank:
        bank = await self.get_bank(db, bank_id)
        await _org_svc.require_org_role(
            db,
            bank.organization_id,
            actor_id,
            OrgMemberRole.owner,
            OrgMemberRole.admin,
        )
        allowed = {
            "title",
            "description",
            "language",
            "time_per_question_sec",
            "passing_score",
            "status",
        }
        previous_status = bank.status.value if hasattr(bank.status, "value") else bank.status
        for key, value in fields.items():
            if key in allowed and value is not None:
                setattr(bank, key, value)
        await db.commit()
        await db.refresh(bank)

        # Publish transition fires audio pregeneration for every supported
        # language so learners never wait on the timer for TTS (#1674).
        new_status = bank.status.value if hasattr(bank.status, "value") else bank.status
        if previous_status != "published" and new_status == "published":
            await _enqueue_pregenerate_audio(db, bank_id)

        return bank

    async def delete_bank(
        self,
        db: AsyncSession,
        bank_id: uuid.UUID,
        actor_id: uuid.UUID,
    ) -> None:
        bank = await self.get_bank(db, bank_id)
        await _org_svc.require_org_role(
            db,
            bank.organization_id,
            actor_id,
            OrgMemberRole.owner,
            OrgMemberRole.admin,
        )
        await db.delete(bank)
        await db.commit()

    # ------------------------------------------------------------------
    # Questions
    # ------------------------------------------------------------------

    async def list_questions(
        self,
        db: AsyncSession,
        bank_id: uuid.UUID,
        page: int = 1,
        per_page: int = 50,
    ) -> dict:
        total = await db.scalar(
            select(func.count())
            .select_from(QBankQuestion)
            .where(QBankQuestion.question_bank_id == bank_id)
        )
        result = await db.execute(
            select(QBankQuestion)
            .where(QBankQuestion.question_bank_id == bank_id)
            .order_by(QBankQuestion.order_index)
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
        return {
            "questions": result.scalars().all(),
            "total": total or 0,
            "page": page,
            "per_page": per_page,
        }

    async def update_question(
        self,
        db: AsyncSession,
        question_id: uuid.UUID,
        actor_id: uuid.UUID,
        **fields,
    ) -> QBankQuestion:
        question = await db.get(QBankQuestion, question_id)
        if question is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Question not found.",
            )
        bank = await self.get_bank(db, question.question_bank_id)
        await _org_svc.require_org_role(
            db,
            bank.organization_id,
            actor_id,
            OrgMemberRole.owner,
            OrgMemberRole.admin,
        )
        allowed = {
            "question_text",
            "options",
            "correct_answer_indices",
            "explanation",
            "category",
            "difficulty",
        }
        # Changes to the spoken text or option list make the cached TTS
        # clips stale — drop them and re-enqueue generation downstream.
        invalidating_keys = {"question_text", "options"}
        should_invalidate_audio = any(
            key in invalidating_keys and value is not None and value != getattr(question, key, None)
            for key, value in fields.items()
        )
        for key, value in fields.items():
            if key in allowed and value is not None:
                setattr(question, key, value)
        await db.commit()
        await db.refresh(question)

        if should_invalidate_audio:
            from app.domain.services.qbank_audio_service import QBankAudioService
            from app.domain.services.qbank_translation_service import (
                QBankTranslationService,
            )

            # Stale audio + stale translations both need clearing. Admin-
            # edited translations survive (preserved by the translation
            # service's invalidate_question method). Next audio regen
            # will trigger fresh NLLB calls for dropped rows (#1690).
            await QBankAudioService().invalidate_question(db, question_id)
            await QBankTranslationService().invalidate_question(db, question_id)
            await _enqueue_pregenerate_audio(db, question.question_bank_id)

        return question

    async def delete_question(
        self,
        db: AsyncSession,
        question_id: uuid.UUID,
        actor_id: uuid.UUID,
    ) -> None:
        question = await db.get(QBankQuestion, question_id)
        if question is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Question not found.",
            )
        bank = await self.get_bank(db, question.question_bank_id)
        await _org_svc.require_org_role(
            db,
            bank.organization_id,
            actor_id,
            OrgMemberRole.owner,
            OrgMemberRole.admin,
        )
        await db.delete(question)
        await db.commit()

    # ------------------------------------------------------------------
    # Test CRUD
    # ------------------------------------------------------------------

    async def create_test(
        self,
        db: AsyncSession,
        *,
        question_bank_id: uuid.UUID,
        title: str,
        mode: str,
        created_by: uuid.UUID,
        question_count: int | None = None,
        shuffle_questions: bool = True,
        time_per_question_sec: int | None = None,
        show_feedback: bool = False,
        filter_categories: list[str] | None = None,
        filter_failed_only: bool = False,
    ) -> QBankTest:
        bank = await self.get_bank(db, question_bank_id)
        await _org_svc.require_org_role(
            db,
            bank.organization_id,
            created_by,
            OrgMemberRole.owner,
            OrgMemberRole.admin,
        )
        test = QBankTest(
            question_bank_id=question_bank_id,
            title=title,
            mode=mode,
            question_count=question_count,
            shuffle_questions=shuffle_questions,
            time_per_question_sec=time_per_question_sec,
            show_feedback=show_feedback,
            filter_categories=filter_categories,
            filter_failed_only=filter_failed_only,
            created_by=created_by,
        )
        db.add(test)
        await db.commit()
        await db.refresh(test)
        return test

    async def get_test(self, db: AsyncSession, test_id: uuid.UUID) -> QBankTest:
        test = await db.get(QBankTest, test_id)
        if test is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Test not found.",
            )
        return test

    async def list_tests(self, db: AsyncSession, bank_id: uuid.UUID) -> list[QBankTest]:
        result = await db.execute(
            select(QBankTest)
            .where(QBankTest.question_bank_id == bank_id)
            .order_by(QBankTest.created_at.desc())
        )
        return list(result.scalars().all())

    async def update_test(
        self,
        db: AsyncSession,
        test_id: uuid.UUID,
        actor_id: uuid.UUID,
        **fields,
    ) -> QBankTest:
        test = await self.get_test(db, test_id)
        bank = await self.get_bank(db, test.question_bank_id)
        await _org_svc.require_org_role(
            db,
            bank.organization_id,
            actor_id,
            OrgMemberRole.owner,
            OrgMemberRole.admin,
        )
        allowed = {
            "title",
            "mode",
            "question_count",
            "shuffle_questions",
            "time_per_question_sec",
            "show_feedback",
            "filter_categories",
            "filter_failed_only",
        }
        for key, value in fields.items():
            if key in allowed and value is not None:
                setattr(test, key, value)
        await db.commit()
        await db.refresh(test)
        return test

    async def delete_test(
        self,
        db: AsyncSession,
        test_id: uuid.UUID,
        actor_id: uuid.UUID,
    ) -> None:
        test = await self.get_test(db, test_id)
        bank = await self.get_bank(db, test.question_bank_id)
        await _org_svc.require_org_role(
            db,
            bank.organization_id,
            actor_id,
            OrgMemberRole.owner,
            OrgMemberRole.admin,
        )
        await db.delete(test)
        await db.commit()

    # ------------------------------------------------------------------
    # Test Session — start / submit / history / review
    # ------------------------------------------------------------------

    async def start_test(
        self,
        db: AsyncSession,
        test_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> dict:
        test = await self.get_test(db, test_id)
        bank = await self.get_bank(db, test.question_bank_id)

        # Build question query
        stmt = select(QBankQuestion).where(QBankQuestion.question_bank_id == bank.id)

        # Filter by categories if configured
        if test.filter_categories:
            stmt = stmt.where(QBankQuestion.category.in_(test.filter_categories))

        # Filter to previously failed questions only
        if test.filter_failed_only:
            failed_ids = await self._get_failed_question_ids(db, test_id, user_id)
            if failed_ids:
                stmt = stmt.where(QBankQuestion.id.in_(failed_ids))

        stmt = stmt.order_by(QBankQuestion.order_index)
        result = await db.execute(stmt)
        questions = list(result.scalars().all())

        # Shuffle if configured
        if test.shuffle_questions:
            random.shuffle(questions)

        # Limit question count
        if test.question_count and len(questions) > test.question_count:
            questions = questions[: test.question_count]

        time_per_q = test.time_per_question_sec or bank.time_per_question_sec

        return {
            "test": test,
            "bank": bank,
            "questions": questions,
            "time_per_question_sec": time_per_q,
        }

    async def submit_test(
        self,
        db: AsyncSession,
        test_id: uuid.UUID,
        user_id: uuid.UUID,
        answers: dict,
    ) -> QBankTestAttempt:
        test = await self.get_test(db, test_id)
        bank = await self.get_bank(db, test.question_bank_id)

        # Load all questions for scoring
        question_ids = list(answers.keys())
        result = await db.execute(
            select(QBankQuestion).where(
                QBankQuestion.id.in_([uuid.UUID(qid) for qid in question_ids])
            )
        )
        questions_map = {str(q.id): q for q in result.scalars().all()}

        correct = 0
        total = len(question_ids)
        total_time = 0
        category_counts: dict[str, dict] = defaultdict(lambda: {"correct": 0, "total": 0})

        for qid, answer_data in answers.items():
            question = questions_map.get(qid)
            if not question:
                continue
            selected = answer_data.get("selected", [])
            time_sec = answer_data.get("time_sec", 0)
            total_time += time_sec

            is_correct = sorted(selected) == sorted(question.correct_answer_indices)
            if is_correct:
                correct += 1

            cat = question.category or "uncategorized"
            category_counts[cat]["total"] += 1
            if is_correct:
                category_counts[cat]["correct"] += 1

        score = (correct / total * 100) if total > 0 else 0
        passed = score >= bank.passing_score

        # Count previous attempts
        prev_count = await db.scalar(
            select(func.count())
            .select_from(QBankTestAttempt)
            .where(
                QBankTestAttempt.test_id == test_id,
                QBankTestAttempt.user_id == user_id,
            )
        )

        attempt = QBankTestAttempt(
            test_id=test_id,
            user_id=user_id,
            answers=answers,
            score=score,
            total_questions=total,
            correct_answers=correct,
            time_taken_sec=total_time,
            passed=passed,
            category_breakdown=dict(category_counts),
            attempt_number=(prev_count or 0) + 1,
        )
        db.add(attempt)
        await db.commit()
        await db.refresh(attempt)
        return attempt

    async def get_attempt_history(
        self,
        db: AsyncSession,
        test_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> list[QBankTestAttempt]:
        result = await db.execute(
            select(QBankTestAttempt)
            .where(
                QBankTestAttempt.test_id == test_id,
                QBankTestAttempt.user_id == user_id,
            )
            .order_by(QBankTestAttempt.attempted_at.desc())
        )
        return list(result.scalars().all())

    async def get_review(
        self,
        db: AsyncSession,
        test_id: uuid.UUID,
        attempt_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> dict:
        attempt = await db.get(QBankTestAttempt, attempt_id)
        if attempt is None or attempt.user_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Attempt not found.",
            )
        await self.get_test(db, test_id)

        question_ids = [uuid.UUID(qid) for qid in attempt.answers]
        result = await db.execute(select(QBankQuestion).where(QBankQuestion.id.in_(question_ids)))
        questions = {str(q.id): q for q in result.scalars().all()}

        review_questions = []
        for qid, answer_data in attempt.answers.items():
            q = questions.get(qid)
            if not q:
                continue
            selected = answer_data.get("selected", [])
            is_correct = sorted(selected) == sorted(q.correct_answer_indices)
            review_questions.append(
                {
                    "question": q,
                    "user_selected": selected,
                    "is_correct": is_correct,
                }
            )

        return {
            "attempt": attempt,
            "questions": review_questions,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _get_failed_question_ids(
        self,
        db: AsyncSession,
        test_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> list[uuid.UUID]:
        """Get question IDs the user answered incorrectly in their last attempt."""
        result = await db.execute(
            select(QBankTestAttempt)
            .where(
                QBankTestAttempt.test_id == test_id,
                QBankTestAttempt.user_id == user_id,
            )
            .order_by(QBankTestAttempt.attempted_at.desc())
            .limit(1)
        )
        last_attempt = result.scalar_one_or_none()
        if not last_attempt:
            return []

        failed_ids = []
        for qid, answer_data in last_attempt.answers.items():
            # We need to check against the actual question
            question = await db.get(QBankQuestion, uuid.UUID(qid))
            if question:
                selected = answer_data.get("selected", [])
                if sorted(selected) != sorted(question.correct_answer_indices):
                    failed_ids.append(question.id)
        return failed_ids
