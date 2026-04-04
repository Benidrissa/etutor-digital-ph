from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ARRAY, Boolean, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.models.base import Base

if TYPE_CHECKING:
    from app.domain.models.marketplace import CoursePrice, CourseReview
    from app.domain.models.module import Module


class CourseDomain(enum.StrEnum):
    health_sciences = "health_sciences"
    natural_sciences = "natural_sciences"
    social_sciences = "social_sciences"
    mathematics = "mathematics"
    engineering = "engineering"
    information_technology = "information_technology"
    education = "education"
    arts_humanities = "arts_humanities"
    business_management = "business_management"
    law = "law"
    agriculture = "agriculture"
    environmental_studies = "environmental_studies"
    other = "other"


class CourseLevel(enum.StrEnum):
    beginner = "beginner"
    intermediate = "intermediate"
    advanced = "advanced"
    expert = "expert"


class AudienceType(enum.StrEnum):
    kindergarten = "kindergarten"
    primary_school = "primary_school"
    secondary_school = "secondary_school"
    university = "university"
    professional = "professional"
    researcher = "researcher"
    teacher = "teacher"
    policy_maker = "policy_maker"
    continuing_education = "continuing_education"


_domain_enum = Enum(
    *[e.value for e in CourseDomain],
    name="coursedomain",
    create_type=False,
)
_level_enum = Enum(
    *[e.value for e in CourseLevel],
    name="courselevel",
    create_type=False,
)
_audience_enum = Enum(
    *[e.value for e in AudienceType],
    name="audiencetype",
    create_type=False,
)


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String, unique=True, index=True)
    title_fr: Mapped[str] = mapped_column(Text)
    title_en: Mapped[str] = mapped_column(Text)
    description_fr: Mapped[str | None] = mapped_column(Text)
    description_en: Mapped[str | None] = mapped_column(Text)
    course_domain: Mapped[list[str]] = mapped_column(ARRAY(_domain_enum), server_default="{}")
    course_level: Mapped[list[str]] = mapped_column(ARRAY(_level_enum), server_default="{}")
    audience_type: Mapped[list[str]] = mapped_column(ARRAY(_audience_enum), server_default="{}")
    languages: Mapped[str] = mapped_column(String, server_default="fr,en")
    estimated_hours: Mapped[int] = mapped_column(server_default="20")
    module_count: Mapped[int] = mapped_column(server_default="0")
    status: Mapped[str] = mapped_column(
        Enum("draft", "published", "archived", name="coursestatus"), server_default="draft"
    )
    cover_image_url: Mapped[str | None] = mapped_column(String)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    rag_collection_id: Mapped[str | None] = mapped_column(String)
    is_marketplace: Mapped[bool] = mapped_column(Boolean, server_default="false")
    expert_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    modules: Mapped[list[Module]] = relationship(back_populates="course")
    enrollments: Mapped[list[UserCourseEnrollment]] = relationship(back_populates="course")
    price: Mapped[CoursePrice | None] = relationship(back_populates="course", uselist=False)
    reviews: Mapped[list[CourseReview]] = relationship(back_populates="course")


class UserCourseEnrollment(Base):
    __tablename__ = "user_course_enrollment"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id"), primary_key=True)
    enrolled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    status: Mapped[str] = mapped_column(
        Enum("active", "completed", "dropped", name="enrollmentstatus"), server_default="active"
    )
    completion_pct: Mapped[float] = mapped_column(server_default="0.0")
    payment_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True
    )

    course: Mapped[Course] = relationship(back_populates="enrollments")
