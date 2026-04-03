"""Placement test endpoints for level assignment."""

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from structlog import get_logger

from app.api.deps import get_db as get_db_session
from app.api.deps_local_auth import get_current_user

from ...domain.models.quiz import PlacementTestAttempt
from ...domain.models.user import User
from ...domain.repositories.implementations.user_repository import UserRepository
from ...domain.services.placement_service import PlacementService
from .schemas.placement import PlacementTestResponse, PlacementTestSubmission

logger = get_logger(__name__)
router = APIRouter(prefix="/placement-test", tags=["Placement Test"])


@router.get("/questions", response_model=PlacementTestResponse)
async def get_placement_test_questions(
    language: str | None = Query(default=None, pattern="^(fr|en)$"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> PlacementTestResponse:
    """Get placement test questions.

    Args:
        language: Language override (fr/en). Falls back to user's preferred_language.

    Returns:
        Placement test with 20 questions covering 4 domains

    Raises:
        403: User has already completed placement test recently
        500: Failed to generate questions
    """
    try:
        lang = language if language is not None else current_user.preferred_language
        questions = _get_placement_questions(lang)

        logger.info("Placement test questions retrieved", user_id=str(current_user.id))
        return PlacementTestResponse(
            questions=questions,
            total_questions=20,
            time_limit_minutes=30,
            instructions={
                "en": "Answer all 20 questions covering topics from beginner to expert level. Your score will determine your starting level and unlock the modules that match your knowledge.",
                "fr": "Répondez aux 20 questions couvrant des sujets du niveau débutant au niveau expert. Votre score déterminera votre niveau de départ et débloquera les modules correspondant à vos connaissances.",
            },
            domains={
                "level_1_foundations": {
                    "name": {
                        "en": "Level 1 — Public Health Foundations (M01-M03)",
                        "fr": "Niveau 1 — Fondements de santé publique (M01-M03)",
                    },
                    "questions": [1, 2, 3, 4, 5],
                },
                "level_2_epidemiology": {
                    "name": {
                        "en": "Level 2 — Epidemiology & Surveillance (M04-M07)",
                        "fr": "Niveau 2 — Épidémiologie et surveillance (M04-M07)",
                    },
                    "questions": [6, 7, 8, 9, 10],
                },
                "level_3_advanced": {
                    "name": {
                        "en": "Level 3 — Advanced Statistics & Health Programming (M08-M12)",
                        "fr": "Niveau 3 — Statistiques avancées et programmation (M08-M12)",
                    },
                    "questions": [11, 12, 13, 14, 15],
                },
                "level_4_expert": {
                    "name": {
                        "en": "Level 4 — Expert: Policy, Systems & Research (M13-M15)",
                        "fr": "Niveau 4 — Expert : Politique, systèmes et recherche (M13-M15)",
                    },
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

        # Score the placement test and unlock modules
        result = await placement_service.score_placement_test(
            user_id=current_user.id,
            answers=submission.answers,
            time_taken=submission.time_taken_sec,
            user_context=user_context,
            db=db,
        )

        # Save the attempt to database
        attempt = PlacementTestAttempt(
            user_id=current_user.id,
            answers=submission.answers,
            raw_score=result.score_percentage,  # Using score_percentage as raw score
            adjusted_score=result.score_percentage,
            assigned_level=result.assigned_level,
            time_taken_sec=submission.time_taken_sec,
            domain_scores=result.level_scores,
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
            "level_scores": result.level_scores,
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
    """Get English placement test questions spanning all 4 levels (5 questions per level)."""
    return [
        # ── Level 1 — Foundations (M01-M03) ───────────────────────────────────
        {
            "id": "1",
            "domain": "level_1_foundations",
            "level": 1,
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
            "domain": "level_1_foundations",
            "level": 1,
            "question": "Which of the following is a social determinant of health?",
            "options": [
                {"id": "a", "text": "Socioeconomic status and education"},
                {"id": "b", "text": "Number of CT scanners in a country"},
                {"id": "c", "text": "Average number of hospital beds"},
                {"id": "d", "text": "Pharmaceutical drug prices"},
            ],
            "correct_answer": "a",
        },
        {
            "id": "3",
            "domain": "level_1_foundations",
            "level": 1,
            "question": "What are the three levels of disease prevention?",
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
            "domain": "level_1_foundations",
            "level": 1,
            "question": "Which West African regional body is responsible for health policy coordination among member states?",
            "options": [
                {"id": "a", "text": "African Union (AU)"},
                {"id": "b", "text": "Economic Community of West African States (ECOWAS)"},
                {"id": "c", "text": "International Monetary Fund (IMF)"},
                {"id": "d", "text": "World Trade Organization (WTO)"},
            ],
            "correct_answer": "b",
        },
        {
            "id": "5",
            "domain": "level_1_foundations",
            "level": 1,
            "question": "What does the maternal mortality ratio measure?",
            "options": [
                {"id": "a", "text": "Deaths of mothers per 1 000 live births"},
                {"id": "b", "text": "Deaths of mothers per 100 000 live births"},
                {"id": "c", "text": "Deaths of newborns in the first 28 days per 1 000 births"},
                {"id": "d", "text": "Number of women dying from cancer per year"},
            ],
            "correct_answer": "b",
        },
        # ── Level 2 — Epidemiology & Surveillance (M04-M07) ───────────────────
        {
            "id": "6",
            "domain": "level_2_epidemiology",
            "level": 2,
            "question": "A cohort study in Dakar follows 5 000 HIV-negative adults for 3 years; 75 develop HIV. What is the incidence rate per 100 person-years if total follow-up is 14 800 person-years?",
            "options": [
                {"id": "a", "text": "0.25 per 100 person-years"},
                {"id": "b", "text": "0.51 per 100 person-years"},
                {"id": "c", "text": "1.50 per 100 person-years"},
                {"id": "d", "text": "5.00 per 100 person-years"},
            ],
            "correct_answer": "b",
        },
        {
            "id": "7",
            "domain": "level_2_epidemiology",
            "level": 2,
            "question": "In a case-control study, the odds ratio for malaria and indoor residual spraying non-use is 3.2 (95% CI: 1.8–5.6). How should this be interpreted?",
            "options": [
                {"id": "a", "text": "No statistically significant association as the CI is wide"},
                {"id": "b", "text": "Exposure reduces malaria risk by 3.2 times"},
                {
                    "id": "c",
                    "text": "Non-use of spraying is associated with 3.2-times higher odds of malaria",
                },
                {"id": "d", "text": "32% of malaria cases are caused by non-spraying"},
            ],
            "correct_answer": "c",
        },
        {
            "id": "8",
            "domain": "level_2_epidemiology",
            "level": 2,
            "question": "Which DHIS2 indicator best monitors progress toward eliminating mother-to-child HIV transmission?",
            "options": [
                {"id": "a", "text": "ANC first-visit coverage"},
                {
                    "id": "b",
                    "text": "PMTCT antiretroviral prophylaxis coverage among HIV+ pregnant women",
                },
                {"id": "c", "text": "Number of HIV tests performed"},
                {"id": "d", "text": "Hospital delivery rate"},
            ],
            "correct_answer": "b",
        },
        {
            "id": "9",
            "domain": "level_2_epidemiology",
            "level": 2,
            "question": "What is the purpose of an epidemic curve (epi-curve) in outbreak investigation?",
            "options": [
                {"id": "a", "text": "To count the total number of deaths"},
                {"id": "b", "text": "To identify the causative pathogen"},
                {
                    "id": "c",
                    "text": "To determine the source, mode of transmission, and duration of exposure",
                },
                {"id": "d", "text": "To calculate vaccine efficacy"},
            ],
            "correct_answer": "c",
        },
        {
            "id": "10",
            "domain": "level_2_epidemiology",
            "level": 2,
            "question": "Integrated Disease Surveillance and Response (IDSR) is Africa's primary surveillance strategy. Which event triggers an IMMEDIATE alert report?",
            "options": [
                {"id": "a", "text": "A cluster of fever cases exceeding the seasonal baseline"},
                {
                    "id": "b",
                    "text": "A single confirmed case of viral hemorrhagic fever (e.g., Ebola)",
                },
                {
                    "id": "c",
                    "text": "A 10% increase in malaria cases compared to the previous week",
                },
                {"id": "d", "text": "Any confirmed cholera case in a non-endemic district"},
            ],
            "correct_answer": "b",
        },
        # ── Level 3 — Advanced Stats, Programming & Health Systems (M08-M12) ──
        {
            "id": "11",
            "domain": "level_3_advanced",
            "level": 3,
            "question": "A logistic regression model produces an adjusted OR of 2.4 (95% CI: 1.1–5.2) for the association between open defecation and childhood stunting, controlling for household income. What does 'adjusted' mean here?",
            "options": [
                {"id": "a", "text": "The OR has been corrected for measurement error"},
                {
                    "id": "b",
                    "text": "The effect of open defecation is estimated while holding household income constant",
                },
                {"id": "c", "text": "The sample size has been recalculated"},
                {"id": "d", "text": "The OR has been weighted for survey non-response"},
            ],
            "correct_answer": "b",
        },
        {
            "id": "12",
            "domain": "level_3_advanced",
            "level": 3,
            "question": "In survival analysis of tuberculosis treatment outcomes, what does a hazard ratio of 0.6 for the intervention group indicate?",
            "options": [
                {
                    "id": "a",
                    "text": "The intervention group has 40% lower instantaneous risk of treatment failure at any point",
                },
                {"id": "b", "text": "60% of the intervention group survived"},
                {"id": "c", "text": "The intervention group has 60% higher risk of failure"},
                {"id": "d", "text": "There is a 40% absolute reduction in mortality"},
            ],
            "correct_answer": "a",
        },
        {
            "id": "13",
            "domain": "level_3_advanced",
            "level": 3,
            "question": "You are designing a district health program using the PRECEDE-PROCEED model. Which phase involves identifying predisposing, reinforcing, and enabling factors?",
            "options": [
                {"id": "a", "text": "Administrative and policy assessment"},
                {"id": "b", "text": "Educational and ecological assessment"},
                {"id": "c", "text": "Epidemiological assessment"},
                {"id": "d", "text": "Implementation phase"},
            ],
            "correct_answer": "b",
        },
        {
            "id": "14",
            "domain": "level_3_advanced",
            "level": 3,
            "question": "When visualizing district-level malaria incidence data in R using ggplot2, which geometry is most appropriate for a choropleth map?",
            "options": [
                {"id": "a", "text": "geom_point()"},
                {"id": "b", "text": "geom_bar()"},
                {"id": "c", "text": "geom_histogram()"},
                {"id": "d", "text": "geom_sf() with fill mapped to the incidence variable"},
            ],
            "correct_answer": "d",
        },
        {
            "id": "15",
            "domain": "level_3_advanced",
            "level": 3,
            "question": "The Disability-Adjusted Life Year (DALY) metric combines two components. Which pair is correct?",
            "options": [
                {"id": "a", "text": "Years of Life Lost (YLL) + Years Lived with Disability (YLD)"},
                {"id": "b", "text": "Years of Life Gained + Quality-Adjusted Life Years"},
                {"id": "c", "text": "Mortality rate + Morbidity rate"},
                {"id": "d", "text": "Incidence + Prevalence"},
            ],
            "correct_answer": "a",
        },
        # ── Level 4 — Expert: Policy, Systems Strengthening & Research (M13-M15)
        {
            "id": "16",
            "domain": "level_4_expert",
            "level": 4,
            "question": "A country wants to expand community health worker (CHW) programmes to rural areas. Using the WHO health systems building blocks framework, which block is most directly addressed by recruiting and training 10 000 new CHWs?",
            "options": [
                {"id": "a", "text": "Service delivery"},
                {"id": "b", "text": "Health workforce"},
                {"id": "c", "text": "Health information systems"},
                {"id": "d", "text": "Medical products and technologies"},
            ],
            "correct_answer": "b",
        },
        {
            "id": "17",
            "domain": "level_4_expert",
            "level": 4,
            "question": "In a systematic review applying GRADE methodology, which factor would DOWNGRADE the certainty of evidence?",
            "options": [
                {"id": "a", "text": "Large effect size (OR > 5)"},
                {"id": "b", "text": "Dose-response relationship"},
                {"id": "c", "text": "High risk of bias across included RCTs"},
                {"id": "d", "text": "Consistent findings across studies"},
            ],
            "correct_answer": "c",
        },
        {
            "id": "18",
            "domain": "level_4_expert",
            "level": 4,
            "question": "You are conducting a health technology assessment (HTA) of a new malaria rapid diagnostic test. The incremental cost-effectiveness ratio (ICER) is USD 45 per DALY averted. Using the WHO threshold of 1× GDP per capita for Senegal (~USD 1 650), how should this be classified?",
            "options": [
                {"id": "a", "text": "Not cost-effective — ICER exceeds the threshold"},
                {"id": "b", "text": "Highly cost-effective — ICER is well below the threshold"},
                {
                    "id": "c",
                    "text": "Moderately cost-effective — ICER is between 1× and 3× GDP per capita",
                },
                {"id": "d", "text": "Cannot be assessed without mortality data"},
            ],
            "correct_answer": "b",
        },
        {
            "id": "19",
            "domain": "level_4_expert",
            "level": 4,
            "question": "A national immunisation programme shows falling DTP3 coverage in two northern districts despite adequate vaccine supply. A mixed-methods health systems analysis would BEST identify the root cause by:",
            "options": [
                {"id": "a", "text": "Ordering more vaccines to the districts"},
                {
                    "id": "b",
                    "text": "Combining DHIS2 coverage data with qualitative interviews of health workers and caregivers",
                },
                {"id": "c", "text": "Conducting a new randomised trial in those districts"},
                {"id": "d", "text": "Implementing a new electronic health record system"},
            ],
            "correct_answer": "b",
        },
        {
            "id": "20",
            "domain": "level_4_expert",
            "level": 4,
            "question": "Under the International Health Regulations (IHR 2005), a Public Health Emergency of International Concern (PHEIC) is declared by:",
            "options": [
                {"id": "a", "text": "The affected country's Ministry of Health"},
                {"id": "b", "text": "The WHO Director-General on advice of an Emergency Committee"},
                {"id": "c", "text": "A majority vote of WHO member states"},
                {"id": "d", "text": "The UN Security Council"},
            ],
            "correct_answer": "d",
        },
    ]


def _get_french_questions() -> list[dict[str, Any]]:
    """Get French placement test questions spanning all 4 levels (5 questions per level)."""
    return [
        # ── Niveau 1 — Fondements (M01-M03) ──────────────────────────────────
        {
            "id": "1",
            "domain": "level_1_foundations",
            "level": 1,
            "question": "Quel est l'objectif principal de la santé publique ?",
            "options": [
                {"id": "a", "text": "Traiter les patients individuels"},
                {"id": "b", "text": "Gérer les hôpitaux"},
                {
                    "id": "c",
                    "text": "Prévenir les maladies et promouvoir la santé dans les populations",
                },
                {"id": "d", "text": "Mener des recherches médicales"},
            ],
            "correct_answer": "c",
        },
        {
            "id": "2",
            "domain": "level_1_foundations",
            "level": 1,
            "question": "Lequel des éléments suivants est un déterminant social de la santé ?",
            "options": [
                {"id": "a", "text": "Le statut socio-économique et le niveau d'éducation"},
                {"id": "b", "text": "Le nombre de scanners dans un pays"},
                {"id": "c", "text": "Le nombre moyen de lits d'hôpitaux"},
                {"id": "d", "text": "Le prix des médicaments"},
            ],
            "correct_answer": "a",
        },
        {
            "id": "3",
            "domain": "level_1_foundations",
            "level": 1,
            "question": "Quels sont les trois niveaux de prévention des maladies ?",
            "options": [
                {"id": "a", "text": "Clinique, communautaire, populationnel"},
                {"id": "b", "text": "Primaire, secondaire, tertiaire"},
                {"id": "c", "text": "Individuel, groupe, société"},
                {"id": "d", "text": "Local, national, mondial"},
            ],
            "correct_answer": "b",
        },
        {
            "id": "4",
            "domain": "level_1_foundations",
            "level": 1,
            "question": "Quelle organisation régionale ouest-africaine est responsable de la coordination des politiques de santé entre ses États membres ?",
            "options": [
                {"id": "a", "text": "Union africaine (UA)"},
                {
                    "id": "b",
                    "text": "Communauté économique des États de l'Afrique de l'Ouest (CEDEAO)",
                },
                {"id": "c", "text": "Fonds monétaire international (FMI)"},
                {"id": "d", "text": "Organisation mondiale du commerce (OMC)"},
            ],
            "correct_answer": "b",
        },
        {
            "id": "5",
            "domain": "level_1_foundations",
            "level": 1,
            "question": "Que mesure le ratio de mortalité maternelle ?",
            "options": [
                {"id": "a", "text": "Les décès maternels pour 1 000 naissances vivantes"},
                {"id": "b", "text": "Les décès maternels pour 100 000 naissances vivantes"},
                {
                    "id": "c",
                    "text": "Les décès de nouveau-nés dans les 28 premiers jours pour 1 000 naissances",
                },
                {"id": "d", "text": "Le nombre de femmes mourant d'un cancer par an"},
            ],
            "correct_answer": "b",
        },
        # ── Niveau 2 — Épidémiologie & Surveillance (M04-M07) ─────────────────
        {
            "id": "6",
            "domain": "level_2_epidemiology",
            "level": 2,
            "question": "Une étude de cohorte à Dakar suit 5 000 adultes VIH-négatifs pendant 3 ans ; 75 développent le VIH. Quel est le taux d'incidence pour 100 personnes-années si le suivi total est de 14 800 personnes-années ?",
            "options": [
                {"id": "a", "text": "0,25 pour 100 personnes-années"},
                {"id": "b", "text": "0,51 pour 100 personnes-années"},
                {"id": "c", "text": "1,50 pour 100 personnes-années"},
                {"id": "d", "text": "5,00 pour 100 personnes-années"},
            ],
            "correct_answer": "b",
        },
        {
            "id": "7",
            "domain": "level_2_epidemiology",
            "level": 2,
            "question": "Dans une étude cas-témoins, l'odds ratio entre le paludisme et la non-utilisation de la pulvérisation intradomiciliaire est de 3,2 (IC 95 % : 1,8–5,6). Comment interpréter ce résultat ?",
            "options": [
                {
                    "id": "a",
                    "text": "Pas d'association statistiquement significative car l'IC est large",
                },
                {"id": "b", "text": "L'exposition réduit le risque de paludisme de 3,2 fois"},
                {
                    "id": "c",
                    "text": "La non-utilisation de la pulvérisation est associée à des chances 3,2 fois plus élevées de paludisme",
                },
                {
                    "id": "d",
                    "text": "32 % des cas de paludisme sont causés par la non-pulvérisation",
                },
            ],
            "correct_answer": "c",
        },
        {
            "id": "8",
            "domain": "level_2_epidemiology",
            "level": 2,
            "question": "Quel indicateur DHIS2 permet de mieux suivre les progrès vers l'élimination de la transmission mère-enfant du VIH ?",
            "options": [
                {"id": "a", "text": "Couverture de la première consultation prénatale"},
                {
                    "id": "b",
                    "text": "Couverture prophylactique antirétrovirale PTME chez les femmes enceintes VIH+",
                },
                {"id": "c", "text": "Nombre de tests VIH réalisés"},
                {"id": "d", "text": "Taux d'accouchement en établissement de santé"},
            ],
            "correct_answer": "b",
        },
        {
            "id": "9",
            "domain": "level_2_epidemiology",
            "level": 2,
            "question": "Quel est le rôle de la courbe épidémique (courbe épi) dans l'investigation d'une épidémie ?",
            "options": [
                {"id": "a", "text": "Compter le nombre total de décès"},
                {"id": "b", "text": "Identifier l'agent pathogène responsable"},
                {
                    "id": "c",
                    "text": "Déterminer la source, le mode de transmission et la durée de l'exposition",
                },
                {"id": "d", "text": "Calculer l'efficacité vaccinale"},
            ],
            "correct_answer": "c",
        },
        {
            "id": "10",
            "domain": "level_2_epidemiology",
            "level": 2,
            "question": "La Surveillance intégrée des maladies et riposte (SIMR) est la stratégie principale de surveillance en Afrique. Quel événement déclenche un rapport d'alerte IMMÉDIAT ?",
            "options": [
                {
                    "id": "a",
                    "text": "Un groupe de cas fébriles dépassant la ligne de base saisonnière",
                },
                {
                    "id": "b",
                    "text": "Un seul cas confirmé de fièvre hémorragique virale (ex. Ebola)",
                },
                {
                    "id": "c",
                    "text": "Une augmentation de 10 % des cas de paludisme par rapport à la semaine précédente",
                },
                {"id": "d", "text": "Tout cas de choléra confirmé dans un district non endémique"},
            ],
            "correct_answer": "b",
        },
        # ── Niveau 3 — Statistiques avancées, Programmation & Systèmes (M08-M12)
        {
            "id": "11",
            "domain": "level_3_advanced",
            "level": 3,
            "question": "Un modèle de régression logistique produit un OR ajusté de 2,4 (IC 95 % : 1,1–5,2) pour l'association entre la défécation à l'air libre et le retard de croissance chez l'enfant, après ajustement sur le revenu du ménage. Que signifie « ajusté » ici ?",
            "options": [
                {"id": "a", "text": "L'OR a été corrigé pour les erreurs de mesure"},
                {
                    "id": "b",
                    "text": "L'effet de la défécation à l'air libre est estimé en maintenant le revenu du ménage constant",
                },
                {"id": "c", "text": "La taille de l'échantillon a été recalculée"},
                {"id": "d", "text": "L'OR a été pondéré pour la non-réponse à l'enquête"},
            ],
            "correct_answer": "b",
        },
        {
            "id": "12",
            "domain": "level_3_advanced",
            "level": 3,
            "question": "Dans une analyse de survie des résultats du traitement de la tuberculose, que signifie un hazard ratio de 0,6 pour le groupe d'intervention ?",
            "options": [
                {
                    "id": "a",
                    "text": "Le groupe d'intervention présente un risque instantané d'échec thérapeutique 40 % inférieur à tout moment",
                },
                {"id": "b", "text": "60 % du groupe d'intervention ont survécu"},
                {
                    "id": "c",
                    "text": "Le groupe d'intervention présente un risque d'échec 60 % plus élevé",
                },
                {"id": "d", "text": "Il y a une réduction absolue de 40 % de la mortalité"},
            ],
            "correct_answer": "a",
        },
        {
            "id": "13",
            "domain": "level_3_advanced",
            "level": 3,
            "question": "Vous concevez un programme de santé de district en utilisant le modèle PRECEDE-PROCEED. Quelle phase identifie les facteurs prédisposants, de renforcement et facilitants ?",
            "options": [
                {"id": "a", "text": "Évaluation administrative et politique"},
                {"id": "b", "text": "Évaluation éducationnelle et écologique"},
                {"id": "c", "text": "Évaluation épidémiologique"},
                {"id": "d", "text": "Phase d'implémentation"},
            ],
            "correct_answer": "b",
        },
        {
            "id": "14",
            "domain": "level_3_advanced",
            "level": 3,
            "question": "Pour visualiser les données d'incidence du paludisme à l'échelle des districts en R avec ggplot2, quelle géométrie convient le mieux pour une carte choroplèthe ?",
            "options": [
                {"id": "a", "text": "geom_point()"},
                {"id": "b", "text": "geom_bar()"},
                {"id": "c", "text": "geom_histogram()"},
                {"id": "d", "text": "geom_sf() avec fill mappé à la variable d'incidence"},
            ],
            "correct_answer": "d",
        },
        {
            "id": "15",
            "domain": "level_3_advanced",
            "level": 3,
            "question": "La métrique AVCI (Années de Vie Corrigées de l'Incapacité) combine deux composantes. Quelle paire est correcte ?",
            "options": [
                {
                    "id": "a",
                    "text": "Années de vie perdues (AVP) + Années vécues avec incapacité (AVI)",
                },
                {
                    "id": "b",
                    "text": "Années de vie gagnées + Années de vie ajustées sur la qualité",
                },
                {"id": "c", "text": "Taux de mortalité + Taux de morbidité"},
                {"id": "d", "text": "Incidence + Prévalence"},
            ],
            "correct_answer": "a",
        },
        # ── Niveau 4 — Expert : Politique, Renforcement des systèmes & Recherche (M13-M15)
        {
            "id": "16",
            "domain": "level_4_expert",
            "level": 4,
            "question": "Un pays souhaite étendre les programmes d'agents de santé communautaires (ASC) en zones rurales. En utilisant le cadre des blocs constitutifs des systèmes de santé de l'OMS, quel bloc est le plus directement adressé par le recrutement et la formation de 10 000 nouveaux ASC ?",
            "options": [
                {"id": "a", "text": "Prestation de services"},
                {"id": "b", "text": "Personnel de santé"},
                {"id": "c", "text": "Systèmes d'information sanitaire"},
                {"id": "d", "text": "Produits médicaux et technologies"},
            ],
            "correct_answer": "b",
        },
        {
            "id": "17",
            "domain": "level_4_expert",
            "level": 4,
            "question": "Dans une revue systématique appliquant la méthodologie GRADE, quel facteur DIMINUERAIT le niveau de certitude des preuves ?",
            "options": [
                {"id": "a", "text": "Grande taille d'effet (OR > 5)"},
                {"id": "b", "text": "Relation dose-réponse"},
                {"id": "c", "text": "Risque élevé de biais dans les ECR inclus"},
                {"id": "d", "text": "Résultats cohérents entre les études"},
            ],
            "correct_answer": "c",
        },
        {
            "id": "18",
            "domain": "level_4_expert",
            "level": 4,
            "question": "Vous réalisez une évaluation des technologies de santé (ETS) pour un nouveau test de diagnostic rapide du paludisme. Le ratio coût-efficacité incrémental (RCEI) est de 45 USD par AVCI évitée. En utilisant le seuil OMS de 1× PIB par habitant pour le Sénégal (~1 650 USD), comment classer ce résultat ?",
            "options": [
                {"id": "a", "text": "Pas rentable — le RCEI dépasse le seuil"},
                {"id": "b", "text": "Très rentable — le RCEI est bien en dessous du seuil"},
                {
                    "id": "c",
                    "text": "Modérément rentable — le RCEI est entre 1× et 3× le PIB par habitant",
                },
                {"id": "d", "text": "Ne peut être évalué sans données de mortalité"},
            ],
            "correct_answer": "b",
        },
        {
            "id": "19",
            "domain": "level_4_expert",
            "level": 4,
            "question": "Un programme national de vaccination montre une baisse de la couverture DTP3 dans deux districts du nord malgré un approvisionnement adéquat en vaccins. Une analyse mixte des systèmes de santé permettrait MIEUX d'identifier la cause profonde en :",
            "options": [
                {"id": "a", "text": "Commandant plus de vaccins pour ces districts"},
                {
                    "id": "b",
                    "text": "Combinant les données de couverture DHIS2 avec des entretiens qualitatifs auprès des agents de santé et des soignants",
                },
                {"id": "c", "text": "Menant un nouvel essai randomisé dans ces districts"},
                {
                    "id": "d",
                    "text": "Mettant en place un nouveau système de dossiers de santé électroniques",
                },
            ],
            "correct_answer": "b",
        },
        {
            "id": "20",
            "domain": "level_4_expert",
            "level": 4,
            "question": "En vertu du Règlement sanitaire international (RSI 2005), une Urgence de santé publique de portée internationale (USPPI) est déclarée par :",
            "options": [
                {"id": "a", "text": "Le Ministère de la santé du pays affecté"},
                {"id": "b", "text": "Le Directeur général de l'OMS sur avis d'un Comité d'urgence"},
                {"id": "c", "text": "Un vote à la majorité des États membres de l'OMS"},
                {"id": "d", "text": "Le Conseil de sécurité de l'ONU"},
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
