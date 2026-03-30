# Software Requirements Specification
## SantePublique AOF Learning Platform

> **Application Web Mobile-First Bilingue pour la Formation en Sante Publique — Afrique de l'Ouest**  
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

Ce document définit les exigences fonctionnelles et non-fonctionnelles pour le développement de **SantePublique AOF**, une plateforme d'apprentissage en ligne adaptative, bilingue (FR/EN) et mobile-first, destinée aux professionnels de santé et étudiants en Afrique de l'Ouest.

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
| 🎓 **Fatou** — Étudiante MPH, Dakar | Master en Sante Publique, prépare examens, bilingue FR/EN | Contenu structuré, flashcards, quiz d'entraînement | Android basique, WiFi campus, budget limité |
| 🏥 **Ibrahim** — Directeur Sante, Burkina | Cadre supérieur MoH, 15 ans expérience | Leadership, politiques, gouvernance, évaluation programmes | iPad + smartphone haut de gamme, peu de temps |

---

## 4. User Stories

> Convention: Chaque story suit le format "En tant que [persona], je veux [action] afin de [bénéfice]" avec critères d'acceptation.
> Priorités: CRITIQUE (P0) · ÉLEVÉE (P1) · MOYENNE (P2) · BASSE (P3)

---

### Epic 1 : Authentification & Profil Utilisateur

**US-001** *(P0 — CRITIQUE)* — En tant qu'utilisateur, je veux m'inscrire avec mon email, Google ou LinkedIn afin d'accéder à la plateforme.
- **AC1:** Formulaire inscription avec email + mot de passe (min 8 chars, 1 majuscule, 1 chiffre)
- **AC2:** OAuth Google et LinkedIn fonctionnels
- **AC3:** Email de vérification envoyé dans les 30s
- **AC4:** Redirection vers profil initial après vérification

**US-002** *(P0 — CRITIQUE)* — En tant que nouvel utilisateur, je veux compléter une évaluation diagnostique de 20 minutes afin d'être placé dans le bon niveau de départ.
- **AC1:** 20 questions couvrant 4 domaines (fondements SP, épidémiologie, biostatistiques, systèmes de santé)
- **AC2:** Placement automatique dans un des 4 niveaux
- **AC3:** Résultat affiché avec explication du niveau attribué
- **AC4:** Option de refaire le test après 3 mois

**US-003** *(P0 — CRITIQUE)* — En tant qu'utilisateur, je veux choisir ma langue (FR/EN) et basculer entre les deux à tout moment.
- **AC1:** Sélection de langue au premier accès
- **AC2:** Switch instantané FR↔EN dans la barre de navigation
- **AC3:** Préférence persistée en base de données
- **AC4:** Contenu UI et contenu généré suivent la langue choisie

**US-004** *(P1 — ÉLEVÉE)* — En tant qu'utilisateur, je veux éditer mon profil (nom, pays, rôle, langue) afin de personnaliser mon expérience.
- **AC1:** Page profil avec tous les champs éditables
- **AC2:** Changement de pays met à jour la contextualisation du contenu
- **AC3:** Validation des champs avec feedback en temps réel

**US-005** *(P1 — ÉLEVÉE)* — En tant qu'utilisateur, je veux supprimer mon compte et exporter mes données afin de respecter mon droit RGPD.
- **AC1:** Bouton "Supprimer mon compte" avec confirmation en 2 étapes
- **AC2:** Export JSON de toutes les données personnelles
- **AC3:** Suppression effective sous 48h avec email de confirmation
- **AC4:** Données anonymisées dans les analytics

**US-006** *(P1 — ÉLEVÉE)* — En tant qu'utilisateur, je veux réinitialiser mon mot de passe via email afin de récupérer l'accès à mon compte.
- **AC1:** Lien "Mot de passe oublié" sur la page de connexion
- **AC2:** Email avec lien de reset (expiration 1h)
- **AC3:** Nouveau mot de passe validé avec les mêmes critères que l'inscription

---

### Epic 2 : Dashboard & Navigation

**US-010** *(P0 — CRITIQUE)* — En tant qu'apprenant, je veux voir mon tableau de bord avec la progression par module, mon streak et mes prochaines révisions.
- **AC1:** Carte des 15 modules avec statut visuel (verrouillé/en cours/complété)
- **AC2:** Pourcentage de complétion par module
- **AC3:** Compteur de streak quotidien
- **AC4:** Liste des 5 prochaines révisions flashcards planifiées
- **AC5:** Score moyen aux quiz affiché

