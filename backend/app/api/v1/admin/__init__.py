"""Admin routes package — combines user management and course management."""

from fastapi import APIRouter

from .courses import router as courses_router
from .users import router as users_router

router = APIRouter(prefix="/admin")
router.include_router(users_router)
router.include_router(courses_router)

__all__ = ["router"]
