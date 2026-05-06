/**
 * Known fixture IDs and slugs from the staging seed.
 *
 * Source of truth: backend/scripts/seed_e2e_users.py (issue #2109).
 * UUIDs captured from the staging dry-run on 2026-05-01.
 *
 * If the seed is re-run on a fresh DB, IDs change — but slugs/codes are stable.
 * Specs should prefer slug/code matching over UUID matching where possible.
 */

export const SEED_ORG = {
  slug: 'e2e-test-org',
  name: 'E2E Test Org',
  // staging UUID (captured 2026-05-01) — informational, prefer slug
  id: '9a25da22-f4a3-44a6-aa3c-40a533e0bf51',
} as const;

export const SEED_COURSES = {
  published: {
    slug: 'e2e-published-course',
    id: 'a611148d-cf61-4262-9282-e47eb81fcb16',
  },
  draft: {
    slug: 'e2e-draft-course',
    id: '849fac54-0a23-4702-bf1f-0236d9d65bd0',
  },
} as const;

export const SEED_CURRICULA = {
  public: {
    slug: 'e2e-public-curriculum',
    id: 'a1ac32e1-0897-4b4b-aabe-816b7ad9578a',
  },
  private: {
    slug: 'e2e-private-curriculum',
    id: 'edc4b664-8e72-4be0-bfdb-f6a45082fdea',
  },
} as const;

export const SEED_ACTIVATION_CODE = 'E2E-FIXTURE-CODE';

/**
 * The 9 sidebar links a plain `role=user` learner with no org membership
 * should see. Used by 02-learner/dashboard.spec.ts as the canary assertion
 * for role-scoped navigation.
 *
 * NOTE: localized labels — these are the FR strings. EN counterparts live
 * in messages/en.json under the same Navigation namespace.
 */
export const LEARNER_SIDEBAR_LINKS_FR = [
  'Dashboard',
  'Formations',
  'Modules',
  'Flashcards',
  'Tests de révision',
  'Certificats',
  'Tuteur IA',
  'Profil',
  'Abonnement',
] as const;

/** Links that must NOT appear for a plain learner (role-scoped UI gating). */
export const LEARNER_HIDDEN_LINKS_FR = [
  'Administration',
  'Organisations',
  'Banques de questions',
] as const;
