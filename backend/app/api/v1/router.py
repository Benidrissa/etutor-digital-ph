from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.content import router as content_router
from app.api.v1.dashboard import router as dashboard_router
from app.api.v1.health import router as health_router
from app.api.v1.local_auth import router as local_auth_router
from app.api.v1.quiz import router as quiz_router

api_v1_router = APIRouter()
api_v1_router.include_router(health_router)
api_v1_router.include_router(local_auth_router)  # New local auth
api_v1_router.include_router(auth_router)  # Legacy Supabase auth (will be removed)
api_v1_router.include_router(dashboard_router)
api_v1_router.include_router(content_router)
api_v1_router.include_router(quiz_router)
