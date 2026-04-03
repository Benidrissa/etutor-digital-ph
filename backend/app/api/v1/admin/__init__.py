from fastapi import APIRouter

from app.api.v1.admin.courses import router as courses_router
from app.api.v1.admin.users import router as users_router

router = APIRouter()
router.include_router(users_router)
router.include_router(courses_router)

__all__ = ["router"]