**US-011** *(P0 — CRITIQUE)* — En tant qu'apprenant, je veux que les modules se débloquent automatiquement quand j'atteins 80% de maîtrise sur le module précédent.
- **AC1:** Module verrouillé visuellement avec icône cadenas
- **AC2:** Déverrouillage automatique quand score quiz ≥ 80% sur le prérequis
- **AC3:** Notification in-app lors du déverrouillage
- **AC4:** Modules sans prérequis (M01) accessibles immédiatement

**US-012** *(P1 — ÉLEVÉE)* — En tant qu'apprenant avancé, je veux pouvoir sauter à un module supérieur via un test de placement afin de ne pas perdre de temps.
- **AC1:** Bouton "Tester mes acquis" sur chaque module verrouillé
- **AC2:** Mini-quiz de 10 questions ciblées sur le module
- **AC3:** Score ≥ 85% débloque le module et marque le prérequis comme "acquis par test"

**US-013** *(P2 — MOYENNE)* — En tant qu'apprenant, je veux recevoir des recommandations personnalisées sur quoi étudier ensuite.
- **AC1:** Section "Recommandé pour vous" sur le dashboard
- **AC2:** Basé sur : modules en cours, révisions en retard, points faibles aux quiz
- **AC3:** Maximum 3 recommandations affichées

**US-014** *(P2 — MOYENNE)* — En tant qu'apprenant, je veux voir mon calendrier d'étude avec les révisions planifiées.
- **AC1:** Vue calendrier mensuelle avec jours de révision marqués
- **AC2:** Détail des cartes à réviser par jour
- **AC3:** Synchronisation avec l'algorithme FSRS

---

### Epic 3 : Structure des Modules & Contenu

**US-020** *(P0 — CRITIQUE)* — En tant qu'apprenant, je veux accéder à une page d'aperçu de module avec objectifs, durée estimée et unités.
- **AC1:** Titre, description, objectifs d'apprentissage (FR/EN)
- **AC2:** Durée estimée et nombre d'unités
- **AC3:** Barre de progression du module
- **AC4:** Liste des unités avec statut (à faire/en cours/fait)

**US-021** *(P0 — CRITIQUE)* — En tant qu'apprenant, je veux lire des leçons générées dynamiquement depuis les 3 livres sources, contextualisées pour mon pays.
- **AC1:** Contenu de 400-600 mots par unité, structuré (Intro → Concept → Exemple AOF → Points clés)
- **AC2:** Exemples spécifiques au pays de l'utilisateur
- **AC3:** 3-5 termes techniques affichés en FR et EN
- **AC4:** Citations des sources (livre + chapitre) visibles
- **AC5:** Contenu streamé en SSE avec skeleton loader pendant la génération

**US-022** *(P0 — CRITIQUE)* — En tant qu'apprenant, je veux que chaque concept soit illustré par un cas réel d'Afrique de l'Ouest avec des données récentes.
- **AC1:** Au moins 1 exemple AOF par leçon avec données datées
- **AC2:** Données issues de DHIS2, DHS, ou WHO AFRO
- **AC3:** Source et année des données citées

**US-023** *(P1 — ÉLEVÉE)* — En tant qu'apprenant, je veux que le contenu généré soit validé par un expert avant publication.
- **AC1:** Contenu généré marqué "draft" par défaut
- **AC2:** Queue de validation visible pour les admins/experts
- **AC3:** Statut "validé" requis avant affichage aux autres utilisateurs
- **AC4:** Fallback: premier utilisateur voit le contenu "draft" avec avertissement

---

### Epic 4 : Tuteur Virtuel IA

**US-030** *(P0 — CRITIQUE)* — En tant qu'apprenant, je veux avoir accès à un tuteur virtuel (Claude) que je peux interroger en FR ou EN sur n'importe quel concept du curriculum.
- **AC1:** Interface chat accessible depuis chaque module
- **AC2:** Réponses basées sur les 3 sources indexées + données AOF
- **AC3:** Chaque réponse cite la source (livre + chapitre)
- **AC4:** Historique de conversation conservé par module
- **AC5:** Limite de 50 messages/jour affichée avec compteur

