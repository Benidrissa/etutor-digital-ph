# Software Requirements Specification
## SantéPublique AOF Learning Platform

> **Application Web Mobile-First Bilingue pour la Formation en Santé Publique — Afrique de l'Ouest**  
> Version : 1.0-draft | Statut : Draft pour validation | Audience : Développeurs, Product Owner, Parties prenantes

---

## Table des matières

1. [Introduction et Portée](#1-introduction-et-portée)
2. [Vision Produit & Objectifs](#2-vision-produit--objectifs)
3. [Utilisateurs & Personas](#3-utilisateurs--personas)
4. [User Stories](#4-user-stories)
5. [Architecture Système](#5-architecture-système)
6. [Moteur IA & Pipeline RAG](#6-moteur-ia--pipeline-rag)
7. [Exigences Fonctionnelles](#7-exigences-fonctionnelles)
8. [Exigences Non-Fonctionnelles](#8-exigences-non-fonctionnelles)
9. [Modèle de Données](#9-modèle-de-données)
10. [APIs & Intégrations Externes](#10-apis--intégrations-externes)
11. [Interface Utilisateur](#11-interface-utilisateur)
12. [Sécurité & Conformité](#12-sécurité--conformité)
13. [Roadmap de Développement](#13-roadmap-de-développement)

---

## 1. Introduction et Portée

Ce document définit les exigences fonctionnelles et non-fonctionnelles pour le développement de **SantéPublique AOF**, une plateforme d'apprentissage en ligne adaptative, bilingue (FR/EN) et mobile-first, destinée aux professionnels de santé et étudiants en Afrique de l'Ouest.

La plateforme génère dynamiquement du contenu pédagogique à partir de 3 ouvrages de référence en santé publique, contextualise chaque leçon dans le contexte de l'Afrique de l'Ouest, et adapte l'expérience au niveau de progression de chaque utilisateur.

### Portée du document

| Élément | Dans portée | Hors portée (v1) |
|---|---|---|
| Application web responsive (PWA) | ✅ | |
| Application native iOS/Android | | ❌ Phase 2 |
| Génération IA de contenu (RAG) | ✅ | |
| Quiz, flashcards, cas pratiques | ✅ | |
| Sandbox R/Python intégré | ✅ basique | |
| Vidéos et cours en direct (live) | | ❌ Phase 3 |
| Intégration DHIS2 données réelles | ✅ | |
| LMS institutionnel (SCORM) | | ❌ Phase 2 |
| Certification officielle (PDF + badge) | ✅ | |

---

## 2. Vision Produit & Objectifs

### Vision

Rendre la formation en santé publique de niveau expert accessible à tous les professionnels de santé d'Afrique de l'Ouest, en français et en anglais, depuis n'importe quel smartphone, même avec une connexion limitée.

### Objectifs mesurables (OKR)

#### 🎯 Obj. 1 — Accessibilité
- 100% fonctionnel sur connexion 2G (EDGE)
- Temps de chargement < 3s sur mobile moyen
- Mode offline complet pour dernier module
- Support des écrans depuis 320px

#### 🎯 Obj. 2 — Apprentissage
- 80% des utilisateurs complètent au moins 3 modules
- Score quiz moyen > 75% (indicateur de maîtrise)
- Taux de rétention à 30 jours > 60%
- NPS (satisfaction) > 50

#### 🎯 Obj. 3 — Pertinence AOF
- 100% des exemples et cas contextualisés AOF
- Données réelles intégrées depuis ≥5 pays CEDEAO
- Mise à jour données épidémiologiques ≤ 30 jours
- Revue pédagogique par experts santé publique AOF

---

## 3. Utilisateurs & Personas

| Persona | Profil | Besoins principaux | Contraintes tech |
|---|---|---|---|
| 🩺 **Dr. Aminata** — Médecin districtale, Mali | Médecin, 8 ans d'expérience, supervise 12 centres de santé | Épidémiologie pratique, surveillance DHIS2, rapports district | Android milieu de gamme, 3G instable, sessions 15min |
| 📊 **Kofi** — Data Analyst, Ghana MoH | Informaticien en santé, configure DHIS2, veut maîtriser biostatistique et R | Statistiques avancées, R/Python, DHIS2 analytique | Laptop + smartphone, WiFi bureau lent, Anglophone |
| 🎓 **Fatou** — Étudiante MPH, Dakar | Master en Santé Publique, prépare examens, bilingue FR/EN | Contenu structuré, flashcards, quiz d'entraînement | Android basique, WiFi campus, budget limité |
| 🏥 **Ibrahim** — Directeur Santé, Burkina | Cadre supérieur MoH, 15 ans expérience | Leadership, politiques, gouvernance, évaluation programmes | iPad + smartphone haut de gamme, peu de temps |

---

## 4. User Stories

### Epic 1 : Authentification & Profil

- **US-001** *(CRITIQUE)* — En tant qu'utilisateur, je veux m'inscrire avec mon email ou Google/LinkedIn afin d'accéder à la plateforme.
- **US-002** *(CRITIQUE)* — En tant que nouvel utilisateur, je veux compléter une évaluation diagnostique de 20 minutes afin d'être automatiquement placé dans le bon niveau de départ.
- **US-003** *(CRITIQUE)* — En tant qu'utilisateur, je veux choisir ma langue préférée (FR ou EN) et basculer entre les deux à tout moment.

### Epic 2 : Navigation & Progression

- **US-010** *(CRITIQUE)* — En tant qu'apprenant, je veux voir mon tableau de bord de progression avec le % de completion de chaque module, mon streak quotidien et mes prochaines révisions planifiées.
- **US-011** *(CRITIQUE)* — En tant qu'apprenant, je veux que les modules se débloquent automatiquement quand j'atteins 80% de maîtrise sur le module précédent.
- **US-012** *(ÉLEVÉE)* — En tant qu'apprenant, je veux pouvoir sauter à un module plus avancé si je démontre déjà la maîtrise (test de placement).

### Epic 3 : Contenu Généré par IA

- **US-020** *(CRITIQUE)* — En tant qu'apprenant, je veux que chaque leçon soit générée dynamiquement depuis les 3 livres sources, avec des exemples spécifiques à mon pays.
- **US-021** *(CRITIQUE)* — En tant qu'apprenant, je veux avoir accès à un tuteur virtuel (Claude) que je peux interroger en FR ou EN sur n'importe quel concept du curriculum.
- **US-022** *(CRITIQUE)* — En tant qu'apprenant, je veux que chaque concept soit illustré par un cas réel d'Afrique de l'Ouest avec des données récentes.

### Epic 4 : Quiz & Évaluation

- **US-030** *(CRITIQUE)* — En tant qu'apprenant, je veux répondre à des quiz formatifs (10 questions) après chaque sous-unité, avec feedback immédiat et explication.
- **US-031** *(ÉLEVÉE)* — En tant qu'apprenant, je veux que la difficulté des questions s'adapte automatiquement à ma performance (algorithme adaptatif CAT).
- **US-032** *(CRITIQUE)* — En tant qu'apprenant, je veux voir l'explication détaillée de chaque mauvaise réponse avec renvoi aux chapitres sources.

### Epic 5 : Flashcards & Révision Espacée

- **US-040** *(CRITIQUE)* — En tant qu'apprenant, je veux accéder à des flashcards bilingues (FR/EN) pour chaque concept clé d'un module.
- **US-041** *(ÉLEVÉE)* — En tant qu'apprenant, je veux que le système planifie automatiquement mes révisions avec l'algorithme de répétition espacée (FSRS ou SM-2).

### Epic 6 : Données & Pratique

- **US-050** *(ÉLEVÉE)* — En tant qu'apprenant niveau intermédiaire+, je veux avoir accès à un sandbox de données (datasets DHIS2/DHS réels) pour des exercices d'analyse guidés.
- **US-051** *(ÉLEVÉE)* — En tant qu'apprenant, je veux exécuter du code R ou Python de base dans le navigateur (sandboxé) pour les exercices de biostatistique.

---

## 5. Architecture Système

### Stack technologique

| Couche | Technologie | Justification |
|---|---|---|
| Frontend Framework | Next.js 15 + React 19 | SSR/SSG pour performance, App Router, Server Components |
| Styling | Tailwind CSS + shadcn/ui | Rapidité de développement, cohérence, accessibilité |
| PWA | next-pwa + Workbox | Cache offline, push notifications, installation mobile |
| State Management | Zustand + TanStack Query | Légèreté, gestion cache serveur |
| Backend API | FastAPI (Python 3.12) | Performance asynchrone, typage fort, documentation auto |
| Base de données | PostgreSQL 16 (Supabase) | Open-source, Row Level Security, temps réel |
| Cache | Redis 7 | Cache sessions, queue Celery, rate limiting |
| Auth | Supabase Auth | Email, OAuth (Google/LinkedIn), JWT |
| LLM | Anthropic Claude 3.5 Sonnet | Meilleure performance multilangue FR/EN, RAG |
| Vector DB | ChromaDB / pgvector | Embeddings des 3 livres, recherche sémantique |
| Orchestration IA | LangChain / LlamaIndex | RAG pipeline, agents, tool calling |
| Code Sandbox | Pyodide (Python in browser) | Exécution Python côté client, sécurisé |
| CDN | Cloudflare Workers | Edge caching, optimisation AOF (nœuds Afrique) |
| Monitoring | Sentry + PostHog | Erreurs + analytics privacy-first |
| CI/CD | GitHub Actions + Docker | Déploiement automatisé, conteneurisation |
| Hébergement | Fly.io ou Railway | Présence en Afrique ou faible latence, coût raisonnable |

### Vue d'ensemble architecture en couches

```
┌─────────────────────────────────────────────────────┐
│  FRONTEND  │ Next.js 15 · React 19 · Tailwind · PWA │
└──────────────────────┬──────────────────────────────┘
                       │ HTTPS / WebSocket
┌──────────────────────▼──────────────────────────────┐
│  BACKEND   │ FastAPI · Supabase Auth · PostgreSQL    │
│            │ Redis · Celery (async tasks)            │
└──────────────────────┬──────────────────────────────┘
                       │ API calls
┌──────────────────────▼──────────────────────────────┐
│  IA / RAG  │ Anthropic Claude API · ChromaDB         │
│            │ LangChain · OpenAI Embeddings · PyMuPDF │
└──────────────────────┬──────────────────────────────┘
                       │ ETL pipelines
┌──────────────────────▼──────────────────────────────┐
│  DONNÉES   │ DHIS2 API · DHS Program · World Bank   │
│            │ WHO AFRO · PubMed · OOAS                │
└─────────────────────────────────────────────────────┘
```

---

## 6. Moteur IA & Pipeline RAG

### Vue d'ensemble du pipeline

```
PHASE 1 — INDEXATION DES SOURCES
  ├── Donaldson's Essential Public Health   (PDF → chunks 512 tokens)
  ├── Scutchfield Principles of PH Practice (PDF → chunks)
  ├── Triola Biostatistics                  (PDF → texte + équations → chunks)
  ├── Données OMS/AFRO                      (API → JSON → documents)
  └── Articles PubMed AOF récents           (API → abstracts → résumés)

PHASE 2 — EMBEDDINGS
  ├── Modèle : text-embedding-3-small (OpenAI) ou claude-3-haiku
  ├── Dimensions : 1536
  └── Stockage : ChromaDB avec métadonnées (source, chapitre, niveau, pays)

PHASE 3 — GÉNÉRATION DYNAMIQUE (à la demande utilisateur)
  ├── Input  : {module_id} + {level} + {langue} + {pays} + {objectif}
  ├── Retrieval : Top-K (k=8) chunks pertinents des 3 livres + données AOF
  ├── Prompt : System prompt spécialisé pédagogie + contexte AOF
  └── Output : Contenu structuré (leçon / quiz / flashcard / cas pratique)
```

### Prompt système (exemple pour génération de leçon)

```
Tu es un expert en santé publique et pédagogue spécialisé en Afrique de l'Ouest.
Génère une leçon sur {topic} pour un apprenant de niveau {level}.
Langue: {langue}. Pays de l'apprenant: {pays}.
Base-toi EXCLUSIVEMENT sur les sources ci-dessous: {retrieved_chunks}

Règles:
- Tous les exemples doivent être contextualisés pour l'Afrique de l'Ouest
- Cite les données réelles récentes (OMS, DHIS2, DHS) pour le {pays}
- Structure: Introduction → Concept clé → Exemple AOF → Points clés
- Longueur: 400-600 mots
- Inclure 3-5 termes techniques en FR et EN
- Respecter le niveau taxonomique Bloom: {bloom_level}
```

### Types de contenu générés

| Type | Structure générée | Paramètres clés |
|---|---|---|
| **Leçon** | Introduction → Concepts → Exemple AOF → Synthèse → Points clés (5) | module_id, level, langue, pays, bloom_level |
| **Quiz** | 10-20 QCM avec 4 options, 1 correct, explication + source | module_id, difficulty, type (recall/application/analysis) |
| **Flashcard** | Terme FR → Définition FR/EN + exemple AOF + formule si applicable | concept_id, langue_principale, include_formula |
| **Cas pratique** | Contexte AOF → Données → Questions guidées → Correction commentée | module_id, pays, disease_type, data_source |
| **Exercice** | Données réelles (CSV/JSON) → Instructions → Résultats → Corrigé | stats_method, tool (R/Python/Excel), dataset |

---

## 7. Exigences Fonctionnelles

### FR-01 : Authentification & Gestion de Compte

**FR-01.1** *(CRITIQUE)* — **Inscription et connexion multi-méthodes**  
Le système doit permettre l'inscription via : (1) email + mot de passe, (2) Google OAuth, (3) LinkedIn OAuth. À l'inscription, l'utilisateur sélectionne sa langue, son pays, son rôle professionnel et son niveau auto-estimé. Un email de vérification est envoyé. Après vérification, redirection vers l'évaluation diagnostique.

**FR-01.2** *(CRITIQUE)* — **Évaluation diagnostique de placement**  
Questionnaire adaptatif de 20 questions (15-20 min) couvrant 4 domaines : fondements SP, épidémiologie, biostatistiques, systèmes de santé. L'algorithme place l'utilisateur dans l'un des 4 niveaux. Test refaisable après 3 mois.

### FR-02 : Navigation & Modules

**FR-02.1** *(CRITIQUE)* — **Dashboard de progression**  
Affiche : carte des 15 modules avec statut (verrouillé/en cours/complété), % de complétion par module, score moyen aux quiz, streak quotidien, calendrier de révisions Spaced Repetition, et recommandations personnalisées.

**FR-02.2** *(CRITIQUE)* — **Structure de module**  
Chaque module : (1) Page d'aperçu avec objectifs et durée, (2) Unités d'apprentissage (3-6 par module, 10-15 min), (3) Quiz formatif par unité (10 questions), (4) Section flashcards, (5) Exercice pratique/cas d'étude, (6) Évaluation sommative (20 questions, score ≥ 80% pour validation).

### FR-03 : Génération de Contenu IA

**FR-03.1** *(CRITIQUE)* — **Génération dynamique de leçons**  
Contenu de chaque unité généré via pipeline RAG au premier accès, puis mis en cache. Paramètres : pays utilisateur, langue, niveau Bloom cible, module et unité. Chaque génération cite ses sources (livre + chapitre). Workflow de validation expert avant publication en production.

**FR-03.2** *(CRITIQUE)* — **Tuteur virtuel IA**  
Chatbot pédagogique (Claude API + RAG) disponible dans chaque module. Réponses basées uniquement sur les 3 sources indexées + données AOF. Chaque réponse cite la source. Limite : 50 messages/jour en version gratuite.

### FR-04 : Quiz Adaptatif

**FR-04.1** *(ÉLEVÉE)* — **Algorithme CAT (Computer Adaptive Testing)**  
Questions classées par difficulté (1-5). Niveau utilisateur estimé par modèle IRT simplifié. Prochaine question sélectionnée à ±0.5 niveau selon performance. Pool minimal de 50 questions par module requis.

### FR-05 : Flashcards & Révision Espacée

**FR-05.1** *(ÉLEVÉE)* — **Algorithme FSRS**  
L'algorithme FSRS (ou SM-2 comme fallback) planifie les révisions selon la courbe d'oubli. Notation utilisateur : "Facile / Bien / Difficile / Oublié". Notification push pour rappels. Mode "révision rapide" (max 15 min/jour) : 10-20 cartes les plus urgentes.

### FR-06 : Données & Exercices Pratiques

**FR-06.1** *(ÉLEVÉE)* — **Bibliothèque de datasets AOF**  
20+ datasets préformatés : données paludisme DHIS2 (Ghana, Nigeria, Sénégal), enquêtes DHS, données OMS AFRO, données démographiques UNFPA. Chaque dataset inclut : source, année, variables, taille d'échantillon, exercices guidés associés.

**FR-06.2** *(ÉLEVÉE)* — **Sandbox Python/R dans le navigateur**  
Environnement d'exécution Python léger (Pyodide) dans le navigateur. Bibliothèques disponibles : pandas, numpy, scipy, matplotlib, lifelines, statsmodels. Code pré-rempli avec espaces à compléter. Vérification automatique des résultats.

---

## 8. Exigences Non-Fonctionnelles

### NFR-01 : Performance (critique pour AOF)

| Métrique | Cible | Mesure |
|---|---|---|
| Time to Interactive (TTI) — 3G | < 3 secondes | Lighthouse sur Moto G4 simulé |
| First Contentful Paint (FCP) | < 1.5s | PageSpeed Insights |
| Bundle JS initial | < 150KB gzippé | Bundle analyzer |
| Génération IA (leçon) | < 8 secondes (streaming) | P95 latence API |
| Génération quiz (10 questions) | < 5 secondes | P95 latence API |
| Disponibilité | 99.5% uptime | Monitoring Uptime Robot |
| Offline (Service Worker) | Dernier module + toutes flashcards | Cache-first strategy |

### NFR-02 : Accessibilité & Internationalisation

| Exigence | Spécification |
|---|---|
| Accessibilité | WCAG 2.1 niveau AA — navigation clavier, lecteur d'écran (VoiceOver, TalkBack), contraste ≥ 4.5:1 |
| Langues | FR (principal) + EN (secondaire) avec switch instantané. i18n via next-intl. Contenu généré bilingue en parallèle. |
| Responsive | 320px (feature phones) → 1440px (desktop). Mobile-first breakpoints : 320/375/768/1024/1280 |
| Typographie | Taille minimum 16px (mobile). Contraste renforcé pour lecture en plein soleil. |

### NFR-03 : Sécurité

| Domaine | Mesures |
|---|---|
| Authentification | JWT + refresh tokens, HTTPS obligatoire, rate limiting (100 req/min/IP), 2FA optionnel |
| Protection des données | Chiffrement au repos (AES-256), en transit (TLS 1.3), PII minimales collectées |
| API Claude | Clé API côté serveur uniquement, jamais exposée au frontend. Proxy sécurisé. |
| Sandbox code | Pyodide exécuté en WebWorker isolé. Pas d'accès réseau depuis sandbox. |
| Injections | Validation entrées (Pydantic), ORM (pas de SQL brut), Content Security Policy |

---

## 9. Modèle de Données

### Schéma PostgreSQL (simplifié)

```sql
-- Table: users
users {
  id UUID PRIMARY KEY,
  email TEXT UNIQUE,
  name TEXT,
  preferred_language ENUM('fr','en'),
  country TEXT,
  professional_role TEXT,
  current_level INT (1-4),
  streak_days INT,
  last_active TIMESTAMP,
  created_at TIMESTAMP
}

-- Table: modules
modules {
  id UUID PRIMARY KEY,
  module_number INT (1-15),
  level INT (1-4),
  title_fr TEXT,
  title_en TEXT,
  description_fr TEXT,
  description_en TEXT,
  estimated_hours INT,
  bloom_level TEXT,
  prereq_modules UUID[],
  books_sources JSONB  -- {donaldson: [ch2,ch3], triola: [ch4]}
}

-- Table: user_module_progress
user_module_progress {
  user_id UUID FK,
  module_id UUID FK,
  status ENUM('locked','in_progress','completed'),
  completion_pct FLOAT,
  quiz_score_avg FLOAT,
  time_spent_minutes INT,
  last_accessed TIMESTAMP,
  PRIMARY KEY (user_id, module_id)
}

-- Table: generated_content
generated_content {
  id UUID PRIMARY KEY,
  module_id UUID FK,
  content_type ENUM('lesson','quiz','flashcard','case'),
  language ENUM('fr','en'),
  level INT,
  content JSONB,          -- Structure spécifique par type
  sources_cited JSONB,    -- [{book, chapter, page}]
  country_context TEXT,
  generated_at TIMESTAMP,
  validated BOOLEAN DEFAULT false
}

-- Table: quiz_attempts
quiz_attempts {
  id UUID PRIMARY KEY,
  user_id UUID FK,
  quiz_id UUID FK,
  answers JSONB,
  score FLOAT,
  time_taken_sec INT,
  attempted_at TIMESTAMP
}

-- Table: flashcard_reviews (algorithme FSRS)
flashcard_reviews {
  id UUID PRIMARY KEY,
  user_id UUID FK,
  card_id UUID FK,
  rating ENUM('again','hard','good','easy'),
  next_review TIMESTAMP,  -- Calculé par FSRS
  stability FLOAT,
  difficulty FLOAT,
  reviewed_at TIMESTAMP
}

-- Table: tutor_conversations
tutor_conversations {
  id UUID PRIMARY KEY,
  user_id UUID FK,
  module_id UUID FK,
  messages JSONB,  -- [{role, content, sources, timestamp}]
  created_at TIMESTAMP
}
```

---

## 10. APIs & Intégrations Externes

| Service | Usage | Endpoint / SDK | Fréquence |
|---|---|---|---|
| Anthropic Claude API | Génération contenu, tuteur virtuel | api.anthropic.com/v1/messages | À la demande |
| DHIS2 API (OMS) | Données épidémiologiques pays CEDEAO | dhis2.who.int/api | Hebdomadaire |
| DHS Program API | Enquêtes démographiques et de santé | api.dhsprogram.com/rest/dhs | Mensuelle |
| World Bank Health | Indicateurs santé, financement | api.worldbank.org/v2/indicator | Mensuelle |
| WHO AFRO Open Data | Bulletins épidémiologiques régionaux | who.int/afro/data | Hebdomadaire |
| PubMed API (E-utils) | Articles récents santé publique AOF | eutils.ncbi.nlm.nih.gov | Mensuelle |
| Supabase Auth | Authentification, gestion sessions | SDK Supabase | Temps réel |
| Resend / Sendgrid | Emails transactionnels, rappels | API email | Événementiel |
| Cloudflare | CDN, Edge caching, DDoS protection | Workers SDK | Continu |
| Sentry | Monitoring erreurs frontend + backend | Sentry SDK | Continu |

---

## 11. Interface Utilisateur

### Principes de design

| Principe | Application |
|---|---|
| 📱 Mobile-First | Navigation bottom bar (mobile) / sidebar (desktop), swipe gestures, boutons touch-friendly (min 44×44px), lisible en plein soleil |
| 🎨 Identité Visuelle | Palette : vert (santé/espoir) + or (Afrique) + blanc. Illustrations contextuelles AOF. Dark mode pour économiser batterie. |
| ⚡ Performance UX | Skeleton loaders pendant génération IA, streaming SSE, optimistic updates pour quiz, feedback haptic sur mobile |

### Écrans principaux

| Écran | Description | Actions clés |
|---|---|---|
| 🏠 Onboarding | Choix langue, pays, rôle, puis test de placement | Inscription, Test diagnostique |
| 📊 Dashboard | Carte des modules, streak, prochaines révisions, recommandations IA | Continuer module, Démarrer révisions |
| 📖 Module overview | Objectifs, durée, unités, progression actuelle | Commencer, Voir flashcards, Quiz final |
| 📝 Leçon (unité) | Contenu généré en streaming, exemples AOF, termes bilingues | Lire, Marquer termes, Quiz formatif |
| ❓ Quiz | Questions adaptatives, feedback immédiat + explication + source | Répondre, Voir correction, Continuer |
| 🃏 Flashcards | Swipe-deck bilingue, notation FSRS, mode "due today" | Swipe gauche/droite, Retourner carte |
| 🗂️ Cas pratique | Contexte AOF, données intégrées, questions guidées, correction commentée | Lire, Analyser, Soumettre |
| 💻 Sandbox | Éditeur Python/R, dataset chargé, vérification automatique résultats | Écrire code, Exécuter, Soumettre |
| 🤖 Tuteur virtuel | Chat FR/EN, réponses sourcées, suggestions exercices | Poser question, Voir sources |
| 🏆 Certificat | Attestation complétion niveau, badge numérique | Télécharger PDF, Partager LinkedIn |

---

## 12. Sécurité & Conformité

### Réglementations applicables

| Réglementation | Scope | Mesures clés |
|---|---|---|
| **RGPD (UE)** | Standard de facto pour AOF francophone | Consentement explicite, droit à l'effacement, portabilité, DPO si >5000 utilisateurs |
| **Sénégal** — Loi 2008-12 | Protection données personnelles | Déclaration CDPDP, collecte minimale |
| **Ghana** — Data Protection Act 2012 | Protection données personnelles | Enregistrement Data Protection Commission |
| **Nigeria** — NDPR 2019 | Nigeria Data Protection Regulation | Audit annuel de conformité, DPO obligatoire |
| **Côte d'Ivoire** — Loi n°2013-450 | Protection données personnelles | Autorisation ARTCI pour traitements sensibles |

### Mesures techniques

- **Chiffrement au repos :** AES-256 (Supabase)
- **Transit :** HTTPS/TLS 1.3 obligatoire
- **Logs :** Conservation maximale 90 jours
- **Analytics :** Pseudonymisation des données (PostHog privacy mode)
- **API Claude :** Clé strictement côté serveur, jamais dans le frontend
- **Sandbox :** Pyodide en WebWorker isolé, pas d'accès réseau

---

## 13. Roadmap de Développement

| Phase | Durée | Livrables | Modules couverts |
|---|---|---|---|
| **Phase 0** — Setup & Infrastructure | 2 sem. | Repo GitHub, CI/CD, environnements dev/staging/prod, DB schema, indexation RAG des 3 livres | — |
| **Phase 1** — MVP Alpha | 6 sem. | Auth, Onboarding, Dashboard, M01+M02+M03 avec contenu généré, Quiz basique, Flashcards | M01, M02, M03 |
| **Phase 2** — Beta Fermée | 8 sem. | Intégration DHIS2/DHS, Cas pratiques, Sandbox Python, Tuteur virtuel, Quiz adaptatif | M04, M05, M06, M07 |
| **Phase 3** — Beta Ouverte | 8 sem. | Révision espacée FSRS, Surveillance numérique, Statistiques avancées, Profil pays | M08, M09, M10 |
| **Phase 4** — Release v1.0 | 6 sem. | Modules Env & SMNI, Niveaux 3-4, Certifications PDF, Optimisation performance | M11, M12, M13, M14 |
| **Phase 5** — v1.1 Capstone | 4 sem. | Module M15, Forum communautaire, Analytics apprenants, App store PWA | M15 |
| **Phase 6** — v2.0 Scale | Ongoing | App native React Native, LMS SCORM, API ouverte, multilangue (Wolof/Haoussa) | All |

### Équipe recommandée

**Core Team (Phase 1-2)**
- 1× Product Manager / PO
- 1× Lead Developer Full-Stack (Next.js + FastAPI)
- 1× AI/ML Engineer (RAG, Claude API)
- 1× UI/UX Designer (mobile-first)
- 1× Expert Santé Publique AOF (validation contenu)

**Extended Team (Phase 3+)**
- 1× DevOps/Infrastructure Engineer
- 1× Data Engineer (pipelines DHIS2/DHS)
- 1× QA Engineer
- 2× Relecteurs contenu (FR et EN)
- 1× Community Manager AOF

### Estimation budgétaire Phase 1

| Poste | Coût estimé |
|---|---|
| Développement (6 mois) | ~$80,000–$120,000 |
| Infrastructure Cloud | ~$500/mois |
| Claude API (génération) | ~$200–$500/mois |
| Licences et outils | ~$200/mois |
| Validation pédagogique | ~$5,000–$10,000 |

---

*SantéPublique AOF Platform · SRS v1.0 · 2025 · Basé sur : Donaldson's Essential Public Health · Principles of Public Health Practice (Scutchfield & Keck) · Biostatistics for the Biological and Health Sciences (Triola) · Sources de données : WHO AFRO · ECOWAS/CEDEAO · DHIS2 · DHS Program · World Bank*
