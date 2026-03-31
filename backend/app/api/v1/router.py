from fastapi import APIRouter

from app.api.v1.content import router as content_router
from app.api.v1.dashboard import router as dashboard_router
from app.api.v1.flashcards import router as flashcards_router
from app.api.v1.health import router as health_router
from app.api.v1.local_auth import router as local_auth_router
<<<<<<< HEAD
<<<<<<< HEAD
from app.api.v1.tutor import router as tutor_router
=======
from app.api.v1.quiz import router as quiz_router
from app.api.v1.tutor import router as tutor_router
from app.api.v1.users import router as users_router
>>>>>>> 12a5b76 (feat(onboarding): implement 4-step user onboarding flow)
=======
from app.api.v1.quiz import router as quiz_router
from app.api.v1.tutor import router as tutor_router
>>>>>>> 3d0e726 (feat: implement summative assessment with 20 questions and 80% pass gate)

api_v1_router = APIRouter()
api_v1_router.include_router(health_router)
api_v1_router.include_router(local_auth_router)
api_v1_router.include_router(users_router)
api_v1_router.include_router(dashboard_router)
api_v1_router.include_router(content_router)
<<<<<<< HEAD
<<<<<<< HEAD
=======
api_v1_router.include_router(quiz_router)
>>>>>>> 12a5b76 (feat(onboarding): implement 4-step user onboarding flow)
=======
api_v1_router.include_router(quiz_router)
>>>>>>> 3d0e726 (feat: implement summative assessment with 20 questions and 80% pass gate)
api_v1_router.include_router(flashcards_router)
api_v1_router.include_router(tutor_router)