**US-031** *(P1 — ÉLEVÉE)* — En tant qu'apprenant, je veux que le tuteur me suggère des exercices complémentaires quand je pose des questions.
- **AC1:** Suggestion contextuelle de quiz, flashcards ou exercices liés
- **AC2:** Liens cliquables vers les ressources suggérées

**US-032** *(P2 — MOYENNE)* — En tant qu'apprenant, je veux que le tuteur s'adapte à mon niveau de compréhension.
- **AC1:** Réponses simplifiées pour niveau 1, techniques pour niveaux 3-4
- **AC2:** Détection de questions répétées → reformulation différente

---

### Epic 5 : Quiz & Évaluation

**US-040** *(P0 — CRITIQUE)* — En tant qu'apprenant, je veux répondre à des quiz formatifs (10 questions) après chaque sous-unité avec feedback immédiat.
- **AC1:** 10 QCM avec 4 options chacune
- **AC2:** Feedback immédiat après chaque réponse (correct/incorrect)
- **AC3:** Explication détaillée avec renvoi au chapitre source
- **AC4:** Score final affiché avec récapitulatif

**US-041** *(P1 — ÉLEVÉE)* — En tant qu'apprenant, je veux que la difficulté des questions s'adapte à ma performance (algorithme CAT).
- **AC1:** Questions classées par difficulté (1-5)
- **AC2:** Niveau estimé par modèle IRT simplifié
- **AC3:** Question suivante sélectionnée à ±0.5 niveau de l'estimation courante
- **AC4:** Pool minimum de 50 questions par module

**US-042** *(P0 — CRITIQUE)* — En tant qu'apprenant, je veux passer une évaluation sommative (20 questions, 80% pour valider) à la fin de chaque module.
- **AC1:** 20 questions couvrant toutes les unités du module
- **AC2:** Score ≥ 80% marque le module comme complété
- **AC3:** Score < 80% : feedback sur les unités à revoir, retry possible après 24h
- **AC4:** Nombre de tentatives enregistré

**US-043** *(P2 — MOYENNE)* — En tant qu'apprenant, je veux voir mon historique de quiz et mes tendances de performance.
- **AC1:** Liste de toutes les tentatives avec scores et dates
- **AC2:** Graphique d'évolution des scores par module
- **AC3:** Identification des domaines faibles

---

### Epic 6 : Flashcards & Révision Espacée

**US-050** *(P0 — CRITIQUE)* — En tant qu'apprenant, je veux accéder à des flashcards bilingues (FR/EN) pour chaque concept clé.
- **AC1:** Carte recto (terme/question) → verso (définition + exemple AOF)
- **AC2:** Contenu bilingue FR/EN sur chaque carte
- **AC3:** Formule mathématique affichée si applicable (LaTeX rendu)

**US-051** *(P1 — ÉLEVÉE)* — En tant qu'apprenant, je veux que le système planifie mes révisions avec l'algorithme FSRS.
- **AC1:** Notation utilisateur : Facile / Bien / Difficile / Oublié
- **AC2:** Date de prochaine révision calculée par FSRS
- **AC3:** Paramètres stability/difficulty mis à jour après chaque révision

**US-052** *(P1 — ÉLEVÉE)* — En tant qu'apprenant, je veux un mode "révision du jour" limité à 15 minutes.
- **AC1:** Sélection automatique des 10-20 cartes les plus urgentes
- **AC2:** Timer visible (15 min max)
- **AC3:** Progression sauvegardée si session interrompue

**US-053** *(P2 — MOYENNE)* — En tant qu'apprenant, je veux recevoir des notifications push pour mes rappels de révision.
- **AC1:** Notification push quotidienne si cartes dues
- **AC2:** Heure de notification configurable dans les paramètres
- **AC3:** Opt-out possible

---

### Epic 7 : Données Réelles & Exercices Pratiques

**US-060** *(P1 — ÉLEVÉE)* — En tant qu'apprenant intermédiaire+, je veux accéder à une bibliothèque de datasets AOF pour des exercices d'analyse.
- **AC1:** 20+ datasets préformatés (DHIS2, DHS, WHO AFRO)
- **AC2:** Chaque dataset avec : source, année, variables, taille, description
- **AC3:** Filtrage par pays, thème, niveau de difficulté

