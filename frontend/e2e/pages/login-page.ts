/**
 * Page object for /[locale]/login.
 *
 * Thin wrapper — exposes locators + a couple of high-level actions.
 * No service-layer abstraction.
 */

import type { Locator, Page } from '@playwright/test';

export class LoginPage {
  constructor(public readonly page: Page) {}

  async goto(locale: 'fr' | 'en' = 'fr'): Promise<void> {
    await this.page.goto(`/${locale}/login`);
  }

  identifierInput(): Locator {
    return this.page.locator('input[name="identifier"]');
  }

  passwordInput(): Locator {
    return this.page.locator('input[name="password"]');
  }

  submitButton(): Locator {
    return this.page.locator('button[type="submit"]', { hasText: /se connecter|sign in/i });
  }

  forgotPasswordLink(): Locator {
    return this.page.getByRole('link', { name: /mot de passe oublié|forgot password/i });
  }

  /** "S'inscrire" / "Sign up" link — only renders when registration is enabled. */
  signupLink(): Locator {
    return this.page.getByRole('link', { name: /^s'inscrire$|^sign up$/i });
  }

  /** Toggle to the TOTP-only login view. */
  totpModeButton(): Locator {
    return this.page.getByRole('button', { name: /application d'authentification|authenticator/i });
  }
}
