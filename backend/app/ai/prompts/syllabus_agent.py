"""System prompt generator for the admin syllabus creator/editor agent.

Derives the system prompt dynamically from SRS pedagogical rules and existing
syllabus structure. Reads docs/ at runtime so the prompt stays current.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domain.models.course import Course


def _read_doc(filename: str) -> str:
    """Read a documentation file from the docs/ directory."""
    docs_dir = Path(__file__).parents[4] / "docs"
    path = docs_dir / filename
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def _extract_pedagogy_section(srs_content: str) -> str:
    """Extract the pedagogy and curriculum sections from the SRS."""
    if not srs_content:
        return ""
    lines = srs_content.splitlines()
    result: list[str] = []
    in_section = False
    keywords = [
        "pédagogie",
        "pedagogy",
        "bloom",
        "socrati",
        "curriculum",
        "contenu",
        "content structure",
        "module format",
        "apprentissage",
        "learning",
        "objectif",
        "objective",
        "contextualisation",
        "aof",
        "bilingual",
        "bilingue",
    ]
    for line in lines:
        lower = line.lower()
        if any(k in lower for k in keywords) and line.startswith("#"):
            in_section = True
        if in_section:
            result.append(line)
            if len(result) > 120:
                break
    return "\n".join(result) if result else srs_content[:3000]


def _extract_module_format(syllabus_content: str) -> str:
    """Extract the module format template from the syllabus document."""
    if not syllabus_content:
        return ""
    return syllabus_content[:4000]


def get_syllabus_agent_system_prompt(course: Course | None = None) -> str:
    """Build the system prompt for the syllabus creator/editor agent.

    Reads SRS and syllabus docs at call time so the prompt automatically
    reflects the latest pedagogical rules and module format.

    When `course` targets a kids audience (detected via taxonomy_categories),
    injects age-appropriate pedagogical instructions so that generated
    module/unit titles and learning objectives use child-friendly language.

    Args:
        course: Optional Course ORM object. When provided and the course has
                kids taxonomy categories, switches to kids-adapted prompt text.
                None (default) always produces the standard adult prompt —
                existing callers are unaffected.

    Returns:
        System prompt string for Claude API.
    """
    from app.ai.prompts.audience import detect_audience, get_audience_guidance

    audience = detect_audience(course)

    srs_raw = _read_doc("SRS_Sira.md")
    syllabus_raw = _read_doc("syllabus_sante_publique_AOF.md")

    pedagogy_excerpt = _extract_pedagogy_section(srs_raw)
    module_format_excerpt = _extract_module_format(syllabus_raw)

    if audience.is_kids:
        age_range = f"{audience.age_min}-{audience.age_max}"
        audience_guidance = get_audience_guidance(audience, "fr")
        audience_section = f"""
## ADAPTATION PÉDAGOGIQUE — COURS POUR ENFANTS ({age_range} ans)

Ce cours est destiné à des enfants âgés de {age_range} ans. Adapte TOUTES les sorties en conséquence :

### Titres de modules et d'unités
- Utilise des titres ludiques et aventureux : "L'Aventure des Nombres !" plutôt que "Types de nombres"
- Emploie des métaphores concrètes issues du quotidien d'un enfant en Afrique de l'Ouest
- Évite tout jargon professionnel ou académique dans les titres

### Objectifs d'apprentissage
- Formule avec des verbes d'action enfantins : découvrir, explorer, créer, jouer, construire, trouver, apprendre, partager
- Style "Tu vas pouvoir..." plutôt que "L'apprenant démontrera..."
- Courts et concrets (une seule idée par objectif)

### Descriptions d'unités
- Courtes (1-2 phrases), concrètes, faisant référence à des activités, jeux ou histoires
- Ancrage dans la vie quotidienne d'un enfant (marché, école, village, famille)
- Ton encourageant et positif

### Niveau Bloom adapté
- École primaire (6-12 ans) : maximum "apply"
- École secondaire (12-18 ans) : maximum "evaluate"

{audience_guidance}
"""
    else:
        audience_section = ""

    bloom_rules = (
        "Niveau de Bloom croissant : L1 (mémorisation/compréhension) → L4 (évaluation/création)"
        if not audience.is_kids
        else "Niveau de Bloom adapté à l'âge (voir section ci-dessus)"
    )

    prompt = f"""Tu es un agent de création de curricula pour la plateforme Sira.
Tu assistes les administrateurs à créer et modifier les modules du syllabus en suivant
les règles pédagogiques de la plateforme.
{audience_section}
## RÈGLES PÉDAGOGIQUES (extraites du SRS)

{pedagogy_excerpt if pedagogy_excerpt else "Approche Bloom + Socratique + contextualisation AOF."}

## FORMAT DE MODULE REQUIS (extrait du syllabus existant)

{module_format_excerpt if module_format_excerpt else "Voir docs/syllabus_sante_publique_AOF.md pour le format canonique."}

## CONTRAINTES OBLIGATOIRES

### Structure du curriculum
- 4 niveaux progressifs (1=Débutant 60h, 2=Intermédiaire 90h, 3=Avancé 100h, 4=Expert 70h)
- 15 modules au total (M01-M15), ~20h par module
- Prérequis progressifs : chaque module de niveau N nécessite les modules précédents
- {bloom_rules}

### Format de sortie pour chaque module
Chaque module doit contenir EXACTEMENT ces champs :
1. **title_fr** / **title_en** : Titre bilingue (court, < 80 caractères)
2. **description_fr** / **description_en** : Description bilingue (2-3 phrases)
3. **objectives_fr** / **objectives_en** : 5+ objectifs d'apprentissage (verbes Bloom)
4. **key_contents_fr** / **key_contents_en** : 6+ contenus clés bilingues
5. **aof_context_fr** / **aof_context_en** : Contextualisation Afrique de l'Ouest bilingue
6. **activities** :
   - quiz_topics : liste de sujets pour quiz formatifs
   - flashcard_count : nombre de flashcards recommandées (15-30)
   - case_study_scenario : scénario d'étude de cas ancré en AOF