**US-061** *(P1 — ÉLEVÉE)* — En tant qu'apprenant, je veux exécuter du code Python dans le navigateur pour les exercices de biostatistique.
- **AC1:** Éditeur de code intégré avec coloration syntaxique
- **AC2:** Exécution via Pyodide (Python in browser)
- **AC3:** Bibliothèques disponibles : pandas, numpy, scipy, matplotlib, statsmodels
- **AC4:** Code pré-rempli avec espaces à compléter
- **AC5:** Vérification automatique des résultats

**US-062** *(P1 — ÉLEVÉE)* — En tant qu'apprenant, je veux suivre des cas pratiques guidés avec données AOF réelles.
- **AC1:** Scénario contextualisé (ex: analyse paludisme Ghana)
- **AC2:** Données intégrées + questions guidées étape par étape
- **AC3:** Correction commentée avec explication méthodologique

---

### Epic 8 : Mode Offline & PWA

**US-070** *(P0 — CRITIQUE)* — En tant qu'apprenant sur réseau instable, je veux installer l'app comme PWA sur mon téléphone.
- **AC1:** Manifest PWA valide, installable depuis Chrome/Safari
- **AC2:** Icône sur écran d'accueil
- **AC3:** Splash screen au lancement

**US-071** *(P0 — CRITIQUE)* — En tant qu'apprenant, je veux accéder au dernier module consulté et à mes flashcards hors connexion.
- **AC1:** Service Worker cache le dernier module complètement (leçons + quiz)
- **AC2:** Flashcards dues disponibles offline
- **AC3:** Indicateur visuel "mode hors-ligne" dans le header
- **AC4:** Bannière de reconnexion quand le réseau revient

**US-072** *(P1 — ÉLEVÉE)* — En tant qu'apprenant, je veux que mes actions offline se synchronisent quand je retrouve une connexion.
- **AC1:** Réponses quiz sauvegardées localement en IndexedDB
- **AC2:** Révisions flashcards synchronisées au retour en ligne
- **AC3:** Résolution de conflits : dernière écriture gagne
- **AC4:** Notification de synchronisation réussie

---

### Epic 9 : Internationalisation & Accessibilité

**US-080** *(P0 — CRITIQUE)* — En tant qu'apprenant, je veux que toute l'interface soit disponible en français et en anglais.
- **AC1:** 100% des textes UI traduits via next-intl
- **AC2:** Contenu généré disponible dans les deux langues
- **AC3:** Formats de date, nombre adaptés à la locale

**US-081** *(P1 — ÉLEVÉE)* — En tant qu'apprenant malvoyant, je veux naviguer au clavier et utiliser un lecteur d'écran.
- **AC1:** Navigation clavier complète (tab, enter, escape)
- **AC2:** Rôles ARIA sur tous les composants interactifs
- **AC3:** Contraste ≥ 4.5:1 (WCAG 2.1 AA)
- **AC4:** Taille minimale de texte 16px sur mobile

---

### Epic 10 : Certification & Gamification

**US-090** *(P2 — MOYENNE)* — En tant qu'apprenant, je veux recevoir un certificat PDF à la complétion d'un niveau.
- **AC1:** Certificat généré automatiquement au score ≥ 80% sur tous les modules du niveau
- **AC2:** PDF téléchargeable avec nom, date, niveau, score
- **AC3:** URL de vérification unique sur le certificat

**US-091** *(P2 — MOYENNE)* — En tant qu'apprenant, je veux partager mon certificat sur LinkedIn.
- **AC1:** Bouton "Partager sur LinkedIn" avec pré-remplissage
- **AC2:** Badge numérique associé au certificat

**US-092** *(P2 — MOYENNE)* — En tant qu'apprenant, je veux voir des badges et récompenses pour ma progression.
- **AC1:** Badge "Premier module complété", "Streak 7 jours", "100 flashcards révisées"
- **AC2:** Affichage sur le profil utilisateur

---

### Epic 11 : Administration & Modération

**US-100** *(P1 — ÉLEVÉE)* — En tant qu'administrateur, je veux voir un tableau de bord avec les statistiques d'utilisation.
- **AC1:** Nombre d'utilisateurs actifs (DAU/MAU)
- **AC2:** Modules les plus/moins populaires
- **AC3:** Score moyen par module
- **AC4:** Taux de complétion par niveau

