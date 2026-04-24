from fastapi import APIRouter

from app.api.v1.activation_codes import router as activation_codes_router
from app.api.v1.admin import router as admin_router
from app.api.v1.admin_courses import router as admin_courses_router
from app.api.v1.admin_curricula import router as admin_curricula_router
from app.api.v1.admin_groups import router as admin_groups_router
from app.api.v1.admin_settings import router as admin_settings_router
from app.api.v1.admin_taxonomy import router as admin_taxonomy_router
from app.api.v1.analytics import router as analytics_router
from app.api.v1.certificates import router as certificates_router
from app.api.v1.content import router as content_router
from app.api.v1.course_preassessment import router as course_preassessment_router
from app.api.v1.courses import router as courses_router
from app.api.v1.curricula import router as curricula_router
from app.api.v1.dashboard import router as dashboard_router
from app.api.v1.flashcards import router as flashcards_router
from app.api.v1.health import router as health_router
from app.api.v1.images import router as images_router
from app.api.v1.lesson_audio import (
    router as lesson_audio_router,
)
from app.api.v1.lesson_video import router as lesson_video_router
from app.api.v1.local_auth import router as local_auth_router
from app.api.v1.org_codes import router as org_codes_router

# module_media + webhooks routers removed in #1802 — per-module video
# was rescoped to per-lesson and the webhook path is obsolete.
from app.api.v1.org_curricula import router as org_curricula_router
from app.api.v1.org_reports import router as org_reports_router
from app.api.v1.organizations import router as organizations_router
from app.api.v1.placement import router as placement_router
from app.api.v1.progress import router as progress_router
from app.api.v1.qbank import router as qbank_router
from app.api.v1.quiz import router as quiz_router
from app.api.v1.sms_relay import (
    router as sms_relay_router,
)
from app.api.v1.source_images import router as source_images_router
from app.api.v1.subscriptions import router as subscriptions_router
from app.api.v1.tutor import router as tutor_router
from app.api.v1.tutor_voice import router as tutor_voice_router
from app.api.v1.users import router as users_router

api_v1_router = APIRouter()
api_v1_router.include_router(health_router)
api_v1_router.include_router(analytics_router)
api_v1_router.include_router(local_auth_router)
api_v1_router.include_router(users_router)
api_v1_router.include_router(placement_router)
api_v1_router.include_router(dashboard_router)
api_v1_router.include_router(progress_router)
api_v1_router.include_router(content_router)
api_v1_router.include_router(quiz_router)
api_v1_router.include_router(flashcards_router)
api_v1_router.include_router(tutor_router)
api_v1_router.include_router(tutor_voice_router)
api_v1_router.include_router(images_router)
api_v1_router.include_router(lesson_audio_router)
api_v1_router.include_router(lesson_video_router)
api_v1_router.include_router(admin_router)
api_v1_router.include_router(admin_settings_router)
api_v1_router.include_router(admin_courses_router)
api_v1_router.include_router(admin_curricula_router)
api_v1_router.include_router(admin_groups_router)
api_v1_router.include_router(admin_taxonomy_router)
api_v1_router.include_router(courses_router)
api_v1_router.include_router(curricula_router)
api_v1_router.include_router(course_preassessment_router)
api_v1_router.include_router(sms_relay_router)
api_v1_router.include_router(source_images_router)
api_v1_router.include_router(subscriptions_router)
api_v1_router.include_router(activation_codes_router)
api_v1_router.include_router(organizations_router)
api_v1_router.include_router(org_curricula_router)
api_v1_router.include_router(org_codes_router)
api_v1_router.include_router(org_reports_router)
api_v1_router.include_router(qbank_router)
api_v1_router.include_router(certificates_router)
