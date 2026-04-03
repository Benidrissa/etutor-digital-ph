"""Admin API package — user management + syllabus agent."""

from fastapi import APIRouter

from app.api.v1.admin.syllabus import router as syllabus_router
from app.api.v1.admin.users import router as users_router

router = APIRouter()
router.include_router(users_router)
router.include_router(syllabus_router)