**US-101** *(P1 — ÉLEVÉE)* — En tant qu'expert pédagogique, je veux valider le contenu IA avant publication.
- **AC1:** Queue de contenu à valider avec filtres (type, module, langue)
- **AC2:** Interface de review : voir le contenu, approuver, rejeter, demander régénération
- **AC3:** Historique des validations

**US-102** *(P2 — MOYENNE)* — En tant qu'administrateur, je veux gérer les utilisateurs (désactiver, changer rôle).
- **AC1:** Liste des utilisateurs avec recherche et filtres
- **AC2:** Actions : désactiver, réactiver, promouvoir en expert/admin
- **AC3:** Log d'audit des actions admin

---

### Epic 12 : Notifications & Engagement

**US-110** *(P2 — MOYENNE)* — En tant qu'apprenant, je veux recevoir des rappels pour maintenir mon streak d'apprentissage.
- **AC1:** Notification push quotidienne configurable
- **AC2:** Email de rappel si inactif depuis 3 jours
- **AC3:** Opt-out granulaire (push, email, in-app)

**US-111** *(P2 — MOYENNE)* — En tant qu'apprenant, je veux recevoir des notifications in-app pour les événements importants.
- **AC1:** Module débloqué, certificat disponible, nouveau contenu
- **AC2:** Badge de notification avec compteur
- **AC3:** Centre de notifications avec historique

---

### Epic 13 : Performance & Monitoring

**US-120** *(P0 — CRITIQUE)* — En tant qu'utilisateur sur réseau 3G, je veux que la page charge en moins de 3 secondes.
- **AC1:** TTI < 3s sur Moto G4 simulé (Lighthouse)
- **AC2:** FCP < 1.5s
- **AC3:** Bundle JS initial < 150KB gzippé

**US-121** *(P1 — ÉLEVÉE)* — En tant qu'apprenant, je veux que la génération IA soit rapide avec un feedback visuel.
- **AC1:** Leçon générée en < 8s (P95) avec streaming SSE
- **AC2:** Quiz généré en < 5s (P95)
- **AC3:** Skeleton loader + progress indicator pendant la génération
- **AC4:** Fallback gracieux si l'API Claude est indisponible (contenu cache ou message d'erreur)

---

### Epic 14 : Infrastructure & DevOps

**US-130** *(P0 — CRITIQUE)* — En tant que développeur, je veux un pipeline CI/CD automatisé.
- **AC1:** GitHub Actions : lint, test, build, deploy sur push
- **AC2:** Environnements dev/staging/prod séparés
- **AC3:** Docker Compose pour développement local

**US-131** *(P0 — CRITIQUE)* — En tant que développeur, je veux un pipeline d'indexation RAG pour les 3 livres PDF.
- **AC1:** Extraction PDF → texte (PyMuPDF)
- **AC2:** Chunking en segments de 512 tokens avec overlap
- **AC3:** Embeddings via text-embedding-3-small
- **AC4:** Stockage dans ChromaDB avec métadonnées (source, chapitre, page, niveau)
- **AC5:** Script reproductible et idempotent

**US-132** *(P0 — CRITIQUE)* — En tant que développeur, je veux un schéma de base de données avec migrations.
- **AC1:** Toutes les tables définies dans la section 9 implémentées
- **AC2:** Migrations Alembic versionnées
- **AC3:** Row Level Security activé sur Supabase
- **AC4:** Seeds de données pour les 15 modules

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
| Vector DB | pgvector (extension PostgreSQL) | Embeddings dans PostgreSQL existant, pas de service supplémentaire |
| Orchestration IA | Anthropic Python SDK | Appels Claude API directs, streaming SSE, pas de middleware LangChain/LlamaIndex |
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
│  IA / RAG  │ Anthropic Claude API · Anthropic SDK      │
│            │ pgvector · OpenAI Embeddings · PyMuPDF   │
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
  └── Stockage : pgvector (PostgreSQL) avec métadonnées (source, chapitre, niveau, pays)

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
- 1× Expert Sante Publique AOF (validation contenu)

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

*SantePublique AOF Platform · SRS v1.0 · 2025 · Basé sur : Donaldson's Essential Public Health · Principles of Public Health Practice (Scutchfield & Keck) · Biostatistics for the Biological and Health Sciences (Triola) · Sources de données : WHO AFRO · ECOWAS/CEDEAO · DHIS2 · DHS Program · World Bank*