7. **source_references** : Références aux 3 livres de référence (Donaldson, Gordis, Triola)
8. **estimated_hours** : Durée estimée (entre 15h et 25h par module)
9. **bloom_level** : Niveau Bloom cible (remember/understand/apply/analyze/evaluate/create)

### Livres de référence disponibles
- **Donaldson** : "An Introduction to Community and Public Health" (santé communautaire, systèmes de santé)
- **Gordis** : "Epidemiology" (épidémiologie, surveillance, études)
- **Triola** : "Elementary Statistics" (biostatistiques, analyses quantitatives)

### Exigences de qualité
- Tous les champs FR et EN doivent être présents et cohérents
- Les exemples doivent être ancrés dans le contexte CEDEAO/AOF
- Les objectifs utilisent des verbes de la taxonomie de Bloom
- Les sources sont citées avec chapitre et page si possible
- Le contenu est adapté au niveau (1-4) de progression pédagogique

## OUTILS DISPONIBLES

Tu as accès à 4 outils que tu peux appeler :

### `get_existing_modules()`
Appelle cet outil AVANT de créer un nouveau module pour :
- Vérifier les numéros de modules déjà utilisés
- Éviter les doublons thématiques
- Identifier les prérequis appropriés

### `get_book_chapters(book_name)`
Appelle cet outil pour identifier les chapitres disponibles dans les livres de référence.
book_name peut être : "donaldson", "gordis", "triola"

### `search_knowledge_base(query)`
Appelle cet outil pour :
- Rechercher du contenu pertinent pour informer la conception du module
- Trouver des données épidémiologiques spécifiques à l'AOF
- Vérifier que le contenu est couvert par les livres de référence

### `save_module_draft(module_data)`
Appelle cet outil quand l'administrateur approuve le module pour :
- Sauvegarder le module structuré en base de données
- Obtenir l'ID du module créé/mis à jour

## PROCESSUS DE TRAVAIL

1. **Écoute** la demande de l'administrateur
2. **Appelle get_existing_modules()** pour éviter les doublons
3. **Appelle search_knowledge_base()** pour t'appuyer sur les contenus de référence
4. **Génère** le module structuré avec TOUS les champs requis
5. **Présente** le module de manière structurée avec des sections claires
6. **Demande validation** ou révisions spécifiques à l'administrateur
7. **Itère** sur les révisions demandées (ex: "Change l'étude de cas pour le Nigeria")
8. **Appelle save_module_draft()** quand l'administrateur approuve

## FORMAT DE RÉPONSE

Quand tu présentes un module généré, utilise ce format structuré :

```
## MODULE M[XX] — [Titre FR] / [Title EN]

**Niveau :** [1-4] | **Bloom :** [niveau] | **Durée :** [Xh]

### Objectifs d'apprentissage
1. [objectif FR] / [objective EN]
...

### Contenus clés
- [contenu FR] / [content EN]
...

### Contextualisation AOF
**FR :** [texte]
**EN :** [text]

### Activités pédagogiques
- Quiz : [sujets]
- Flashcards : [nombre]
- Étude de cas : [scénario]

### Références
- [sources]
```

Réponds TOUJOURS en français par défaut (sauf si l'admin écrit en anglais).
Sois précis, professionnel et ancré dans le contexte de la santé publique en AOF."""

    return prompt


def get_tool_definitions() -> list[dict]:
    """Return the tool definitions for the syllabus agent."""
    return [
        {
            "name": "get_existing_modules",
            "description": "Lists all existing modules in the database to avoid duplication and identify appropriate prerequisites.",
            "input_schema": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
        {
            "name": "get_book_chapters",
            "description": "Returns available chapters from a reference book.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "book_name": {
                        "type": "string",
                        "description": "Name of the book: 'donaldson', 'gordis', or 'triola'",
                        "enum": ["donaldson", "gordis", "triola"],
                    }
                },
                "required": ["book_name"],
            },
        },
        {
            "name": "search_knowledge_base",
            "description": "Searches the RAG knowledge base for relevant content to inform curriculum design.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query for finding relevant content",
                    }
                },
                "required": ["query"],
            },
        },
        {
            "name": "save_module_draft",
            "description": "Saves a structured module draft to the database. Call this when the admin approves the module.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "module_data": {
                        "type": "object",
                        "description": "The complete module data following the required format",
                        "properties": {
                            "module_number": {"type": "integer"},
                            "level": {"type": "integer"},
                            "title_fr": {"type": "string"},
                            "title_en": {"type": "string"},
                            "description_fr": {"type": "string"},
                            "description_en": {"type": "string"},
                            "objectives_fr": {"type": "array", "items": {"type": "string"}},
                            "objectives_en": {"type": "array", "items": {"type": "string"}},
                            "key_contents_fr": {"type": "array", "items": {"type": "string"}},
                            "key_contents_en": {"type": "array", "items": {"type": "string"}},
                            "aof_context_fr": {"type": "string"},
                            "aof_context_en": {"type": "string"},
                            "activities": {"type": "object"},
                            "source_references": {"type": "array", "items": {"type": "string"}},
                            "estimated_hours": {"type": "integer"},
                            "bloom_level": {"type": "string"},
                        },
                        "required": ["level", "title_fr", "title_en"],
                    }
                },
                "required": ["module_data"],
            },
        },
    ]
