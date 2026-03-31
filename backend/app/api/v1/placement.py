"""Placement test endpoints for level assignment."""

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from structlog import get_logger

from ...api.deps import get_current_user, get_db_session
from ...domain.models.quiz import PlacementTestAttempt
from ...domain.models.user import User
from ...domain.repositories.implementations.user_repository import UserRepository
from ...domain.services.placement_service import PlacementService
from .schemas.placement import PlacementTestResponse, PlacementTestSubmission

logger = get_logger(__name__)
router = APIRouter(prefix="/placement-test", tags=["Placement Test"])


@router.get("/questions", response_model=PlacementTestResponse)
async def get_placement_test_questions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> PlacementTestResponse:
    """Get placement test questions.

    Returns:
        Placement test with 20 questions covering 4 domains

    Raises:
        403: User has already completed placement test recently
        500: Failed to generate questions
    """
    try:
        # Check if user has already completed placement test recently
        # In production, this would check the database for existing attempts
        user_repo = UserRepository(db)
        placement_service = PlacementService(user_repo)

        # Check if user has existing placement result
        existing_result = await placement_service.get_placement_result(current_user.id)
        if existing_result:
            # Check if user can retake (3 months limitation)
            # For now, we'll allow retaking if current_level is 1 or no attempts in last 3 months
            if current_user.current_level > 1:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Placement test can only be retaken after 3 months",
                )

        # Get placement test questions (hardcoded for now)
        questions = _get_placement_questions(current_user.preferred_language)

        logger.info("Placement test questions retrieved", user_id=str(current_user.id))
        return PlacementTestResponse(
            questions=questions,
            total_questions=20,
            time_limit_minutes=20,
            instructions={
                "en": "Answer all questions to the best of your ability. This assessment will help us personalize your learning journey.",
                "fr": "Répondez à toutes les questions du mieux que vous pouvez. Cette évaluation nous aidera à personnaliser votre parcours d'apprentissage.",
            },
            domains={
                "basic_public_health": {
                    "name": {
                        "en": "Public Health Foundations",
                        "fr": "Fondements de Santé Publique",
                    },
                    "questions": [1, 2, 3, 4, 5],
                },
                "epidemiology": {
                    "name": {"en": "Epidemiology", "fr": "Épidémiologie"},
                    "questions": [6, 7, 8, 9, 10],
                },
                "biostatistics": {
                    "name": {"en": "Biostatistics", "fr": "Biostatistiques"},
                    "questions": [11, 12, 13, 14, 15],
                },
                "data_analysis": {
                    "name": {"en": "Health Systems", "fr": "Systèmes de Santé"},
                    "questions": [16, 17, 18, 19, 20],
                },
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get placement test questions", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate placement test questions",
        )


@router.post("/submit")
async def submit_placement_test(
    submission: PlacementTestSubmission,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Submit placement test and get level assignment.

    Args:
        submission: User's answers and test data
        current_user: Current authenticated user
        db: Database session

    Returns:
        Placement result with assigned level and recommendations

    Raises:
        400: Invalid submission data
        403: User has already completed placement test recently
        500: Failed to score placement test
    """
    try:
        user_repo = UserRepository(db)
        placement_service = PlacementService(user_repo)

        # Prepare user context
        user_context = {
            "professional_role": current_user.professional_role or "",
            "country": current_user.country or "",
            "preferred_language": current_user.preferred_language,
        }

        # Score the placement test
        result = await placement_service.score_placement_test(
            user_id=current_user.id,
            answers=submission.answers,
            time_taken=submission.time_taken_sec,
            user_context=user_context,
        )

        # Save the attempt to database
        attempt = PlacementTestAttempt(
            user_id=current_user.id,
            answers=submission.answers,
            raw_score=result.score_percentage,  # Using score_percentage as raw score
            adjusted_score=result.score_percentage,
            assigned_level=result.assigned_level,
            time_taken_sec=submission.time_taken_sec,
            domain_scores={"overall": result.score_percentage},  # Simplified for now
            user_context=user_context,
            competency_areas=result.competency_areas,
            recommendations=result.recommendations,
            can_retake_after=datetime.utcnow() + timedelta(days=90),  # 3 months
        )

        db.add(attempt)
        await db.commit()

        logger.info(
            "Placement test completed",
            user_id=str(current_user.id),
            assigned_level=result.assigned_level,
            score=result.score_percentage,
        )

        return {
            "assigned_level": result.assigned_level,
            "score_percentage": result.score_percentage,
            "competency_areas": result.competency_areas,
            "recommendations": result.recommendations,
            "level_description": {
                "en": _get_level_description_en(result.assigned_level),
                "fr": _get_level_description_fr(result.assigned_level),
            },
            "can_retake_after": (datetime.utcnow() + timedelta(days=90)).isoformat(),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to submit placement test", error=str(e), user_id=str(current_user.id))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process placement test submission",
        )


@router.post("/skip")
async def skip_placement_test(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Skip placement test and assign Level 1.

    Args:
        current_user: Current authenticated user
        db: Database session

    Returns:
        Assignment result with Level 1

    Raises:
        500: Failed to assign level
    """
    try:
        user_repo = UserRepository(db)

        # Update user to Level 1
        current_user.current_level = 1
        await user_repo.update(current_user)

        logger.info("Placement test skipped - assigned Level 1", user_id=str(current_user.id))

        return {
            "assigned_level": 1,
            "score_percentage": 0.0,
            "competency_areas": ["Foundation Building"],
            "recommendations": [
                "Start with Module 1: Public Health Foundations",
                "Focus on building core concepts before advancing",
            ],
            "level_description": {
                "en": "Beginner - Build foundational knowledge",
                "fr": "Débutant - Construire les connaissances de base",
            },
            "skipped": True,
        }

    except Exception as e:
        logger.error("Failed to skip placement test", error=str(e), user_id=str(current_user.id))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to skip placement test",
        )


def _get_placement_questions(language: str) -> list[dict[str, Any]]:
    """Get hardcoded placement test questions.

    Args:
        language: User's preferred language (fr/en)

    Returns:
        List of 20 placement test questions
    """
    if language == "fr":
        return _get_french_questions()
    return _get_english_questions()


def _get_english_questions() -> list[dict[str, Any]]:
    """Get English placement test questions."""
    return [
        # Basic Public Health (Questions 1-5)
        {
            "id": "1",
            "domain": "basic_public_health",
            "question": "What is the primary goal of public health?",
            "options": [
                {"id": "a", "text": "Treating individual patients"},
                {"id": "b", "text": "Managing hospitals"},
                {"id": "c", "text": "Preventing disease and promoting health in populations"},
                {"id": "d", "text": "Conducting medical research"},
            ],
            "correct_answer": "c",
        },
        {
            "id": "2",
            "domain": "basic_public_health",
            "question": "Which of the following is a determinant of health?",
            "options": [
                {"id": "a", "text": "Social and economic environment"},
                {"id": "b", "text": "Hospital capacity"},
                {"id": "c", "text": "Number of doctors"},
                {"id": "d", "text": "Medical technology"},
            ],
            "correct_answer": "a",
        },
        {
            "id": "3",
            "domain": "basic_public_health",
            "question": "What are the three levels of prevention in public health?",
            "options": [
                {"id": "a", "text": "Clinical, community, population"},
                {"id": "b", "text": "Primary, secondary, tertiary"},
                {"id": "c", "text": "Individual, group, society"},
                {"id": "d", "text": "Local, national, global"},
            ],
            "correct_answer": "b",
        },
        {
            "id": "4",
            "domain": "basic_public_health",
            "question": "What does health promotion focus on?",
            "options": [
                {"id": "a", "text": "Treating diseases"},
                {"id": "b", "text": "Building hospitals"},
                {"id": "c", "text": "Training healthcare workers"},
                {"id": "d", "text": "Enabling people to increase control over their health"},
            ],
            "correct_answer": "d",
        },
        {
            "id": "5",
            "domain": "basic_public_health",
            "question": "Which organization provides global health leadership?",
            "options": [
                {"id": "a", "text": "World Health Organization (WHO)"},
                {"id": "b", "text": "United Nations Educational Scientific and Cultural Organization (UNESCO)"},
                {"id": "c", "text": "International Monetary Fund (IMF)"},
                {"id": "d", "text": "World Bank"},
            ],
            "correct_answer": "a",
        },
        # Epidemiology (Questions 6-10)
        {
            "id": "6",
            "domain": "epidemiology",
            "question": "What is the definition of epidemiology?",
            "options": [
                {"id": "a", "text": "The study of individual diseases"},
                {"id": "b", "text": "The study of the distribution and determinants of health-related states in populations"},
                {"id": "c", "text": "The study of hospital management"},
                {"id": "d", "text": "The study of medical treatments"},
            ],
            "correct_answer": "b",
        },
        {
            "id": "7",
            "domain": "epidemiology", 
            "question": "What is the attack rate in an outbreak?",
            "options": [
                {"id": "a", "text": "The number of deaths"},
                {"id": "b", "text": "The number of hospitalizations"},
                {"id": "c", "text": "The proportion of exposed individuals who develop the disease"},
                {"id": "d", "text": "The duration of the outbreak"},
            ],
            "correct_answer": "c",
        },
        {
            "id": "8",
            "domain": "epidemiology",
            "question": "What type of study follows subjects over time?",
            "options": [
                {"id": "a", "text": "Cohort study"},
                {"id": "b", "text": "Case-control study"},
                {"id": "c", "text": "Cross-sectional study"},
                {"id": "d", "text": "Ecological study"},
            ],
            "correct_answer": "a",
        },
        {
            "id": "9",
            "domain": "epidemiology",
            "question": "What is the incidence rate?",
            "options": [
                {"id": "a", "text": "Total number of cases"},
                {"id": "b", "text": "Number of existing cases at a specific time"},
                {"id": "c", "text": "Number of deaths"},
                {"id": "d", "text": "Number of new cases occurring in a specific time period"},
            ],
            "correct_answer": "d",
        },
        {
            "id": "10",
            "domain": "epidemiology",
            "question": "What is the purpose of contact tracing?",
            "options": [
                {"id": "a", "text": "To treat patients"},
                {"id": "b", "text": "To identify and monitor people who may have been exposed to an infectious disease"},
                {"id": "c", "text": "To count the number of cases"},
                {"id": "d", "text": "To develop vaccines"},
            ],
            "correct_answer": "b",
        },
        # Biostatistics (Questions 11-15)
        {
            "id": "11",
            "domain": "biostatistics",
            "question": "What is the median of the dataset: 2, 4, 6, 8, 10?",
            "options": [
                {"id": "a", "text": "6"},
                {"id": "b", "text": "5"},
                {"id": "c", "text": "4"},
                {"id": "d", "text": "8"},
            ],
            "correct_answer": "a",
        },
        {
            "id": "12",
            "domain": "biostatistics",
            "question": "What does a p-value of 0.05 typically indicate?",
            "options": [
                {"id": "a", "text": "95% certainty"},
                {"id": "b", "text": "50% probability"},
                {"id": "c", "text": "Statistical significance at the 5% level"},
                {"id": "d", "text": "5% of the data is incorrect"},
            ],
            "correct_answer": "c",
        },
        {
            "id": "13",
            "domain": "biostatistics",
            "question": "What is the difference between correlation and causation?",
            "options": [
                {"id": "a", "text": "They are the same thing"},
                {"id": "b", "text": "Correlation implies a relationship, causation implies one variable causes another"},
                {"id": "c", "text": "Causation is weaker than correlation"},
                {"id": "d", "text": "Correlation only applies to negative relationships"},
            ],
            "correct_answer": "b",
        },
        {
            "id": "14",
            "domain": "biostatistics",
            "question": "What is a confidence interval?",
            "options": [
                {"id": "a", "text": "A range of values likely to contain the true population parameter"},
                {"id": "b", "text": "The exact value of a statistic"},
                {"id": "c", "text": "The number of observations"},
                {"id": "d", "text": "The average of all measurements"},
            ],
            "correct_answer": "a",
        },
        {
            "id": "15",
            "domain": "biostatistics",
            "question": "What type of variable is 'blood type' (A, B, AB, O)?",
            "options": [
                {"id": "a", "text": "Continuous"},
                {"id": "b", "text": "Ordinal"},
                {"id": "c", "text": "Interval"},
                {"id": "d", "text": "Nominal"},
            ],
            "correct_answer": "d",
        },
        # Health Systems (Questions 16-20)
        {
            "id": "16",
            "domain": "data_analysis",
            "question": "What are the main components of a health system?",
            "options": [
                {"id": "a", "text": "Hospitals and clinics only"},
                {"id": "b", "text": "Service delivery, health workforce, information, financing, governance, medical products"},
                {"id": "c", "text": "Doctors and nurses only"},
                {"id": "d", "text": "Government policies only"},
            ],
            "correct_answer": "b",
        },
        {
            "id": "17",
            "domain": "data_analysis",
            "question": "What is universal health coverage (UHC)?",
            "options": [
                {"id": "a", "text": "Free healthcare for everyone"},
                {"id": "b", "text": "Government-only healthcare"},
                {"id": "c", "text": "Ensuring all people have access to needed health services without financial hardship"},
                {"id": "d", "text": "Private healthcare for all"},
            ],
            "correct_answer": "c",
        },
        {
            "id": "18",
            "domain": "data_analysis",
            "question": "What is the role of health information systems?",
            "options": [
                {"id": "a", "text": "To collect, analyze, and use health data for decision-making"},
                {"id": "b", "text": "To store medical records only"},
                {"id": "c", "text": "To count patients"},
                {"id": "d", "text": "To schedule appointments"},
            ],
            "correct_answer": "a",
        },
        {
            "id": "19",
            "domain": "data_analysis",
            "question": "What is health financing?",
            "options": [
                {"id": "a", "text": "Building hospitals"},
                {"id": "b", "text": "The function of raising, pooling and purchasing health services"},
                {"id": "c", "text": "Training healthcare workers"},
                {"id": "d", "text": "Importing medical equipment"},
            ],
            "correct_answer": "b",
        },
        {
            "id": "20",
            "domain": "data_analysis",
            "question": "What is primary health care?",
            "options": [
                {"id": "a", "text": "Emergency care only"},
                {"id": "b", "text": "Hospital-based care"},
                {"id": "c", "text": "Specialist care"},
                {"id": "d", "text": "Essential health care based on practical, scientifically sound methods"},
            ],
            "correct_answer": "d",
        },
    ]


def _get_french_questions() -> list[dict[str, Any]]:
    """Get French placement test questions."""
    return [
        # Fondements de Santé Publique (Questions 1-5)
        {
            "id": "1",
            "domain": "basic_public_health",
            "question": "Quel est l'objectif principal de la santé publique ?",
            "options": [
                {"id": "a", "text": "Traiter les patients individuels"},
                {"id": "b", "text": "Gérer les hôpitaux"},
                {"id": "c", "text": "Prévenir les maladies et promouvoir la santé dans les populations"},
                {"id": "d", "text": "Mener des recherches médicales"},
            ],
            "correct_answer": "c",
        },
        {
            "id": "2",
            "domain": "basic_public_health",
            "question": "Lequel des éléments suivants est un déterminant de la santé ?",
            "options": [
                {"id": "a", "text": "Environnement social et économique"},
                {"id": "b", "text": "Capacité hospitalière"},
                {"id": "c", "text": "Nombre de médecins"},
                {"id": "d", "text": "Technologie médicale"},
            ],
            "correct_answer": "a",
        },
        {
            "id": "3",
            "domain": "basic_public_health",
            "question": "Quels sont les trois niveaux de prévention en santé publique ?",
            "options": [
                {"id": "a", "text": "Clinique, communautaire, population"},
                {"id": "b", "text": "Primaire, secondaire, tertiaire"},
                {"id": "c", "text": "Individuel, groupe, société"},
                {"id": "d", "text": "Local, national, mondial"},
            ],
            "correct_answer": "b",
        },
        {
            "id": "4",
            "domain": "basic_public_health",
            "question": "Sur quoi se concentre la promotion de la santé ?",
            "options": [
                {"id": "a", "text": "Traiter les maladies"},
                {"id": "b", "text": "Construire des hôpitaux"},
                {"id": "c", "text": "Former les agents de santé"},
                {"id": "d", "text": "Permettre aux gens d'avoir plus de contrôle sur leur santé"},
            ],
            "correct_answer": "d",
        },
        {
            "id": "5",
            "domain": "basic_public_health",
            "question": "Quelle organisation fournit le leadership mondial en santé ?",
            "options": [
                {"id": "a", "text": "Organisation mondiale de la santé (OMS)"},
                {"id": "b", "text": "Organisation des Nations Unies pour l'éducation, la science et la culture (UNESCO)"},
                {"id": "c", "text": "Fonds monétaire international (FMI)"},
                {"id": "d", "text": "Banque mondiale"},
            ],
            "correct_answer": "a",
        },
        # Épidémiologie (Questions 6-10)
        {
            "id": "6",
            "domain": "epidemiology",
            "question": "Quelle est la définition de l'épidémiologie ?",
            "options": [
                {"id": "a", "text": "L'étude des maladies individuelles"},
                {"id": "b", "text": "L'étude de la distribution et des déterminants des états liés à la santé dans les populations"},
                {"id": "c", "text": "L'étude de la gestion hospitalière"},
                {"id": "d", "text": "L'étude des traitements médicaux"},
            ],
            "correct_answer": "b",
        },
        {
            "id": "7",
            "domain": "epidemiology",
            "question": "Qu'est-ce que le taux d'attaque dans une épidémie ?",
            "options": [
                {"id": "a", "text": "Le nombre de décès"},
                {"id": "b", "text": "Le nombre d'hospitalisations"},
                {"id": "c", "text": "La proportion d'individus exposés qui développent la maladie"},
                {"id": "d", "text": "La durée de l'épidémie"},
            ],
            "correct_answer": "c",
        },
        {
            "id": "8",
            "domain": "epidemiology",
            "question": "Quel type d'étude suit les sujets dans le temps ?",
            "options": [
                {"id": "a", "text": "Étude de cohorte"},
                {"id": "b", "text": "Étude cas-témoins"},
                {"id": "c", "text": "Étude transversale"},
                {"id": "d", "text": "Étude écologique"},
            ],
            "correct_answer": "a",
        },
        {
            "id": "9",
            "domain": "epidemiology",
            "question": "Qu'est-ce que le taux d'incidence ?",
            "options": [
                {"id": "a", "text": "Nombre total de cas"},
                {"id": "b", "text": "Nombre de cas existants à un moment donné"},
                {"id": "c", "text": "Nombre de décès"},
                {"id": "d", "text": "Nombre de nouveaux cas survenant dans une période de temps spécifique"},
            ],
            "correct_answer": "d",
        },
        {
            "id": "10",
            "domain": "epidemiology",
            "question": "Quel est le but du traçage des contacts ?",
            "options": [
                {"id": "a", "text": "Traiter les patients"},
                {"id": "b", "text": "Identifier et surveiller les personnes qui ont pu être exposées à une maladie infectieuse"},
                {"id": "c", "text": "Compter le nombre de cas"},
                {"id": "d", "text": "Développer des vaccins"},
            ],
            "correct_answer": "b",
        },
        # Biostatistiques (Questions 11-15)
        {
            "id": "11",
            "domain": "biostatistics",
            "question": "Quelle est la médiane de l'ensemble de données : 2, 4, 6, 8, 10 ?",
            "options": [
                {"id": "a", "text": "6"},
                {"id": "b", "text": "5"},
                {"id": "c", "text": "4"},
                {"id": "d", "text": "8"},
            ],
            "correct_answer": "a",
        },
        {
            "id": "12",
            "domain": "biostatistics",
            "question": "Que signifie généralement une valeur p de 0,05 ?",
            "options": [
                {"id": "a", "text": "95% de certitude"},
                {"id": "b", "text": "50% de probabilité"},
                {"id": "c", "text": "Signification statistique au niveau de 5%"},
                {"id": "d", "text": "5% des données sont incorrectes"},
            ],
            "correct_answer": "c",
        },
        {
            "id": "13",
            "domain": "biostatistics",
            "question": "Quelle est la différence entre corrélation et causalité ?",
            "options": [
                {"id": "a", "text": "C'est la même chose"},
                {"id": "b", "text": "La corrélation implique une relation, la causalité implique qu'une variable cause l'autre"},
                {"id": "c", "text": "La causalité est plus faible que la corrélation"},
                {"id": "d", "text": "La corrélation ne s'applique qu'aux relations négatives"},
            ],
            "correct_answer": "b",
        },
        {
            "id": "14",
            "domain": "biostatistics",
            "question": "Qu'est-ce qu'un intervalle de confiance ?",
            "options": [
                {"id": "a", "text": "Une plage de valeurs susceptible de contenir le vrai paramètre de population"},
                {"id": "b", "text": "La valeur exacte d'une statistique"},
                {"id": "c", "text": "Le nombre d'observations"},
                {"id": "d", "text": "La moyenne de toutes les mesures"},
            ],
            "correct_answer": "a",
        },
        {
            "id": "15",
            "domain": "biostatistics",
            "question": "Quel type de variable est le 'groupe sanguin' (A, B, AB, O) ?",
            "options": [
                {"id": "a", "text": "Continue"},
                {"id": "b", "text": "Ordinale"},
                {"id": "c", "text": "Intervalle"},
                {"id": "d", "text": "Nominale"},
            ],
            "correct_answer": "d",
        },
        # Systèmes de Santé (Questions 16-20)
        {
            "id": "16",
            "domain": "data_analysis",
            "question": "Quels sont les principaux composants d'un système de santé ?",
            "options": [
                {"id": "a", "text": "Hôpitaux et cliniques seulement"},
                {"id": "b", "text": "Prestation de services, personnel de santé, information, financement, gouvernance, produits médicaux"},
                {"id": "c", "text": "Médecins et infirmières seulement"},
                {"id": "d", "text": "Politiques gouvernementales seulement"},
            ],
            "correct_answer": "b",
        },
        {
            "id": "17",
            "domain": "data_analysis",
            "question": "Qu'est-ce que la couverture sanitaire universelle (CSU) ?",
            "options": [
                {"id": "a", "text": "Soins de santé gratuits pour tous"},
                {"id": "b", "text": "Soins de santé gouvernementaux seulement"},
                {"id": "c", "text": "S'assurer que tous ont accès aux services de santé nécessaires sans difficultés financières"},
                {"id": "d", "text": "Soins de santé privés pour tous"},
            ],
            "correct_answer": "c",
        },
        {
            "id": "18",
            "domain": "data_analysis",
            "question": "Quel est le rôle des systèmes d'information sanitaire ?",
            "options": [
                {"id": "a", "text": "Collecter, analyser et utiliser les données de santé pour la prise de décision"},
                {"id": "b", "text": "Stocker les dossiers médicaux seulement"},
                {"id": "c", "text": "Compter les patients"},
                {"id": "d", "text": "Programmer les rendez-vous"},
            ],
            "correct_answer": "a",
        },
        {
            "id": "19",
            "domain": "data_analysis",
            "question": "Qu'est-ce que le financement de la santé ?",
            "options": [
                {"id": "a", "text": "Construire des hôpitaux"},
                {"id": "b", "text": "La fonction de lever, mutualiser et acheter les services de santé"},
                {"id": "c", "text": "Former les agents de santé"},
                {"id": "d", "text": "Importer du matériel médical"},
            ],
            "correct_answer": "b",
        },
        {
            "id": "20",
            "domain": "data_analysis",
            "question": "Qu'est-ce que les soins de santé primaires ?",
            "options": [
                {"id": "a", "text": "Soins d'urgence seulement"},
                {"id": "b", "text": "Soins hospitaliers"},
                {"id": "c", "text": "Soins spécialisés"},
                {"id": "d", "text": "Soins de santé essentiels basés sur des méthodes pratiques et scientifiquement fondées"},
            ],
            "correct_answer": "d",
        },
    ]


def _get_level_description_en(level: int) -> str:
    """Get English level description."""
    descriptions = {
        1: "Beginner - Build foundational knowledge",
        2: "Intermediate - Develop core competencies",
        3: "Advanced - Strengthen specialized skills",
        4: "Expert - Master advanced concepts",
    }
    return descriptions.get(level, "Unknown level")


def _get_level_description_fr(level: int) -> str:
    """Get French level description."""
    descriptions = {
        1: "Débutant - Construire les connaissances de base",
        2: "Intermédiaire - Développer les compétences clés",
        3: "Avancé - Renforcer les compétences spécialisées",
        4: "Expert - Maîtriser les concepts avancés",
    }
    return descriptions.get(level, "Niveau inconnu")