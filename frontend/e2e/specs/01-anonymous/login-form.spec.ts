/**
 * Anonymous canary — verifies the login page renders correctly without auth.
 *
 * This is the one anonymous-persona spec in #2116-1. Other anonymous flows
 * (catalog browse, curricula, about page, register flow end-to-end) come in
 * follow-up PRs.
 *
 * The "S'inscrire" link assertion is a regression sentinel for the
 * `auth-self-registration-enabled` setting flag (verified TRUE on staging
 * 2026-04-30). If the flag flips to false on staging, this spec fails —
 * intentional drift detection per F-001 in the sweep doc.
 */

import { expect, test } from '@playwright/test';

import { LoginPage } from '../../pages/login-page';

test.describe('@anonymous login form', () => {
  test('renders identifier + password fields and submit button', async ({ page }) => {
    const login = new LoginPage(page);
    await login.goto('fr');

    await expect(login.identifierInput()).toBeVisible();
    await expect(login.passwordInput()).toBeVisible();
    await expect(login.submitButton()).toBeVisible();
  });

  test('shows "Mot de passe oublié ?" link to /fr/magic-link', async ({ page }) => {
    const login = new LoginPage(page);
    await login.goto('fr');

    const forgot = login.forgotPasswordLink();
    await expect(forgot).toBeVisible();
    await expect(forgot).toHaveAttribute('href', '/fr/magic-link');
  });

  test('shows "S\'inscrire" link when self-registration is enabled (drift sentinel)', async ({
    page,
  }) => {
    const login = new LoginPage(page);
    await login.goto('fr');

    // Gated by `auth-self-registration-enabled` setting on the backend.
    // Verified TRUE on staging 2026-04-30. If staging flips it off, this
    // spec fails by design — see F-001 in docs/qa/sweep-2026-04-28.md.
    await expect(login.signupLink()).toBeVisible();
    await expect(login.signupLink()).toHaveAttribute('href', /\/register-options$/);
  });

  test('toggles into TOTP-only mode when authenticator button clicked', async ({ page }) => {
    const login = new LoginPage(page);
    await login.goto('fr');

    await login.totpModeButton().click();

    // TOTP mode shows email + 6-digit code fields, no password field.
    await expect(page.getByLabel(/code d'authentification|authentication code/i)).toBeVisible();
    await expect(login.passwordInput()).toHaveCount(0);
  });
});
