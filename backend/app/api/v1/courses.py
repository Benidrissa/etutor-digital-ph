"""Public course catalog and learner enrollment endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import delete as sa_delete
from sqlalchemy import exists, select
from structlog import get_logger

from app.api.deps import get_db as get_db_session
from app.api.deps_local_auth import get_current_user, get_optional_user
from app.domain.models.content import GeneratedContent
from app.domain.models.conversation import TutorConversation
from app.domain.models.course import Course, UserCourseEnrollment
from app.domain.models.curriculum import Curriculum, CurriculumCourse
from app.domain.models.flashcard import FlashcardReview
from app.domain.models.lesson_reading import LessonReading
from app.domain.models.module import Module
from app.domain.models.module_unit import ModuleUnit
from app.domain.models.progress import UserModuleProgress
from app.domain.models.quiz import PlacementTestAttempt, QuizAttempt, SummativeAssessmentAttempt
from app.domain.models.taxonomy import CourseTaxonomy, TaxonomyCategory
from app.domain.services.enrollment_helper import enroll_user_in_course

logger = get_logger(__name__)
router = APIRouter(prefix="/courses", tags=["Courses"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class CourseListItem(BaseModel):
    id: str
    slug: str
    title_fr: str
    title_en: str
    description_fr: str | None
    description_en: str | None
    course_domain: list[dict]
    course_level: list[dict]
    audience_type: list[dict]
    estimated_hours: int
    module_count: int
    cover_image_url: str | None
    languages: str
    enrolled: bool = False


class CourseModuleUnit(BaseModel):
    id: str
    unit_number: str
    title_fr: str | None
    title_en: str | None
    order_index: int


class CourseModuleDetail(BaseModel):
    id: str
    module_number: int
    title_fr: str | None
    title_en: str | None
    description_fr: str | None
    description_en: str | None
    level: int
    estimated_hours: int
    bloom_level: str | None
    units: list[CourseModuleUnit]


class CourseDetailResponse(CourseListItem):
    syllabus_json: dict | list | None
    modules: list[CourseModuleDetail]
    preassessment_enabled: bool = False
    preassessment_mandatory: bool = False


class EnrollmentResponse(BaseModel):
    course_id: str
    user_id: str
    status: str
    enrolled_at: str
    completion_pct: float


def _taxonomy_by_type(categories: list[TaxonomyCategory], cat_type: str) -> list[dict]:
    return [
        {"value": tc.slug, "label_fr": tc.label_fr, "label_en": tc.label_en}
        for tc in categories
        if tc.type == cat_type
    ]


def _course_to_list_item(course: Course, enrolled: bool = False) -> CourseListItem:
    cats = course.taxonomy_categories or []
    return CourseListItem(
        id=str(course.id),
        slug=course.slug,
        title_fr=course.title_fr,
        title_en=course.title_en,
        description_fr=course.description_fr,
        description_en=course.description_en,
        course_domain=_taxonomy_by_type(cats, "domain"),
        course_level=_taxonomy_by_type(cats, "level"),
        audience_type=_taxonomy_by_type(cats, "audience"),
        estimated_hours=course.estimated_hours,
        module_count=course.module_count,
        cover_image_url=course.cover_image_url,
        languages=course.languages,
        enrolled=enrolled,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/taxonomy")
async def get_taxonomy(db=Depends(get_db_session)) -> dict:
    """Return active taxonomy values with bilingual labels. No auth."""
    result = await db.execute(
        select(TaxonomyCategory)
        .where(TaxonomyCategory.is_active.is_(True))
        .order_by(TaxonomyCategory.type, TaxonomyCategory.sort_order)
    )
    categories = result.scalars().all()

    grouped: dict[str, list] = {"domains": [], "levels": [], "audience_types": []}
    type_key = {"domain": "domains", "level": "levels", "audience": "audience_types"}

    for cat in categories:
        key = type_key.get(cat.type)
        if key:
            grouped[key].append(
                {
                    "value": cat.slug,
                    "label_fr": cat.label_fr,
                    "label_en": cat.label_en,
                }
            )

    return grouped


@router.get("", response_model=list[CourseListItem])
async def list_published_courses(
    course_domain: str | None = Query(None, description="Filter by domain slug"),
    course_level: str | None = Query(None, description="Filter by level slug"),
    audience_type: str | None = Query(None, description="Filter by audience slug"),
    search: str | None = Query(None, description="Search in title FR/EN"),
    curriculum: str | None = Query(None, description="Filter by curriculum slug or ID"),
    current_user=Depends(get_optional_user),
    db=Depends(get_db_session),
) -> list[CourseListItem]:
    """Browse published courses. No auth required. Use ?curriculum= to scope to a curriculum."""
    stmt = (
        select(Course)
        .where(Course.status == "published", Course.visibility != "private")
        .order_by(Course.published_at.desc())
    )

    if curriculum:
        curriculum_obj: Curriculum | None = None
        try:
            cid = uuid.UUID(curriculum)
            result_c = await db.execute(
                select(Curriculum).where(Curriculum.id == cid, Curriculum.status == "published")
            )
            curriculum_obj = result_c.scalar_one_or_none()
        except ValueError:
            pass

        if not curriculum_obj:
            result_c = await db.execute(
                select(Curriculum).where(
                    Curriculum.slug == curriculum, Curriculum.status == "published"
                )
            )
            curriculum_obj = result_c.scalar_one_or_none()

        if curriculum_obj:
            if curriculum_obj.visibility == "private":
                from app.domain.models.user_group import CurriculumAccess, UserGroupMember

                has_access = False
                if current_user:
                    uid = uuid.UUID(current_user.id)
                    direct = await db.execute(
                        select(CurriculumAccess).where(
                            CurriculumAccess.curriculum_id == curriculum_obj.id,
                            CurriculumAccess.user_id == uid,
                        )
                    )
                    has_access = direct.scalar_one_or_none() is not None
                    if not has_access:
                        group_q = await db.execute(
                            select(CurriculumAccess)
                            .join(
                                UserGroupMember,
                                UserGroupMember.group_id == CurriculumAccess.group_id,
                            )
                            .where(
                                CurriculumAccess.curriculum_id == curriculum_obj.id,
                                UserGroupMember.user_id == uid,
                            )
                        )
                        has_access = group_q.scalar_one_or_none() is not None
                if not has_access:
                    return []
            stmt = stmt.where(
                exists(
                    select(CurriculumCourse.course_id).where(
                        CurriculumCourse.course_id == Course.id,
                        CurriculumCourse.curriculum_id == curriculum_obj.id,
                    )
                )
            )
        else:
            return []
    else:
        stmt = stmt.where(
            ~exists(
                select(CurriculumCourse.course_id)
                .join(Curriculum, Curriculum.id == CurriculumCourse.curriculum_id)
                .where(
                    CurriculumCourse.course_id == Course.id,
                    Curriculum.visibility == "private",
                )
            )
        )

    if course_domain:
        stmt = stmt.where(
            exists(
                select(CourseTaxonomy.course_id).where(
                    CourseTaxonomy.course_id == Course.id,
                    CourseTaxonomy.category_id == TaxonomyCategory.id,
                    TaxonomyCategory.type == "domain",
                    TaxonomyCategory.slug == course_domain,
                )
            )
        )
    if course_level:
        stmt = stmt.where(
            exists(
                select(CourseTaxonomy.course_id).where(
                    CourseTaxonomy.course_id == Course.id,
                    CourseTaxonomy.category_id == TaxonomyCategory.id,
                    TaxonomyCategory.type == "level",
                    TaxonomyCategory.slug == course_level,
                )
            )
        )
    if audience_type:
        stmt = stmt.where(
            exists(
                select(CourseTaxonomy.course_id).where(
                    CourseTaxonomy.course_id == Course.id,
                    CourseTaxonomy.category_id == TaxonomyCategory.id,
                    TaxonomyCategory.type == "audience",
                    TaxonomyCategory.slug == audience_type,
                )
            )
        )

    result = await db.execute(stmt)
    courses = result.scalars().all()

    if search:
        q = search.lower()
        courses = [
            c for c in courses if q in (c.title_fr or "").lower() or q in (c.title_en or "").lower()
        ]

    enrolled_ids: set[str] = set()
    if current_user:
        enroll_result = await db.execute(
            select(UserCourseEnrollment.course_id).where(
                UserCourseEnrollment.user_id == uuid.UUID(current_user.id),
                UserCourseEnrollment.status == "active",
            )
        )
        enrolled_ids = {str(row[0]) for row in enroll_result.all()}

    return [_course_to_list_item(c, enrolled=str(c.id) in enrolled_ids) for c in courses]


@router.get("/my-enrollments", response_model=list[CourseListItem])
async def my_enrollments(
    current_user=Depends(get_current_user),
    db=Depends(get_db_session),
) -> list[CourseListItem]:
    """Get courses the current user is enrolled in."""
    result = await db.execute(
        select(Course)
        .join(
            UserCourseEnrollment,
            (UserCourseEnrollment.course_id == Course.id)
            & (UserCourseEnrollment.user_id == uuid.UUID(current_user.id))
            & (UserCourseEnrollment.status == "active"),
        )
        .order_by(UserCourseEnrollment.enrolled_at.desc())
    )
    courses = result.scalars().all()
    return [_course_to_list_item(c, enrolled=True) for c in courses]


@router.get("/{course_id_or_slug}", response_model=CourseDetailResponse)
async def get_course_detail(
    course_id_or_slug: str,
    current_user=Depends(get_optional_user),
    db=Depends(get_db_session),
) -> CourseDetailResponse:
    """Get course detail with syllabus and modules. No auth required (public catalog).

    Accepts either a UUID or a slug as the path parameter.
    """
    # Try UUID lookup first, fall back to slug
    course: Course | None = None
    try:
        cid = uuid.UUID(course_id_or_slug)
        result = await db.execute(select(Course).where(Course.id == cid))
        course = result.scalar_one_or_none()
    except ValueError:
        pass

    if not course:
        result = await db.execute(select(Course).where(Course.slug == course_id_or_slug))
        course = result.scalar_one_or_none()

    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    course_id = course.id

    # Fetch modules with units
    modules_result = await db.execute(
        select(Module).where(Module.course_id == course_id).order_by(Module.module_number)
    )
    modules = modules_result.scalars().all()

    module_details = []
    for mod in modules:
        units_result = await db.execute(
            select(ModuleUnit)
            .where(ModuleUnit.module_id == mod.id)
            .order_by(ModuleUnit.order_index)
        )
        units = units_result.scalars().all()
        module_details.append(
            CourseModuleDetail(
                id=str(mod.id),
                module_number=mod.module_number,
                title_fr=mod.title_fr,
                title_en=mod.title_en,
                description_fr=mod.description_fr,
                description_en=mod.description_en,
                level=mod.level,
                estimated_hours=mod.estimated_hours,
                bloom_level=mod.bloom_level,
                units=[
                    CourseModuleUnit(
                        id=str(u.id),
                        unit_number=u.unit_number,
                        title_fr=u.title_fr,
                        title_en=u.title_en,
                        order_index=u.order_index,
                    )
                    for u in units
                ],
            )
        )

    enrolled = False
    if current_user:
        enroll_result = await db.execute(
            select(UserCourseEnrollment).where(
                UserCourseEnrollment.user_id == uuid.UUID(current_user.id),
                UserCourseEnrollment.course_id == course_id,
                UserCourseEnrollment.status == "active",
            )
        )
        enrolled = enroll_result.scalar_one_or_none() is not None

    base = _course_to_list_item(course, enrolled=enrolled)
    return CourseDetailResponse(
        **base.model_dump(),
        syllabus_json=course.syllabus_json,
        modules=module_details,
        preassessment_enabled=course.preassessment_enabled,
        preassessment_mandatory=course.preassessment_mandatory,
    )


@router.post("/{course_id}/enroll", response_model=EnrollmentResponse)
async def enroll_in_course(
    course_id: uuid.UUID,
    current_user=Depends(get_current_user),
    db=Depends(get_db_session),
) -> EnrollmentResponse:
    """Enroll the current user in a published course."""
    course_result = await db.execute(
        select(Course).where(Course.id == course_id, Course.status == "published")
    )
    course = course_result.scalar_one_or_none()
    if not course:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found or not published",
        )

    enrollment = await enroll_user_in_course(db, uuid.UUID(current_user.id), course_id)
    await db.commit()
    await db.refresh(enrollment)

    logger.info(
        "User enrolled in course",
        user_id=current_user.id,
        course_id=str(course_id),
    )
    return EnrollmentResponse(
        course_id=str(enrollment.course_id),
        user_id=str(enrollment.user_id),
        status=enrollment.status,
        enrolled_at=enrollment.enrolled_at.isoformat(),
        completion_pct=enrollment.completion_pct,
    )


@router.post("/{course_id}/unenroll", status_code=status.HTTP_204_NO_CONTENT)
async def unenroll_from_course(
    course_id: uuid.UUID,
    current_user=Depends(get_current_user),
    db=Depends(get_db_session),
) -> None:
    """Hard-delete enrollment and all associated learner data for this course."""
    user_id = uuid.UUID(current_user.id)

    result = await db.execute(
        select(UserCourseEnrollment).where(
            UserCourseEnrollment.user_id == user_id,
            UserCourseEnrollment.course_id == course_id,
        )
    )
    enrollment = result.scalar_one_or_none()
    if not enrollment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Enrollment not found",
        )

    module_ids_subq = select(Module.id).where(Module.course_id == course_id).scalar_subquery()
    content_ids_subq = (
        select(GeneratedContent.id)
        .where(
            GeneratedContent.module_id.in_(select(Module.id).where(Module.course_id == course_id))
        )
        .scalar_subquery()
    )

    await db.execute(
        sa_delete(QuizAttempt).where(
            QuizAttempt.user_id == user_id,
            QuizAttempt.quiz_id.in_(content_ids_subq),
        )
    )
    await db.execute(
        sa_delete(FlashcardReview).where(
            FlashcardReview.user_id == user_id,
            FlashcardReview.card_id.in_(content_ids_subq),
        )
    )
    await db.execute(
        sa_delete(LessonReading).where(
            LessonReading.user_id == user_id,
            LessonReading.lesson_id.in_(content_ids_subq),
        )
    )
    await db.execute(
        sa_delete(SummativeAssessmentAttempt).where(
            SummativeAssessmentAttempt.user_id == user_id,
            SummativeAssessmentAttempt.module_id.in_(module_ids_subq),
        )
    )
    await db.execute(
        sa_delete(UserModuleProgress).where(
            UserModuleProgress.user_id == user_id,
            UserModuleProgress.module_id.in_(module_ids_subq),
        )
    )
    await db.execute(
        sa_delete(TutorConversation).where(
            TutorConversation.user_id == user_id,
            TutorConversation.module_id.in_(module_ids_subq),
        )
    )
    await db.execute(
        sa_delete(PlacementTestAttempt).where(
            PlacementTestAttempt.user_id == user_id,
            PlacementTestAttempt.course_id == course_id,
        )
    )

    await db.delete(enrollment)
    await db.commit()
    logger.info(
        "User unenrolled from course and all data deleted",
        user_id=current_user.id,
        course_id=str(course_id),
    )
