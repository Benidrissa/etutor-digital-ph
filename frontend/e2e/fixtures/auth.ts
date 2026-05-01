/**
 * Auth helpers for the persona-based Playwright suite.
 *
 * The setup project (e2e/auth.setup.ts) calls `loginAndSaveState()` once per
 * persona to populate `e2e/.auth/{persona}.json` with cookies + localStorage.
 * Each persona's project loads that storage state so specs start pre-authed.
 *
 * Auth endpoint: POST /api/v1/auth/login-password
 * Request:  { identifier: string, password: string }
 * Response: { access_token, refresh_token, token_type, expires_in, user }
 *
 * Verified against staging on 2026-05-01 with the e2e-* fixture accounts
 * seeded by backend/scripts/seed_e2e_users.py (issue #2109).
 */

import type { Page, APIRequestContext } from '@playwright/test';

export type Persona = 'learner' | 'org-owner' | 'sub-admin' | 'admin';

export interface PersonaCredentials {
  email: string;
  passwordEnvVar: string;
}

export const PERSONAS: Record<Persona, PersonaCredentials> = {
  'learner': {
    email: 'e2e-learner@sira-test.local',
    passwordEnvVar: 'E2E_LEARNER_PASSWORD',
  },
  'org-owner': {
    email: 'e2e-org-owner@sira-test.local',
    passwordEnvVar: 'E2E_ORG_OWNER_PASSWORD',
  },
  'sub-admin': {
    email: 'e2e-sub-admin@sira-test.local',
    passwordEnvVar: 'E2E_SUB_ADMIN_PASSWORD',
  },
  'admin': {
    email: 'e2e-admin@sira-test.local',
    passwordEnvVar: 'E2E_ADMIN_PASSWORD',
  },
};

export function getPasswordForPersona(persona: Persona): string {
  const { passwordEnvVar, email } = PERSONAS[persona];
  const pwd = process.env[passwordEnvVar];
  if (!pwd) {
    throw new Error(
      `Missing env var ${passwordEnvVar}. Set it locally before running, or in GitHub Actions secrets for CI. ` +
        `Account: ${email}. See backend/scripts/seed_e2e_users.py manifest (issue #2109).`,
    );
  }
  return pwd;
}

export interface LoginResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  user: {
    id: string;
    email: string;
    name: string;
    role: string;
    preferred_language: string;
    country: string | null;
    current_level: number;
  };
}

/**
 * POST credentials to the staging auth endpoint and return the JSON body.
 * Throws on any non-2xx response.
 */
export async function loginViaApi(
  request: APIRequestContext,
  baseURL: string,
  persona: Persona,
): Promise<LoginResponse> {
  const { email } = PERSONAS[persona];
  const password = getPasswordForPersona(persona);
  const res = await request.post(`${baseURL}/api/v1/auth/login-password`, {
    data: { identifier: email, password },
  });
  if (!res.ok()) {
    const body = await res.text();
    throw new Error(
      `login-password failed for ${persona} (${email}): ${res.status()} ${body.slice(0, 200)}`,
    );
  }
  return (await res.json()) as LoginResponse;
}

/**
 * Populate localStorage with the tokens + user object the FE expects after
 * password login. Idempotent — overwrites any existing keys.
 */
export async function applyAuthToLocalStorage(page: Page, login: LoginResponse): Promise<void> {
  await page.evaluate((data) => {
    localStorage.setItem('access_token', data.access_token);
    localStorage.setItem('refresh_token', data.refresh_token);
    localStorage.setItem('user', JSON.stringify(data.user));
    localStorage.setItem('preferred-locale', data.user.preferred_language ?? 'fr');
  }, login);
}
