"""Seed staging fixture accounts for E2E tests.

Idempotent: re-runs are safe and skip rows that already exist.
Closes part of issue #2109 (production-readiness epic #2123).

Usage:
    cd backend && DATABASE_URL=postgresql://... python scripts/seed_e2e_users.py

Output:
    Prints a credentials manifest to stdout. Operator copies it into
    1Password (vault: sira-staging-test) and GitHub Actions secrets:
    E2E_LEARNER_PASSWORD, E2E_ORG_OWNER_PASSWORD,
    E2E_SUB_ADMIN_PASSWORD, E2E_ADMIN_PASSWORD.

Provisions on the target DB:
    Users:
        e2e-learner@sira-test.local        role=user, no org
        e2e-org-owner@sira-test.local      role=user, owner of e2e-test-org
        e2e-sub-admin@sira-test.local      role=sub_admin
        e2e-admin@sira-test.local          role=admin
    Organization:
        e2e-test-org (slug)                org-owner is OrgMemberRole.owner
    Courses (under e2e-test-org):
        e2e-published-course               status=published
        e2e-draft-course                   status=draft
    Curricula:
        e2e-public-curriculum              public
        e2e-private-curriculum             org_restricted (owned by e2e-test-org)
    Activation code:
        E2E-FIXTURE-CODE                   for e2e-published-course
    Enrollment:
        e2e-learner enrolled in e2e-published-course
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.domain.models.activation_code import ActivationCode
from app.domain.models.course import Course, UserCourseEnrollment
from app.domain.models.curriculum import Curriculum, CurriculumCourse
from app.domain.models.organization import Organization
from app.domain.models.user import User, UserRole
from app.domain.services.organization_service import OrganizationService
from app.domain.services.password_service import PasswordService

logger = structlog.get_logger(__name__)

FIXTURES = [
    {
        "email": "e2e-learner@sira-test.local",
        "name": "E2E Learner",
        "password": "E2E-Learner-2026!",
        "role": UserRole.user,
    },
    {
        "email": "e2e-org-owner@sira-test.local",
        "name": "E2E Org Owner",
        "password": "E2E-OrgOwner-2026!",
        "role": UserRole.user,
    },
    {
        "email": "e2e-sub-admin@sira-test.local",
        "name": "E2E Sub Admin",
        "password": "E2E-SubAdmin-2026!",
        "role": UserRole.sub_admin,
    },
    {
        "email": "e2e-admin@sira-test.local",
        "name": "E2E Admin",
        "password": "E2E-Admin-2026!",
        "role": UserRole.admin,
    },
]

ORG_NAME = "E2E Test Org"
ORG_SLUG = "e2e-test-org"
COURSE_PUBLISHED_SLUG = "e2e-published-course"
COURSE_DRAFT_SLUG = "e2e-draft-course"
CURRICULUM_PUBLIC_SLUG = "e2e-public-curriculum"
CURRICULUM_PRIVATE_SLUG = "e2e-private-curriculum"
ACTIVATION_CODE = "E2E-FIXTURE-CODE"


async def upsert_user(session: AsyncSession, fixture: dict, hasher: PasswordService) -> User:
    existing = (
        await session.execute(select(User).where(User.email == fixture["email"]))
    ).scalar_one_or_none()
    if existing:
        logger.info("user_exists", email=fixture["email"], id=str(existing.id))
        return existing

    user = User(
        email=fixture["email"],
        name=fixture["name"],
        password_hash=hasher.hash_password(fixture["password"]),
        role=fixture["role"],
        preferred_language="fr",
    )
    session.add(user)
    await session.flush()
    logger.info("user_created", email=fixture["email"], id=str(user.id), role=fixture["role"].value)
    return user


async def upsert_course(session: AsyncSession, *, slug: str, status: str, org_id, creator_id) -> Course:
    existing = (
        await session.execute(select(Course).where(Course.slug == slug))
    ).scalar_one_or_none()
    if existing:
        logger.info("course_exists", slug=slug, id=str(existing.id))
        return existing

    course = Course(
        slug=slug,
        title_fr=f"E2E — {slug}",
        title_en=f"E2E — {slug}",
        description_fr="Cours de test E2E. Ne pas modifier.",
        description_en="E2E test course. Do not modify.",
        languages="fr,en",
        estimated_hours=1,
        status=status,
        creation_mode="legacy",
        visibility="public",
        organization_id=org_id,
        created_by=creator_id,
    )
    session.add(course)
    await session.flush()
    logger.info("course_created", slug=slug, id=str(course.id), status=status)
    return course


async def upsert_curriculum(
    session: AsyncSession, *, slug: str, visibility: str, org_id, creator_id, course_ids: list
) -> Curriculum:
    existing = (
        await session.execute(select(Curriculum).where(Curriculum.slug == slug))
    ).scalar_one_or_none()
    if existing:
        logger.info("curriculum_exists", slug=slug, id=str(existing.id))
        return existing

    curriculum = Curriculum(
        slug=slug,
        title_fr=f"E2E — {slug}",
        title_en=f"E2E — {slug}",
        description_fr="Curriculum de test E2E.",
        description_en="E2E test curriculum.",
        status="published",
        visibility=visibility,
        organization_id=org_id if visibility == "org_restricted" else None,
        created_by=creator_id,
    )
    session.add(curriculum)
    await session.flush()
    for course_id in course_ids:
        session.add(CurriculumCourse(curriculum_id=curriculum.id, course_id=course_id))
    logger.info("curriculum_created", slug=slug, id=str(curriculum.id), visibility=visibility)
    return curriculum


async def upsert_activation_code(
    session: AsyncSession, *, code: str, course_id, org_id
) -> ActivationCode:
    existing = (
        await session.execute(select(ActivationCode).where(ActivationCode.code == code))
    ).scalar_one_or_none()
    if existing:
        logger.info("activation_code_exists", code=code, id=str(existing.id))
        return existing

    # Constraint: (organization_id IS NULL) OR (created_by IS NULL) — set org_id only.
    ac = ActivationCode(
        code=code,
        course_id=course_id,
        organization_id=org_id,
        created_by=None,
    )
    session.add(ac)
    await session.flush()
    logger.info("activation_code_created", code=code, id=str(ac.id))
    return ac


async def upsert_enrollment(session: AsyncSession, *, user_id, course_id) -> None:
    existing = (
        await session.execute(
            select(UserCourseEnrollment).where(
                UserCourseEnrollment.user_id == user_id,
                UserCourseEnrollment.course_id == course_id,
            )
        )
    ).scalar_one_or_none()
    if existing:
        logger.info("enrollment_exists", user_id=str(user_id), course_id=str(course_id))
        return

    session.add(UserCourseEnrollment(user_id=user_id, course_id=course_id, status="active"))
    logger.info("enrollment_created", user_id=str(user_id), course_id=str(course_id))


async def seed() -> None:
    database_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@localhost:5432/santepublique",
    )
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(database_url)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    hasher = PasswordService()
    org_service = OrganizationService()

    async with Session() as session:
        # Users
        users: dict[str, User] = {}
        for fixture in FIXTURES:
            users[fixture["email"]] = await upsert_user(session, fixture, hasher)
        await session.commit()

        owner = users["e2e-org-owner@sira-test.local"]
        learner = users["e2e-learner@sira-test.local"]

        # Organization (owner becomes OrgMemberRole.owner inside the service call)
        existing_org = (
            await session.execute(select(Organization).where(Organization.slug == ORG_SLUG))
        ).scalar_one_or_none()
        if existing_org:
            logger.info("org_exists", slug=ORG_SLUG, id=str(existing_org.id))
            org = existing_org
        else:
            org = await org_service.create_organization(
                session,
                name=ORG_NAME,
                slug=ORG_SLUG,
                description="E2E test organization. Do not modify.",
                creator_id=owner.id,
            )

        # Courses (under the org, created by the org owner)
        published = await upsert_course(
            session, slug=COURSE_PUBLISHED_SLUG, status="published",
            org_id=org.id, creator_id=owner.id,
        )
        draft = await upsert_course(
            session, slug=COURSE_DRAFT_SLUG, status="draft",
            org_id=org.id, creator_id=owner.id,
        )
        await session.commit()

        # Curricula
        await upsert_curriculum(
            session, slug=CURRICULUM_PUBLIC_SLUG, visibility="public",
            org_id=org.id, creator_id=owner.id, course_ids=[published.id],
        )
        await upsert_curriculum(
            session, slug=CURRICULUM_PRIVATE_SLUG, visibility="org_restricted",
            org_id=org.id, creator_id=owner.id, course_ids=[published.id, draft.id],
        )
        await session.commit()

        # Activation code (org-scoped → created_by must be NULL per XOR constraint)
        await upsert_activation_code(
            session, code=ACTIVATION_CODE, course_id=published.id, org_id=org.id,
        )

        # Enrollment of learner in published course
        await upsert_enrollment(session, user_id=learner.id, course_id=published.id)

        await session.commit()

    await engine.dispose()

    # Manifest — operator copies into 1Password + GH Actions secrets
    print()
    print("=" * 60)
    print("E2E FIXTURE MANIFEST — copy these into 1Password + GH Actions")
    print("=" * 60)
    print(f"DB target: {database_url.split('@')[-1] if '@' in database_url else database_url}")
    print()
    print("Credentials:")
    for f in FIXTURES:
        print(f"  {f['email']:40s} | password: {f['password']}")
    print()
    print(f"Org slug:                       {ORG_SLUG}")
    print(f"Published course slug:          {COURSE_PUBLISHED_SLUG}")
    print(f"Draft course slug:              {COURSE_DRAFT_SLUG}")
    print(f"Public curriculum slug:         {CURRICULUM_PUBLIC_SLUG}")
    print(f"Private curriculum slug:        {CURRICULUM_PRIVATE_SLUG}")
    print(f"Activation code:                {ACTIVATION_CODE}")
    print()
    print("GH Actions secrets to set:")
    for f in FIXTURES:
        env_name = f["email"].split("@")[0].replace("-", "_").upper() + "_PASSWORD"
        print(f"  {env_name}={f['password']}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(seed())
